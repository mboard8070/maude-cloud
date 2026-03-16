#!/usr/bin/env python3
"""
MAUDE Gateway — HTTP server for mobile apps, Telegram, and remote clients.

Routes:
  /v1/chat/completions  -> Tool-enabled LLM via engine
  /v1/models            -> Available models list
  /models               -> Available models (UI format)
  /health               -> Health check
  /list                 -> Shared folder listing
  /download/*           -> Download from shared
  /upload/*             -> Upload to transfers
  /share/*              -> Upload to shared
  /transfers            -> List transfers
  /ws/terminal          -> SSH WebSocket proxy (PTY)
  /api/terminal/*       -> HTTP terminal (iOS fallback)
  /api/chat/*           -> HTTP chat sessions (iOS fallback)
  /api/conversations    -> Conversation sync
  /api/collab/*         -> Collaboration mesh API
  /api/tools            -> Tool catalog
  /api/tools/execute    -> Direct tool execution
  /proxy?url=           -> Web proxy for browser app
  /app/*                -> PWA static files
  /                     -> Redirect to /app/

Usage:
    maude --serve                    # Start on port 8080
    maude --serve --port 30000       # Custom port
    maude --serve --ssl              # With SSL (requires certs)
"""

import os
import sys
import json
import re
import ssl
import logging
import mimetypes
import hashlib
import struct
import base64
import subprocess
import threading
import time
import uuid
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import unquote, urlparse, parse_qs, urljoin

logger = logging.getLogger("maude.gateway")

# ── Configuration ─────────────────────────────────────────────────

DEFAULT_PORT = 8080
SHARED_DIR = Path.home() / ".config" / "maude" / "data" / "shared"
TRANSFERS_DIR = Path.home() / ".config" / "maude" / "data" / "transfers"
CONVERSATIONS_DIR = Path.home() / ".config" / "maude" / "data" / "conversations"
PWA_DIR = None  # Set via --pwa-dir flag or auto-detect

