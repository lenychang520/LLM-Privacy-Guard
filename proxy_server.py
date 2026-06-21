# -*- coding: utf-8 -*-
"""LLM Privacy Guard — Local HTTP Proxy

Intercepts LLM API requests, filters sensitive data via privacy_engine,
then forwards to the real upstream API. Detects the target provider
automatically from the request body's model field — no upstream
configuration needed for common providers.

Usage:
    python -m proxy_server                          # auto-detect
    python -m proxy_server --port 19999
    python -m proxy_server --upstream https://api.deepseek.com  # fallback only
"""

import json
import logging
import os
import signal
import sys
import time
from http.client import HTTPConnection, HTTPSConnection
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, urlunparse

_prj_dir = os.path.dirname(os.path.abspath(__file__))
if _prj_dir not in sys.path:
    sys.path.insert(0, _prj_dir)

from privacy_engine import filter_text, __version__ as engine_version
from privacy_engine.config import load_config

logger = logging.getLogger("privacy_guard.proxy")

DEFAULT_PORT = 19999
PID_FILE = os.path.join(_prj_dir, ".privacy_guard.pid")
WATCHDOG_PID_FILE = os.path.join(_prj_dir, ".privacy_guard_watchdog.pid")
STOP_FILE = os.path.join(_prj_dir, ".privacy_guard_stop")

# ── Paths that contain user messages and need filtering ──
_FILTER_PATHS = {
    "/v1/chat/completions",
    "/v1/messages",
    "/v1/responses",
    "/chat/completions",  # OpenAI SDK may strip /v1 prefix
    "/messages",           # Anthropic SDK variant
    "/responses",          # Responses API without /v1 prefix
}

