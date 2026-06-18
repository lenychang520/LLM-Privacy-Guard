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
import subprocess
import sys
from pathlib import Path

# ── JSONC / trailing-comma tolerant parser ──

_JSONC_LINE_COMMENT = re.compile(r"(?<!:)//.*$", re.MULTILINE)
_JSONC_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_JSONC_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


# ── Manifest — records original tool configs so we can restore them ──

_MANIFEST_DIR = os.path.join(
    os.path.expanduser("~"), ".config", "llm-privacy-guard"
)
_MANIFEST_PATH = os.path.join(_MANIFEST_DIR, "tool-manifest.json")


def _load_manifest() -> dict:
    """Load the tool config manifest, or return empty on first run."""
    if not os.path.isfile(_MANIFEST_PATH):
        return {"version": 1, "tools": []}
    try:
        with open(_MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except Exception:
        return {"version": 1, "tools": []}


def _save_manifest(manifest: dict):
    """Persist the manifest to disk."""
    os.makedirs(_MANIFEST_DIR, exist_ok=True)
    with open(_MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _record_original(tool: str, path: str, **kwargs):
    """Record a tool's original config in the manifest.

    Only records if this path+tool combo isn't already in the manifest.
    The original values are stored so restore() can revert them.
    """
    manifest = _load_manifest()
    tools = manifest.get("tools", [])

    # Don't duplicate entries — update if path+tool matches
    for entry in tools:
        if entry.get("path") == path and entry.get("tool") == tool:
            entry["original"] = kwargs
            _save_manifest(manifest)
            return

    tools.append({
        "tool": tool,
        "path": path,
        "original": kwargs,
    })
    manifest["tools"] = tools
    _save_manifest(manifest)


def _clear_manifest():
    """Remove the manifest file."""
    try:
        os.remove(_MANIFEST_PATH)
    except OSError:
        pass


def _is_proxy_reachable(port: int = 19999) -> bool:
    """Check if the privacy guard proxy is alive on localhost."""
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
        return True
    except Exception:
        return False


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


def _normalize_model_key(model: str) -> str:
    """Normalize a model name into a stable config key fragment."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", model.strip().lower()).strip("-")
    return cleaned or "default-model"


def _related_codex_models(model: str) -> list[str]:
    """Return the active model plus a few closely related Codex/OpenAI variants."""
    candidates = []
    seen = set()

    def _add(value: str):
        if value and value not in seen:
            seen.add(value)
            candidates.append(value)

    model = (model or "").strip()
    _add(model)

    model_lower = model.lower()
    if model_lower in {"gpt-5.4", "gpt-5.4-mini", "gpt-5.5"}:
        _add("gpt-5.4")
        _add("gpt-5.4-mini")
        _add("gpt-5.5")

    return candidates


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

                # Record original before overwriting
                original_base = existing_base or prov_cfg.get("options", {}).get("baseURL", "")
                if original_base and original_base != proxy_url:
                    _record_original("opencode", config_path,
                                     provider=prov_name,
                                     baseURL=original_base)

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
        for idx, model in enumerate(cfg.get("models", [])):
            if not isinstance(model, dict):
                continue
            if model.get("apiBase"):
                continue  # Already has a custom base
            _record_original("continue", config_path,
                             modelIndex=idx,
                             modelTitle=model.get("title", model.get("model", "?")),
                             apiBase=None)  # None = no original — we added it
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
                    _record_original("cline", settings_path,
                                     key=key,
                                     ideName=ide_name,
                                     value=cfg[key])
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


# ── Codex ───────────────────────────────────────────────────────────────────

_CODEX_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".codex", "config.toml")


def _quote_toml_string(value: str) -> str:
    """Quote a TOML basic string safely."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _ensure_proxy_upstream_mapping(
    model: str,
    upstream: str,
    dry_run: bool = False,
) -> str:
    """Persist a model -> upstream override in the user's config.yaml."""
    import yaml
    from privacy_engine.config import get_user_config_path

    config_path = get_user_config_path()
    key = _normalize_model_key(model)

    try:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        else:
            cfg = {}
    except Exception:
        cfg = {}

    cfg.setdefault("proxy", {})
    cfg["proxy"].setdefault("upstream_map", {})
    existing = cfg["proxy"]["upstream_map"].get(key)
    cfg["proxy"]["upstream_map"][key] = upstream

    if not dry_run:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)

    if existing == upstream:
        return f"  config.yaml: upstream_map[{key}] already points to {upstream}"
    return f"  config.yaml: upstream_map[{key}] -> {upstream}"


