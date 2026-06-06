# LLM Privacy Guard 🔒

> 在消息发给 LLM API 之前，自动检测并脱敏敏感信息。
> 防止 IP、密钥、UUID 等隐私数据泄露到云端 AI 服务商。

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green)]()
[![QwenPaw](https://img.shields.io/badge/QwenPaw-1.1%2B-orange)]()

---

## 这是什么？

使用 ChatGPT、DeepSeek、Claude 等云端 AI 时，你输入的内容会离开你的电脑，经过 API 供应商的服务器。如果你不小心粘贴了 IP 地址、API Key、UUID、身份证号……这些数据就可能在对方的日志/训练数据里留下来。

**LLM Privacy Guard** 在你的电脑上，在消息发出之前，自动把敏感信息替换成占位符。

```
你输入:  "ssh root@[REDACTED_IP]，key=sk-abc123..."
    ↓ 本地脱敏
发给 LLM: "ssh root@[IP]，key=[API_KEY]..."
```

AI 永远看不到你的真实数据。

---

## 特性

- 🔍 **内置 27 种检测规则**：IP（含 IPv6/十六进制变体）、UUID、邮箱、手机号（中国+国际）、身份证（中国+美国 SSN）、API Key、GitHub Token、JWT、数据库连接串和命令行、信用卡号、SSH 公私钥、凭证赋值……
- 🧠 **熵检测**：自动识别无格式的高熵随机字符串（可能是密钥/token）
- 🛡️ **白名单**：`0.0.0.0`、`255.255.255.255` 等协议地址默认不过滤；私有 IP（`192.168.x`、`10.x` 等）现在也会被脱敏
- 📝 **自定义规则**：通过 `config.yaml` 添加你自己的敏感模式
- 🔌 **QwenPaw 插件**：一键安装，透明拦截
- 📦 **跨平台核心**：`privacy_engine/` 不依赖任何 AI 框架，可接入 Dify、LangChain 等

---

## 快速开始

### 方式一：QwenPaw 插件（推荐）

```bash
# 1. 安装插件
qwenpaw plugin install /path/to/llm-privacy-guard

# 2. (可选) 复制配置文件
copy config.example.yaml config.yaml
# 编辑 config.yaml 添加你的自定义规则

# 3. 启动 QwenPaw
qwenpaw app
```

插件会自动生效。你可以用 `/privacy test` 命令验证：

```
/privacy test
> 输出: 当前检测到 27 条规则正在运行，覆盖 27 种敏感类型
```

### 方式二：纯 Python 库

```bash
pip install -e /path/to/llm-privacy-guard
```

```python
from privacy_engine import filter_text, scan_text

# 脱敏
safe = filter_text("ssh root@[REDACTED_IP]")
print(safe)  # "ssh root@[IP]"

# 扫描（不修改，用于审核）
matches = scan_text("key=sk-abc123def4567890")
for m in matches:
    print(f"{m['type']}: {m['value']} -> {m['placeholder']}")
```

---

## 内置检测规则

| 规则名 | 检测内容 | 占位符 |
|--------|---------|--------|
| `ipv4` | IPv4 地址（含私有 IP） | `[IP]` |
| `ipv4_hex` | 十六进制 IPv4（`0xC0A80101`） | `[IP]` |
| `ipv6` | IPv6 地址（含压缩/方括号/混合格式） | `[IP]` |
| `ipv6_hyphen` | IPv6 连字符格式（`FE80-0000-...`） | `[IP]` |
| `uuid` | UUID 带横杠格式 | `[UUID]` |
| `uuid_hex` | UUID 无连字符 32 位 hex | `[UUID]` |
| `email` | 邮箱地址 | `[EMAIL]` |
| `phone_cn` | 中国大陆手机号（连续数字） | `[PHONE]` |
| `phone_cn_sep` | 中国大陆手机号（含括号/连字符） | `[PHONE]` |
| `phone_intl` | 国际手机号（+1、+44 等） | `[PHONE]` |
| `id_card_cn` | 中国大陆身份证号（连续） | `[ID_CARD]` |
| `id_card_cn_sep` | 中国大陆身份证号（连字符分隔） | `[ID_CARD]` |
| `ssn_us` | 美国 SSN（XXX-XX-XXXX） | `[SSN]` |
| `api_key_prefix` | `sk-`、`pk-`、`Bearer` 开头的 key（大小写不敏感） | `[API_KEY]` |
| `aws_access_key` | AWS Access Key（`AKIA...`，大小写不敏感） | `[AWS_KEY]` |
| `ssh_private_key` | SSH 私钥头（`-----BEGIN...`，含 PKCS#8 通用格式） | `[SSH_KEY]` |
| `ssh_public_key` | SSH 公钥（`ssh-rsa`/`ssh-ed25519` 等） | `[SSH_KEY]` |
| `sha_hash` | 64 位十六进制哈希（SHA256 等） | `[HASH]` |
| `github_token` | GitHub Token（`ghp_`、`github_pat_` 等） | `[GITHUB_TOKEN]` |
| `jwt` | JWT Token（标准三段式） | `[JWT]` |
| `jwt_multiline` | JWT Token（换行分隔变体） | `[JWT]` |
| `db_connection_string` | 数据库连接 URL（`postgresql://`、`mysql://` 等） | `[DB_URL]` |
| `db_cli` | 数据库命令行（`psql -h`、`mysql -h` 等） | `[DB_CMD]` |
| `credit_card` | 信用卡号（含 Luhn 校验） | `[CARD]` |
| `credential_value` | 凭证赋值（SecretAccessKey=、password= 等） | `[CREDENTIAL]` |
| `url_query_credential` | URL query string 凭证（`?pass=...`） | `[CREDENTIAL]` |
| `credential_inline` | 行内凭证（注释/heredoc/日志中的 token= 等） | `[CREDENTIAL]` |

### 熵检测

对于无固定格式但字符分布异常均匀的高熵字符串（可能是随机生成的 token、AES Key、hash），熵检测会标记为 `[HIGH_ENTROPY]`。默认自动替换（`mode: "auto"`），可切换为仅标记模式（`mode: "review"`）避免误杀。

---

## 配置

复制 `config.example.yaml` 为 `config.yaml` 即可自定义：

```yaml
entropy:
  enabled: true          # 启用熵检测
  threshold: 5.0         # 熵阈值（越高越严格）
  mode: "auto"           # "auto" 自动替换 / "review" 仅标记

rules:
  ipv4: true             # 关闭不需要的规则
  email: false

custom_rules:
  - name: "my_server"
    pattern: "srv-\\d{4}\\.internal\\.com"
    placeholder: "[MY_SERVER]"

whitelist:
  ips:
    - "8.8.8.8"          # 不脱敏 Google DNS
    - "192.168.1.1"       # 如有需要，手动加回私有 IP
  strings:
    - "public-value-123" # 不脱敏这条字符串
```

---

## 架构

```
llm-privacy-guard/
├── privacy_engine/        ← 核心引擎（零平台依赖）
│   ├── __init__.py        ← filter(), scan(), add_rule()
│   ├── detector.py        ← 检测编排（正则 + 熵）
│   ├── patterns.py        ← 27 种内置规则
│   ├── entropy.py         ← 香农熵检测算法
│   ├── whitelist.py       ← 内置白名单
│   └── config.py          ← config.yaml 加载
├── plugin.json            ← QwenPaw 插件清单
├── plugin.py              ← QwenPaw 适配器（monkey-patch）
├── config.example.yaml    ← 配置模板
├── LICENSE                ← Apache 2.0
└── README_zh.md           ← 本文件
```

`privacy_engine/` 是纯 Python，不依赖任何 AI 框架。QwenPaw adapter 只是薄薄一层 glue code，之后接入 Dify、LangChain 也是同样的模式。

---

## 路线图

- [x] QwenPaw 插件
- [x] `/privacy scan` 命令（对话中扫描当前聊天记录）
- [ ] `/privacy report` 生成脱敏报告
- [ ] Dify 插件适配
- [ ] LangChain callback 适配
- [ ] 内置小型 LLM 语义理解过滤 — 捕捉正则无法覆盖的语义级敏感信息

---

## 贡献

欢迎提 Issue、PR，或者接入更多 AI 平台的适配器。

---

## 许可

Apache License 2.0 © 2026 lenychang
