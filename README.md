<p align="center">
  <img src="https://img.shields.io/badge/License-Apache%202.0-blue?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/Python-3.10%2B-green?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/Rules-27-8A2BE2?style=flat-square" alt="Rules">
  <img src="https://img.shields.io/badge/Tests-64%20passed-success?style=flat-square" alt="Tests">
</p>

<h1 align="center">LLM Privacy Guard</h1>

<p align="center">
  <b>Your messages. Your machine. Your rules.</b><br>
  <sub>Redact sensitive data <i>before</i> it leaves your computer — not after.</sub>
</p>

<br>

---

## What It Does

Every message you send to ChatGPT, DeepSeek, or Claude passes through the API provider's servers. Paste an IP address, an API key, or a customer's email? It could end up in their logs, training data, or worse.

**LLM Privacy Guard is a local HTTP proxy** that sits between you and every LLM API, scanning outgoing messages and replacing sensitive data — all locally:

```
┌──────────────────────────────────────────────────────────┐
│  $ You type                                              │
│  ssh root@203.0.113.1 -p 22, key=sk-abc123def4567890    │
│  Customer: zhangjie@company.com, ID: 110101199001011234  │
│                                                           │
│                         ↓  LLM Privacy Guard  ↓          │
│                                                           │
│  $ LLM receives                                          │
│  ssh root@[IP] -p 22, key=[API_KEY]                     │
│  Customer: [EMAIL], ID: [ID_CARD]                        │
└──────────────────────────────────────────────────────────┘
```

The AI never sees your real data.

**One proxy covers all your tools** — no need for a plugin per tool.

---

## Setup Guide

### New User — One-Time Setup (5 minutes)

**Step 1: Install**

```bash
pip install llm-privacy-guard
```

**Step 2: Auto-configure everything**

```bash
privacy-guard setup
```

This single command does **all of this** in one shot:
- Starts the proxy in background (with watchdog — auto-restarts if it crashes)
- Scans `auth.json` to find your connected LLM providers
- Configures **opencode**, **Continue.dev**, **Cline / Roo Code**, **Codex** to route through the proxy
- Prints what was configured

Expected output:

```
LLM Privacy Guard — Auto Setup
  Proxy: http://127.0.0.1:19999
  Upstream: auto-detect from request model

[opencode]
  .../opencode.json: [deepseek] -> http://127.0.0.1:19999
  .../opencode.json: [openai] -> http://127.0.0.1:19999

Configured 1 tool(s). Your LLM traffic is now filtered.
```

**Step 3: Verify filtering works**

```bash
privacy-guard test
```

Output should show ≥3 matches:

```
  Raw      : ssh root@203.0.113.1 key=sk-abc123def456 ...
  Filtered : ssh root@[IP] key=sk-abc123def456 ...
  Matches  : 3
    [ipv4]  203.0.113.1 => [IP]
    [api_key] sk-abc123def456 => [API_KEY]
    [email] user@example.com => [EMAIL]
```

If fewer than 3 matches: check `config.yaml`.

**Step 4: Enable auto-start (recommended)**

```bash
privacy-guard setup --auto-start
```

This registers the proxy to start on login AND survive crashes — including `pkill python`:

| OS | Supervisor | Survives `pkill python`? |
|----|-----------|--------------------------|
| **Linux** | systemd `--user` service (`.desktop` fallback) | **Yes** — systemd restarts it in 3 seconds |
| **macOS** | launchd plist (`KeepAlive` enabled) | **Yes** — launchd restarts it immediately |
| **Windows** | Startup folder VBS script | **No** — runs once at login; no auto-restart |

> **How it works:** systemd and launchd are native OS components — they are NOT Python processes. When someone runs `pkill python` (or another script kills all Python processes on your machine), the OS supervisor simply starts the proxy again. Your filter is back within seconds without you touching anything.

Now the proxy starts automatically every time you log in and keeps itself alive. You'll never need to think about it again.

**Done.** Open your AI tools and use them as normal. Every message is silently filtered.

### Codex: one-time setup, then automatic

If you use Codex, the intended flow is:

```bash
privacy-guard setup
privacy-guard setup --auto-start
```

`setup` rewrites your current Codex provider to `http://127.0.0.1:19999` and preserves the original upstream in `config.yaml`.

`setup --auto-start` is a one-time step that makes the proxy start automatically when you log in, so you do **not** need to manually run `python cli.py setup` or restart the proxy before each Codex session.

### Does your traffic actually go through the proxy?

