# -*- coding: utf-8 -*-
"""LLM Privacy Guard — CLI

Install:
    pip install llm-privacy-guard

Usage:
    privacy-guard setup --auto-start
    privacy-guard start
    privacy-guard stop
    privacy-guard status
    privacy-guard test
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time

_prj_dir = os.path.dirname(os.path.abspath(__file__))
if _prj_dir not in sys.path:
    sys.path.insert(0, _prj_dir)

# ── OS supervisor detection ──

_SYSTEMD_SERVICE = "privacy-guard.service"
_LAUNCHD_LABEL = "com.privacyguard"
_LAUNCHD_PLIST = os.path.join(
    os.path.expanduser("~"), "Library", "LaunchAgents", "com.privacyguard.plist"
)


def _is_supervised_by_systemd() -> bool:
    """Check if the proxy is running under systemd --user supervision."""
    if not shutil.which("systemctl"):
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", _SYSTEMD_SERVICE],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _is_supervised_by_launchd() -> bool:
    """Check if the proxy is managed by launchd (plist exists and is loaded)."""
    if not shutil.which("launchctl"):
        return False
    try:
        result = subprocess.run(
            ["launchctl", "list", _LAUNCHD_LABEL],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(
        prog="privacy-guard",
        description="LLM Privacy Guard — filter sensitive data before it reaches LLM APIs",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── start ──
    p_start = sub.add_parser(
        "start",
        help="Start the privacy proxy (daemon + auto-recovery by default)",
        epilog="Without flags, starts in background with watchdog auto-restart enabled.",
    )
    p_start.add_argument(
        "--port", type=int, default=None,
        help="Proxy port (default: 19999, or $PRIVACY_GUARD_PORT)",
    )
    p_start.add_argument(
        "--upstream", default=None,
        help="Fallback upstream URL (auto-detected from model if not set, or $PRIVACY_GUARD_UPSTREAM)",
    )
    p_start.add_argument(
        "--foreground", action="store_true",
        help="Run in foreground without watchdog (for debugging)",
    )
    p_start.add_argument(
        "--watchdog", action="store_true",
        help="Run watchdog in foreground with visible restart logs (for debugging)",
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
    p_setup.add_argument(
        "--auto-start", action="store_true",
        help="Register proxy to auto-start on Windows login",
    )
    p_setup.add_argument(
        "--remove-auto-start", action="store_true",
        help="Remove Windows auto-start registration",
    )

    # ── fix ──
    p_fix = sub.add_parser(
        "fix",
        help="Fix tool configs: restore originals if proxy dead, re-apply proxy if alive",
    )
    p_fix.add_argument(
        "--port", type=int, default=None,
        help="Proxy port (default: 19999, or $PRIVACY_GUARD_PORT)",
    )

    # ── restore ──
    p_restore = sub.add_parser(
        "restore",
        help="Restore all tool configs to their originals (without modifying proxy)",
    )
    p_restore.add_argument(
        "--port", type=int, default=None,
        help="Proxy port (default: 19999, or $PRIVACY_GUARD_PORT)",
    )

    # ── teardown ──
    p_teardown = sub.add_parser(
        "teardown",
        help="Full cleanup: restore configs, stop proxy, remove auto-start",
    )
    p_teardown.add_argument(
        "--port", type=int, default=None,
        help="Proxy port (default: 19999, or $PRIVACY_GUARD_PORT)",
    )

    # ── config ──
    p_config = sub.add_parser(
        "config",
        help="Manage config.yaml: set, unset, list upstream routes",
    )
    p_config.add_argument(
        "action", choices=["list", "set", "unset"],
        help="list: show all routes. set: add/update. unset: remove.",
    )
    p_config.add_argument(
        "model_key", nargs="?",
        help="Model key (e.g. 'gpt-4' or 'deepseek'). Required for set/unset.",
    )
    p_config.add_argument(
        "upstream", nargs="?",
        help="Upstream URL (e.g. https://api.openai.com/v1). Required for set.",
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
    elif args.command == "fix":
        _cmd_fix(args)
    elif args.command == "restore":
        _cmd_restore(args)
    elif args.command == "teardown":
        _cmd_teardown(args)
    elif args.command == "config":
        _cmd_config(args)
    else:
        parser.print_help()


# ── Command implementations ──

def _cmd_start(args):
    from proxy_server import start_server, _run_daemon, DEFAULT_PORT

    port = args.port
    if port is None:
        env_port = os.environ.get("PRIVACY_GUARD_PORT")
        port = int(env_port) if env_port else DEFAULT_PORT

    upstream = args.upstream or os.environ.get("PRIVACY_GUARD_UPSTREAM") or ""

    if args.foreground:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s  %(levelname)-7s  %(message)s",
            datefmt="%H:%M:%S",
        )
        print(f"LLM Privacy Guard v{_get_version()}")
        print(f"  Configure your LLM client to use: http://[IP]:{port}")
        if not upstream:
            print(f"  Upstream auto-detected from request model")
        print()
        start_server(port=port, upstream=upstream)
        return

    if args.watchdog:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s  %(levelname)-7s  %(message)s",
            datefmt="%H:%M:%S",
        )
        _run_watchdog(port, upstream)
        return

    # Default: daemon + watchdog (auto-restart)
    _run_daemon(port, upstream)


def _run_watchdog(port: int, upstream: str):
    """Run proxy with auto-restart on crash."""
    import signal
    import subprocess
    import time

    from proxy_server import (
        WATCHDOG_PID_FILE, STOP_FILE, _cleanup_watchdog,
        _clear_stop_signal,
    )

    logger = logging.getLogger("privacy_guard.watchdog")

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy_server.py")
    cmd = [sys.executable, script, "--port", str(port)]
    if upstream:
        cmd += ["--upstream", upstream]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

    # Write watchdog PID
    _cleanup_watchdog()
    with open(WATCHDOG_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    _clear_stop_signal()

    retry_delay = 1
    max_delay = 30
    logger.info(
        "Watchdog started (PID: %d) — auto-restart on crash",
        os.getpid(),
    )

    # Signal handling: don't let the watchdog die on signals.
    # Forward to proxy, then let the loop decide whether to restart.
    _child_proc = None

    def _forward_signal(sig, frame):
        nonlocal _child_proc
        logger.info("Watchdog received signal %d, forwarding to proxy", sig)
        if _child_proc is not None and _child_proc.poll() is None:
            _child_proc.send_signal(sig)

    for sig_name in ("SIGINT", "SIGTERM"):
        try:
            sig = getattr(signal, sig_name)
            signal.signal(sig, _forward_signal)
        except (ValueError, AttributeError):
            pass

    while True:
        try:
            if os.path.exists(STOP_FILE):
                logger.info("Stop signal received")
                break

            proc = subprocess.Popen(cmd, env=env)
            _child_proc = proc
            logger.info("Proxy started (PID: %d)", proc.pid)

            # Poll while waiting, so we can check stop file
            while True:
                try:
                    proc.wait(timeout=1)
                    break  # Process finished
                except subprocess.TimeoutExpired:
                    if os.path.exists(STOP_FILE):
                        logger.info("Stop signal received — terminating proxy")
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            try:
                                proc.wait(timeout=2)
                            except subprocess.TimeoutExpired:
                                pass
                        break

            exit_code = proc.returncode
            if os.path.exists(STOP_FILE):
                logger.info("Proxy stopped (exit %d) — watchdog exiting", exit_code)
                break

            logger.warning(
                "Proxy exited (code %d). Restarting in %ds...",
                exit_code, retry_delay,
            )
        except Exception as e:
            logger.error("Watchdog error: %s — restarting proxy", e, exc_info=True)

        time.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, max_delay)

    _cleanup_watchdog()
    _clear_stop_signal()


def _cmd_stop():
    import signal
    import time
    from proxy_server import (
        stop_server, status_server, DEFAULT_PORT,
        WATCHDOG_PID_FILE, PID_FILE, _cleanup_watchdog, _signal_stop,
        _is_process_alive,
    )
    port = int(os.environ.get("PRIVACY_GUARD_PORT", str(DEFAULT_PORT)))

    # ── systemd --user ──
    if _is_supervised_by_systemd():
        try:
            subprocess.run(
                ["systemctl", "--user", "stop", _SYSTEMD_SERVICE],
                capture_output=True, text=True, timeout=10,
                check=True,
            )
            print("Proxy stopped (systemd)")
        except subprocess.CalledProcessError as e:
            print(f"Error stopping systemd service: {e.stderr.strip()}")
        return

    # ── launchd ──
    if _is_supervised_by_launchd():
        try:
            subprocess.run(
                ["launchctl", "unload", _LAUNCHD_PLIST],
                capture_output=True, text=True, timeout=10,
                check=True,
            )
            print("Proxy stopped (launchd)")
        except subprocess.CalledProcessError as e:
            print(f"Error stopping launchd service: {e.stderr.strip()}")
        return

    # ── Standalone (PID-file managed) ──
    # 1. Signal watchdog first
    _signal_stop()

    # 2. Stop proxy directly
    stop_server(port)

    # 3. If watchdog still alive, kill it
    try:
        with open(WATCHDOG_PID_FILE, "r") as f:
            pid = int(f.read().strip())
        if _is_process_alive(pid):
            os.kill(pid, signal.SIGTERM)
            print(f"Watchdog stopped (PID: {pid})")
    except (FileNotFoundError, ValueError, OSError):
        pass

    # 4. If proxy still alive, kill it too
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        if _is_process_alive(pid):
            os.kill(pid, signal.SIGTERM)
    except (FileNotFoundError, ValueError, OSError):
        pass

    # 5. Cleanup all files
    _cleanup_watchdog()
    from proxy_server import _clear_stop_signal, _cleanup
    _clear_stop_signal()
    _cleanup()
    time.sleep(0.2)


def _cmd_status():
    from proxy_server import (
        status_server, DEFAULT_PORT,
        WATCHDOG_PID_FILE, _is_process_alive, _cleanup_watchdog,
    )
    port = int(os.environ.get("PRIVACY_GUARD_PORT", str(DEFAULT_PORT)))

    supervisor = None

    # ── systemd --user ──
    if _is_supervised_by_systemd():
        supervisor = "systemd"
        try:
            result = subprocess.run(
                ["systemctl", "--user", "status", _SYSTEMD_SERVICE],
                capture_output=True, text=True, timeout=5,
            )
            # Extract the Active: line
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if stripped.startswith("Active:"):
                    print(f"Supervisor: systemd ({stripped})")
                    break
            else:
                print("Supervisor: systemd (service active)")
        except Exception:
            print("Supervisor: systemd")

    # ── launchd ──
    elif _is_supervised_by_launchd():
        supervisor = "launchd"
        print("Supervisor: launchd (KeepAlive enabled, auto-restart on crash)")

    # ── Standalone (PID-file managed) ──
    if not supervisor:
        watchdog_alive = False
        try:
            with open(WATCHDOG_PID_FILE, "r") as f:
                pid = int(f.read().strip())
            if _is_process_alive(pid):
                print(f"Watchdog running — PID {pid} (auto-restart active)")
                watchdog_alive = True
            else:
                _cleanup_watchdog()
        except (FileNotFoundError, ValueError, OSError):
            pass

    proxy_alive = status_server(port)


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
    from setup_tools import run_setup, register_auto_start, remove_auto_start

    port = args.port
    if port is None:
        env_port = os.environ.get("PRIVACY_GUARD_PORT")
        port = int(env_port) if env_port else DEFAULT_PORT

    upstream = args.upstream or os.environ.get("PRIVACY_GUARD_UPSTREAM") or ""

    if args.auto_start:
        ok = register_auto_start(port=port, upstream=upstream)
        if ok:
            # OS-level supervisors (systemd `enable --now`, launchd KeepAlive)
            # already start the proxy as part of registration. Only the
            # .desktop / Windows-VBS fallback paths need an immediate
            # watchdog spawn — those only schedule a next-login start.
            if not (_is_supervised_by_systemd() or _is_supervised_by_launchd()):
                from proxy_server import _run_daemon
                _run_daemon(port, upstream)
        sys.exit(0 if ok else 1)

    if args.remove_auto_start:
        ok = remove_auto_start()
        sys.exit(0 if ok else 1)

    sys.exit(run_setup(port=port, upstream=upstream, dry_run=args.dry_run))


def _cmd_fix(args):
    """Fix tool configs: restore originals if proxy dead, re-apply if alive."""
    from proxy_server import DEFAULT_PORT
    from setup_tools import fix_tools

    port = args.port
    if port is None:
        port = int(os.environ.get("PRIVACY_GUARD_PORT", str(DEFAULT_PORT)))

    count = fix_tools(port)
    # count=0 means no tools in manifest — not an error, just nothing to do.
    # Don't exit 1 here; systemd treats ExecStartPost failure as unit failure
    # and kills the proxy.


def _cmd_restore(args):
    """Restore all tool configs to their originals."""
    from proxy_server import DEFAULT_PORT
    from setup_tools import restore_tools

    port = args.port
    if port is None:
        port = int(os.environ.get("PRIVACY_GUARD_PORT", str(DEFAULT_PORT)))

    count = restore_tools(port)
    if count == 0:
        sys.exit(1)


def _cmd_teardown(args):
    """Full cleanup: restore, stop proxy, remove auto-start."""
    from proxy_server import DEFAULT_PORT
    from setup_tools import teardown

    port = args.port
    if port is None:
        port = int(os.environ.get("PRIVACY_GUARD_PORT", str(DEFAULT_PORT)))

    ok = teardown(port)
    sys.exit(0 if ok else 1)


def _cmd_config(args):
    """Manage config.yaml: list, set, unset upstream routes."""
    import yaml
    from privacy_engine.config import get_user_config_path

    config_path = get_user_config_path()

    def _load():
        if not config_path.exists():
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Error reading {config_path}: {e}")
            sys.exit(1)

    def _save(cfg):
        from setup_tools import _PRIVACY_GUARD_CONFIG_HEADER
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(_PRIVACY_GUARD_CONFIG_HEADER)
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)

    if args.action == "list":
        cfg = _load()
        routes = cfg.get("proxy", {}).get("upstream_map", {})
        managed = cfg.get("privacy_guard_managed", {}).get("upstream_map", {})

        if not routes:
            print("No upstream routes configured.")
            print("Add one with: privacy-guard config set <model> <url>")
            print("Or run: privacy-guard setup  (auto-detect local gateway)")
            return

        print("Upstream routes (model -> url):")
        for key, url in sorted(routes.items()):
            tag = " [managed]" if key in managed else " [user]"
            print(f"  {key:30} -> {url}{tag}")
        return

    if args.action == "set":
        if not args.model_key or not args.upstream:
            print("Usage: privacy-guard config set <model> <url>")
            print("Example: privacy-guard config set gpt-4 https://api.openai.com/v1")
            sys.exit(1)
        cfg = _load()
        cfg.setdefault("proxy", {}).setdefault("upstream_map", {})[args.model_key] = args.upstream
        cfg.setdefault("privacy_guard_managed", {}).setdefault("upstream_map", {})[args.model_key] = {
            "upstream": args.upstream,
            "set_by": "privacy-guard config set",
        }
        _save(cfg)
        print(f"  {args.model_key} -> {args.upstream}")
        return

    if args.action == "unset":
        if not args.model_key:
            print("Usage: privacy-guard config unset <model>")
            sys.exit(1)
        cfg = _load()
        removed = False
        for section in ("proxy", "privacy_guard_managed"):
            sub = cfg.get(section, {})
            if "upstream_map" in sub and args.model_key in sub["upstream_map"]:
                del sub["upstream_map"][args.model_key]
                removed = True
        if removed:
            _save(cfg)
            print(f"  removed upstream_map[{args.model_key}]")
        else:
            print(f"  upstream_map[{args.model_key}] not found")
        return


def _get_version() -> str:
    from privacy_engine import __version__
    return __version__


if __name__ == "__main__":
    main()
