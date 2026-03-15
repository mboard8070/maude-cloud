"""
MAUDE Engine — extracted tool execution loop.

This is the core of MAUDE: it takes a conversation (messages), selects tools,
calls the LLM, executes tool calls locally, and loops until a final text
response is produced.

Instead of SSE (like the gateway), this uses callbacks so the TUI or any
other frontend can display progress however it wants.

Usage:
    from maude.engine import Engine

    engine = Engine(model="mistral")
    result = engine.run_turn(messages, on_event=my_callback)
"""

import json
import re
import time
import threading
import http.client
import ssl
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlparse

from .providers import PROVIDERS, Provider, get_api_key
from .tools import execute_tool, get_tools_for_message, reset_rate_limits
from .config import MAX_ITERATIONS

logger = logging.getLogger("maude.engine")


@dataclass
class EngineEvent:
    """Event emitted during tool loop execution."""
    type: str           # tool_call, tool_result, llm_call, error, keepalive, context_trim, content
    data: dict = field(default_factory=dict)


@dataclass
class TurnResult:
    """Result of a complete engine turn."""
    content: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0
    elapsed: float = 0.0
    tool_calls_made: int = 0


EventCallback = Callable[[EngineEvent], None]


def _noop_callback(event: EngineEvent):
    pass


class Engine:
    """MAUDE engine — runs tool loops against cloud LLM providers."""

    def __init__(self, model: str = "mistral"):
        self.model = model
        self._resolve_provider()

    def _resolve_provider(self):
        """Resolve model name to provider config and actual model ID."""
        if self.model not in PROVIDERS:
            raise ValueError(f"Unknown model: {self.model}. Available: {', '.join(PROVIDERS.keys())}")
        self.provider_config = PROVIDERS[self.model]
        self.resolved_name = self.provider_config.default_model
        self.api_key = get_api_key(self.model) or ""

    def set_model(self, model: str):
        """Switch to a different model."""
        self.model = model
        self._resolve_provider()

    def run_turn(self, messages: list, on_event: EventCallback = None,
                 max_tokens: int = 4096, temperature: float = 0.2) -> TurnResult:
        """Run one complete turn: LLM call -> tool execution loop -> final response.

        Args:
            messages: Conversation messages (OpenAI format)
            on_event: Callback for progress events
            max_tokens: Max tokens for LLM response
            temperature: Sampling temperature

        Returns:
            TurnResult with final content and usage stats
        """
        if on_event is None:
            on_event = _noop_callback

        if self.provider_config.provider == Provider.ANTHROPIC:
            return self._claude_tool_loop(messages, on_event, max_tokens, temperature)
        else:
            return self._openai_tool_loop(messages, on_event, max_tokens, temperature)

    # ── OpenAI-compatible tool loop (Mistral, OpenAI, xAI, Google) ──

    def _openai_tool_loop(self, messages: list, on_event: EventCallback,
                           max_tokens: int, temperature: float) -> TurnResult:
        result = TurnResult()
        start_time = time.time()
        retries = 0

        # Get user's latest message for tool selection
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
                break

        active_tools = get_tools_for_message(user_msg)
        messages = list(messages)  # Don't mutate caller's list
        self._inject_system_prompt(messages)

        # Connection details
        parsed_url = urlparse(self.provider_config.base_url)
        use_ssl = parsed_url.scheme == "https"
        host = parsed_url.hostname
        port = parsed_url.port or (443 if use_ssl else 80)
        api_path = parsed_url.path.rstrip("/") + "/chat/completions"

        reset_rate_limits()
        recent_tool_calls = []

        for iteration in range(MAX_ITERATIONS):
            is_final = iteration == MAX_ITERATIONS - 1
            if is_final:
                messages.append({"role": "user", "content": "(System: Wrap up now — summarize what you've done.)"})

            # Context trimming
            max_ctx = self.provider_config.max_context
            tool_overhead = len(json.dumps(active_tools)) // 4 if active_tools else 0
            effective_max = max_ctx - tool_overhead
            trimmed = self._trim_messages(messages, effective_max, format="openai")
            if trimmed:
                on_event(EngineEvent("context_trim", {"removed": trimmed}))

            loop_req = {
                "model": self.resolved_name,
                "messages": messages,
                "stream": False,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if not is_final:
                loop_req["tools"] = active_tools
                loop_req["tool_choice"] = "auto"

            body = json.dumps(loop_req).encode()
            llm_start = time.time()

            try:
                if use_ssl:
                    ctx = ssl.create_default_context()
                    conn = http.client.HTTPSConnection(host, port, timeout=300, context=ctx)
                else:
                    conn = http.client.HTTPConnection(host, port, timeout=300)

                headers = {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                }
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                # LLM call with keepalive events
                llm_result_box = [None, None, None]
                def _llm_call():
                    try:
                        conn.request("POST", api_path, body=body, headers=headers)
                        resp = conn.getresponse()
                        llm_result_box[0] = resp.status
                        llm_result_box[1] = resp.read()
                        conn.close()
                    except Exception as exc:
                        llm_result_box[2] = exc

                t = threading.Thread(target=_llm_call)
                t.start()
                while t.is_alive():
                    t.join(timeout=15)
                    if t.is_alive():
                        on_event(EngineEvent("keepalive", {"name": "llm_call", "elapsed": round(time.time() - llm_start, 1)}))
                t.join()

                if llm_result_box[2] is not None:
                    raise llm_result_box[2]

                resp_status = llm_result_box[0]
                resp_body = llm_result_box[1]

                if resp_status != 200:
                    try:
                        err = json.loads(resp_body)
                    except Exception:
                        err = {"error": resp_body.decode(errors="replace")}
                    on_event(EngineEvent("error", {"message": f"LLM error {resp_status}: {err}"}))
                    result.content = f"Error from {self.model}: {err}"
                    break

                resp_data = json.loads(resp_body)
                choice = resp_data.get("choices", [{}])[0]
                message = choice.get("message", {})
                finish_reason = choice.get("finish_reason", "")

            except Exception as e:
                err_msg = str(e)
                transient = any(k in err_msg.lower() for k in ("ssl", "connection", "timed out", "reset", "502", "503"))
                if transient and retries < 3:
                    retries += 1
                    on_event(EngineEvent("error", {"message": f"Retrying ({retries}/3)..."}))
                    time.sleep(2 ** (retries - 1))
                    continue
                on_event(EngineEvent("error", {"message": str(e)}))
                result.content = f"Error: {e}"
                break

            # Track usage
            llm_elapsed = time.time() - llm_start
            usage = resp_data.get("usage", {})
            result.prompt_tokens += usage.get("prompt_tokens", 0)
            result.completion_tokens += usage.get("completion_tokens", 0)
            on_event(EngineEvent("llm_call", {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "elapsed": round(llm_elapsed, 2),
            }))

            # Check for tool calls
            tool_calls = message.get("tool_calls")
            if tool_calls and finish_reason in ("tool_calls", "stop"):
                messages.append(message)

                for tc in tool_calls:
                    func_name = tc["function"]["name"]
                    try:
                        func_args = json.loads(tc["function"]["arguments"])
                    except (json.JSONDecodeError, ValueError):
                        func_args = {}

                    on_event(EngineEvent("tool_call", {"name": func_name, "args": json.dumps(func_args, ensure_ascii=False)[:80]}))

                    # Duplicate detection
                    call_sig = (func_name, json.dumps(func_args, sort_keys=True))
                    if call_sig in recent_tool_calls:
                        tool_result = "(Already called with same arguments.)"
                    else:
                        recent_tool_calls.append(call_sig)
                        tool_start = time.time()

                        tool_result_box = [None]
                        def _run_tool(fn=func_name, fa=func_args):
                            tool_result_box[0] = execute_tool(fn, fa)
                        tt = threading.Thread(target=_run_tool)
                        tt.start()
                        while tt.is_alive():
                            tt.join(timeout=15)
                            if tt.is_alive():
                                on_event(EngineEvent("keepalive", {"name": func_name, "elapsed": round(time.time() - tool_start, 1)}))
                        tool_result = tool_result_box[0]
                        tool_elapsed = time.time() - tool_start

                        preview = (tool_result or "")[:80].replace("\n", " ").strip()
                        on_event(EngineEvent("tool_result", {
                            "name": func_name,
                            "preview": preview + ("..." if len(tool_result or "") > 80 else ""),
                            "elapsed": round(tool_elapsed, 2),
                        }))
                        result.tool_calls_made += 1

                    # Normalize tool_call ID
                    tc_id = tc.get("id", "")
                    import string
                    clean_id = ''.join(c for c in tc_id if c in string.ascii_letters + string.digits)
                    if len(clean_id) < 9:
                        clean_id = clean_id + "x" * (9 - len(clean_id))
                    tc["id"] = clean_id[:9]

                    messages.append({
                        "role": "tool",
                        "name": func_name,
                        "content": _compact_tool_result(func_name, tool_result or ""),
                        "tool_call_id": tc["id"],
                    })

                continue

            # Final text response
            result.content = message.get("content", "")
            break
        else:
            result.content = "I've completed as many steps as I can. Ask me to continue if there's more."

        result.elapsed = time.time() - start_time
        return result

    # ── Claude (Anthropic) tool loop ──

    def _claude_tool_loop(self, messages: list, on_event: EventCallback,
                           max_tokens: int, temperature: float) -> TurnResult:
        result = TurnResult()
        start_time = time.time()
        retries = 0

        # Get user's latest message for tool selection
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
                break

        active_tools_openai = get_tools_for_message(user_msg)

        # Convert OpenAI tool format to Claude format
        claude_tools = []
        for tool in active_tools_openai:
            func = tool.get("function", {})
            claude_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        if claude_tools:
            claude_tools[-1]["cache_control"] = {"type": "ephemeral"}

        # Extract system prompt and convert to Claude format
        system_text = ""
        claude_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_text = msg.get("content", "")
            else:
                claude_messages.append({
                    "role": msg.get("role"),
                    "content": msg.get("content", ""),
                })

        system_text += self._get_tool_addendum()
        system_blocks = [{
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }]

        # Connection details
        parsed_url = urlparse(self.provider_config.base_url)
        use_ssl = parsed_url.scheme == "https"
        host = parsed_url.hostname
        port = parsed_url.port or (443 if use_ssl else 80)
        api_path = "/v1/messages"

        reset_rate_limits()
        recent_tool_calls = []

        for iteration in range(MAX_ITERATIONS):
            is_final = iteration == MAX_ITERATIONS - 1
            if is_final:
                claude_messages.append({"role": "user", "content": "(System: Wrap up now.)"})

            # Context trimming
            max_ctx = self.provider_config.max_context
            system_overhead = len(json.dumps(system_blocks)) // 4
            tool_overhead = len(json.dumps(claude_tools)) // 4 if claude_tools else 0
            effective_max = max_ctx - system_overhead - tool_overhead
            trimmed = self._trim_messages(claude_messages, effective_max, format="claude")
            if trimmed:
                on_event(EngineEvent("context_trim", {"removed": trimmed}))

            loop_req = {
                "model": self.resolved_name,
                "max_tokens": max_tokens,
                "system": system_blocks,
                "messages": claude_messages,
            }
            if not is_final:
                loop_req["tools"] = claude_tools

            body = json.dumps(loop_req).encode()
            llm_start = time.time()

            try:
                if use_ssl:
                    ctx = ssl.create_default_context()
                    conn = http.client.HTTPSConnection(host, port, timeout=300, context=ctx)
                else:
                    conn = http.client.HTTPConnection(host, port, timeout=300)

                headers = {
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Length": str(len(body)),
                }

                llm_result_box = [None, None, None]
                def _llm_call():
                    try:
                        conn.request("POST", api_path, body=body, headers=headers)
                        resp = conn.getresponse()
                        llm_result_box[0] = resp.status
                        llm_result_box[1] = resp.read()
                        conn.close()
                    except Exception as exc:
                        llm_result_box[2] = exc

                t = threading.Thread(target=_llm_call)
                t.start()
                while t.is_alive():
                    t.join(timeout=15)
                    if t.is_alive():
                        on_event(EngineEvent("keepalive", {"name": "llm_call", "elapsed": round(time.time() - llm_start, 1)}))
                t.join()

                if llm_result_box[2] is not None:
                    raise llm_result_box[2]

                resp_status = llm_result_box[0]
                resp_body = llm_result_box[1]

                if resp_status != 200:
                    try:
                        err = json.loads(resp_body)
                    except Exception:
                        err = {"error": resp_body.decode(errors="replace")}
                    err_msg = err.get("error", {}).get("message", str(err)) if isinstance(err.get("error"), dict) else str(err)
                    on_event(EngineEvent("error", {"message": f"Claude error: {err_msg}"}))
                    result.content = f"Error from Claude: {err_msg}"
                    break

                resp_data = json.loads(resp_body)
                stop_reason = resp_data.get("stop_reason", "")

            except Exception as e:
                err_msg = str(e)
                transient = any(k in err_msg.lower() for k in ("ssl", "connection", "timed out", "reset", "502", "503", "overloaded"))
                if transient and retries < 3:
                    retries += 1
                    on_event(EngineEvent("error", {"message": f"Retrying ({retries}/3)..."}))
                    time.sleep(2 ** (retries - 1))
                    continue
                on_event(EngineEvent("error", {"message": str(e)}))
                result.content = f"Error: {e}"
                break

            # Track usage (including cache stats)
            llm_elapsed = time.time() - llm_start
            usage = resp_data.get("usage", {})
            prompt_tok = usage.get("input_tokens", 0)
            compl_tok = usage.get("output_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            cache_create = usage.get("cache_creation_input_tokens", 0)
            result.prompt_tokens += prompt_tok
            result.completion_tokens += compl_tok
            result.cache_read_tokens += cache_read
            result.cache_create_tokens += cache_create

            trace_data = {
                "prompt_tokens": prompt_tok,
                "completion_tokens": compl_tok,
                "elapsed": round(llm_elapsed, 2),
            }
            if cache_read:
                trace_data["cache_read_tokens"] = cache_read
            if cache_create:
                trace_data["cache_create_tokens"] = cache_create
            on_event(EngineEvent("llm_call", trace_data))

            # Parse content blocks
            content_blocks = resp_data.get("content", [])
            text_parts = []
            tool_use_blocks = []
            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_use_blocks.append(block)

            # Tool use
            if tool_use_blocks and stop_reason == "tool_use":
                claude_messages.append({
                    "role": "assistant",
                    "content": content_blocks,
                })

                tool_results = []
                for tu in tool_use_blocks:
                    func_name = tu.get("name", "")
                    func_args = tu.get("input", {})
                    tool_use_id = tu.get("id", "")

                    on_event(EngineEvent("tool_call", {"name": func_name, "args": json.dumps(func_args, ensure_ascii=False)[:80]}))

                    call_sig = (func_name, json.dumps(func_args, sort_keys=True))
                    if call_sig in recent_tool_calls:
                        tool_result = "(Already called with same arguments.)"
                    else:
                        recent_tool_calls.append(call_sig)
                        tool_start = time.time()

                        tool_result_box = [None]
                        def _run_tool(fn=func_name, fa=func_args):
                            tool_result_box[0] = execute_tool(fn, fa)
                        tt = threading.Thread(target=_run_tool)
                        tt.start()
                        while tt.is_alive():
                            tt.join(timeout=15)
                            if tt.is_alive():
                                on_event(EngineEvent("keepalive", {"name": func_name, "elapsed": round(time.time() - tool_start, 1)}))
                        tool_result = tool_result_box[0]
                        tool_elapsed = time.time() - tool_start

                        preview = (tool_result or "")[:80].replace("\n", " ").strip()
                        on_event(EngineEvent("tool_result", {
                            "name": func_name,
                            "preview": preview + ("..." if len(tool_result or "") > 80 else ""),
                            "elapsed": round(tool_elapsed, 2),
                        }))
                        result.tool_calls_made += 1

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": _compact_tool_result(func_name, tool_result or ""),
                    })

                claude_messages.append({
                    "role": "user",
                    "content": tool_results,
                })
                continue

            # Final text response
            result.content = "\n\n".join(text_parts) if text_parts else ""
            break
        else:
            result.content = "I've completed as many steps as I can. Ask me to continue if there's more."

        result.elapsed = time.time() - start_time
        return result

    # ── System prompt ──

    def _get_tool_addendum(self) -> str:
        return (
            "\n\nYou have access to tools for file operations, shell commands, web browsing, and more. "
            "When the user asks about files, directories, code, or system information, USE THE TOOLS "
            "to get real data. Do NOT guess or make up file contents or system information. "
            "\n\nCRITICAL RULES: "
            "1. DO the work. NEVER tell the user to run commands themselves — you have run_command. "
            "2. VERIFY your work. After writing code: build/compile and check for errors. "
            "3. FIX errors yourself. Don't just report errors and stop. "
            "4. NEVER give tutorials for things you can do yourself. "
            "5. Complete the ENTIRE task. Don't stop halfway. "
            "6. DO NOT ask permission at every step. Just do the work. "
            "\n\nYou also have Google Workspace tools (Gmail, Drive, Sheets, Calendar), GitHub tools, "
            "web search (DuckDuckGo), web browsing, and persistent memory. "
            "Use web_search when the user asks to look something up. "
            "\n\nPERSISTENT MEMORY: Use save_memory PROACTIVELY when the user shares personal facts, "
            "preferences, or anything worth remembering. Use recall_memory for past context."
        )

    def _inject_system_prompt(self, messages: list):
        """Inject tool addendum into existing system prompt."""
        addendum = self._get_tool_addendum()
        for msg in messages:
            if msg.get("role") == "system":
                msg["content"] = msg["content"] + addendum
                return
        # No system prompt found — add one
        messages.insert(0, {"role": "system", "content": "You are MAUDE, a capable AI assistant." + addendum})

    # ── Helpers ──

    @staticmethod
    def _estimate_tokens(messages):
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        total += len(json.dumps(block))
                    elif isinstance(block, str):
                        total += len(block)
            tc = msg.get("tool_calls")
            if tc:
                total += len(json.dumps(tc))
        return total // 4

    @staticmethod
    def _trim_messages(messages, max_tokens, format="openai"):
        threshold = int(max_tokens * 0.8)
        est = Engine._estimate_tokens(messages)
        if est <= threshold:
            return 0

        removed = 0
        while Engine._estimate_tokens(messages) > threshold and len(messages) > 4:
            idx = 2
            if idx >= len(messages) - 2:
                break

            if format == "openai":
                if messages[idx].get("role") == "assistant":
                    messages.pop(idx)
                    removed += 1
                    while idx < len(messages) - 2 and messages[idx].get("role") == "tool":
                        messages.pop(idx)
                        removed += 1
                else:
                    messages.pop(idx)
                    removed += 1
            elif format == "claude":
                if messages[idx].get("role") == "assistant":
                    messages.pop(idx)
                    removed += 1
                    if idx < len(messages) - 2 and messages[idx].get("role") == "user":
                        content = messages[idx].get("content", "")
                        is_tool_result = isinstance(content, list) and any(
                            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                        )
                        if is_tool_result:
                            messages.pop(idx)
                            removed += 1
                else:
                    messages.pop(idx)
                    removed += 1

        return removed