**Only messages sent with your own API key / enterprise endpoint are filtered.**

The proxy sits at `http://localhost:19999`. When your tool sends a request to that address, the proxy intercepts it, filters sensitive data, and forwards to the real LLM API. This ONLY works when:

- Your tool is configured to **use your own API endpoint** (base URL → `http://localhost:19999`)
- You select a provider that has a `baseURL` field you can change

**Not filtered:**

| Model type | Why |
|------------|-----|
| Free models provided by the tool itself (opencode free, Trae iCube, Cursor free, Copilot free) | These go through the tool vendor's own backend — never touch your proxy |
| GitHub Copilot (any tier) | Proprietary backend, no custom endpoint support |
| Trae built-in AI (iCube) | Endpoint is hardcoded |

**Before trusting the filter** — send a test message containing a fake IP like `1.2.3.4` and ask the AI "what IP did I just send?". If the AI sees `1.2.3.4`, your current chat is NOT going through the proxy. Switch to a model that uses your own API key.

---

### Everyday Use

| Want to... | Command |
|-----------|---------|
| Check proxy is alive | `privacy-guard status` |
| Stop proxy temporarily | `privacy-guard stop` |
| Re-start after stopping | `privacy-guard start` |
| Proxy was killed by something else | If auto-start is enabled (Linux/macOS): the OS restarts it automatically. Otherwise: `privacy-guard start` |
| See if filtering works | `privacy-guard test` |

> **Warning:** Do NOT write scripts that kill all Python processes (e.g. `Get-Process python \| Stop-Process` or `pkill python`). This will also kill the privacy proxy and its watchdog.

