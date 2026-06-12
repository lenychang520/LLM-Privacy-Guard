# -*- coding: utf-8 -*-
"""Integration test for the privacy proxy — tests filtering end-to-end
using an in-process mock upstream, without needing daemon mode."""
import json
import socket
import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler


def _free_port() -> int:
    """Return a currently available TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_proxy_filtering():
    """Start a mock upstream, proxy, send sensitive data, verify filtering."""

    mock_port = _free_port()
    proxy_port = _free_port()

    # ── 1. Mock upstream: echoes back what it received ──
    class MockUpstream(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = json.loads(body)
            self.wfile.write(
                json.dumps({"received": data, "path": self.path}).encode()
            )

        def log_message(self, *args):
            pass

    mock = HTTPServer(("127.0.0.1", mock_port), MockUpstream)
    mock_thread = threading.Thread(target=mock.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # ── 2. Start proxy pointing to mock ──
    from proxy_server import start_server, _cleanup

    proxy_thread = threading.Thread(
        target=start_server,
        kwargs={
            "port": proxy_port,
            "upstream": f"http://127.0.0.1:{mock_port}",
        },
        daemon=True,
    )
    proxy_thread.start()
    time.sleep(0.5)

    # ── 3. Send request with sensitive data ──
    test_cases = [
        {
            "input": "ssh root@203.0.113.1 key=sk-abc123def456",
            "expected": "ssh root@[IP] key=sk-abc123def456",
            "desc": "IPv4 + API key",
        },
        {
            "input": "email: zhangjie@company.com phone: 13812345678",
            "expected": "email: [EMAIL] phone: [PHONE]",
            "desc": "Email + phone",
        },
        {
            "input": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
            "expected": "[API_KEY]",
            "desc": "JWT token",
        },
    ]

    passed = 0
    failed = 0

    for tc in test_cases:
        body = json.dumps(
            {"model": "test", "messages": [{"role": "user", "content": tc["input"]}]}
        ).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            result = json.loads(resp.read())
            actual = result["received"]["messages"][0]["content"]
            if actual == tc["expected"]:
                print(f"  PASS: {tc['desc']}")
                print(f"        {tc['input'][:60]}")
                print(f"     -> {actual}")
                passed += 1
            else:
                print(f"  FAIL: {tc['desc']}")
                print(f"        expected: {tc['expected']}")
                print(f"        got:      {actual}")
                failed += 1
        except Exception as e:
            print(f"  ERROR: {tc['desc']} — {e}")
            failed += 1

    # ── 4. Cleanup ──
    mock.shutdown()
    _cleanup()

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    assert failed == 0, f"{failed} test(s) failed"


if __name__ == "__main__":
    test_proxy_filtering()

