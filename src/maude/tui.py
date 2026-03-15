"""
MAUDE TUI — Terminal chat with tool visibility and native copy/paste.

Uses Rich for formatted output, prompt_toolkit for input, and the
engine module for direct LLM + tool execution (no gateway needed).
"""

import sys
import uuid
import time
import threading
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML

from .engine import Engine, EngineEvent, TurnResult
from .providers import PROVIDERS, get_available_providers
from .keys import handle_keys_command, KeyManager

# ── Config ────────────────────────────────────────────────────────────────

HISTORY_FILE = Path.home() / ".config" / "maude" / "chat_history"

# Build available models list from configured providers
def _get_available_models() -> dict:
    """Return dict of short_name -> provider_key for models with keys configured."""
    models = {}
    available = get_available_providers()
    for name in available:
        models[name] = name
    return models

# ── Globals ───────────────────────────────────────────────────────────────

console = Console()
_last_response = ""

# ── Event handler for TUI display ────────────────────────────────────────


def make_event_handler(stop_spinner: threading.Event):
    """Create an event handler that displays tool traces in the terminal."""
    thinking = [True]

    def handle_event(event: EngineEvent):
        nonlocal thinking

        if event.type == "tool_call":
            if thinking[0]:
                stop_spinner.set()
                thinking[0] = False
            name = event.data.get("name", "?")
            args = event.data.get("args", "")
            console.print(f"  [bold cyan]>>[/bold cyan] [bold white]{name}[/bold white]")
            if args and args != "{}":
                # Extract key argument for display
                arg_hint = ""
                try:
                    import json
                    parsed = json.loads(args) if isinstance(args, str) else args
                    if isinstance(parsed, dict):
                        for k in ("command", "query", "path", "local_path", "name",
                                   "file_id", "content", "doc_id", "url", "platform"):
                            if k in parsed:
                                arg_hint = str(parsed[k])
                                if len(arg_hint) > 60:
                                    arg_hint = arg_hint[:60] + "..."
                                break
                except Exception:
                    arg_hint = args[:60] if len(args) <= 60 else args[:60] + "..."
                if arg_hint:
                    console.print(f"  [dim]{arg_hint}[/dim]")

        elif event.type == "tool_result":
            name = event.data.get("name", "")
            preview = event.data.get("preview", "")
            elapsed = event.data.get("elapsed", 0)
            color = "green" if not preview.startswith("Error") else "red"
            console.print(f"  [{color}]{preview}[/{color}] [dim]({elapsed:.1f}s)[/dim]")

        elif event.type == "error":
            if thinking[0]:
                stop_spinner.set()
                thinking[0] = False
            msg = event.data.get("message", "unknown error")
            console.print(f"  [red]x {msg}[/red]")

        elif event.type == "llm_call":
            pass  # Token stats shown at the end

    return handle_event


# ── Commands ──────────────────────────────────────────────────────────────