---

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| AI tools can't connect | Proxy not running | `privacy-guard start` |
| `privacy-guard test` shows <3 matches | config issue | Check `config.yaml`, rules enabled? |
| 502 error from proxy | Model not recognized, no fallback | Set `--upstream` or check model name |
| Port 19999 already in use | Old proxy didn't stop cleanly | `privacy-guard stop`, wait, retry |
| Proxy keeps crashing | Unknown error | Run `privacy-guard start --watchdog` to see live logs |
| Sensitive data not filtered | Using free model or tool-provided model | Switch to a provider using your own API key (see ["Does your traffic go through the proxy?"](#does-your-traffic-actually-go-through-the-proxy)) |
| Proxy disappeared unexpectedly | Another script killed all Python processes (e.g., `Get-Process python \| Stop-Process` or `pkill python`) | **On Linux/macOS:** run `privacy-guard setup --auto-start` once — the OS supervisor (systemd/launchd) will restart the proxy automatically after a mass kill. **On Windows:** re-run `privacy-guard setup` to restart. **Never** write code that kills all Python processes. |

---

## Supported Tools

Run `privacy-guard setup` and these are **auto-configured** — no manual steps needed:

| Tool | How it works |
|------|-------------|
| **opencode** | Reads connected providers from auth.json, sets `baseURL` |
| **Continue.dev** | Updates `~/.continue/config.json` → `apiBase` |
| **Cline / Roo Code** | Updates VS Code / Trae / Cursor `settings.json` |
| **Codex** | Updates `~/.codex/config.toml` current provider `base_url`, and saves the original upstream in `config.yaml` so model-based routing still works |

These tools need **one manual URL change** (set API endpoint to `http://localhost:19999`):

| Tool | Where to change |
|------|----------------|
| **Cursor built-in AI** | Custom endpoint not supported |
| **Trae built-in AI (iCube)** | Endpoint is hardcoded, cannot override. Use Continue or Cline plugins instead |
| **GitHub Copilot** | Proprietary backend, proxy not supported |
| **Dify** | Model provider → OpenAI-API-compatible → API Base |
| **LangChain** | `ChatOpenAI(openai_api_base="http://localhost:19999")` |
| **Any curl / SDK** | `base_url` / `--url` param |

> **The proxy auto-detects the target provider from the request's `model` field** (DeepSeek, OpenAI, Anthropic, etc. — 14+ built-in). Unknown providers can use `--upstream` as a fallback.

> **Codex note:** if your Codex client uses a third-party OpenAI-compatible provider, `privacy-guard setup` preserves that provider by writing a model → upstream override into your user `config.yaml`, then points Codex `base_url` to `http://127.0.0.1:19999`.

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `privacy-guard setup` | One-shot: start proxy + auto-configure opencode / Continue / Cline / Codex |
| `privacy-guard setup --auto-start` | Register auto-start on login (Windows/Linux/macOS) |
| `privacy-guard setup --remove-auto-start` | Remove auto-start registration |
| `privacy-guard start` | **Default:** background + watchdog (auto-restarts on crash) |
| `privacy-guard start --foreground` | Foreground, no watchdog (Ctrl+C to stop, for debugging) |
| `privacy-guard start --watchdog` | Foreground watchdog with visible logs (for debugging) |
| `privacy-guard stop` | Stop everything (watchdog + proxy) |
| `privacy-guard status` | Check if watchdog and proxy are running |
| `privacy-guard test` | Verify the filter engine works |

### Options

| Option | Description |
|--------|-------------|
| `--port 12345` | Proxy port (default: 19999, or `$PRIVACY_GUARD_PORT`) |
| `--upstream https://...` | Fallback upstream URL (or `$PRIVACY_GUARD_UPSTREAM`) |
| `--foreground` | (start only) Run in foreground without watchdog |
| `--watchdog` | (start only) Foreground watchdog with visible logs |
| `--auto-start` / `--remove-auto-start` | (setup only) Register/remove auto-start |
| `--dry-run` | (setup only) Preview config changes without applying |

---

## Python Library

Use the engine directly in your code — no proxy needed:

```python
from privacy_engine import filter_text, scan_text

# Redact
filter_text("ssh root@203.0.113.1, key=sk-abc123")
# → "ssh root@[IP], key=[API_KEY]"

# Audit (no modification)
for m in scan_text("token=ghp_xJ3kL9mN2pQ5rS8"):
    print(f"{m['type']}: {m['value']} → {m['placeholder']}")
```

---

## Detection Rules

27 built-in rules:

| Rule | Target | Placeholder |
|------|--------|-------------|
| `ipv4` · `ipv4_hex` | IPv4 (dotted / hex `0xC0A80101`) | `[IP]` |
| `ipv6` · `ipv6_hyphen` | IPv6 (compressed, bracketed, mixed, hyphen) | `[IP]` |
| `uuid` · `uuid_hex` | UUID (with/without dashes) | `[UUID]` |
| `email` | Email addresses | `[EMAIL]` |
| `phone_cn` · `phone_cn_sep` · `phone_intl` | China mainland + international phones | `[PHONE]` |
| `id_card_cn` · `id_card_cn_sep` | China ID card numbers | `[ID_CARD]` |
| `ssn_us` | US SSN (`XXX-XX-XXXX`) | `[SSN]` |
| `api_key_prefix` | Keys: `sk-`, `pk-`, `Bearer` (case-insensitive) | `[API_KEY]` |
| `aws_access_key` | AWS Access Key (`AKIA...`) | `[AWS_KEY]` |
| `ssh_private_key` · `ssh_public_key` | SSH keys (PKCS#8, RSA, Ed25519, ECDSA) | `[SSH_KEY]` |
| `sha_hash` | 64-char hex hashes (SHA256 etc.) | `[HASH]` |
| `github_token` | GitHub tokens (`ghp_`, `github_pat_`, etc.) | `[GITHUB_TOKEN]` |
| `jwt` · `jwt_multiline` | JWT tokens (standard + newline-separated) | `[JWT]` |
| `db_connection_string` · `db_cli` | DB URLs + CLI commands | `[DB_URL]` · `[DB_CMD]` |
| `credit_card` | Credit card numbers (Luhn validated) | `[CARD]` |
| `credential_value` · `url_query_credential` · `credential_inline` | Inline credentials | `[CREDENTIAL]` |

---

## Features

### Deep Detection
27 built-in rules covering network identity, PII, secrets, infrastructure, and financial data.

### Entropy Engine
Catches what regex misses — high-entropy strings that are likely keys or tokens.

### Adversarial Defense
Zero-width char stripping, URL/HTML decode, Unicode NFKC normalization — prevents bypass tricks.

### Secure by Default
ReDoS protection, 100KB input cap, protocol address whitelisting, no raw values in logs.

### Crash Recovery

Two layers of protection, progressively stronger:

| Mode | How it works | Survives `pkill python`? |
|------|-------------|--------------------------|
| `privacy-guard start` | Python watchdog restarts proxy on crash | **No** — watchdog itself is killed |
| `setup --auto-start` (Linux) | systemd `--user` service with `Restart=always` | **Yes** — systemd is not a Python process |
| `setup --auto-start` (macOS) | launchd plist with `KeepAlive` | **Yes** — launchd is not a Python process |
| `setup --auto-start` (Windows) | Startup folder VBS | **No** — no restart mechanism |

**Recommendation:** always use `setup --auto-start`. The OS-native supervisor (systemd/launchd) is the only way to survive `pkill python` — a common pattern in scripts that kill "all Python processes" without realizing they're killing the privacy proxy too.

### Auto-Start
`privacy-guard setup --auto-start` registers the proxy to launch automatically on login and keep itself alive. After the one-time setup, no manual steps are ever needed — even after reboot or a mass process kill.

### Multi-Provider Auto-Routing
Detects target API from the request's `model` field. No vendor lock-in. 14+ providers built in.

### One-Click Setup
`privacy-guard setup` auto-detects and configures opencode, Continue, Codex, and more — no manual config editing.

---

## Architecture

```
Any LLM client (opencode / Continue / Cline / Codex / curl / SDK / …)
              │
              │  baseURL = http://localhost:19999
              ▼
      ┌───────────────────┐
      │   proxy_server.py │  ← HTTP proxy layer
      │   intercept · filter · forward │
      └───────┬───────────┘
              │
      ┌───────▼───────────┐
      │  privacy_engine/  │  ← Filter engine (pure Python, zero AI deps)
      │                  │
      │  preprocess → 27 regex │
      │            → entropy   │
      │            → dedup     │
      │            → replace   │
      └───────┬───────────┘
              │
              ▼
    Real LLM API (DeepSeek / OpenAI / Anthropic / …)
```

| File/Dir | Role |
|----------|------|
| `proxy_server.py` | HTTP proxy: intercept → filter → forward |
| `cli.py` | CLI: `setup` / `start` / `stop` / `status` / `test` |
| `setup_tools.py` | Auto-config: detect & configure opencode, Continue, Codex, etc. |
| `privacy_engine/detector.py` | Orchestration: regex + entropy, overlap dedup, replace |
| `privacy_engine/patterns.py` | 27 compiled regex rules with priorities |
| `privacy_engine/entropy.py` | Sliding-window Shannon entropy + false-positive filters |
| `privacy_engine/whitelist.py` | Protocol addresses, RFC domains, hostnames |
| `privacy_engine/config.py` | YAML config loader |
| `plugin.py` | QwenPaw adapter (optional, maintained for compatibility) |

---

## Configuration

Place `config.yaml` in your project or `~/.config/llm-privacy-guard/` (optional — defaults work out of the box):

```yaml
# Proxy settings
proxy:
  port: 19999
  # Custom model → upstream mappings (checked before built-in map)
  upstream_map:
    my-provider: "https://api.my-provider.com"

# Entropy detection
entropy:
  enabled: true
  threshold: 5.0          # higher = stricter
  mode: "auto"            # "auto" | "review"

# Disable rules you don't need
rules:
  email: false

# Custom rules
custom_rules:
  - name: "internal_srv"
    pattern: "srv-\\d{4}\\.internal\\.com"
    placeholder: "[INTERNAL]"

# Whitelist (never redact)
whitelist:
  ips: ["8.8.8.8"]
  strings: ["public-value-123"]
```

---

## For QwenPaw Users

`plugin.py` is still maintained and works. Install via:

```bash
qwenpaw plugin install https://github.com/lenychang520/llm-privacy-guard/archive/refs/heads/master.zip
```

Upgrade:

```bash
qwenpaw plugin install --force https://github.com/lenychang520/llm-privacy-guard/archive/refs/heads/master.zip
```

`/privacy test`, `/privacy scan`, `/privacy report`, `/privacy export`, and `/privacy reset` commands continue to work inside QwenPaw.

---

## Upgrading

```bash
pip install --upgrade llm-privacy-guard
```

If the proxy is running, stop and restart:

```bash
privacy-guard stop
privacy-guard setup
```

---

## Roadmap

- [x] QwenPaw plugin with transparent interception
- [x] `/privacy` slash commands (4 commands)
- [x] 27 detection rules + entropy engine
- [x] Adversarial bypass defense (preprocess pipeline)
- [x] Security hardening (ReDoS, input cap, rate canary)
- [x] Local HTTP proxy — covers any LLM client
- [x] CLI + one-click setup — `setup` / `start` / `stop` / `status` / `test`
- [x] Multi-provider auto-routing — model-based, no vendor lock-in
- [x] Crash recovery — watchdog auto-restarts proxy on failure
- [x] Auto-start on login — `setup --auto-start` for Windows/Linux/macOS
- [ ] Built-in small LLM for semantic filtering

---

## License

Apache 2.0 © 2026 [lenychang](https://github.com/lenychang520)
