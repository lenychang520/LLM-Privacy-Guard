# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install for development (code changes need reinstall to take effect on CLI)
pip install --force-reinstall -e .

# Run all tests
pytest

# Run a single test file
pytest tests/test_unit.py
pytest tests/test_functional.py
pytest tests/test_proxy.py

# Run a specific test
pytest tests/test_functional.py::test_ipv4_public

# Run the proxy in foreground (for debugging)
privacy-guard start --foreground

# Test the filter engine
privacy-guard test

# Check proxy status
privacy-guard status

# Manifest-based config management (post-`9ae1556`)
privacy-guard fix       # Re-apply proxy config if alive, restore originals if dead
privacy-guard restore   # Revert tool configs to pre-setup state
privacy-guard teardown  # Full uninstall: restore + stop + remove auto-start
```

## Project Architecture

**LLM Privacy Guard** is a local HTTP proxy that sits between LLM clients and API providers, redacting sensitive data (IPs, keys, PII, secrets) before requests leave the machine. Python 3.10+, single runtime dependency: `PyYAML`.

### Layers

```
LLM Client → proxy_server.py → privacy_engine/ → upstream API
                (HTTP intercept)   (filter logic)   (DeepSeek/OpenAI/Anthropic/...)
```

**`proxy_server.py`** — HTTP proxy. Intercepts POST requests on recognized chat paths, filters the JSON body, then forwards to the real upstream. Auto-detects the upstream API from the `model` field in the request body using a substring-match table (14+ built-in providers). Supports custom model→upstream mappings via `config.yaml` `proxy.upstream_map`.

**`privacy_engine/`** — Pure Python filter engine, zero AI dependencies.
- `__init__.py` — Public API (`filter_text`, `scan_text`, `add_rule`, `reload_config`). Uses a module-level singleton `PrivacyDetector`.
- `detector.py` — `PrivacyDetector` orchestrates the detection pipeline (see below). Handles overlap dedup, rate canary, input caps, and ReDoS validation.
- `patterns.py` — 27 `Rule` dataclass instances in `BUILTIN_RULES` list, ordered by priority.
- `entropy.py` — Sliding-window Shannon entropy detection for unstructured secrets that regex misses.
- `whitelist.py` — Built-in protocol-address and domain whitelists (0.0.0.0, 255.255.255.255, localhost, example.com, etc.).
- `config.py` — YAML config loader with deep-merge defaults. Config discovery order: CWD > project dir > `~/.config/llm-privacy-guard/` > `~/.llm-privacy-guard/`.

**`cli.py`** — CLI entry point (`privacy-guard`). Commands: `start`, `stop`, `status`, `test`, `setup`, `fix`, `restore`, `teardown`. `fix` re-applies proxy config if the proxy is alive, or restores originals if it's dead. `restore` reverts tool configs to pre-setup state. `teardown` is the full uninstall (restore + stop + remove auto-start).

**`setup_tools.py`** — Auto-detects and configures opencode, Continue.dev, Cline/Roo Code, Codex, Claude Code to route through the proxy. Includes a JSONC parser (JSON + comments + trailing commas) for VS Code config files. Records every write in a tool-manifest (see Supervision & Manifest below) so `restore`/`teardown` can undo cleanly.

**`plugin.py` + `plugin.json`** — QwenPaw plugin entry. Reuses the same `privacy_engine` but skips the HTTP proxy entirely — registers commands and monkey-patches `query_handler` inside the host process. Independent integration path from the HTTP proxy; the engine is the only shared code.

### Detection Pipeline

```
Preprocess: NFKC normalize → URL decode → HTML unescape → strip zero-width chars
  → Regex matching (27 rules, priority-ordered)
  → Entropy scan (sliding-window Shannon entropy, excluding regex-covered regions)
  → Overlap dedup (priority-based: containment wins, partial overlap → higher priority/longer wins)
  → Replace right-to-left (skip low-confidence matches)
