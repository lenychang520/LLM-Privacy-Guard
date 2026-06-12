<p align="center">
  <img src="https://img.shields.io/badge/License-Apache%202.0-blue?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/Python-3.10%2B-green?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/Rules-27-8A2BE2?style=flat-square" alt="Rules">
  <img src="https://img.shields.io/badge/Tests-64%20passed-success?style=flat-square" alt="Tests">
</p>

<h1 align="center">LLM Privacy Guard</h1>

<p align="center">
  <b>你的消息。你的机器。你的规则。</b><br>
  <sub>在敏感数据离开电脑<b>之前</b>就脱敏 —— 而不是事后补救。</sub>
</p>

<br>

---

## 做什么的

你发给 ChatGPT、DeepSeek、Claude 的每一条消息，都会经过 API 服务商的服务器。不小心粘贴了 IP 地址、API Key 或客户邮箱？这些数据可能留在对方的日志、训练数据里——甚至更糟。

**LLM Privacy Guard 是一个本地 HTTP 代理**，架在你与所有 LLM API 之间，自动扫描并替换敏感数据，全程本地执行：

```
┌──────────────────────────────────────────────────────────┐
│  $ 你输入                                                 │
│  ssh root@203.0.113.1 -p 22, key=sk-abc123def4567890    │
│  Customer: zhangjie@company.com, ID: 110101199001011234  │
│                                                           │
│                         ↓  LLM Privacy Guard  ↓          │
│                                                           │
│  $ LLM 收到                                               │
│  ssh root@[IP] -p 22, key=[API_KEY]                     │
│  Customer: [EMAIL], ID: [ID_CARD]                        │
└──────────────────────────────────────────────────────────┘
```

AI 永远看不到你的真实数据。

**特点**：安装后一条命令搞定所有工具（opencode、Continue、Cline、Dify、LangChain…），不需要给每个工具单独写插件。

---

## 快速开始

```bash
# 1. 安装
pip install llm-privacy-guard

# 2. 一键配置（自动检测 opencode、Continue 等并配置好，同时启动代理）
privacy-guard setup

# 3. 验证
privacy-guard test
```

**输出示例：**
```
LLM Privacy Guard v2.0.0 — Self Test
  Raw      : ssh root@203.0.113.1 key=sk-abc123def456 ...
  Filtered : ssh root@[IP] key=sk-abc123def456 ...
  Matches  : 3
    [ipv4]  203.0.113.1 => [IP]
    [uuid]  ab12cd34-... => [UUID]
    [email] zhangjie@company.com => [EMAIL]
```

**接下来要做什么？** 什么都不用做。代理已在后台运行，opencode 等工具已自动配置为走代理。像平时一样使用你的 LLM 工具即可，敏感数据会在发出前自动脱敏。

---

## 支持哪些工具

代理是 HTTP 层面的，**任何允许自定义 API 地址的 LLM 客户端都能用**：

### 自动配置（`privacy-guard setup` 自动完成）

| 工具 | 配置方式 |
|------|---------|
| **opencode** | 自动修改 `opencode.json`，将已有 provider 的 `baseURL` 指向代理 |
| **Continue.dev** (VS Code) | 自动修改 `~/.continue/config.json`，设置 `apiBase` |

### 手动配置（改一个地址就行）

| 工具 | 在哪里改 |
|------|---------|
| **Cline / Roo Code** | API Provider → OpenAI Compatible → Base URL 填 `http://localhost:19999` |
| **Cursor** | Settings → Models → OpenAI Base URL 填 `http://localhost:19999` |
| **Dify** | 模型供应商 → OpenAI-API-compatible → API Base 填 `http://localhost:19999` |
| **LangChain** | `ChatOpenAI(openai_api_base="http://localhost:19999")` |
| **任意 curl / SDK** | 把 API 地址从 `https://api.xxx.com` 改成 `http://localhost:19999` |

**代理会根据请求里的 `model` 字段自动识别你要调哪个厂商的 API**，不需要额外配置。支持自动识别的厂商包括 DeepSeek、OpenAI、Anthropic、Gemini、Qwen、GLM、Kimi 等 14+ 个。