def _compact_tool_result(name: str, result: str) -> str:
    """Truncate tool results to prevent context bloat."""
    if not result:
        return result
    n = len(result)
    if name in ("write_file", "edit_file", "change_directory", "get_working_directory"):
        return result
    if name == "read_file" and n > 3000:
        lines = result.split("\n")
        if len(lines) > 100:
            head = "\n".join(lines[:80])
            tail = "\n".join(lines[-20:])
            return f"{head}\n\n... ({len(lines) - 100} lines omitted) ...\n\n{tail}"
        return result[:3000] + f"\n... (truncated, {n} chars total)"
    if name == "run_command" and n > 3000:
        return result[:2000] + f"\n\n... ({n - 2800} chars omitted) ...\n\n" + result[-800:]
    if name == "list_directory" and n > 2000:
        lines = result.split("\n")
        if len(lines) > 65:
            return "\n".join(lines[:65]) + f"\n... ({len(lines) - 65} more entries)"
        return result[:2000] + "\n... (truncated)"
    if n > 4000:
        return result[:3500] + f"\n... (truncated, {n} chars total)"
    return result


def run_agent_task(agent_name: str, task: str, context: str = "") -> str:
    """Run a sub-agent task using the engine. Used by run_agent tool."""
    from .keys import KeyManager

    km = KeyManager()
    km.load_all_keys()

    # Pick a model for the agent (prefer cheaper models for sub-tasks)
    from .providers import get_available_providers
    available = get_available_providers()
    model = "mistral" if "mistral" in available else next(iter(available), None)
    if not model:
        return "Error: No models available for agent execution."

    engine = Engine(model=model)

    prompt = f"You are a {agent_name} agent. Complete this task:\n\n{task}"
    if context:
        prompt = f"Context:\n{context}\n\n{prompt}"

    messages = [
        {"role": "system", "content": f"You are MAUDE's {agent_name} agent. Be thorough but concise."},
        {"role": "user", "content": prompt},
    ]

    result = engine.run_turn(messages, max_tokens=4096)
    return result.content
