# -*- coding: utf-8 -*-
"""LLM Privacy Guard — Local HTTP Proxy

Intercepts LLM API requests, filters sensitive data via privacy_engine,
then forwards to the real upstream API. Supports OpenAI-format
(/v1/chat/completions) and Anthropic-format (/v1/messages).

Usage:
    python -m proxy_server --upstream https://api.deepseek.com
    python -m proxy_server --port 19999 --upstream https://api.openai.com/v1
"""

import json
import logging
import os
import signal
import sys
from http.client import HTTPConnection, HTTPSConnection
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, urlunparse

_prj_dir = os.path.dirname(os.path.abspath(__file__))
if _prj_dir not in sys.path:
    sys.path.insert(0, _prj_dir)

from privacy_engine import filter_text, __version__ as engine_version

logger = logging.getLogger("privacy_guard.proxy")

DEFAULT_PORT = 19999
PID_FILE = os.path.join(_prj_dir, ".privacy_guard.pid")

# ── Paths that contain user messages and need filtering ──
_FILTER_PATHS = {"/v1/chat/completions", "/v1/messages"}

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


def _normalize_path(path: str) -> str:
    """Strip query string from path for route matching."""
    return path.split("?", 1)[0]


class _ProxyHandler(BaseHTTPRequestHandler):
    """HTTP request handler that filters LLM messages then forwards."""

    # Set by factory via class variable
    upstream_url: str = ""
    upstream_parsed: ... = None

    def _forward(self, body: bytes):
        """Forward request to upstream and stream response back."""
        parsed = self.__class__.upstream_parsed
        scheme = parsed.scheme
        netloc = parsed.netloc
        path_bits = [parsed.path.rstrip("/"), self.path.lstrip("/")]
        path = "/" + "/".join(b for b in path_bits if b)
        if "?" in self.path:
            path += "?" + self.path.split("?", 1)[1]

        headers = {}
        for k, v in self.headers.items():
            if k.lower() in _HOP_BY_HOP or k.lower() == "host":
                continue
            headers[k] = v
        headers["Host"] = netloc

        try:
            if scheme == "https":
                conn = HTTPSConnection(netloc, timeout=120)
            else:
                conn = HTTPConnection(netloc, timeout=120)

            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()

            self.send_response(resp.status)
            for key, val in resp.getheaders():
                if key.lower() not in _HOP_BY_HOP:
                    self.send_header(key, val)
            self.end_headers()

            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()

            conn.close()
        except Exception as e:
            logger.error("Upstream error: %s", e)
            try:
                self.send_error(502, f"Upstream unreachable: {e}")
            except Exception:
                pass

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

        if filtered:
            logger.info("Filtered sensitive data from request")

        return json.dumps(data, ensure_ascii=False).encode("utf-8")

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
        """Forward GET requests transparently (model list, health checks, etc.)."""
        self._forward(b"")

    def log_message(self, fmt, *args):
        """Suppress default http.server logging — we log at debug level."""
        logger.debug("HTTP %s", fmt % args)


def _make_handler(upstream_url: str):
    parsed = urlparse(upstream_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid upstream URL: {upstream_url}")

    class _ConfiguredHandler(_ProxyHandler):
        pass

    _ConfiguredHandler.upstream_url = upstream_url
    _ConfiguredHandler.upstream_parsed = parsed
    return _ConfiguredHandler


def start_server(port: int = DEFAULT_PORT, upstream: str = ""):
    """Start the proxy server (blocking). Call from CLI."""
    if not upstream:
        raise ValueError(
            "Upstream URL is required. Pass --upstream or set PRIVACY_GUARD_UPSTREAM."
        )

    handler = _make_handler(upstream)
    server = HTTPServer(("127.0.0.1", port), handler)

    # Write PID for stop/status
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    logger.info("LLM Privacy Guard v%s — Proxy started", engine_version)
    logger.info("  Listening : http://127.0.0.1:%d", port)
    logger.info("  Upstream  : %s", upstream)
    logger.info("  Press Ctrl+C to stop")

    def _shutdown(sig, frame):
        logger.info("Shutting down...")
        server.shutdown()

    try:
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)
    except ValueError:
        # Not in main thread — signal registration not available,
        # but this only affects kill-by-signal. HTTP /__shutdown still works.
        pass

    try:
        server.serve_forever()
    finally:
        _cleanup()


def _cleanup():
    try:
        os.remove(PID_FILE)
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
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
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


def _run_daemon(port: int, upstream: str):
    """Start proxy in a background subprocess (--daemon mode)."""
    import subprocess

    script = os.path.join(_prj_dir, "proxy_server.py")
    cmd = [sys.executable, script, "--port", str(port), "--upstream", upstream]
    env = os.environ.copy()
    env["PYTHONPATH"] = _prj_dir

    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW

    subprocess.Popen(
        cmd,
        creationflags=flags,
        env=env,
        cwd=_prj_dir,
    )
    print(f"Proxy started in background — http://127.0.0.1:{port}")
    print(f"Use 'privacy-guard status' to check, 'privacy-guard stop' to stop.")


# ── Direct execution ──

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLM Privacy Guard Proxy")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Listening port")
    parser.add_argument(
        "--upstream",
        default=os.environ.get("PRIVACY_GUARD_UPSTREAM", ""),
        help="Upstream LLM API base URL",
    )
    parser.add_argument("--daemon", action="store_true", help="Run in background")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.upstream:
        parser.error(
            "Upstream URL is required. Use --upstream or set PRIVACY_GUARD_UPSTREAM."
        )

    if args.daemon:
        _run_daemon(args.port, args.upstream)
    else:
        start_server(args.port, args.upstream)
