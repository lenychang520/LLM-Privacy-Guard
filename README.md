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

## Quick Start

```bash
# 1. Install
pip install llm-privacy-guard

# 2. One-click setup (detects opencode, Continue, etc. — auto-configures + starts proxy)
privacy-guard setup

# 3. Verify
privacy-guard test
```

**Sample output:**
```
LLM Privacy Guard v2.0.0 — Self Test
  Raw      : ssh root@203.0.113.1 key=sk-abc123def456 ...
  Filtered : ssh root@[IP] key=sk-abc123def456 ...
  Matches  : 3
    [ipv4]  203.0.113.1 => [IP]
    [uuid]  ab12cd34-... => [UUID]
    [email] zhangjie@company.com => [EMAIL]
```

**What next?** Nothing. The proxy runs in the background. Use your LLM tools as usual — sensitive data is filtered before leaving your machine.

---

## Supported Tools

The proxy works at the HTTP layer. **Any LLM client with a configurable API endpoint works.**

### Auto-configured (`privacy-guard setup`)

| Tool | What happens |
|------|-------------|
| **opencode** | Edits `opencode.json` — sets `baseURL` to proxy for each provider |
| **Continue.dev** (VS Code) | Edits `~/.continue/config.json` — sets `apiBase` |

### Manual setup (change one URL)

| Tool | Where to change |
|------|----------------|
| **Cline / Roo Code** | API Provider → OpenAI Compatible → Base URL = `http://localhost:19999` |
| **Cursor** | Settings → Models → OpenAI Base URL = `http://localhost:19999` |
| **Dify** | Model provider → OpenAI-API-compatible → API Base = `http://localhost:19999` |
| **LangChain** | `ChatOpenAI(openai_api_base="http://localhost:19999")` |
| **Any curl / SDK** | Replace `https://api.xxx.com` with `http://localhost:19999` |

**The proxy auto-detects the target provider from the request's `model` field** — no need to configure upstreams. Supported out of the box: DeepSeek, OpenAI, Anthropic, Gemini, Qwen, GLM, Kimi, and 14+ others.

For providers not auto-detected, or for `GET /v1/models` requests (no model field), specify a fallback:

```bash
privacy-guard start --upstream https://api.your-provider.com --daemon
```

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `privacy-guard setup` | One-shot: start proxy + auto-configure opencode / Continue |
| `privacy-guard start --daemon` | Start proxy only (background, no window) |
| `privacy-guard start` | Start proxy in foreground (Ctrl+C to stop) |
| `privacy-guard stop` | Stop the proxy |
| `privacy-guard status` | Check if proxy is running |
| `privacy-guard test` | Verify the filter engine works |

### Options

| Option | Description |
|--------|-------------|
| `--port 12345` | Proxy port (default: 19999, or `$PRIVACY_GUARD_PORT`) |
| `--upstream https://...` | Fallback upstream URL (or `$PRIVACY_GUARD_UPSTREAM`) |
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

### Multi-Provider Auto-Routing
Detects target API from the request's `model` field. No vendor lock-in. 14+ providers built in.

### One-Click Setup
`privacy-guard setup` auto-detects and configures opencode, Continue, and more — no manual config editing.

---

## Architecture

```
Any LLM client (opencode / Continue / Cline / curl / SDK / …)
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
| `setup_tools.py` | Auto-config: detect & configure opencode, Continue, etc. |
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
  # Custom model → upstream mappings (appended before built-in map)
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
- [ ] Built-in small LLM for semantic filtering

---

## License

Apache 2.0 © 2026 [lenychang](https://github.com/lenychang520)
