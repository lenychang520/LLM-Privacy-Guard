# -*- coding: utf-8 -*-
"""LLM Privacy Guard — Auto-setup for LLM clients

Detects installed tools (opencode, Continue, Cline, etc.) and
automatically configures them to route through the privacy proxy.

Usage:
    from setup_tools import setup_opencode, setup_continue
    setup_opencode(port=19999)
    setup_continue(port=19999)
"""

import json
import os
import re
import sys

# ── JSONC / trailing-comma tolerant parser ──

_JSONC_LINE_COMMENT = re.compile(r"(?<!:)//.*$", re.MULTILINE)
_JSONC_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_JSONC_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def _parse_jsonc(text: str) -> dict:
    """Parse JSON with comments and trailing commas into a dict."""
    # Normalize line endings (Windows \r\n → \n)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _JSONC_BLOCK_COMMENT.sub("", text)
    text = _JSONC_LINE_COMMENT.sub("", text)
    text = _JSONC_TRAILING_COMMA.sub(r"\1", text)
    return json.loads(text)


def _write_json(path: str, data: dict):
    """Write dict as formatted JSON file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ── opencode ──

def _find_opencode_configs() -> list[str]:
    """Find all opencode config files available."""
    candidates = []

    cwd = os.getcwd()
    home = os.path.expanduser("~")

    for base, name in [(cwd, "opencode.json"), (cwd, "opencode.jsonc")]:
        path = os.path.join(base, name)
        if os.path.isfile(path):
            candidates.append(path)

    for base in [cwd, home]:
        for sub in [".opencode"]:
            for name in ["opencode.json", "opencode.jsonc"]:
                path = os.path.join(base, sub, name)
                if os.path.isfile(path):
                    candidates.append(path)

    global_base = os.path.join(home, ".config", "opencode")
    for name in ["opencode.json", "opencode.jsonc"]:
        path = os.path.join(global_base, name)
        if os.path.isfile(path):
            candidates.append(path)

    return candidates


def setup_opencode(port: int = 19999, dry_run: bool = False) -> list[str]:
    """Configure all found opencode configs to route LLM calls through proxy.

    For each existing provider in the config, sets baseURL to the proxy.
    Returns list of messages describing what was done.
    """
    proxy_url = f"http://127.0.0.1:{port}"
    messages = []
    configs = _find_opencode_configs()

    if not configs:
        # Create a global config as fallback
        global_path = os.path.join(
            os.path.expanduser("~"), ".config", "opencode", "opencode.json"
        )
        messages.append(
            "No opencode config found. Create one first with:  opencode /init"
        )
        return messages

    for config_path in configs:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = f.read()

            cfg = _parse_jsonc(raw) if raw.strip() else {}

            modified = False
            providers = cfg.get("provider", {})

            if not providers:
                # No providers configured — add a generic proxy provider template
                cfg["provider"] = cfg.get("provider", {})
                cfg["provider"]["privacy-guard"] = {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Privacy Guard (proxy)",
                    "options": {"baseURL": proxy_url},
                }
                modified = True
                messages.append(
                    f"  {config_path}: added [privacy-guard] proxy provider"
                )
                messages.append(
                    "    Note: rename 'privacy-guard' to match your actual provider"
                    " (e.g. deepseek, openai)"
                )
                if not dry_run:
                    _write_json(config_path, cfg)
                continue

            for prov_name, prov_cfg in list(providers.items()):
                if not isinstance(prov_cfg, dict):
                    continue

                # Skip local providers (ollama, lmstudio, etc.)
                existing_base = (
                    prov_cfg.get("options", {}).get("baseURL", "")
                    or prov_cfg.get("options", {}).get("endpoint", "")
                )
                if "localhost" in existing_base or "127.0.0.1" in existing_base:
                    messages.append(
                        f"  {config_path}: [{prov_name}] already local, skipping"
                    )
                    continue

                prov_cfg.setdefault("options", {})["baseURL"] = proxy_url
                modified = True
                messages.append(
                    f"  {config_path}: [{prov_name}] -> {proxy_url}"
                )

            if modified and not dry_run:
                _write_json(config_path, cfg)

            if not modified:
                messages.append(f"  {config_path}: already configured, nothing to do")

        except Exception as e:
            messages.append(f"  {config_path}: error — {e}")

    return messages


# ── Continue (VS Code) ──

_CONTINUE_CONFIG_PATHS = [
    os.path.join(os.path.expanduser("~"), ".continue", "config.json"),
    os.path.join(os.path.expanduser("~"), ".continue", "config.ts"),
]


def setup_continue(port: int = 19999, dry_run: bool = False) -> list[str]:
    """Configure Continue.dev to route through the proxy.

    Continue uses a JSON config. We set apiBase for each model provider.
    Returns list of messages.
    """
    proxy_url = f"http://127.0.0.1:{port}"
    messages = []

    config_path = None
    for p in _CONTINUE_CONFIG_PATHS:
        if os.path.isfile(p):
            config_path = p
            break

    if not config_path:
        messages.append("Continue config not found at ~/.continue/config.json")
        return messages

    # Continue's config.ts is actually a TypeScript/JS file, not JSON.
    # We skip .ts files and only handle .json
    if config_path.endswith(".ts"):
        messages.append(
            f"  {config_path}: .ts format, please manually set apiBase to {proxy_url}"
        )
        return messages

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = _parse_jsonc(f.read())

        modified = False
        for model in cfg.get("models", []):
            if not isinstance(model, dict):
                continue
            if model.get("apiBase"):
                continue  # Already has a custom base
            model["apiBase"] = proxy_url
            modified = True
            messages.append(
                f"  {config_path}: [{model.get('title', model.get('model', '?'))}] -> {proxy_url}"
            )

        if modified and not dry_run:
            _write_json(config_path, cfg)

        if not modified:
            messages.append(f"  {config_path}: already configured")

    except Exception as e:
        messages.append(f"  {config_path}: error — {e}")

    return messages


# ── Unified setup ──

TOOL_SETUP_FUNCTIONS = {
    "opencode": setup_opencode,
    "continue": setup_continue,
}


def run_setup(port: int = 19999, upstream: str = "", dry_run: bool = False) -> int:
    """Run auto-setup for all detected tools.

    Starts the proxy in daemon mode if not already running,
    then configures each detected tool.

    Returns number of tools configured.
    """
    from proxy_server import status_server, _run_daemon, DEFAULT_PORT

    port = port or DEFAULT_PORT
    configured = 0

    print(f"LLM Privacy Guard — Auto Setup")
    print(f"  Proxy: http://127.0.0.1:{port}")
    if upstream:
        print(f"  Upstream: {upstream}")
    print()

    # ── Start proxy if not running ──
    if not status_server(port):
        if not upstream:
            print(
                "Warning: upstream not set. Proxy will start but won't forward requests.\n"
                "  Set --upstream or PRIVACY_GUARD_UPSTREAM to fix this."
            )
        if not dry_run:
            _run_daemon(port, upstream or "")
    else:
        print("Proxy is already running.")
    print()

    # ── Configure each tool ──
    for tool_name, setup_fn in TOOL_SETUP_FUNCTIONS.items():
        print(f"[{tool_name}]")
        msgs = setup_fn(port=port, dry_run=dry_run)
        if msgs:
            for msg in msgs:
                print(msg)
            configured += 1
        else:
            print(f"  Not detected.")
        print()

    print("─" * 50)
    if configured:
        print(f"Configured {configured} tool(s). Your LLM traffic is now filtered.")
        print(f"Proxy running at http://127.0.0.1:{port}")
    else:
        print("No tools detected. Manually set your LLM client's API base URL to:")
        print(f"  http://127.0.0.1:{port}")

    return configured