# ── Model → upstream URL mapping (checked via substring match) ──
# First match wins. Configure in config.yaml under "proxy.upstream_map".
_MODEL_UPSTREAM_MAP: list[tuple[str, str]] = [
    ("deepseek", "https://api.deepseek.com"),
    ("gpt-", "https://api.openai.com/v1"),
    ("o1-", "https://api.openai.com/v1"),
    ("o3-", "https://api.openai.com/v1"),
    ("o4-", "https://api.openai.com/v1"),
    ("claude", "https://api.anthropic.com"),
    ("gemini", "https://generativelanguage.googleapis.com"),
    ("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ("glm", "https://open.bigmodel.cn/api/paas/v4"),
    ("moonshot", "https://api.moonshot.cn/v1"),
    ("kimi", "https://api.moonshot.cn/v1"),
    ("minimax", "https://api.minimax.chat/v1"),
    ("mistral", "https://api.mistral.ai/v1"),
    ("llama", "https://api.deepinfra.com/v1/openai"),
    ("yi-", "https://api.lingyiwanwu.com/v1"),
]

# Headers to strip when forwarding (they're hop-by-hop or we set our own)
_HOP_BY_HOP = {
    "transfer-encoding",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "upgrade",
}


def _configured_upstream_map() -> list[tuple[str, str]]:
    """Return config-defined model -> upstream routes before built-ins."""
    try:
        config = load_config()
    except Exception:
        return list(_MODEL_UPSTREAM_MAP)

    custom_map = config.get("proxy", {}).get("upstream_map", {})
    if not isinstance(custom_map, dict):
        return list(_MODEL_UPSTREAM_MAP)

    custom_entries = []
    for keyword, upstream in custom_map.items():
        if isinstance(keyword, str) and isinstance(upstream, str) and keyword and upstream:
            custom_entries.append((keyword.lower(), upstream))

    return custom_entries + list(_MODEL_UPSTREAM_MAP)


def _normalize_path(path: str) -> str:
    """Strip query string from path for route matching."""
    return path.split("?", 1)[0]


def _resolve_upstream(model: str, fallback: str = "") -> str:
    """Resolve the upstream API URL from the model name.

    Checks model name against the built-in mapping (substring match).
    Falls back to the configured default if no match found.
    """
    if model:
        model_lower = model.lower()
        model_normalized = "".join(ch if ch.isalnum() else "-" for ch in model_lower)
        for keyword, upstream in _configured_upstream_map():
            if keyword in model_lower or keyword in model_normalized:
                return upstream
        logger.warning(
            "Unrecognized model '%s' — no matching upstream. "
            "Known patterns: %s. Use --upstream to set a fallback.",
            model, [k for k, _ in _configured_upstream_map()],
        )
    return fallback


class _ProxyHandler(BaseHTTPRequestHandler):
    """HTTP request handler that filters LLM messages then forwards."""

    # Set by factory via class variable
    fallback_upstream: str = ""

    def _join_upstream_path(self, upstream_path: str, request_path: str) -> str:
        """Join upstream base path and request path without duplicating /v1."""
        upstream_path = (upstream_path or "").rstrip("/")
        if "?" in request_path:
            req_path, query = request_path.split("?", 1)
        else:
            req_path, query = request_path, ""

        normalized_req = req_path if req_path.startswith("/") else "/" + req_path
        if not upstream_path:
            path = normalized_req
        else:
            normalized_up = upstream_path if upstream_path.startswith("/") else "/" + upstream_path
            if (
                normalized_req == normalized_up
                or normalized_req.startswith(normalized_up + "/")
                or (normalized_up.endswith("/v1") and normalized_req.startswith("/v1/"))
            ):
                path = normalized_req
            else:
                path = normalized_up + normalized_req

        if query:
            path += "?" + query
        return path

    def _forward(self, body: bytes):
        """Forward request to appropriate upstream and stream response back."""
        try:
            # Resolve upstream: extract model from body, match to known provider
            upstream = self._resolve_request_upstream(body)
            parsed = urlparse(upstream)
            scheme = parsed.scheme
            netloc = parsed.netloc

            path = self._join_upstream_path(parsed.path, self.path)

            headers = {}
            for k, v in self.headers.items():
                if k.lower() in _HOP_BY_HOP or k.lower() in {"host", "content-length"}:
                    continue
                headers[k] = v
            headers["Host"] = netloc
            headers["Content-Length"] = str(len(body))

            if scheme == "https":
                conn = HTTPSConnection(netloc, timeout=120)
            else:
                conn = HTTPConnection(netloc, timeout=120)

            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()

            response_preview = b""
            chunks = []
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                if len(response_preview) < 1000:
                    response_preview += chunk[: 1000 - len(response_preview)]
                chunks.append(chunk)

            if resp.status >= 400:
                logger.error(
                    "Upstream returned %d for %s://%s%s | preview=%r",
                    resp.status,
                    scheme,
                    netloc,
                    path,
                    response_preview.decode("utf-8", errors="replace"),
                )

            self.send_response(resp.status)
            for key, val in resp.getheaders():
                if key.lower() not in _HOP_BY_HOP:
                    self.send_header(key, val)
            self.end_headers()

            for chunk in chunks:
                self.wfile.write(chunk)
                self.wfile.flush()

            conn.close()
        except Exception as e:
            logger.error("Forward error: %s", e)
            try:
                self.send_error(502, f"Upstream unreachable: {e}")
            except Exception:
                pass

    def _resolve_request_upstream(self, body: bytes) -> str:
        """Determine which upstream API to forward to based on request body."""
        model = ""
        try:
            data = json.loads(body)
            model = data.get("model", "")
        except (json.JSONDecodeError, Exception):
            pass

        upstream = _resolve_upstream(model, self.__class__.fallback_upstream)
        if not upstream:
            msg = (
                f"Cannot determine upstream. Model '{model}' not recognized "
                "and no --upstream fallback configured.\n"
                "Use --upstream for your default provider, e.g.:\n"
                "  privacy-guard start --upstream https://api.deepseek.com"
            )
            logger.error(msg)
            raise ValueError(msg)
        return upstream

    def _filter_request_body(self, body: bytes) -> bytes:
        """Filter sensitive data from request body if it's a known LLM path."""
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return body

        filtered = False

        if "system" in data and isinstance(data["system"], str):
            original = data["system"]
            data["system"] = filter_text(original)
            if data["system"] != original:
                filtered = True

        if "instructions" in data and isinstance(data["instructions"], str):
            original = data["instructions"]
            data["instructions"] = filter_text(original)
            if data["instructions"] != original:
                filtered = True

        if "messages" in data:
            for msg in data["messages"]:
                content = msg.get("content")
                if isinstance(content, str):
                    original = content
                    msg["content"] = filter_text(content)
                    if msg["content"] != original:
                        filtered = True
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                original = text
                                block["text"] = filter_text(text)
                                if block["text"] != original:
                                    filtered = True

        if "input" in data:
            if isinstance(data["input"], str):
                original = data["input"]
                data["input"] = filter_text(original)
                if data["input"] != original:
                    filtered = True
            else:
                filtered = self._filter_responses_input(data["input"]) or filtered

        if filtered:
            logger.info("Filtered sensitive data from request")
            # Also write a debug-level access log so users can verify
            # what the proxy actually saw vs what it forwarded. Disabled
            # by default; enable with PRIVACY_GUARD_DEBUG_LOG=1.
            if os.environ.get("PRIVACY_GUARD_DEBUG_LOG"):
                try:
                    log_path = os.path.join(_prj_dir, ".privacy_guard_access.log")
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(f"--- {time.strftime('%H:%M:%S')} {self.path} ---\n")
                        f.write("ORIGINAL (received from client):\n")
                        f.write(body.decode("utf-8", errors="replace") + "\n")
                        f.write("FILTERED (forwarded to upstream):\n")
                        f.write(json.dumps(data, ensure_ascii=False) + "\n\n")
                except Exception as e:
                    # Visible error so users can see why logging didn't work
                    logger.error("access log write failed: %s", e)
                    import traceback
                    logger.error(traceback.format_exc())

        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    def _filter_responses_input(self, input_data) -> bool:
        """Filter user-visible text in Responses API payloads."""
        filtered = False

        if isinstance(input_data, str):
            return False
        if not isinstance(input_data, list):
            return False

        for item in input_data:
            if not isinstance(item, dict):
                continue

            instructions = item.get("instructions")
            if isinstance(instructions, str):
                redacted = filter_text(instructions)
                if redacted != instructions:
                    item["instructions"] = redacted
                    filtered = True

            content = item.get("content")
            if isinstance(content, str):
                redacted = filter_text(content)
                if redacted != content:
                    item["content"] = redacted
                    filtered = True
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    for key in ("text", "input_text"):
                        text = block.get(key)
                        if isinstance(text, str):
                            redacted = filter_text(text)
                            if redacted != text:
                                block[key] = redacted
                                filtered = True

        return filtered

    # ── HTTP Methods ──

    def do_POST(self):
        norm = _normalize_path(self.path)

        # Internal shutdown endpoint
        if norm == "/__shutdown":
            self._handle_shutdown()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        if norm in _FILTER_PATHS:
            body = self._filter_request_body(body)
            # Update Content-Length since filtering may change body size
            self.headers["Content-Length"] = str(len(body))

        self._forward(body)

    def _handle_shutdown(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
        # Shutdown in a separate thread to allow response to finish
        import threading
        def _delayed_shutdown():
            import time
            time.sleep(0.1)
            self.server.shutdown()
        threading.Thread(target=_delayed_shutdown, daemon=True).start()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        """Forward GET requests, except /health which is self-served."""
        norm = _normalize_path(self.path)
        if norm == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return
        self._forward(b"")

    def log_message(self, fmt, *args):
        """Suppress default http.server logging — we log at debug level."""
        logger.debug("HTTP %s", fmt % args)


def _make_handler(fallback_upstream: str = ""):
    class _ConfiguredHandler(_ProxyHandler):
        pass

    _ConfiguredHandler.fallback_upstream = fallback_upstream
    return _ConfiguredHandler


def start_server(port: int = DEFAULT_PORT, upstream: str = ""):
    """Start the proxy server (blocking). Call from CLI.

    upstream is optional — if not provided, the proxy auto-detects
    the target provider from the request body's model field.
    """
    handler = _make_handler(upstream or "")
    # allow_reuse_address=True (SO_REUSEADDR) so a restart right after
    # the old process dies can rebind the port immediately, instead of
    # crashing with "Address already in use" during the TIME_WAIT window.
    HTTPServer.allow_reuse_address = True
    server = HTTPServer(("127.0.0.1", port), handler)

    # Write PID for stop/status
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    logger.info("LLM Privacy Guard v%s — Proxy started", engine_version)
    logger.info("  Listening : http://127.0.0.1:%d", port)
    if upstream:
        logger.info("  Fallback  : %s", upstream)
    else:
        logger.info("  Upstream  : auto-detect from request model")
    logger.info("  Press Ctrl+C to stop")

    exit_code_override = 0

    def _shutdown(sig, frame):
        nonlocal exit_code_override
        exit_code_override = 128 + sig
        logger.info("Received signal %d, shutting down...", sig)
        server.shutdown()

    try:
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)
    except ValueError:
        pass

    try:
        server.serve_forever()
    finally:
        _cleanup()

    sys.exit(exit_code_override)


def _cleanup():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def _cleanup_watchdog():
    try:
        os.remove(WATCHDOG_PID_FILE)
    except OSError:
        pass


def _signal_stop():
    """Signal watchdog/proxy to stop (cross-platform)."""
    try:
        with open(STOP_FILE, "w") as f:
            f.write("stop")
    except OSError:
        pass


def _clear_stop_signal():
    try:
        os.remove(STOP_FILE)
    except OSError:
        pass


def _is_process_alive(pid: int) -> bool:
    """Check if a process exists (cross-platform)."""
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def stop_server(port: int = DEFAULT_PORT):
    """Stop a running proxy by sending shutdown request."""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/__shutdown", method="POST", data=b""
        )
        urllib.request.urlopen(req, timeout=3)
        print(f"Proxy stopped (port {port})")
    except Exception:
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            print(f"Proxy stopped (PID: {pid})")
        except FileNotFoundError:
            print("No running proxy found.")
        except Exception:
            print("No running proxy found.")
    finally:
        _cleanup()


