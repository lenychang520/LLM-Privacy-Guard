# -*- coding: utf-8 -*-
"""LLM Privacy Guard — CLI

Install:
    pip install llm-privacy-guard

Usage:
    privacy-guard setup --upstream https://api.deepseek.com
    privacy-guard start --upstream https://api.deepseek.com --daemon
    privacy-guard stop
    privacy-guard status
    privacy-guard test
"""

import argparse
import logging
import os
import sys
import time

_prj_dir = os.path.dirname(os.path.abspath(__file__))
if _prj_dir not in sys.path:
    sys.path.insert(0, _prj_dir)


def main():
    parser = argparse.ArgumentParser(
        prog="privacy-guard",
        description="LLM Privacy Guard — filter sensitive data before it reaches LLM APIs",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── start ──
    p_start = sub.add_parser("start", help="Start the privacy proxy")
    p_start.add_argument(
        "--port", type=int, default=None,
        help="Proxy port (default: 19999, or $PRIVACY_GUARD_PORT)",
    )
    p_start.add_argument(
        "--upstream", default=None,
        help="Upstream LLM API base URL (or set $PRIVACY_GUARD_UPSTREAM)",
    )
    p_start.add_argument(
        "--daemon", action="store_true",
        help="Run proxy in background (no terminal window)",
    )

    # ── stop ──
    sub.add_parser("stop", help="Stop a running proxy")

    # ── status ──
    sub.add_parser("status", help="Check if proxy is running")

    # ── test ──
    sub.add_parser("test", help="Verify the filter engine is working")

    # ── setup ──
    p_setup = sub.add_parser(
        "setup",
        help="Auto-detect and configure all LLM tools to use the proxy",
    )
    p_setup.add_argument(
        "--upstream", default=None,
        help="Upstream LLM API base URL (or set $PRIVACY_GUARD_UPSTREAM)",
    )
    p_setup.add_argument(
        "--port", type=int, default=None,
        help="Proxy port (default: 19999, or $PRIVACY_GUARD_PORT)",
    )
    p_setup.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be configured without making changes",
    )

    args = parser.parse_args()

    if args.command == "start":
        _cmd_start(args)
    elif args.command == "stop":
        _cmd_stop()
    elif args.command == "status":
        _cmd_status()
    elif args.command == "test":
        _cmd_test()
    elif args.command == "setup":
        _cmd_setup(args)
    else:
        parser.print_help()


# ── Command implementations ──

def _cmd_start(args):
    from proxy_server import start_server, _run_daemon, DEFAULT_PORT

    port = args.port
    if port is None:
        env_port = os.environ.get("PRIVACY_GUARD_PORT")
        port = int(env_port) if env_port else DEFAULT_PORT

    upstream = args.upstream or os.environ.get("PRIVACY_GUARD_UPSTREAM")
    if not upstream:
        print("Error: Upstream URL is required.")
        print()
        print("  privacy-guard start --upstream https://api.deepseek.com")
        print("  or set the PRIVACY_GUARD_UPSTREAM environment variable.")
        print()
        print("Common upstream URLs:")
        print("  DeepSeek : https://api.deepseek.com")
        print("  OpenAI   : https://api.openai.com/v1")
        print("  Anthropic: https://api.anthropic.com")
        sys.exit(1)

    if args.daemon:
        _run_daemon(port, upstream)
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    print(f"LLM Privacy Guard v{_get_version()}")
    print(f"  Configure your LLM client to use: http://127.0.0.1:{port}")
    print()

    start_server(port=port, upstream=upstream)


def _cmd_stop():
    from proxy_server import stop_server, DEFAULT_PORT
    port = int(os.environ.get("PRIVACY_GUARD_PORT", str(DEFAULT_PORT)))
    stop_server(port)


def _cmd_status():
    from proxy_server import status_server, DEFAULT_PORT
    port = int(os.environ.get("PRIVACY_GUARD_PORT", str(DEFAULT_PORT)))
    status_server(port)


def _cmd_test():
    from privacy_engine import filter_text, scan_text, __version__

    test_input = (
        "ssh root@203.0.113.1 key=sk-abc123def456 "
        "ID: ab12cd34-5678-90ab-cdef-1234567890ab "
        "email: zhangjie@company.com"
    )
    filtered = filter_text(test_input)
    matches = scan_text(test_input)

    print(f"LLM Privacy Guard v{__version__} — Self Test")
    print("─" * 50)
    print(f"  Raw      : {test_input}")
    print(f"  Filtered : {filtered}")
    print(f"  Matches  : {len(matches)}")
    for m in matches:
        conf = " ⚠low confidence" if m.get("confidence") == "low" else ""
        print(f"    [{m['type']}]{conf}  {m['value'][:50]}  =>  {m['placeholder']}")
    print("─" * 50)
    if len(matches) >= 3:
        print("Filter engine working correctly.")
    else:
        print(f"Warning: Expected >=3 matches, got {len(matches)}. Check config.yaml.")


def _cmd_setup(args):
    """Auto-detect and configure all LLM tools to use the proxy."""
    from proxy_server import DEFAULT_PORT
    from setup_tools import run_setup

    port = args.port
    if port is None:
        env_port = os.environ.get("PRIVACY_GUARD_PORT")
        port = int(env_port) if env_port else DEFAULT_PORT

    upstream = args.upstream or os.environ.get("PRIVACY_GUARD_UPSTREAM")

    if not upstream and not args.dry_run:
        print("Note: --upstream not set. Proxy will be started but won't forward requests.")
        print("  You can set it later:  set PRIVACY_GUARD_UPSTREAM=https://api.deepseek.com")
        print()

    sys.exit(run_setup(port=port, upstream=upstream or "", dry_run=args.dry_run))


def _get_version() -> str:
    from privacy_engine import __version__
    return __version__


if __name__ == "__main__":
    main()
