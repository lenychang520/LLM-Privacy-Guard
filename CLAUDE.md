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

**`cli.py`** — CLI entry point (`privacy-guard`). Commands: `start`, `stop`, `status`, `test`, `setup`.

**`setup_tools.py`** — Auto-detects and configures opencode, Continue.dev, Cline/Roo Code, Codex to route through the proxy. Includes a JSONC parser (JSON + comments + trailing commas) for VS Code config files, and cross-platform auto-start (Windows VBS, Linux autostart .desktop, macOS launchd plist).

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
- **PID-file coordination**: `proxy_server.py` uses `.privacy_guard.pid`, `.privacy_guard_watchdog.pid`, and `.privacy_guard_stop` files for cross-process communication between CLI, watchdog, and proxy.
- **Watchdog**: Exponential backoff (1s→30s), only stops on STOP_FILE, never on exit code. Signal forwarding (SIGINT/SIGTERM) from watchdog to child proxy.
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