def handle_command(cmd: str, messages: list, current_model: list) -> bool:
    """Handle slash commands. Returns True if handled."""
    parts = cmd.strip().split()
    command = parts[0].lower()

    if command in ("/quit", "/exit", "/q"):
        console.print("[dim]Goodbye.[/dim]")
        sys.exit(0)

    if command == "/clear":
        messages.clear()
        messages.append(_system_prompt())
        console.print("[dim]Conversation cleared.[/dim]\n")
        return True

    if command == "/model":
        available = _get_available_models()
        if len(parts) > 1:
            name = parts[1]
            if name in available:
                current_model[0] = name
                console.print(f"[dim]Model: {name} ({PROVIDERS[name].default_model})[/dim]\n")
            else:
                console.print(f"[dim]Unknown model. Available: {', '.join(available.keys())}[/dim]\n")
        else:
            console.print(f"[dim]Current: {current_model[0]}\nAvailable: {', '.join(available.keys())}[/dim]\n")
        return True

    if command == "/keys":
        result = handle_keys_command(parts[1:])
        console.print(result + "\n")
        return True

    if command == "/copy":
        if not _last_response:
            console.print("[dim]Nothing to copy.[/dim]\n")
            return True
        for clip_cmd_str in ["xclip -selection clipboard", "xsel --clipboard",
                         "pbcopy", "wl-copy"]:
            try:
                import subprocess
                proc = subprocess.Popen(
                    clip_cmd_str.split(), stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                proc.communicate(input=_last_response.encode())
                if proc.returncode == 0:
                    console.print("[dim]Copied to clipboard.[/dim]\n")
                    return True
            except Exception:
                continue
        p = Path.home() / ".config" / "maude" / "last_response.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_last_response)
        console.print(f"[dim]Saved to {p}[/dim]\n")
        return True

    if command == "/help":
        console.print(Panel(
            "[bold]/quit[/bold]          Exit\n"
            "[bold]/clear[/bold]         Clear conversation\n"
            "[bold]/model[/bold] <name>  Switch model\n"
            "[bold]/keys[/bold]          Manage API keys\n"
            "[bold]/copy[/bold]          Copy last response\n"
            "[bold]/help[/bold]          This help",
            title="Commands", border_style="dim",
        ))
        console.print()
        return True

    return False


def _system_prompt() -> dict:
    return {
        "role": "system",
        "content": "You are MAUDE, a capable AI assistant. Be concise and helpful.",
    }


# ── Key Bindings ──────────────────────────────────────────────────────────


def make_keybindings():
    kb = KeyBindings()

    @kb.add("escape", "enter")
    def _(event):
        event.current_buffer.insert_text("\n")

    return kb


# ── Main ──────────────────────────────────────────────────────────────────


def main():
    global _last_response

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Load keys
    km = KeyManager()
    km.load_all_keys()

    available = _get_available_models()
    if not available:
        console.print("[red]No API keys configured. Run: maude[/red]")
        return

    # Pick default model
    default_model = "mistral" if "mistral" in available else next(iter(available))

    session = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        auto_suggest=AutoSuggestFromHistory(),
        key_bindings=make_keybindings(),
        multiline=False,
        enable_history_search=True,
    )

    messages = [_system_prompt()]
    current_model = [default_model]
    engine = Engine(model=default_model)

    # Banner
    console.print()
    console.print(Panel.fit(
        "[bold magenta]MAUDE[/bold magenta]\n"
        f"[dim]Model: {current_model[0]} | /model <name> | /help for commands[/dim]",
        border_style="magenta",
    ))
    console.print()

    while True:
        try:
            model_tag = current_model[0]
            user_input = session.prompt(
                HTML(f"<ansigreen><b>{model_tag}</b></ansigreen> <ansigray>></ansigray> "),
            ).strip()

            if not user_input:
                continue

            if user_input.startswith("/"):
                if handle_command(user_input, messages, current_model):
                    # Update engine model if changed
                    if engine.model != current_model[0]:
                        engine.set_model(current_model[0])
                    continue

            messages.append({"role": "user", "content": user_input})

            # Spinner
            spinner_chars = [".", "..", "...", "....", "....."]
            spinner_idx = [0]
            stop_spinner = threading.Event()

            def _spinner():
                while not stop_spinner.is_set():
                    frame = spinner_chars[spinner_idx[0] % len(spinner_chars)]
                    print(f"\r  thinking{frame}   ", end="", flush=True)
                    spinner_idx[0] += 1
                    stop_spinner.wait(0.3)
                print("\r" + " " * 30 + "\r", end="", flush=True)

            spinner_thread = threading.Thread(target=_spinner, daemon=True)
            spinner_thread.start()

            event_handler = make_event_handler(stop_spinner)

            # Run the engine
            turn_result = engine.run_turn(
                messages,
                on_event=event_handler,
                max_tokens=4096,
                temperature=0.2,
            )

            stop_spinner.set()
            spinner_thread.join(timeout=1)

            if turn_result.content:
                console.print()
                console.print("[bold magenta]MAUDE[/bold magenta]")
                # Print content directly for native terminal scrollback
                print(turn_result.content)
                console.print(f"[dim]{turn_result.prompt_tokens}+{turn_result.completion_tokens} tokens | {turn_result.elapsed:.1f}s[/dim]")
                if turn_result.cache_read_tokens:
                    console.print(f"[dim]cache: {turn_result.cache_read_tokens} read, {turn_result.cache_create_tokens} create[/dim]")
                console.print()

                messages.append({"role": "assistant", "content": turn_result.content})
                _last_response = turn_result.content

        except KeyboardInterrupt:
            console.print("\n[dim]Ctrl+C — /quit to exit[/dim]\n")
        except EOFError:
            break


if __name__ == "__main__":
    main()