```

### Key Design Patterns

- **Singleton `PrivacyDetector`**: Module-level `_detector` variable in `privacy_engine/__init__.py`. Use `reload_config()` to reset it. Tests use a `reset_detector` fixture that calls `reload_config()` per test.
- **Supervision (don't trust the README — this is the real layout)**: there are three supervisor tiers and which one is active depends on how the proxy was started, NOT on the OS alone:
  - **OS-level (preferred when `setup --auto-start` ran on the current code)**: systemd `--user` on Linux (`~/.config/systemd/user/privacy-guard.service`, `Restart=always`), launchd on macOS (`~/Library/LaunchAgents/com.privacyguard.plist`, `KeepAlive`), VBS shim on Windows. Selection happens in `setup_tools.py:_register_auto_start_linux/_macos/_windows`. The Linux branch prefers systemd and only falls back to XDG `.desktop` autostart when `_is_systemd_available()` returns False. Under OS supervision the proxy runs as `start --foreground` — single process, no Python watchdog.
  - **Python watchdog (fallback / non-OS-supervised path)**: `privacy-guard start` without `--foreground` goes through `proxy_server._run_daemon` → spawns `cli.py start --watchdog`, which is the loop in `cli.py:_run_watchdog`. Exponential backoff (1s→30s), only stops on `STOP_FILE`, never on child exit code, signal-forwards SIGINT/SIGTERM to the child. This is still the path used by `.desktop` autostart, by Windows VBS, and by any manual `privacy-guard start`. Not deprecated.
  - **Detection at runtime**: `_cmd_status`/`_cmd_stop` in `cli.py` probe `_is_supervised_by_systemd()` then `_is_supervised_by_launchd()` before falling through to the watchdog/PID-file branch. If both probes fail but `.privacy_guard_watchdog.pid` points to a live PID, the machine is on the watchdog path — even on systemd-capable Linux. This happens when `setup --auto-start` hasn't re-run since commit `9ae1556` (systemd unit landed), so the unit was never installed.
- **PID-file coordination (watchdog path only)**: `proxy_server.py` uses `.privacy_guard.pid`, `.privacy_guard_watchdog.pid`, and `.privacy_guard_stop` for cross-process communication between CLI, watchdog, and proxy. Under systemd/launchd these files are not the source of truth — the supervisor is.
- **Tool manifest (`~/.config/llm-privacy-guard/tool-manifest.json`)**: `setup_tools.py` records every config file it touched (path, backup location, hash) before modification. `fix`/`restore`/`teardown` read this manifest to undo or re-apply cleanly. Do not write to client configs without going through the manifest layer.
- **Model-based routing**: Proxy extracts `model` from request JSON body, matches it against a keyword→URL table via substring. Custom mappings from `config.yaml` checked before built-ins. Falls back to `--upstream` CLI arg or `$PRIVACY_GUARD_UPSTREAM` env var.
- **Preprocess pipeline**: Decode-first to catch adversarially encoded bypasses (URL-encoded, HTML-entity-encoded, zero-width-character-injected). Last step strips zero-width chars so decoded ZW chars from earlier steps are caught.

### Security Guards (don't weaken these)

- **ReDoS protection**: `_validate_regex_safety()` rejects nested-quantifier patterns + runs 1-second smoke test. IPv6 regex skipped on text > 5KB. Input truncated at 100KB.
- **Rate canary**: Logs warning at 500 filter/scan calls/sec (soft signal, not a block).
- **Credit card Luhn check**: Regex patterns match card formats; Luhn algorithm runs in `_find_regex_matches()`. Failed Luhn → match kept but confidence set to `"low"`, and low-confidence matches are excluded from replacement (still appear in `scan()`).
- **Whitelist before redaction**: Protocol addresses (0.0.0.0, 255.255.255.255) and known-safe domains/hostnames are checked against built-in + user-configured whitelists.

## AGENTS.md Invariants

From `.opencode/AGENTS.md`:
- **NEVER run `privacy-guard stop`** unless the user explicitly asks — it kills the proxy globally.
- **NEVER run `privacy-guard start`** unless the user asks — `setup --auto-start` handles it.
- **Code changes require `pip install --force-reinstall .`** to take effect on the installed CLI.

## Testing

Tests use `pytest`. Five test files:
- `test_unit.py` — Unit tests for `_luhn_check`, `_shannon_entropy`, `_may_be_secret`, whitelist checks.
- `test_functional.py` — Positive detection, adversarial regression, known limitations. Uses `reload_config()` fixture.
- `test_proxy.py` — Integration: starts mock upstream + proxy in threads, verifies filtering end-to-end.
- `test_proxy_routing.py` — Integration: verifies model-based routing to correct upstream.
- `test_setup_tools.py` — Tests `setup_codex` TOML rewriting and config.yaml persistence with `monkeypatch` + `tmp_path`.

Integration tests use `_free_port()` to avoid port conflicts and run in-process without daemon mode.
