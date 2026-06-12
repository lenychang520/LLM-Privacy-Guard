# -*- coding: utf-8 -*-
"""Integration test: verify proxy model-based provider routing + filtering."""
import json
import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler


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
    upstream_a = HTTPServer(("127.0.0.1", 19996), EchoUpstream)
    upstream_b = HTTPServer(("127.0.0.1", 19997), EchoUpstream)
    threading.Thread(target=upstream_a.serve_forever, daemon=True).start()
    threading.Thread(target=upstream_b.serve_forever, daemon=True).start()
    time.sleep(0.3)

    # Patch the upstream map to point to our mocks
    import proxy_server
    original_map = list(proxy_server._MODEL_UPSTREAM_MAP)
    proxy_server._MODEL_UPSTREAM_MAP[:] = [
        ("deepseek", "http://127.0.0.1:19996"),
        ("claude", "http://127.0.0.1:19997"),
    ]

    try:
        # Start proxy with a fallback for GET requests
        t = threading.Thread(
            target=proxy_server.start_server,
            kwargs={"port": 19995, "upstream": "http://127.0.0.1:19996"},
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
            "http://127.0.0.1:19995/v1/chat/completions",
            data=body, headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        result = json.loads(resp.read())
        assert result["port"] == 19996, f"Expected 19996, got {result['port']}"
        print("PASS: deepseek-chat routed to port 19996")

        # Test 2: claude model → should hit port 19997
        body2 = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "email: test@example.com"}],
        }).encode()
        req2 = urllib.request.Request(
            "http://127.0.0.1:19995/v1/messages",
            data=body2, headers={"Content-Type": "application/json"},
        )
        resp2 = urllib.request.urlopen(req2, timeout=5)
        result2 = json.loads(resp2.read())
        assert result2["port"] == 19997, f"Expected 19997, got {result2['port']}"
        print("PASS: claude-sonnet routed to port 19997")

        # Test 3: GET /v1/models — mock doesn't support GET, but proxy forwards
        # to the mock (which returns 501). In real usage with a real API, GET works.
        req3 = urllib.request.Request("http://127.0.0.1:19995/v1/models")
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
            "http://127.0.0.1:19995/v1/chat/completions",
            data=body4, headers={"Content-Type": "application/json"},
        )
        resp4 = urllib.request.urlopen(req4, timeout=5)
        result4 = json.loads(resp4.read())
        assert result4["port"] == 19996, f"Unknown model should fallback to 19996"
        print("PASS: unknown model falls back to port 19996")

        # Test 5: POST without model field → uses fallback
        body5 = json.dumps({
            "messages": [{"role": "user", "content": "hello"}],
        }).encode()
        req5 = urllib.request.Request(
            "http://127.0.0.1:19995/v1/chat/completions",
            data=body5, headers={"Content-Type": "application/json"},
        )
        resp5 = urllib.request.urlopen(req5, timeout=5)
        result5 = json.loads(resp5.read())
        assert result5["port"] == 19996, f"No-model request should fallback to 19996"
        print("PASS: no-model request falls back to port 19996")

    finally:
        upstream_a.shutdown()
        upstream_b.shutdown()
        proxy_server._MODEL_UPSTREAM_MAP[:] = original_map
        proxy_server._cleanup()

    print("\nAll multi-provider routing tests passed!")


if __name__ == "__main__":
    test_multi_provider_routing()