如果你用的厂商没被自动识别到，或者你想用 `GET /v1/models` 这样的无 model 请求，可以通过 `--upstream` 指定默认 fallback：

```bash
privacy-guard start --upstream https://api.your-provider.com --daemon
```

---

## 命令行参考

| 命令 | 作用 |
|------|------|
| `privacy-guard setup` | 一键：启动代理 + 自动配置 opencode / Continue |
| `privacy-guard start --daemon` | 只启动代理（后台，无窗口） |
| `privacy-guard start` | 前台启动代理（Ctrl+C 停止） |
| `privacy-guard stop` | 停止代理 |
| `privacy-guard status` | 检查代理是否在运行 |
| `privacy-guard test` | 验证过滤引擎是否正常工作 |

### 可选参数

| 参数 | 说明 |
|------|------|
| `--port 12345` | 指定代理端口（默认 19999，也可设环境变量 `PRIVACY_GUARD_PORT`） |
| `--upstream https://...` | 指定默认 fallback 上游地址（也可设环境变量 `PRIVACY_GUARD_UPSTREAM`） |
| `--dry-run` | （仅 `setup`）预览会改什么配置，不实际修改 |

---

## Python 库

不需要代理，直接在你的 Python 代码里用：

```python
from privacy_engine import filter_text, scan_text

# 脱敏
filter_text("ssh root@203.0.113.1, key=sk-abc123")
# → "ssh root@[IP], key=[API_KEY]"

# 审计（不修改原文）
for m in scan_text("token=ghp_xJ3kL9mN2pQ5rS8"):
    print(f"{m['type']}: {m['value']} → {m['placeholder']}")
```

---

## 检测规则

27 条内置规则：

| 规则 | 目标 | 占位符 |
|------|------|--------|
| `ipv4` · `ipv4_hex` | IPv4（点分 / 十六进制 `0xC0A80101`） | `[IP]` |
| `ipv6` · `ipv6_hyphen` | IPv6（压缩、方括号、混合、连字符） | `[IP]` |
| `uuid` · `uuid_hex` | UUID（带/不带横杠） | `[UUID]` |
| `email` | 邮箱地址 | `[EMAIL]` |
| `phone_cn` · `phone_cn_sep` · `phone_intl` | 中国大陆 + 国际手机号 | `[PHONE]` |
| `id_card_cn` · `id_card_cn_sep` | 中国身份证号 | `[ID_CARD]` |
| `ssn_us` | 美国 SSN（`XXX-XX-XXXX`） | `[SSN]` |
| `api_key_prefix` | 密钥：`sk-`、`pk-`、`Bearer` | `[API_KEY]` |
| `aws_access_key` | AWS Access Key（`AKIA...`） | `[AWS_KEY]` |
| `ssh_private_key` · `ssh_public_key` | SSH 密钥（PKCS#8、RSA、Ed25519、ECDSA） | `[SSH_KEY]` |
| `sha_hash` | 64 位十六进制哈希（SHA256 等） | `[HASH]` |
| `github_token` | GitHub Token（`ghp_`、`github_pat_` 等） | `[GITHUB_TOKEN]` |
| `jwt` · `jwt_multiline` | JWT Token（标准 + 换行分隔变体） | `[JWT]` |
| `db_connection_string` · `db_cli` | 数据库 URL + CLI 命令 | `[DB_URL]` · `[DB_CMD]` |
| `credit_card` | 信用卡号（Luhn 校验） | `[CARD]` |
| `credential_value` · `url_query_credential` · `credential_inline` | 行内凭证 | `[CREDENTIAL]` |

---

## 特性

### 深度检测
27 条内置规则覆盖：网络身份、个人信息、机密凭证、基础设施、金融数据。

### 熵引擎
捕捉正则漏掉的东西——无固定格式但字符分布异常均匀的高熵字符串。

### 对抗防御
零宽字符剥离、URL 解码、HTML 实体解码、Unicode NFKC 规范化，防止绕过。

### 默认安全
ReDoS 防护、100KB 输入截断、白名单机制（协议地址永不过滤）、日志不存原始值。