def _ensure_proxy_upstream_mappings(
    models: list[str],
    upstream: str,
    dry_run: bool = False,
) -> list[str]:
    """Persist multiple model -> upstream overrides."""
    messages = []
    for model in models:
        messages.append(
            _ensure_proxy_upstream_mapping(model, upstream, dry_run=dry_run)
        )
    return messages


def setup_codex(port: int = 19999, dry_run: bool = False) -> list[str]:
    """Configure Codex to route its current model provider through the proxy."""
    proxy_url = f"http://127.0.0.1:{port}"
    messages = []

    if not os.path.isfile(_CODEX_CONFIG_PATH):
        messages.append("Codex config not found at ~/.codex/config.toml")
        return messages

    try:
        with open(_CODEX_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        return [f"  {_CODEX_CONFIG_PATH}: error - {e}"]

    provider_match = re.search(r'(?m)^model_provider\s*=\s*"([^"]+)"\s*$', raw)
    model_match = re.search(r'(?m)^model\s*=\s*"([^"]+)"\s*$', raw)
    if not provider_match:
        return [f"  {_CODEX_CONFIG_PATH}: model_provider not found"]

    provider = provider_match.group(1)
    model = model_match.group(1) if model_match else ""
    section_pattern = (
        r'(?ms)^(\[model_providers\.'
        + re.escape(provider)
        + r'\]\s*$)(.*?)(?=^\[|\Z)'
    )
    section_match = re.search(section_pattern, raw)
    if not section_match:
        return [f"  {_CODEX_CONFIG_PATH}: provider section [{provider}] not found"]

    section_header = section_match.group(1)
    section_body = section_match.group(2)
    base_match = re.search(r'(?m)^base_url\s*=\s*"([^"]+)"\s*$', section_body)
    if not base_match:
        return [f"  {_CODEX_CONFIG_PATH}: [{provider}] has no base_url"]

    original_base = base_match.group(1)
    if "127.0.0.1" in original_base or "localhost" in original_base:
        messages.append(f"  {_CODEX_CONFIG_PATH}: [{provider}] already local, skipping")
        return messages

    _record_original("codex", _CODEX_CONFIG_PATH,
                     provider=provider,
                     model=model,
                     base_url=original_base)

    mapping_keys = _related_codex_models(model or provider)
    messages.extend(
        _ensure_proxy_upstream_mappings(mapping_keys, original_base, dry_run=dry_run)
    )

    new_section_body, replaced = re.subn(
        r'(?m)^base_url\s*=\s*"([^"]+)"\s*$',
        f"base_url = {_quote_toml_string(proxy_url)}",
        section_body,
        count=1,
    )
    if replaced != 1:
        return [f"  {_CODEX_CONFIG_PATH}: failed to rewrite [{provider}] base_url"]

    new_section = section_header + new_section_body
    updated = raw[:section_match.start()] + new_section + raw[section_match.end():]

    if not dry_run:
        with open(_CODEX_CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(updated)

    route_note = f" (model {model!r})" if model else ""
    messages.append(f"  {_CODEX_CONFIG_PATH}: [{provider}] -> {proxy_url}{route_note}")
    return messages


# ── Auto-start on login ──


def register_auto_start(port: int = 19999, upstream: str = "") -> bool:
    """Register proxy to auto-start on login (cross-platform)."""
    if sys.platform == "win32":
        return _register_auto_start_windows()
    elif sys.platform == "linux":
        return _register_auto_start_linux(port, upstream)
    elif sys.platform == "darwin":
        return _register_auto_start_macos(port, upstream)
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


def _find_entry_point_cmd(mode: str = "start") -> str:
    """Return a command string that launches privacy-guard.

    mode: the CLI subcommand + flags, e.g. "start" or "start --foreground".
    Used by VBS (Windows) and .desktop (Linux fallback).
    """
    import shutil
    pg = shutil.which("privacy-guard")
    if pg:
        return f'"{pg}" {mode}'
    cli_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli.py")
    if os.path.isfile(cli_path):
        return f'"{sys.executable}" "{cli_path}" {mode}'
    return f'"{sys.executable}" -m cli {mode}'


def _find_entry_point_args(mode: str = "start") -> list[str]:
    """Return an argv list for systemd / launchd.

    mode: the CLI subcommand + flags, e.g. "start" or "start --foreground".
    Returns a list of individual argument strings.
    """
    import shutil
    pg = shutil.which("privacy-guard")
    if pg:
        return [pg] + mode.split()
    cli_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli.py")
    if os.path.isfile(cli_path):
        return [sys.executable, cli_path] + mode.split()
    return [sys.executable, "-m", "cli"] + mode.split()


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


# ── systemd (Linux) ──

_SYSTEMD_SERVICE_NAME = "privacy-guard.service"
_SYSTEMD_USER_UNIT_DIR = os.path.join(
    os.path.expanduser("~"), ".config", "systemd", "user"
)


def _is_systemd_available() -> bool:
    """Check if systemd --user is usable."""
    import shutil
    if not shutil.which("systemctl"):
        return False
    # systemd --user requires the user manager to be running
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-system-running"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _register_auto_start_systemd(port: int, upstream: str) -> bool:
    """Create and enable a systemd --user service with Restart=always.

    systemd is NOT a Python process — it survives pkill python and
    restarts the proxy within seconds.

    Uses start --foreground so there is ONE Python process.
    systemd replaces both the watchdog and the daemon launcher.
    """
    import shutil
    import subprocess as sp

    unit_dir = _SYSTEMD_USER_UNIT_DIR
    unit_path = os.path.join(unit_dir, _SYSTEMD_SERVICE_NAME)

    args = _find_entry_point_args("start --foreground")
    # Build ExecStart: join with spaces; systemd handles this safely
    # because args are already individual tokens.
    exec_start = " ".join(args)
    if port != 19999:
        exec_start += f" --port {port}"
    if upstream:
        exec_start += f" --upstream {upstream}"

    # Build fix command for ExecStartPost (re-apply proxy when it comes up)
    fix_args = _find_entry_point_args("fix")
    exec_post = " ".join(fix_args)
    if port != 19999:
        exec_post += f" --port {port}"

    unit_content = (
        "[Unit]\n"
        "Description=LLM Privacy Guard — local proxy for sensitive-data filtering\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={exec_start}\n"
        f"ExecStartPost={exec_post}\n"
        "Restart=always\n"
        "RestartSec=3\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )

    try:
        os.makedirs(unit_dir, exist_ok=True)
        with open(unit_path, "w", encoding="utf-8") as f:
            f.write(unit_content)
        sp.run(["systemctl", "--user", "daemon-reload"], check=True,
               capture_output=True, text=True)
        sp.run(["systemctl", "--user", "enable", "--now",
                _SYSTEMD_SERVICE_NAME], check=True,
               capture_output=True, text=True)
        print("✓ PrivacyGuard will auto-start on login (systemd)")
        print(f"  Service: {unit_path}")
        print("  systemd will restart the proxy automatically if it crashes.")
        return True
    except (OSError, sp.CalledProcessError) as e:
        stderr = getattr(e, "stderr", "")
        print(f"Error creating systemd service: {e}")
        if stderr:
            print(f"  {stderr.strip()}")
        return False


def _remove_auto_start_systemd() -> bool:
    """Disable and remove the systemd --user service."""
    import subprocess as sp

    unit_path = os.path.join(_SYSTEMD_USER_UNIT_DIR, _SYSTEMD_SERVICE_NAME)
    removed = False

    # Try to stop + disable even if unit file already gone
    try:
        sp.run(["systemctl", "--user", "stop", _SYSTEMD_SERVICE_NAME],
               capture_output=True, text=True)
        sp.run(["systemctl", "--user", "disable", _SYSTEMD_SERVICE_NAME],
               capture_output=True, text=True)
    except Exception:
        pass

    try:
        if os.path.isfile(unit_path):
            os.remove(unit_path)
            sp.run(["systemctl", "--user", "daemon-reload"],
                   capture_output=True, text=True)
            removed = True
    except OSError:
        pass

    if removed:
        print("✓ Auto-start removed (systemd)")
    return True


# ── .desktop autostart (Linux fallback) ──

_DESKTOP_PATH = os.path.join(
    os.path.expanduser("~"), ".config", "autostart", "privacy-guard.desktop"
)


def _register_auto_start_linux(port: int = 19999, upstream: str = "") -> bool:
    """Create a .desktop file OR systemd service for auto-start on login.

    Prefers systemd --user when available (survives pkill python).
    Falls back to XDG .desktop autostart on non-systemd systems.
    """
    if _is_systemd_available():
        # Remove stale .desktop if migrating from older version
        if os.path.isfile(_DESKTOP_PATH):
            try:
                os.remove(_DESKTOP_PATH)
            except OSError:
                pass
        return _register_auto_start_systemd(port, upstream)

    # Fallback: XDG .desktop autostart
    autostart_dir = os.path.dirname(_DESKTOP_PATH)
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
        with open(_DESKTOP_PATH, "w", encoding="utf-8") as f:
            f.write(desktop_content)
        os.chmod(_DESKTOP_PATH, 0o755)
        print("✓ PrivacyGuard will auto-start on login (autostart)")
        return True
    except OSError as e:
        print(f"Error creating autostart entry: {e}")
        return False


def _remove_auto_start_linux() -> bool:
    """Remove auto-start registration (handles both systemd and .desktop)."""
    any_removed = False

    # Remove systemd service if present
    unit_path = os.path.join(_SYSTEMD_USER_UNIT_DIR, _SYSTEMD_SERVICE_NAME)
    if os.path.isfile(unit_path):
        _remove_auto_start_systemd()
        any_removed = True

    # Remove stale .desktop file
    if os.path.isfile(_DESKTOP_PATH):
        try:
            os.remove(_DESKTOP_PATH)
            print("✓ Auto-start removed (autostart .desktop)")
            any_removed = True
        except OSError as e:
            print(f"Error removing autostart: {e}")

    if not any_removed:
        print("No auto-start registration found")
    return True


def _register_auto_start_macos(port: int = 19999, upstream: str = "") -> bool:
    """Create a launchd plist in ~/Library/LaunchAgents.

    Uses start --foreground: a single Python process. launchd's KeepAlive
    flag handles crash recovery, so the Python watchdog is redundant.
    """
    launch_agents = os.path.join(
        os.path.expanduser("~"), "Library", "LaunchAgents"
    )
    plist_path = os.path.join(launch_agents, "com.privacyguard.plist")

    mode = "start --foreground"
    if port != 19999:
        mode += f" --port {port}"
    if upstream:
        mode += f" --upstream {upstream}"
    args = _find_entry_point_args(mode)

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
    for arg in args:
        plist_content += f"        <string>{arg}</string>\n"
    plist_content += (
        "    </array>\n"
        "    <key>RunAtLoad</key>\n"
        "    <true/>\n"
        "    <key>KeepAlive</key>\n"
        "    <true/>\n"  # Auto-restart if crashes — survives pkill python
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
        print("  launchd will restart the proxy automatically if it crashes.")
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


# ── Claude Code ──

_CLAUDE_SETTINGS_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "settings.json"
)


def setup_claude(port: int = 19999, dry_run: bool = False) -> list[str]:
    """Configure Claude Code to route through the proxy.

    Claude Code reads ANTHROPIC_BASE_URL from settings.json's env section.
    We save the original upstream in config.yaml (so the proxy can auto-route
    by model name), then point Claude Code at the local proxy.
    """
    proxy_url = f"http://127.0.0.1:{port}"
    messages = []

    if not os.path.isfile(_CLAUDE_SETTINGS_PATH):
        messages.append("Claude Code settings not found at ~/.claude/settings.json")
        return messages

    # Parse settings.json
    try:
        with open(_CLAUDE_SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = json.loads(f.read())
    except Exception as e:
        return [f"  {_CLAUDE_SETTINGS_PATH}: error parsing JSON — {e}"]

    env = settings.get("env", {})
    if not isinstance(env, dict):
        return [f"  {_CLAUDE_SETTINGS_PATH}: 'env' section missing or invalid"]

    original_base = env.get("ANTHROPIC_BASE_URL", "")
    if not original_base:
        # Claude Code defaults to api.anthropic.com when no env var is set
        original_base = "https://api.anthropic.com"

    if "127.0.0.1" in original_base or "localhost" in original_base:
        messages.append(f"  {_CLAUDE_SETTINGS_PATH}: already configured for local proxy")
        return messages

    _record_original("claude", _CLAUDE_SETTINGS_PATH,
                     baseURL=original_base,
                     model=settings.get("model", ""))

    # Save original upstream in config.yaml so proxy auto-routes correctly
    model_name = settings.get("model", "")
    if model_name:
        key = _normalize_model_key(model_name)
        messages.append(
            _ensure_proxy_upstream_mapping(key, original_base, dry_run=dry_run)
        )
        # Also register a broad key based on model base name for flexibility
        short_key = key.rsplit("-", 1)[0] if "-" in key else key
        if short_key != key and len(short_key) >= 3:
            messages.append(
                _ensure_proxy_upstream_mapping(short_key, original_base, dry_run=dry_run)
            )

    # Update ANTHROPIC_BASE_URL to point at the proxy
    if not dry_run:
        settings.setdefault("env", {})["ANTHROPIC_BASE_URL"] = proxy_url
        with open(_CLAUDE_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
            f.write("\n")

    model_note = f" (model {model_name!r})" if model_name else ""
    messages.append(f"  {_CLAUDE_SETTINGS_PATH}: ANTHROPIC_BASE_URL -> {proxy_url}{model_note}")
    return messages


# ── Recovery: restore original configs when proxy is dead ──


def _restore_entry(entry: dict, port: int) -> bool:
    """Revert a single tool entry to its original config. Returns True on success."""
    tool = entry.get("tool")
    path = entry.get("path")
    original = entry.get("original", {})

    if not tool or not path or not os.path.isfile(path):
        return False

    try:
        if tool == "opencode":
            return _restore_opencode(path, original)
        elif tool == "claude":
            return _restore_claude(path, original)
        elif tool == "cline":
            return _restore_cline(path, original)
        elif tool == "codex":
            return _restore_codex(path, original)
        elif tool == "continue":
            return _restore_continue(path, original)
    except Exception:
        return False
    return False


def _restore_opencode(path: str, original: dict) -> bool:
    """Restore an opencode provider's original baseURL."""
    provider = original.get("provider")
    base_url = original.get("baseURL")
    if not provider:
        return False

    with open(path, "r", encoding="utf-8-sig") as f:
        cfg = _parse_jsonc(f.read())
    prov = cfg.get("provider", {}).get(provider)
    if isinstance(prov, dict):
        prov.setdefault("options", {})["baseURL"] = base_url
        _write_json(path, cfg)
        return True
    return False


def _restore_claude(path: str, original: dict) -> bool:
    """Restore Claude Code's original ANTHROPIC_BASE_URL."""
    base_url = original.get("baseURL")
    if not base_url:
        return False

    with open(path, "r", encoding="utf-8") as f:
        settings = json.loads(f.read())
    settings.setdefault("env", {})["ANTHROPIC_BASE_URL"] = base_url
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return True


def _restore_cline(path: str, original: dict) -> bool:
    """Restore a Cline/Roo Code settings key to its original value."""
    key = original.get("key")
    value = original.get("value")
    if not key:
        return False

    with open(path, "r", encoding="utf-8-sig") as f:
        cfg = _parse_jsonc(f.read())
    cfg[key] = value
    _write_json(path, cfg)
    return True


def _restore_codex(path: str, original: dict) -> bool:
    """Restore Codex provider's original base_url in config.toml."""
    provider = original.get("provider")
    base_url = original.get("base_url")
    if not provider or not base_url:
        return False

    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    section_pattern = (
        r'(?ms)^(\[model_providers\.'
        + re.escape(provider)
        + r'\]\s*$)(.*?)(?=^\[|\Z)'
    )
    m = re.search(section_pattern, raw)
    if not m:
        return False

    section_header = m.group(1)
    section_body = m.group(2)
    new_body, replaced = re.subn(
        r'(?m)^base_url\s*=\s*"[^"]*"\s*$',
        f'base_url = "{base_url}"',
        section_body,
        count=1,
    )
    if replaced != 1:
        return False

    updated = raw[:m.start()] + section_header + new_body + raw[m.end():]
    with open(path, "w", encoding="utf-8") as f:
        f.write(updated)
    return True


def _restore_continue(path: str, original: dict) -> bool:
    """Restore a Continue.dev model config — remove the apiBase we added."""
    idx = original.get("modelIndex")
    if idx is None:
        return False

    with open(path, "r", encoding="utf-8") as f:
        cfg = _parse_jsonc(f.read())

    models = cfg.get("models", [])
    if idx < len(models) and isinstance(models[idx], dict):
        models[idx].pop("apiBase", None)
        _write_json(path, cfg)
        return True
    return False


def _reapply_proxy_configs(port: int) -> int:
    """Re-apply proxy configs to all tools in the manifest. Returns count."""
    manifest = _load_manifest()
    proxy_url = f"http://127.0.0.1:{port}"
    tools = manifest.get("tools", [])
    if not tools:
        print("No tool configs to re-apply.")
        return 0

    count = 0
    for entry in tools:
        tool = entry.get("tool")
        path = entry.get("path")
        if not tool or not path or not os.path.isfile(path):
            print(f"  [{tool}] skipping — config file not found: {path}")
            continue
        try:
            if _apply_proxy_to_entry(entry, proxy_url):
                print(f"  [{tool}] {path} -> {proxy_url}")
                count += 1
        except Exception as e:
            print(f"  [{tool}] {path}: error — {e}")
    return count


def _apply_proxy_to_entry(entry: dict, proxy_url: str) -> bool:
    """Apply the proxy URL to a single tool entry. Used by re-apply."""
    tool = entry.get("tool")
    path = entry.get("path")

    if tool == "claude":
        with open(path, "r", encoding="utf-8") as f:
            settings = json.loads(f.read())
        settings.setdefault("env", {})["ANTHROPIC_BASE_URL"] = proxy_url
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return True

    elif tool == "opencode":
        provider = entry.get("original", {}).get("provider")
        if not provider:
            return False
        with open(path, "r", encoding="utf-8-sig") as f:
            cfg = _parse_jsonc(f.read())
        prov = cfg.get("provider", {}).get(provider)
        if isinstance(prov, dict):
            prov.setdefault("options", {})["baseURL"] = proxy_url
            _write_json(path, cfg)
            return True
        return False

    elif tool == "cline":
        key = entry.get("original", {}).get("key")
        if not key:
            return False
        with open(path, "r", encoding="utf-8-sig") as f:
            cfg = _parse_jsonc(f.read())
        cfg[key] = proxy_url
        _write_json(path, cfg)
        return True

    elif tool == "codex":
        provider = entry.get("original", {}).get("provider")
        if not provider:
            return False
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        section_pattern = (
            r'(?ms)^(\[model_providers\.'
            + re.escape(provider)
            + r'\]\s*$)(.*?)(?=^\[|\Z)'
        )
        m = re.search(section_pattern, raw)
        if not m:
            return False
        new_body, replaced = re.subn(
            r'(?m)^base_url\s*=\s*"[^"]*"\s*$',
            f'base_url = {_quote_toml_string(proxy_url)}',
            m.group(2),
            count=1,
        )
        if replaced != 1:
            return False
        updated = raw[:m.start()] + m.group(1) + new_body + raw[m.end():]
        with open(path, "w", encoding="utf-8") as f:
            f.write(updated)
        return True

    elif tool == "continue":
        idx = entry.get("original", {}).get("modelIndex")
        if idx is None:
            return False
        with open(path, "r", encoding="utf-8") as f:
            cfg = _parse_jsonc(f.read())
        models = cfg.get("models", [])
        if idx < len(models) and isinstance(models[idx], dict):
            models[idx]["apiBase"] = proxy_url
            _write_json(path, cfg)
            return True
        return False

    return False


def restore_tools(port: int = 19999) -> int:
    """Restore all tool configs to their originals. Returns count."""
    manifest = _load_manifest()
    tools = manifest.get("tools", [])
    if not tools:
        print("No tool configs to restore.")
        return 0

    count = 0
    for entry in tools:
        tool = entry.get("tool")
        path = entry.get("path")
        original = entry.get("original", {})
        if _restore_entry(entry, port):
            detail = _describe_original(tool, original)
            print(f"  [{tool}] {path} -> original{detail}")
            count += 1
        else:
            print(f"  [{tool}] skipping — config file not found or already reverted")

    if count:
        print(f"Restored {count} tool(s) to original configs.")
    return count


def _describe_original(tool: str, original: dict) -> str:
    """Human-readable description of what was restored."""
    if tool in ("opencode", "codex"):
        return f" ({original.get('provider', '?'):} -> {original.get('baseURL', original.get('base_url', '?'))})"
    elif tool == "cline":
        return f" ({original.get('key', '?'):} -> {original.get('value', '?'):})"
    elif tool == "claude":
        return f" (ANTHROPIC_BASE_URL -> {original.get('baseURL', '?'):})"
    elif tool == "continue":
        return f" ({original.get('modelTitle', '?'):} apiBase removed)"
    return ""


def fix_tools(port: int = 19999) -> int:
    """Fix tool configs based on whether the proxy is alive or dead.

    Proxy alive  → re-apply proxy URL to all tools (filtering works)
    Proxy dead   → restore original configs (tools work directly)

    Returns count of tools fixed.
    """
    manifest = _load_manifest()
    tools = manifest.get("tools", [])
    if not tools:
        print("No tool configs in manifest. Run 'privacy-guard setup' first.")
        return 0

    if _is_proxy_reachable(port):
        print(f"Proxy is reachable — re-applying proxy configs")
        print()
        return _reapply_proxy_configs(port)
    else:
        print(f"Proxy is not reachable — restoring original configs")
        print()
        return restore_tools(port)


def teardown(port: int = 19999) -> bool:
    """Full cleanup: restore originals, stop proxy, remove auto-start, clear manifest."""
    from proxy_server import stop_server, _signal_stop, _cleanup

    print("LLM Privacy Guard — Teardown")
    print()

    # 1. Restore all tool configs
    print("[configs] Restoring original tool configs...")
    restore_tools(port)
    print()

    # 2. Stop the proxy
    print("[proxy] Stopping proxy...")
    try:
        _signal_stop()
        stop_server(port)
        print("  Proxy stopped.")
    except Exception as e:
        print(f"  Note: {e}")
    print()

    # 3. Remove auto-start
    print("[auto-start] Removing auto-start registration...")
    remove_auto_start()
    print()

    # 4. Clear manifest
    _clear_manifest()
    print("[manifest] Manifest cleared.")
    print()
    print("Teardown complete. All configs reverted to originals.")
    return True


# ── Unified setup ──

TOOL_SETUP_FUNCTIONS = {
    "opencode": setup_opencode,
    "continue": setup_continue,
    "cline": setup_cline,
    "codex": setup_codex,
    "claude": setup_claude,
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
    detected_tools: list[str] = []

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
            detected_tools.append(tool_name)
        else:
            print(f"  Not detected.")
        print()

    print("─" * 50)
    if configured:
        print(f"Configured {configured} tool(s). Your LLM traffic is now filtered.")
        print(f"Proxy running at http://127.0.0.1:{port}")
        if "codex" in detected_tools and not dry_run:
            print()
            print("Codex detected.")
            print("Recommended one-time step for hands-off use:")
            print("  privacy-guard setup --auto-start")
            print("After that, the proxy starts automatically on login and Codex keeps using the filtered local endpoint.")
    else:
        print("No tools detected. Manually set your LLM client's API base URL to:")
        print(f"  http://127.0.0.1:{port}")

    return configured
