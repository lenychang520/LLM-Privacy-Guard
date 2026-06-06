# LLM Privacy Guard 🔒

> Automatically detect and mask sensitive information before messages are sent to LLM APIs.
> Prevent private data like IPs, keys, and UUIDs from leaking to cloud AI providers.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green)]()
[![QwenPaw](https://img.shields.io/badge/QwenPaw-1.1%2B-orange)]()

---

## What is this?

When you use cloud AI services like ChatGPT, DeepSeek, or Claude, what you type leaves your computer and passes through the API provider's servers. If you accidentally paste an IP address, API key, UUID, or ID card number… that data could end up in their logs or training data.

**LLM Privacy Guard** runs on your machine and automatically replaces sensitive information with placeholders before the message is sent.

```
You type:   "ssh root@[REDACTED_IP], key=sk-abc123..."
    ↓ masked locally
Sent to LLM: "ssh root@[IP], key=[API_KEY]..."
```

The AI never sees your real data.

---

## Features

- 🔍 **27 built-in detection rules**: IPs (including IPv6 and hex variants), UUIDs, emails, phone numbers (China + international), ID cards (China + US SSN), API keys, GitHub tokens, JWTs, database connection strings and CLI commands, credit card numbers, SSH public/private keys, credential assignments…
- 🧠 **Entropy detection**: Automatically identifies high-entropy random strings without a fixed format (likely keys/tokens)
- 🛡️ **Allowlist**: Protocol addresses like `0.0.0.0` and `255.255.255.255` are not filtered by default; private IPs (`192.168.x`, `10.x`, etc.) are now also masked
- 📝 **Custom rules**: Add your own sensitive patterns via `config.yaml`
- 🔌 **QwenPaw plugin**: One-click install, transparent interception
- 📦 **Cross-platform core**: `privacy_engine/` has zero dependency on any AI framework — works with Dify, LangChain, and more

---

## Quick Start

### Option 1: QwenPaw Plugin (recommended)

```bash
# 1. Install the plugin
qwenpaw plugin install /path/to/llm-privacy-guard

# 2. (Optional) Copy the config file
copy config.example.yaml config.yaml
# Edit config.yaml to add your custom rules

# 3. Start QwenPaw
qwenpaw app
```

The plugin takes effect automatically. Verify with the `/privacy test` command:

```
/privacy test
> Output: 27 rules currently running, covering 27 sensitive types
```

### Option 2: Pure Python Library

```bash
pip install -e /path/to/llm-privacy-guard
```

```python
from privacy_engine import filter_text, scan_text

# Mask
safe = filter_text("ssh root@[REDACTED_IP]")
print(safe)  # "ssh root@[IP]"

# Scan (inspect without modifying — for auditing)
matches = scan_text("key=sk-abc123def4567890")
for m in matches:
    print(f"{m['type']}: {m['value']} -> {m['placeholder']}")
```

---

## Built-in Detection Rules

| Rule | Detects | Placeholder |
|------|---------|-------------|
| `ipv4` | IPv4 addresses (including private IPs) | `[IP]` |
| `ipv4_hex` | Hex IPv4 (`0xC0A80101`) | `[IP]` |
| `ipv6` | IPv6 addresses (compressed / bracketed / mixed formats) | `[IP]` |
| `ipv6_hyphen` | IPv6 hyphen format (`FE80-0000-...`) | `[IP]` |
| `uuid` | UUID with dashes | `[UUID]` |
| `uuid_hex` | UUID without dashes (32 hex chars) | `[UUID]` |
| `email` | Email addresses | `[EMAIL]` |
| `phone_cn` | Mainland China mobile numbers (consecutive digits) | `[PHONE]` |
| `phone_cn_sep` | Mainland China mobile numbers (parentheses / hyphens) | `[PHONE]` |
| `phone_intl` | International phone numbers (+1, +44, etc.) | `[PHONE]` |
| `id_card_cn` | Mainland China ID card numbers (consecutive) | `[ID_CARD]` |
| `id_card_cn_sep` | Mainland China ID card numbers (hyphen-separated) | `[ID_CARD]` |
| `ssn_us` | US SSN (XXX-XX-XXXX) | `[SSN]` |
| `api_key_prefix` | Keys starting with `sk-`, `pk-`, `Bearer` (case-insensitive) | `[API_KEY]` |
| `aws_access_key` | AWS Access Key (`AKIA...`, case-insensitive) | `[AWS_KEY]` |
| `ssh_private_key` | SSH private key header (`-----BEGIN...`, includes PKCS#8) | `[SSH_KEY]` |
| `ssh_public_key` | SSH public key (`ssh-rsa`, `ssh-ed25519`, etc.) | `[SSH_KEY]` |
| `sha_hash` | 64-char hex hashes (SHA256, etc.) | `[HASH]` |
| `github_token` | GitHub tokens (`ghp_`, `github_pat_`, etc.) | `[GITHUB_TOKEN]` |
| `jwt` | JWT tokens (standard three-part format) | `[JWT]` |
| `jwt_multiline` | JWT tokens (newline-separated variant) | `[JWT]` |
| `db_connection_string` | Database connection URLs (`postgresql://`, `mysql://`, etc.) | `[DB_URL]` |
| `db_cli` | Database CLI commands (`psql -h`, `mysql -h`, etc.) | `[DB_CMD]` |
| `credit_card` | Credit card numbers (with Luhn check) | `[CARD]` |
| `credential_value` | Credential assignments (`SecretAccessKey=`, `password=`, etc.) | `[CREDENTIAL]` |
| `url_query_credential` | URL query string credentials (`?pass=...`) | `[CREDENTIAL]` |
| `credential_inline` | Inline credentials (token= in comments, heredocs, logs) | `[CREDENTIAL]` |

### Entropy Detection

For high-entropy strings with no fixed format but an unusually even character distribution (likely randomly generated tokens, AES keys, hashes), entropy detection marks them as `[HIGH_ENTROPY]`. By default, they are auto-replaced (`mode: "auto"`). Switch to review-only mode (`mode: "review"`) to reduce false positives.

---

## Configuration

Copy `config.example.yaml` to `config.yaml` to customize:

```yaml
entropy:
  enabled: true          # Enable entropy detection
  threshold: 5.0         # Entropy threshold (higher = stricter)
  mode: "auto"           # "auto" for automatic replacement / "review" for mark-only

rules:
  ipv4: true             # Disable rules you don't need
  email: false

custom_rules:
  - name: "my_server"
    pattern: "srv-\\d{4}\\.internal\\.com"
    placeholder: "[MY_SERVER]"

whitelist:
  ips:
    - "8.8.8.8"          # Don't mask Google DNS
    - "192.168.1.1"      # Manually add back a private IP if needed
  strings:
    - "public-value-123" # Don't mask this string
```

---

## Architecture

```
llm-privacy-guard/
├── privacy_engine/        ← Core engine (zero platform dependencies)
│   ├── __init__.py        ← filter(), scan(), add_rule()
│   ├── detector.py        ← Detection orchestration (regex + entropy)
│   ├── patterns.py        ← 27 built-in rules
│   ├── entropy.py         ← Shannon entropy detection algorithm
│   ├── whitelist.py       ← Built-in allowlist
│   └── config.py          ← config.yaml loader
├── plugin.json            ← QwenPaw plugin manifest
├── plugin.py              ← QwenPaw adapter (monkey-patch)
├── config.example.yaml    ← Configuration template
├── LICENSE                ← Apache 2.0
├── README_zh.md           ← Chinese README
└── README.md              ← This file (English)
```

`privacy_engine/` is pure Python with zero AI framework dependencies. The QwenPaw adapter is just a thin glue layer — integrating with Dify, LangChain, etc. follows the same pattern.

---

## Roadmap

- [x] QwenPaw plugin
- [x] `/privacy scan` command (scan current chat history in-conversation)
- [ ] `/privacy report` to generate a masking report
- [ ] Dify plugin adapter
- [ ] LangChain callback adapter
- [ ] Built-in small LLM for semantic filtering — detect sensitive info that regex alone can't catch

---

## Contributing

Issues, PRs, and adapters for more AI platforms are welcome!

---

## License

Apache License 2.0 © 2026 lenychang
