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

# Providers built into opencode's AI SDK — don't need "npm" field
_BUILTIN_PROVIDERS = {
    "deepseek", "openai", "anthropic", "google", "google-vertex",
    "amazon-bedrock", "azure", "azure-cognitive", "groq",
    "together", "fireworks", "cerebras", "xai", "mistral",
    "perplexity", "cohere", "huggingface",
}


def _read_opencode_auth() -> list[str]:
    """Read opencode auth.json to find connected provider names (no keys exposed)."""
    auth_path = os.path.join(
        os.path.expanduser("~"), ".local", "share", "opencode", "auth.json"
    )
    if not os.path.isfile(auth_path):
        return []
    try:
        with open(auth_path, "r", encoding="utf-8") as f:
            auth_data = json.loads(f.read())
        return [k for k, v in auth_data.items() if isinstance(v, dict)]
    except Exception:
        return []

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
            with open(config_path, "r", encoding="utf-8-sig") as f:
                raw = f.read()

            cfg = _parse_jsonc(raw) if raw.strip() else {}

            modified = False
            providers = cfg.get("provider", {})

            if not providers:
                # No providers in config — add entries for each connected provider
                connected = _read_opencode_auth()
                if not connected:
                    messages.append(
                        f"  {config_path}: no providers configured and no auth found."
                        " Run opencode /connect first."
                    )
                    continue

                cfg["provider"] = cfg.get("provider", {})
                for prov_name in connected:
                    entry = {
                        "options": {"baseURL": proxy_url},
                    }
                    if prov_name not in _BUILTIN_PROVIDERS:
                        entry["npm"] = "@ai-sdk/openai-compatible"
                    cfg["provider"][prov_name] = entry
                    modified = True
                    messages.append(
                        f"  {config_path}: [{prov_name}] -> {proxy_url}"
                    )

                if modified and not dry_run:
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

            # Also add connected providers from auth.json not yet in config
            for prov_name in _read_opencode_auth():
                if prov_name not in providers:
                    entry = {"options": {"baseURL": proxy_url}}
                    if prov_name not in _BUILTIN_PROVIDERS:
                        entry["npm"] = "@ai-sdk/openai-compatible"
                    cfg["provider"][prov_name] = entry
                    modified = True
                    messages.append(
                        f"  {config_path}: [{prov_name}] (from auth) -> {proxy_url}"
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


# ── VS Code IDE forks (Cline, Roo Code, continue in IDE settings) ──

# Known VS Code-based IDE config directories
_VSCODE_IDE_DIRS: list[tuple[str, str]] = [
    ("Code", "VS Code"),
    ("Code - Insiders", "VS Code Insiders"),
    ("Cursor", "Cursor"),
    ("Windsurf", "Windsurf"),
    ("Trae CN", "Trae"),
    ("Trae", "Trae"),
]

# Cline / Roo Code extension IDs
_CLINE_EXTENSION_ID = "saoudrizwan.claude-dev"
_ROO_CLINE_EXTENSION_ID = "rooveterinaryinc.roo-cline"


def _find_vscode_settings() -> list[tuple[str, str]]:
    """Find all VS Code settings.json files. Returns [(path, ide_name), ...]."""
    results = []
    appdata = os.environ.get("APPDATA", "")
    for dirname, ide_name in _VSCODE_IDE_DIRS:
        settings_path = os.path.join(appdata, dirname, "User", "settings.json")
        if os.path.isfile(settings_path):
            results.append((settings_path, ide_name))
    return results


def setup_cline(port: int = 19999, dry_run: bool = False) -> list[str]:
    """Configure Cline/Roo Code extensions in all VS Code IDE forks.

    These extensions store API config in VS Code's settings.json
    under cline.* or roo-cline.* keys.
    Returns list of messages.
    """
    proxy_url = f"http://127.0.0.1:{port}"
    messages = []
    found_any = False

    for settings_path, ide_name in _find_vscode_settings():
        try:
            with open(settings_path, "r", encoding="utf-8-sig") as f:
                cfg = _parse_jsonc(f.read())

            modified = False
            base_url_keys = [
                "cline.openAiBaseUrl",
                "roo-cline.openAiBaseUrl",
            ]

            for key in base_url_keys:
                if key in cfg:
                    if cfg[key] == proxy_url:
                        messages.append(
                            f"  {ide_name}: [{key}] already configured"
                        )
                        continue
                    cfg[key] = proxy_url
                    modified = True
                    found_any = True
                    messages.append(
                        f"  {ide_name}: [{key}] -> {proxy_url}"
                    )

            if modified and not dry_run:
                _write_json(settings_path, cfg)

        except Exception as e:
            messages.append(f"  {ide_name}: error — {e}")

    if not found_any:
        messages.append(
            "  No Cline/Roo Code config found in any IDE."
            " Install Cline/Roo Code extension first."
        )

    return messages


# ── Auto-start on login ──


def register_auto_start() -> bool:
    """Register proxy to auto-start on login (cross-platform)."""
    if sys.platform == "win32":
        return _register_auto_start_windows()
    elif sys.platform == "linux":
        return _register_auto_start_linux()
    elif sys.platform == "darwin":
        return _register_auto_start_macos()
    else:
        print(f"Unsupported platform: {sys.platform}")
        return False


def remove_auto_start() -> bool:
    """Remove auto-start registration."""
    if sys.platform == "win32":
        return _remove_auto_start_windows()
    elif sys.platform == "linux":
        return _remove_auto_start_linux()
    elif sys.platform == "darwin":
        return _remove_auto_start_macos()
    else:
        print(f"Unsupported platform: {sys.platform}")
        return False


def _find_entry_point_cmd() -> str:
    """Return a command string that launches privacy-guard."""
    import shutil
    pg = shutil.which("privacy-guard")
    if pg:
        return f'"{pg}" start'
    cli_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli.py")
    if os.path.isfile(cli_path):
        return f'"{sys.executable}" "{cli_path}" start'
    return f'"{sys.executable}" -m cli start'


def _register_auto_start_windows() -> bool:
    """Create a VBS script in Windows Startup folder (no admin needed)."""
    startup = os.path.expandvars(
        r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
    )
    vbs_path = os.path.join(startup, "PrivacyGuard.vbs")
    cmd = _find_entry_point_cmd()
    # VBScript: run command with window hidden (0 = hide).
    # In VBS strings, double quotes are escaped by doubling: "" → "
    vbs_escaped = cmd.replace('"', '""')
    vbs_content = (
        f'CreateObject("Wscript.Shell").Run "{vbs_escaped}", 0, False'
    )
    try:
        os.makedirs(startup, exist_ok=True)
        with open(vbs_path, "w", encoding="utf-8") as f:
            f.write(vbs_content)
        print(f"✓ PrivacyGuard will auto-start on login (Startup folder)")
        return True
    except OSError as e:
        print(f"Error creating startup script: {e}")
        return False


def _remove_auto_start_windows() -> bool:
    """Remove PrivacyGuard from Windows Startup folder."""
    startup = os.path.expandvars(
        r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
    )
    vbs_path = os.path.join(startup, "PrivacyGuard.vbs")
    lnk_path = os.path.join(startup, "PrivacyGuard.lnk")
    removed = False
    for p in [vbs_path, lnk_path]:
        try:
            if os.path.isfile(p):
                os.remove(p)
                removed = True
        except OSError:
            pass
    if removed:
        print("✓ Auto-start removed from Startup folder")
    else:
        print("No auto-start registration found")
    return True


def _register_auto_start_linux() -> bool:
    """Create a .desktop file in ~/.config/autostart."""
    autostart_dir = os.path.join(os.path.expanduser("~"), ".config", "autostart")
    desktop_path = os.path.join(autostart_dir, "privacy-guard.desktop")
    cmd = _find_entry_point_cmd()
    desktop_content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=LLM Privacy Guard\n"
        f"Exec={cmd}\n"
        "Hidden=false\n"
        "NoDisplay=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    try:
        os.makedirs(autostart_dir, exist_ok=True)
        with open(desktop_path, "w", encoding="utf-8") as f:
            f.write(desktop_content)
        os.chmod(desktop_path, 0o755)
        print("✓ PrivacyGuard will auto-start on login (autostart)")
        return True
    except OSError as e:
        print(f"Error creating autostart entry: {e}")
        return False


def _remove_auto_start_linux() -> bool:
    desktop_path = os.path.join(
        os.path.expanduser("~"), ".config", "autostart", "privacy-guard.desktop"
    )
    try:
        if os.path.isfile(desktop_path):
            os.remove(desktop_path)
            print("✓ Auto-start removed")
        else:
            print("No auto-start registration found")
        return True
    except OSError as e:
        print(f"Error removing autostart: {e}")
        return False


def _register_auto_start_macos() -> bool:
    """Create a launchd plist in ~/Library/LaunchAgents."""
    launch_agents = os.path.join(
        os.path.expanduser("~"), "Library", "LaunchAgents"
    )
    plist_path = os.path.join(launch_agents, "com.privacyguard.plist")
    cmd = _find_entry_point_cmd()
    plist_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "    <key>Label</key>\n"
        "    <string>com.privacyguard</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
    )
    for part in cmd.split('"'):
        if part.strip():
            plist_content += f"        <string>{part}</string>\n"
    plist_content += (
        "    </array>\n"
        "    <key>RunAtLoad</key>\n"
        "    <true/>\n"
        "    <key>KeepAlive</key>\n"
        "    <true/>\n"  # Auto-restart if crashes!
        "</dict>\n"
        "</plist>\n"
    )
    try:
        os.makedirs(launch_agents, exist_ok=True)
        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(plist_content)
        os.chmod(plist_path, 0o644)
        import subprocess
        subprocess.run(["launchctl", "load", plist_path], capture_output=True)
        print("✓ PrivacyGuard will auto-start on login (launchd)")
        return True
    except OSError as e:
        print(f"Error creating launchd plist: {e}")
        return False