### 多厂商自动路由
根据请求中的 `model` 字段自动识别目标 API，无需指定厂商。支持 14+ 常见厂商。

### 一键配置
`privacy-guard setup` 自动检测并配置 opencode、Continue 等工具，无需手动改配置。

---

## 架构

```
任何 LLM 客户端（opencode / Continue / Cline / curl / SDK / …）
              │
              │  baseURL = http://localhost:19999
              ▼
      ┌───────────────────┐
      │   proxy_server.py │  ← HTTP 代理层
      │   拦截 · 过滤 · 转发  │
      └───────┬───────────┘
              │
      ┌───────▼───────────┐
      │  privacy_engine/  │  ← 过滤引擎（纯 Python，零依赖）
      │                  │
      │  预处理 → 正则27条 │
      │         → 熵检测   │
      │         → 去重合并  │
      │         → 替换     │
      └───────┬───────────┘
              │
              ▼
    真实 LLM API（DeepSeek / OpenAI / Anthropic / …）
```

| 文件/目录 | 职责 |
|-----------|------|
| `proxy_server.py` | HTTP 代理：拦截请求 → 调用引擎过滤 → 转发到真实 API |
| `cli.py` | CLI 入口：`setup` / `start` / `stop` / `status` / `test` |
| `setup_tools.py` | 自动配置：检测并配置 opencode、Continue 等工具 |
| `privacy_engine/detector.py` | 编排层：正则 + 熵、重叠去重、替换 |
| `privacy_engine/patterns.py` | 27 条编译后的正则规则（含优先级） |
| `privacy_engine/entropy.py` | 滑动窗口香农熵 + 误报过滤器 |
| `privacy_engine/whitelist.py` | 协议地址、RFC 域名、主机名 |
| `privacy_engine/config.py` | YAML 配置加载器 |
| `plugin.py` | QwenPaw 适配器（可选，保留兼容） |

---

## 配置

在项目目录或 `~/.config/llm-privacy-guard/` 下放 `config.yaml`（可选，默认就能用）：

```yaml
# 代理设置
proxy:
  port: 19999
  # 自定义 model → upstream 映射（追加到内置映射之前）
  upstream_map:
    my-provider: "https://api.my-provider.com"

# 熵检测
entropy:
  enabled: true
  threshold: 5.0          # 越高越严格
  mode: "auto"            # "auto" | "review"

# 关闭不需要的规则
rules:
  email: false

# 自定义规则
custom_rules:
  - name: "internal_srv"
    pattern: "srv-\\d{4}\\.internal\\.com"
    placeholder: "[INTERNAL]"

# 白名单（永不脱敏）
whitelist:
  ips: ["8.8.8.8"]
  strings: ["public-value-123"]
```

---

## QwenPaw 用户

如果你还在用 QwenPaw，`plugin.py` 仍然保留且正常工作。安装方式：

```bash
qwenpaw plugin install https://github.com/lenychang520/llm-privacy-guard/archive/refs/heads/master.zip
```

升级：

```bash
qwenpaw plugin install --force https://github.com/lenychang520/llm-privacy-guard/archive/refs/heads/master.zip
```

QwenPaw 内的 `/privacy test`、`/privacy scan`、`/privacy report`、`/privacy export`、`/privacy reset` 命令仍然可用。

---

## 升级

```bash
pip install --upgrade llm-privacy-guard
```

升级后如果代理在跑，先停再启：

```bash
privacy-guard stop
privacy-guard setup
```

---

## 路线图

- [x] QwenPaw 插件（透明拦截）
- [x] `/privacy` 系列斜杠命令（4 个）
- [x] 27 条检测规则 + 熵引擎
- [x] 对抗绕过防御（预处理管道）
- [x] 安全加固（ReDoS、输入截断、速率检测）
- [x] 本地 HTTP 代理——覆盖所有 LLM 客户端
- [x] CLI + 一键配置——`setup` / `start` / `stop` / `status` / `test`
- [x] 多厂商自动路由——根据 model 字段识别，不绑定厂商
- [ ] 内置小型 LLM 语义过滤

---

## 许可

Apache 2.0 © 2026 [lenychang](https://github.com/lenychang520)