for _d in (SHARED_DIR, TRANSFERS_DIR, CONVERSATIONS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ── WebSocket helpers (RFC 6455) ──────────────────────────────────

WS_MAGIC = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_accept_key(key):
    return base64.b64encode(
        hashlib.sha1(key.encode() + WS_MAGIC).digest()
    ).decode()


def ws_encode_frame(data, opcode=0x01):
    frame = bytearray()
    frame.append(0x80 | opcode)
    if isinstance(data, str):
        data = data.encode("utf-8")
    length = len(data)
    if length < 126:
        frame.append(length)
    elif length < 65536:
        frame.append(126)
        frame.extend(struct.pack(">H", length))
    else:
        frame.append(127)
        frame.extend(struct.pack(">Q", length))
    frame.extend(data)
    return bytes(frame)


def ws_decode_frame(raw):
    if len(raw) < 2:
        return None, None, 0
    b0, b1 = raw[0], raw[1]
    opcode = b0 & 0x0F
    masked = b1 & 0x80
    length = b1 & 0x7F
    offset = 2
    if length == 126:
        if len(raw) < 4:
            return None, None, 0
        length = struct.unpack(">H", raw[2:4])[0]
        offset = 4
    elif length == 127:
        if len(raw) < 10:
            return None, None, 0
        length = struct.unpack(">Q", raw[2:10])[0]
        offset = 10
    if masked:
        if len(raw) < offset + 4 + length:
            return None, None, 0
        mask = raw[offset:offset + 4]
        offset += 4
        payload = bytearray(raw[offset:offset + length])
        for i in range(length):
            payload[i] ^= mask[i % 4]
        payload = bytes(payload)
    else:
        if len(raw) < offset + length:
            return None, None, 0
        payload = raw[offset:offset + length]
    return opcode, payload, offset + length


# ── WebSocket Terminal ────────────────────────────────────────────

def handle_terminal_websocket(handler):
    """Handle a WebSocket connection for terminal access."""
    import pty
    import fcntl
    import termios
    import select
    import signal

    key = handler.headers.get("Sec-WebSocket-Key", "")
    accept = ws_accept_key(key)
    handler.send_response(101)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()

    sock = handler.request
    master_fd, slave_fd = pty.openpty()
    pid = os.fork()
    if pid == 0:
        os.close(master_fd)
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        os.close(slave_fd)
        os.execvp("/bin/bash", ["/bin/bash", "--login"])
        sys.exit(0)

    os.close(slave_fd)
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    ws_buffer = bytearray()
    running = True
    last_ping = [time.time()]

    def read_from_pty():
        nonlocal running
        while running:
            try:
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if master_fd in r:
                    data = os.read(master_fd, 4096)
                    if not data:
                        running = False
                        break
                    frame = ws_encode_frame(data, opcode=0x02)
                    try:
                        sock.sendall(frame)
                    except Exception:
                        running = False
                        break
                now = time.time()
                if now - last_ping[0] > 25:
                    try:
                        sock.sendall(ws_encode_frame(b"keepalive", opcode=0x09))
                        last_ping[0] = now
                    except Exception:
                        running = False
                        break
            except OSError:
                running = False
                break

    pty_thread = threading.Thread(target=read_from_pty, daemon=True)
    pty_thread.start()

    try:
        while running:
            r, _, _ = select.select([sock], [], [], 0.1)
            if sock not in r:
                continue
            try:
                chunk = sock.recv(8192)
            except Exception:
                break
            if not chunk:
                break
            ws_buffer.extend(chunk)

            while True:
                opcode, payload, consumed = ws_decode_frame(ws_buffer)
                if opcode is None:
                    break
                ws_buffer = ws_buffer[consumed:]

                if opcode in (0x01, 0x02):
                    if opcode == 0x01:
                        try:
                            msg = json.loads(payload)
                            if isinstance(msg, dict) and msg.get("type") == "resize":
                                import fcntl as _fcntl, termios as _termios
                                cols = msg.get("cols", 80)
                                rows = msg.get("rows", 24)
                                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                                _fcntl.ioctl(master_fd, _termios.TIOCSWINSZ, winsize)
                                continue
                            os.write(master_fd, payload)
                        except (json.JSONDecodeError, ValueError):
                            os.write(master_fd, payload)
                    else:
                        os.write(master_fd, payload)
                elif opcode == 0x08:
                    running = False
                    break
                elif opcode == 0x09:
                    sock.sendall(ws_encode_frame(payload, opcode=0x0A))
    except Exception:
        pass
    finally:
        running = False
        try:
            os.close(master_fd)
        except Exception:
            pass
        try:
            os.kill(pid, signal.SIGTERM)
            os.waitpid(pid, 0)
        except Exception:
            pass
        pty_thread.join(timeout=2)


# ── HTTP Terminal Sessions (iOS fallback) ─────────────────────────

_http_terminal_sessions = {}
_chat_sessions = {}
_device_location = {}


# ── Threaded HTTP Server ──────────────────────────────────────────

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ── Gateway Handler ───────────────────────────────────────────────

class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        logger.debug("HTTP %s", format % args)

    def _add_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "86400")

    def _json_response(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self._add_cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_post_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""
        try:
            return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return {}

    # ── SSE helpers ───────────────────────────────────────────────

    def _start_sse_headers(self):
        self.send_response(200)
        self._add_cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

    def _send_sse_chunk(self, data: str):
        """Send a single SSE data line via chunked encoding."""
        line = data.encode()
        self.wfile.write(b"%x\r\n%s\r\n" % (len(line), line))
        self.wfile.flush()

    def _send_trace_sse(self, trace_type: str, data: dict):
        """Send a trace event as an SSE comment."""
        payload = json.dumps({"type": trace_type, **data})
        if getattr(self, '_eventstream_mode', False):
            self._send_sse_chunk(f"event: trace\ndata: {payload}\n\n")
        else:
            self._send_sse_chunk(f": trace {payload}\n\n")

    def _send_content_chunks(self, content: str, model_name: str, chunk_id: str, created: int):
        """Send content as SSE chunks for typewriter effect."""
        words = content.split(" ") if content else [""]
        chunks = []
        current = ""
        for word in words:
            current += (" " if current else "") + word
            if len(current) > 20:
                chunks.append(current)
                current = ""
        if current:
            chunks.append(current)

        for i, chunk_text in enumerate(chunks):
            spacer = " " if i < len(chunks) - 1 else ""
            sse_data = json.dumps({
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "choices": [{"index": 0, "delta": {"content": chunk_text + spacer}, "finish_reason": None}]
            })
            self._send_sse_chunk(f"data: {sse_data}\n\n")

    def _send_sse_done(self, model_name: str, chunk_id: str, created: int):
        finish_data = json.dumps({
            "id": chunk_id, "object": "chat.completion.chunk", "created": created,
            "model": model_name, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
        })
        self._send_sse_chunk(f"data: {finish_data}\n\n")
        self._send_sse_chunk("data: [DONE]\n\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    # ── OPTIONS ───────────────────────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(204)
        self._add_cors()
        self.end_headers()

    # ── GET routes ────────────────────────────────────────────────

    def do_GET(self):
        path = unquote(self.path)
        parsed = urlparse(path)
        query = parse_qs(parsed.query)

        # WebSocket terminal
        if parsed.path == "/ws/terminal":
            if self.headers.get("Upgrade", "").lower() == "websocket":
                handle_terminal_websocket(self)
                return
            self._json_response({"error": "WebSocket upgrade required"}, 400)
            return

        # HTTP terminal SSE stream (iOS)
        if parsed.path == "/api/terminal/stream":
            sid = query.get("sid", [None])[0]
            if sid:
                self._handle_terminal_stream(sid)
            else:
                self._json_response({"error": "missing sid"}, 400)
            return

        # HTTP chat SSE stream (iOS)
        if parsed.path == "/api/chat/stream":
            sid = query.get("sid", [None])[0]
            if not sid:
                self._json_response({"error": "missing sid"}, 400)
                return
            session = _chat_sessions.pop(sid, None)
            if not session:
                self._json_response({"error": "session not found"}, 404)
                return
            req = session["req"]
            req["stream"] = True
            self._eventstream_mode = True
            self._handle_chat_completions(req)
            return

        # File operations
        if parsed.path == "/list":
            req_path = query.get("path", [None])[0]
            target = Path(req_path) if req_path else SHARED_DIR
            if target.exists() and target.is_dir():
                self._list_dir(target)
            else:
                self._json_response({"error": "Directory not found"}, 404)
        elif parsed.path == "/transfers":
            self._list_dir(TRANSFERS_DIR)
        elif parsed.path.startswith("/download/"):
            self._send_file(SHARED_DIR / parsed.path[len("/download/"):])
        elif parsed.path.startswith("/download-transfer/"):
            self._send_file(TRANSFERS_DIR / parsed.path[len("/download-transfer/"):])

        # API routes
        elif parsed.path == "/health":
            self._serve_health()
        elif parsed.path == "/v1/models":
            self._serve_v1_models()
        elif parsed.path == "/models":
            self._serve_models()
        elif parsed.path == "/api/tools":
            self._serve_tools(query)
        elif parsed.path == "/api/conversations":
            self._get_conversations()
        elif parsed.path.startswith("/api/conversations/") and parsed.path.endswith("/messages"):
            conv_id = parsed.path.split("/")[3]
            self._get_messages(conv_id)
        elif parsed.path.startswith("/api/collab/"):
            self._handle_collab_get(parsed.path, query)
        elif parsed.path == "/api/location":
            if _device_location and time.time() - _device_location.get("ts", 0) < 3600:
                self._json_response(_device_location)
            else:
                self._json_response({"error": "no recent location"}, 404)

        # Web proxy
        elif parsed.path.startswith("/proxy"):
            self._web_proxy(query)

        # PWA static files
        elif parsed.path.startswith("/app") or parsed.path == "/":
            self._serve_static(parsed.path)
        elif parsed.path == "/manifest.json":
            self._serve_static("/manifest.json")
        elif parsed.path.startswith("/assets"):
            self._serve_static(parsed.path)
        elif parsed.path in ("/maude", "/maude/voice", "/terminal", "/browser",
                              "/messages", "/files", "/settings", "/collab"):
            self._serve_static("/index.html")
        else:
            if self._try_serve_static(parsed.path):
                return
            self._json_response({"error": "Not found"}, 404)

    # ── POST routes ───────────────────────────────────────────────

    def do_POST(self):
        path = unquote(self.path)
        parsed = urlparse(path)

        # HTTP terminal (iOS)
        if parsed.path == "/api/terminal/create":
            self._create_terminal_session()
            return
        if parsed.path == "/api/terminal/input":
            self._terminal_input()
            return
        if parsed.path == "/api/terminal/resize":
            self._terminal_resize()
            return

        # HTTP chat session (iOS)
        if parsed.path == "/api/chat/create":
            data = self._read_post_body()
            sid = uuid.uuid4().hex[:12]
            _chat_sessions[sid] = {"req": data, "created": time.time()}
            # Cleanup stale sessions
            cutoff = time.time() - 300
            for k in [k for k, v in _chat_sessions.items() if v["created"] < cutoff]:
                del _chat_sessions[k]
            self._json_response({"sid": sid})
            return

        # Tool execution
        if parsed.path == "/api/tools/execute":
            self._execute_tool_api()
            return

        # Collab
        if parsed.path.startswith("/api/collab/"):
            self._handle_collab_post(parsed.path)
            return

        # Conversations
        if parsed.path == "/api/conversations":
            self._save_conversations()
            return
        if parsed.path.startswith("/api/conversations/") and parsed.path.endswith("/messages"):
            conv_id = parsed.path.split("/")[3]
            self._save_messages(conv_id)
            return
        if parsed.path.startswith("/api/conversations/") and parsed.path.endswith("/delete"):
            conv_id = parsed.path.split("/")[3]
            self._delete_conversation(conv_id)
            return

        # File upload
        if parsed.path.startswith("/upload/"):
            self._receive_file(TRANSFERS_DIR / parsed.path[len("/upload/"):])
            return
        if parsed.path.startswith("/share/"):
            self._receive_file(SHARED_DIR / parsed.path[len("/share/"):])
            return

        # Location update
        if parsed.path == "/api/location":
            global _device_location
            data = self._read_post_body()
            if data.get("lat") is not None:
                _device_location = {**data, "ts": time.time()}
            self._json_response({"ok": True})
            return

        # LLM chat completions (the main endpoint)
        if parsed.path.startswith("/v1"):
            self._handle_chat_completions()
            return

        self._json_response({"error": "Not found"}, 404)

    # ── Chat completions via engine ───────────────────────────────

    def _handle_chat_completions(self, pre_parsed_req=None):
        """Route /v1/chat/completions through the engine with SSE streaming."""
        from .engine import Engine, EngineEvent
        from .providers import PROVIDERS, get_available_providers
        from .keys import KeyManager

        km = KeyManager()
        km.load_all_keys()

        if pre_parsed_req is not None:
            req = pre_parsed_req
        else:
            req = self._read_post_body()

        model_name = req.get("model", "mistral")
        is_streaming = req.get("stream", False)

        # Resolve model aliases
        from .providers import MODELS
        if model_name in MODELS:
            provider_key = MODELS[model_name][0]
        else:
            # Try to find by default_model name
            provider_key = None
            for key, cfg in PROVIDERS.items():
                if cfg.default_model == model_name:
                    provider_key = key
                    break
            if not provider_key:
                # Use first available
                available = get_available_providers()
                provider_key = next(iter(available), None)

        if not provider_key:
            self._json_response({"error": f"No provider available for model: {model_name}"}, 503)
            return

        # Cache phone location
        global _device_location
        if "location" in req:
            loc = req["location"]
            if isinstance(loc, dict) and loc.get("lat") is not None:
                _device_location = {**loc, "ts": time.time()}

        try:
            engine = Engine(model=provider_key)
        except ValueError as e:
            self._json_response({"error": str(e)}, 400)
            return

        messages = req.get("messages", [])
        max_tokens = req.get("max_tokens", 4096)
        temperature = req.get("temperature", 0.2)

        if is_streaming:
            self._start_sse_headers()

            def on_event(event: EngineEvent):
                try:
                    self._send_trace_sse(event.type, event.data)
                except Exception:
                    pass

            result = engine.run_turn(messages, on_event=on_event,
                                      max_tokens=max_tokens, temperature=temperature)

            chunk_id = f"chatcmpl-{int(time.time())}"
            created = int(time.time())
            self._send_content_chunks(result.content, engine.resolved_name, chunk_id, created)
            self._send_sse_done(engine.resolved_name, chunk_id, created)
        else:
            result = engine.run_turn(messages, max_tokens=max_tokens, temperature=temperature)
            self._json_response({
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": engine.resolved_name,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": result.content},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "total_tokens": result.prompt_tokens + result.completion_tokens,
                },
            })

    # ── Models ────────────────────────────────────────────────────

    def _serve_v1_models(self):
        from .providers import PROVIDERS
        data = []
        for name, cfg in PROVIDERS.items():
            data.append({"id": name, "object": "model", "owned_by": "maude"})
            data.append({"id": cfg.default_model, "object": "model", "owned_by": "maude"})
        self._json_response({"object": "list", "data": data})

    def _serve_models(self):
        from .providers import PROVIDERS, get_api_key
        models = []
        for name, cfg in PROVIDERS.items():
            models.append({
                "id": name,
                "model": cfg.default_model,
                "provider": cfg.provider.value,
                "available": bool(get_api_key(name)),
            })
        self._json_response({"models": models})

    # ── Health ────────────────────────────────────────────────────

    def _serve_health(self):
        from .providers import get_available_providers
        available = get_available_providers()
        self._json_response({
            "status": "ok",
            "providers": len(available),
            "provider_names": list(available.keys()),
            "uptime": time.time(),
        })

    # ── Tool catalog & execution ──────────────────────────────────

    def _serve_tools(self, query):
        from .tools import TOOLS, get_tools_for_message
        message = query.get("message", [None])[0]
        if message:
            tools = get_tools_for_message(message)
            self._json_response({"tools": tools, "message": message})
        else:
            self._json_response({"tools": TOOLS, "count": len(TOOLS)})

    def _execute_tool_api(self):
        from .tools import execute_tool
        data = self._read_post_body()
        name = data.get("name", "")
        arguments = data.get("arguments", {})
        if not name:
            self._json_response({"error": "Missing 'name' field"}, 400)
            return
        try:
            result = execute_tool(name, arguments)
            self._json_response({"result": result, "error": None})
        except Exception as e:
            self._json_response({"result": None, "error": str(e)}, 500)

    # ── File operations ───────────────────────────────────────────

    def _list_dir(self, directory):
        entries = []
        try:
            for entry in sorted(directory.iterdir()):
                stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "size": stat.st_size,
                    "is_dir": entry.is_dir(),
                    "modified": stat.st_mtime,
                })
        except Exception:
            pass
        self._json_response({"path": str(directory), "files": entries})

    def _send_file(self, filepath):
        if not filepath.exists():
            self._json_response({"error": f"File not found: {filepath.name}"}, 404)
            return
        try:
            data = filepath.read_bytes()
            content_type = mimetypes.guess_type(filepath.name)[0] or "application/octet-stream"
            self.send_response(200)
            self._add_cors()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if content_type.startswith(("image/", "video/", "audio/")):
                self.send_header("Content-Disposition", f'inline; filename="{filepath.name}"')
            else:
                self.send_header("Content-Disposition", f'attachment; filename="{filepath.name}"')
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    def _receive_file(self, filepath):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = self.rfile.read(length)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_bytes(data)
            self._json_response({"status": "ok", "filename": filepath.name, "size": len(data)})
        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    # ── PWA static files ──────────────────────────────────────────

    def _serve_static(self, path):
        if PWA_DIR is None:
            self._json_response({"error": "No PWA directory configured. Use --pwa-dir"}, 404)
            return

        if path in ("/", "/app", "/app/"):
            path = "/index.html"
        elif path.startswith("/app/"):
            path = path[4:]

        filepath = PWA_DIR / path.lstrip("/")
        if not filepath.exists() or filepath.is_dir():
            if "." not in filepath.name:
                filepath = PWA_DIR / "index.html"

        if not filepath.exists():
            self._json_response({"error": "Not found"}, 404)
            return

        try:
            data = filepath.read_bytes()
            content_type = mimetypes.guess_type(filepath.name)[0] or "application/octet-stream"
            self.send_response(200)
            self._add_cors()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if filepath.name == "index.html" or content_type == "application/javascript":
                self.send_header("Cache-Control", "no-store, must-revalidate")
            else:
                self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    def _try_serve_static(self, path):
        if PWA_DIR is None:
            return False
        filepath = PWA_DIR / path.lstrip("/")
        if filepath.exists() and filepath.is_file():
            self._serve_static(path)
            return True
        return False

    # ── Web proxy ─────────────────────────────────────────────────

    def _web_proxy(self, query):
        import http.client as _http
        url = query.get("url", [None])[0]
        if not url:
            self._json_response({"error": "Missing url parameter"}, 400)
            return
        try:
            parsed = urlparse(url)
            use_ssl = parsed.scheme == "https"
            host = parsed.hostname
            port = parsed.port or (443 if use_ssl else 80)
            request_path = parsed.path or "/"
            if parsed.query:
                request_path += "?" + parsed.query
            if use_ssl:
                ctx = ssl.create_default_context()
                conn = _http.HTTPSConnection(host, port, timeout=15, context=ctx)
            else:
                conn = _http.HTTPConnection(host, port, timeout=15)
            conn.request("GET", request_path, headers={
                "User-Agent": "Mozilla/5.0 (Linux; Android 14) MAUDE/2.0",
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Host": host,
            })
            resp = conn.getresponse()
            data = resp.read()
            content_type = resp.headers.get("Content-Type", "text/html")
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location", "")
                if location and not location.startswith("http"):
                    location = urljoin(url, location)
                self._json_response({"redirect": location, "status": resp.status})
                conn.close()
                return
            self.send_response(200)
            self._add_cors()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            conn.close()
        except Exception as e:
            self._json_response({"error": f"Proxy error: {e}"}, 502)

    # ── Conversations ─────────────────────────────────────────────

    def _get_conversations(self):
        index_file = CONVERSATIONS_DIR / "index.json"
        if index_file.exists():
            self._json_response(json.loads(index_file.read_text()))
        else:
            self._json_response([])

    def _save_conversations(self):
        data = self._read_post_body()
        (CONVERSATIONS_DIR / "index.json").write_text(json.dumps(data))
        self._json_response({"ok": True})

    def _get_messages(self, conv_id):
        safe_id = conv_id.replace("/", "").replace("..", "")
        msg_file = CONVERSATIONS_DIR / f"{safe_id}.json"
        if msg_file.exists():
            self._json_response(json.loads(msg_file.read_text()))
        else:
            self._json_response([])

    def _save_messages(self, conv_id):
        safe_id = conv_id.replace("/", "").replace("..", "")
        data = self._read_post_body()
        (CONVERSATIONS_DIR / f"{safe_id}.json").write_text(json.dumps(data))
        self._json_response({"ok": True})

    def _delete_conversation(self, conv_id):
        safe_id = conv_id.replace("/", "").replace("..", "")
        msg_file = CONVERSATIONS_DIR / f"{safe_id}.json"
        if msg_file.exists():
            msg_file.unlink()
        self._json_response({"ok": True})

    # ── Collab API ────────────────────────────────────────────────

    def _handle_collab_get(self, path: str, query: dict):
        from .collab import get_hub
        hub = get_hub()

        if path == "/api/collab/presence":
            self._json_response(hub.presence.get_all())
        elif path == "/api/collab/activity":
            self._json_response(hub.activity.get_recent())
        elif path == "/api/collab/projects":
            self._json_response(hub.list_projects())
        elif path.startswith("/api/collab/projects/"):
            project_id = path.split("/")[4]
            proj = hub.projects.get(project_id)
            self._json_response(proj if proj else {"error": "Not found"}, 200 if proj else 404)
        elif path == "/api/collab/tasks":
            self._json_response(hub.tasks.list_all())
        elif path == "/api/collab/tasks/poll":
            client_id = query.get("client_id", [""])[0]
            if not client_id:
                self._json_response({"error": "client_id required"}, 400)
            else:
                tasks = hub.tasks.get_queued_for_client(client_id)
                self._json_response(tasks)
        elif path.startswith("/api/collab/tasks/"):
            task_id = path.split("/")[4]
            task = hub.tasks.get(task_id)
            self._json_response(task if task else {"error": "Not found"}, 200 if task else 404)
        elif path == "/api/collab/status":
            self._json_response(hub.get_status())
        else:
            self._json_response({"error": "Not found"}, 404)

    def _handle_collab_post(self, path: str):
        from .collab import get_hub
        hub = get_hub()
        data = self._read_post_body()

        if path == "/api/collab/presence":
            hub.heartbeat(
                client_id=data.get("client_id", ""),
                client_type=data.get("client_type", "unknown"),
                activity=data.get("activity", ""),
                conversation_id=data.get("conversation_id", ""),
                hostname=data.get("hostname", ""),
                platform=data.get("platform", ""),
            )
            self._json_response({"ok": True})
        elif path == "/api/collab/activity":
            hub.emit(
                event_type=data.get("type", "custom"),
                summary=data.get("summary", ""),
                data=data.get("data"),
                client_id=data.get("client_id", ""),
                conversation_id=data.get("conversation_id", ""),
            )
            self._json_response({"ok": True})
        elif path == "/api/collab/projects":
            proj = hub.create_project(name=data.get("name", "Untitled"), description=data.get("description", ""))
            self._json_response(proj, 201)
        elif path == "/api/collab/tasks":
            task = hub.dispatch_task(
                prompt=data.get("prompt", ""),
                target=data.get("target", ""),
                capability=data.get("capability", "LLM"),
                target_client_id=data.get("target_client_id", ""),
                target_platform=data.get("target_platform", ""),
            )
            self._json_response(task, 201)
        elif path.endswith("/claim") and "/tasks/" in path:
            task_id = path.split("/")[4]
            task = hub.tasks.get(task_id)
            if not task:
                self._json_response({"error": "Not found"}, 404)
            elif task.get("status") != "queued":
                self._json_response({"error": "Already claimed"}, 409)
            else:
                hub.tasks.update_status(task_id, "running")
                self._json_response({"ok": True})
        elif path.endswith("/result") and "/tasks/" in path:
            task_id = path.split("/")[4]
            hub.tasks.update_status(task_id, data.get("status", "completed"), data.get("result", ""))
            self._json_response({"ok": True})
        else:
            self._json_response({"error": "Not found"}, 404)

    # ── HTTP Terminal (iOS fallback) ──────────────────────────────

    def _create_terminal_session(self):
        import pty
        import fcntl
        import termios

        session_id = uuid.uuid4().hex[:12]
        master_fd, slave_fd = pty.openpty()
        pid = os.fork()
        if pid == 0:
            os.close(master_fd)
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            os.close(slave_fd)
            os.execvp("/bin/bash", ["/bin/bash", "--login"])
            sys.exit(0)
        os.close(slave_fd)
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        _http_terminal_sessions[session_id] = {"master_fd": master_fd, "pid": pid, "created": time.time()}
        self._json_response({"sid": session_id})

    def _terminal_input(self):
        data = self._read_post_body()
        sid = data.get("sid", "")
        text = data.get("data", "")
        session = _http_terminal_sessions.get(sid)
        if not session:
            self._json_response({"error": "session not found"}, 404)
            return
        try:
            os.write(session["master_fd"], text.encode() if isinstance(text, str) else text)
            self._json_response({"ok": True})
        except OSError:
            self._json_response({"error": "session closed"}, 410)

    def _terminal_resize(self):
        import fcntl as _fcntl, termios as _termios
        data = self._read_post_body()
        sid = data.get("sid", "")
        session = _http_terminal_sessions.get(sid)
        if not session:
            self._json_response({"error": "session not found"}, 404)
            return
        cols = data.get("cols", 80)
        rows = data.get("rows", 24)
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        _fcntl.ioctl(session["master_fd"], _termios.TIOCSWINSZ, winsize)
        self._json_response({"ok": True})

    def _handle_terminal_stream(self, session_id):
        import select
        session = _http_terminal_sessions.get(session_id)
        if not session:
            self._json_response({"error": "session not found"}, 404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._add_cors()
        self.end_headers()

        master_fd = session["master_fd"]
        try:
            while session_id in _http_terminal_sessions:
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if master_fd in r:
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    b64 = base64.b64encode(data).decode()
                    self.wfile.write(f"data: {b64}\n\n".encode())
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


# ── Server startup ────────────────────────────────────────────────

def serve(port: int = None, ssl_cert: str = None, ssl_key: str = None,
          pwa_dir: str = None, bind: str = "0.0.0.0"):
    """Start the MAUDE gateway server."""
    global PWA_DIR

    import socket

    if port is None:
        port = int(os.environ.get("MAUDE_PORT", DEFAULT_PORT))

    if pwa_dir:
        PWA_DIR = Path(pwa_dir)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load keys
    from .keys import KeyManager
    km = KeyManager()
    km.load_all_keys()

    from .providers import get_available_providers
    available = get_available_providers()

    logger.info("MAUDE Gateway on %s:%d", bind, port)
    logger.info("  Providers  : %s", ", ".join(available.keys()) if available else "NONE")
    logger.info("  Shared     : %s", SHARED_DIR)
    logger.info("  Transfers  : %s", TRANSFERS_DIR)
    if PWA_DIR:
        logger.info("  PWA dir    : %s", PWA_DIR)

    # Start collab heartbeat
    def _gateway_heartbeat():
        from .collab import get_hub
        hostname = socket.gethostname().lower()
        hub = get_hub()
        while True:
            try:
                hub.heartbeat(f"gateway-{hostname}", "gateway", "serving requests")
            except Exception:
                pass
            time.sleep(30)
    threading.Thread(target=_gateway_heartbeat, daemon=True).start()
    logger.info("  Collab     : heartbeat started")

    server = ThreadedHTTPServer((bind, port), GatewayHandler)

    if ssl_cert and ssl_key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(ssl_cert, ssl_key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        logger.info("  SSL        : enabled")

    logger.info("  Ready.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping.")


if __name__ == "__main__":
    serve()