def _remove_auto_start_macos() -> bool:
    plist_path = os.path.join(
        os.path.expanduser("~"), "Library", "LaunchAgents", "com.privacyguard.plist"
    )
    try:
        if os.path.isfile(plist_path):
            import subprocess
            subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
            os.remove(plist_path)
            print("✓ Auto-start removed")
        else:
            print("No auto-start registration found")
        return True
    except OSError as e:
        print(f"Error removing launchd plist: {e}")
        return False


# ── Unified setup ──

TOOL_SETUP_FUNCTIONS = {
    "opencode": setup_opencode,
    "continue": setup_continue,
    "cline": setup_cline,
}


def run_setup(port: int = 19999, upstream: str = "", dry_run: bool = False) -> int:
    """Run auto-setup for all detected tools.

    Starts the proxy in daemon mode if not already running,
    then configures each detected tool.

    upstream is optional — the proxy auto-detects the target provider
    from the request body's model field.

    Returns number of tools configured.
    """
    from proxy_server import status_server, _run_daemon, DEFAULT_PORT

    port = port or DEFAULT_PORT
    configured = 0

    print(f"LLM Privacy Guard — Auto Setup")
    print(f"  Proxy: http://127.0.0.1:{port}")
    if upstream:
        print(f"  Fallback upstream: {upstream}")
    else:
        print(f"  Upstream: auto-detect from request model (DeepSeek, OpenAI, Anthropic, etc.)")
    print()

    # ── Start proxy if not running ──
    if not status_server(port):
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
