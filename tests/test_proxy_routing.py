# -*- coding: utf-8 -*-
"""Integration test: verify proxy model-based provider routing + filtering."""
import json
import socket
import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_multi_provider_routing():
    """Verify proxy routes to correct upstream based on model name."""

    class EchoUpstream(BaseHTTPRequestHandler):
        """Echoes back what it received, including which port handled it."""
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = json.loads(body)
            self.wfile.write(json.dumps({
                "port": self.server.server_port,
                "received": data,
            }).encode())
        def log_message(self, *a): pass

    # Start two mock upstreams on different ports
    upstream_a_port = _free_port()
    upstream_b_port = _free_port()
    proxy_port = _free_port()
    upstream_a = HTTPServer(("127.0.0.1", upstream_a_port), EchoUpstream)
    upstream_b = HTTPServer(("127.0.0.1", upstream_b_port), EchoUpstream)
    threading.Thread(target=upstream_a.serve_forever, daemon=True).start()
    threading.Thread(target=upstream_b.serve_forever, daemon=True).start()
    time.sleep(0.3)

    # Patch the upstream map to point to our mocks.
    # Also stub _configured_upstream_map so real config.yaml doesn't leak in.
    import proxy_server
    original_map = list(proxy_server._MODEL_UPSTREAM_MAP)
    original_configured = proxy_server._configured_upstream_map
    mock_map = [
        ("deepseek", f"http://127.0.0.1:{upstream_a_port}"),
        ("claude", f"http://127.0.0.1:{upstream_b_port}"),
    ]
    proxy_server._MODEL_UPSTREAM_MAP[:] = mock_map
    proxy_server._configured_upstream_map = lambda: mock_map

    try:
        # Start proxy with a fallback for GET requests
        t = threading.Thread(
            target=proxy_server.start_server,
            kwargs={"port": proxy_port, "upstream": f"http://127.0.0.1:{upstream_a_port}"},
            daemon=True,
        )
        t.start()
        time.sleep(0.5)

        # Test 1: deepseek model → should hit port 19996
        body = json.dumps({
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "ssh root@203.0.113.1"}],
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/v1/chat/completions",
            data=body, headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        result = json.loads(resp.read())
        assert result["port"] == upstream_a_port, f"Expected {upstream_a_port}, got {result['port']}"
        print(f"PASS: deepseek-chat routed to port {upstream_a_port}")

        # Test 2: claude model → should hit port 19997
        body2 = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "email: test@example.com"}],
        }).encode()
        req2 = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/v1/messages",
            data=body2, headers={"Content-Type": "application/json"},
        )
        resp2 = urllib.request.urlopen(req2, timeout=5)
        result2 = json.loads(resp2.read())
        assert result2["port"] == upstream_b_port, f"Expected {upstream_b_port}, got {result2['port']}"
        print(f"PASS: claude-sonnet routed to port {upstream_b_port}")

        # Test 3: GET /v1/models — mock doesn't support GET, but proxy forwards
        # to the mock (which returns 501). In real usage with a real API, GET works.
        req3 = urllib.request.Request(f"http://127.0.0.1:{proxy_port}/v1/models")
        try:
            urllib.request.urlopen(req3, timeout=5)
        except urllib.error.HTTPError as e:
            assert e.code == 501  # Mock doesn't implement GET, but proxy forwarded correctly
        print("PASS: GET /v1/models forwarded (mock returned 501, as expected)")

        # Test 4: unknown model → uses fallback
        body4 = json.dumps({
            "model": "unknown-model-xyz",
            "messages": [{"role": "user", "content": "hello"}],
        }).encode()
        req4 = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/v1/chat/completions",
            data=body4, headers={"Content-Type": "application/json"},
        )
        resp4 = urllib.request.urlopen(req4, timeout=5)
        result4 = json.loads(resp4.read())
        assert result4["port"] == upstream_a_port, f"Unknown model should fallback to {upstream_a_port}"
        print(f"PASS: unknown model falls back to port {upstream_a_port}")

        # Test 5: POST without model field → uses fallback
        body5 = json.dumps({
            "messages": [{"role": "user", "content": "hello"}],
        }).encode()
        req5 = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/v1/chat/completions",
            data=body5, headers={"Content-Type": "application/json"},
        )
        resp5 = urllib.request.urlopen(req5, timeout=5)
        result5 = json.loads(resp5.read())
        assert result5["port"] == upstream_a_port, f"No-model request should fallback to {upstream_a_port}"
        print(f"PASS: no-model request falls back to port {upstream_a_port}")

    finally:
        upstream_a.shutdown()
        upstream_b.shutdown()
        proxy_server._MODEL_UPSTREAM_MAP[:] = original_map
        proxy_server._configured_upstream_map = original_configured
        proxy_server._cleanup()

    print("\nAll multi-provider routing tests passed!")


def test_custom_upstream_map_overrides_builtin(tmp_path, monkeypatch):
    """Config-defined upstream_map should route before built-in defaults."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "proxy:\n  upstream_map:\n    gpt-5-4: http://127.0.0.1:29997\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    import proxy_server

    resolved = proxy_server._resolve_upstream("gpt-5.4", fallback="")
    assert resolved == "http://127.0.0.1:29997"


if __name__ == "__main__":
    test_multi_provider_routing()