def status_server(port: int = DEFAULT_PORT) -> bool:
    """Check if proxy is running. Returns True if running."""
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
        print(f"Proxy running — http://127.0.0.1:{port}")
        return True
    except Exception:
        pass

    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        if _is_process_alive(pid):
            print(f"Proxy running — http://127.0.0.1:{port} (PID: {pid})")
            return True
        else:
            print("PID file found but process is dead. Cleaning up.")
            _cleanup()
            return False
    except FileNotFoundError:
        print("Proxy is not running.")
        return False
    except (ValueError, Exception):
        print("Proxy is not running.")
        _cleanup()
        return False


def _run_daemon(port: int, upstream: str = ""):
    """Start proxy with watchdog in background."""
    import subprocess
    import time

    script = os.path.join(_prj_dir, "cli.py")
    cmd = [sys.executable, script, "start", "--watchdog", "--port", str(port)]
    if upstream:
        cmd += ["--upstream", upstream]
    env = os.environ.copy()
    env["PYTHONPATH"] = _prj_dir

    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW

    proc = subprocess.Popen(
        cmd,
        creationflags=flags,
        env=env,
        cwd=_prj_dir,
    )
    # Write watchdog PID immediately (watchdog will overwrite with its own PID)
    _cleanup_watchdog()
    with open(WATCHDOG_PID_FILE, "w") as f:
        f.write(str(proc.pid))

    time.sleep(0.3)  # Give watchdog time to start and write its PID
    print(f"Proxy started in background — http://127.0.0.1:{port}")
    print(f"Auto-restart enabled (watchdog PID: {proc.pid})")
    print(f"Use 'privacy-guard status' to check, 'privacy-guard stop' to stop.")


# ── Direct execution ──

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLM Privacy Guard Proxy")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Listening port")
    parser.add_argument(
        "--upstream",
        default=os.environ.get("PRIVACY_GUARD_UPSTREAM", ""),
        help="Fallback upstream URL (optional — auto-detected from model if not set)",
    )
    parser.add_argument("--daemon", action="store_true", help="Run in background")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.daemon:
        _run_daemon(args.port, args.upstream or "")
    else:
        start_server(args.port, args.upstream or "")
