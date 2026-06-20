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

AI 永远看不到你的原始数据。

**特点**：安装后一条命令搞定所有工具（opencode、Continue、Cline、Dify、LangChain…），不需要给每个工具单独写插件。

---

## 快速开始

### 新用户——一次性配置（5 分钟）

**第一步：安装**

```bash
pip install llm-privacy-guard
```

**第二步：一键配置所有工具**

```bash
privacy-guard setup
```

这一条命令会自动做完以下**全部事情**：
- 启动代理（后台，带 watchdog —— 崩溃自动重启）
- 扫描 `auth.json` 找到你已连接的 LLM 厂商
- 配置 **opencode**、**Continue.dev**、**Cline / Roo Code**、**Codex** 走代理
- 打印配置结果

预期输出：

```
LLM Privacy Guard — Auto Setup
  Proxy: http://127.0.0.1:19999
  Upstream: auto-detect from request model

[opencode]
  .../opencode.json: [deepseek] -> http://127.0.0.1:19999
  .../opencode.json: [alibaba-cn] -> http://127.0.0.1:19999

Configured 1 tool(s). Your LLM traffic is now filtered.
```

**第三步：验证过滤引擎**

```bash
privacy-guard test
```

输出应显示 ≥3 个匹配项：

```
  Raw      : ssh root@203.0.113.1 key=sk-abc123def456 ...
  Filtered : ssh root@[IP] key=sk-abc123def456 ...
  Matches  : 3
    [ipv4]  203.0.113.1 => [IP]
    [api_key] sk-abc123def456 => [API_KEY]
    [email] user@example.com => [EMAIL]
```

匹配项低于 3 个：检查 `config.yaml`。

**第四步：开启开机自启（推荐）**

```bash
privacy-guard setup --auto-start
```

之后每次登录电脑,代理自动运行,不需要再管。

**搞定了。** 打开你的 AI 工具正常使用,每条消息都会自动脱敏。

### Codex：配置一次，后续自动生效

如果你用的是 Codex，推荐流程是：

```bash
privacy-guard setup
privacy-guard setup --auto-start
```

`setup` 会把你当前的 Codex provider 改到 `http://127.0.0.1:19999`，并把原始 upstream 保存在 `config.yaml` 里。

`setup --auto-start` 只需要做一次。做完之后，代理会在你登录系统时自动启动，所以你**不需要**每次在使用 Codex 前手动执行 `python cli.py setup` 或手动拉起代理。

### 你的流量真的经过代理了吗?

**只有用你自己的 API Key / 企业端点发的消息才会被过滤。**

代理在 `http://localhost:19999`。当你的工具把请求发到这个地址时,代理才能拦截、脱敏、再转发到真正的 LLM API。这**只有**在以下情况才生效:

- 你的工具配置了**你自己接入的 API 端点**(base URL → `http://localhost:19999`)
- 你选的模型供应商有可以修改的 `baseURL` 字段

**以下情况不会被过滤:**

| 模型类型 | 为什么 |
|---------|--------|
| 工具自带的免费模型(opencode 免费、Trae iCube、Cursor 免费、Copilot 免费) | 这些走的是工具厂商自己的后端——根本不经过你的代理 |
| GitHub Copilot(任何套餐) | 微软私有后端,不支持自定义端点 |
| Trae 自带 AI(iCube) | endpoint 硬编码 |

**在使用插件前,先测试** — 发一条带假 IP 的消息,比如 `1.2.3.4`,然后问 AI"我刚才发的 IP 是多少?"。如果 AI 看到了 `1.2.3.4`,说明你当前的聊天**没有经过代理**。切换到你自己接入的 API Key 模型再试。

---

### 日常使用

| 想干什么 | 命令 |
|---------|------|
| 检查代理活着没 | `privacy-guard status` |
| 临时停掉代理 | `privacy-guard stop` |
| 停了之后重启 | `privacy-guard start` |
| 代理被其他东西杀了 | `privacy-guard start`(watchdog 大多数情况会自动拉起来) |
| 看过滤有没有效 | `privacy-guard test` |

> **警告:** 不要写杀掉所有 Python 进程的代码(如 `Get-Process python \| Stop-Process` 或 `pkill python`),这会把隐私代理和 watchdog 一起干掉。

---

### 遇到问题？

| 现象 | 原因 | 解决 |
|------|------|------|
| AI 工具连不上 | 代理没在跑 | `privacy-guard start` |
| `test` 显示少于 3 个匹配 | 配置问题 | 检查 `config.yaml`，规则是否开启 |
| 代理返回 502 错误 | 模型未识别，没 fallback | 加 `--upstream` 或检查模型名 |
| 端口 19999 被占用 | 之前的代理没关干净 | `privacy-guard stop`，等几秒，重试 |
| 代理反复崩溃 | 未知错误 | 用 `privacy-guard start --watchdog` 看实时日志 |
| 敏感信息没被过滤 | 正在用免费模型或工具自带的模型 | 切换到你自己的 API Key 模型(见[“你的流量真的经过代理了吗”](#你的流量真的经过代理了吗)) |
| 代理莫名消失 | 其他脚本杀了所有 Python 进程(如 `Get-Process python \| Stop-Process`) | **绝对不要**写杀所有 Python 进程的代码。敲 `privacy-guard start` 重新启动。 |

## 支持哪些工具

运行 `privacy-guard setup` 后,以下工具**自动配置完成**,无需手动操作：

| 工具 | 自动配置 | 说明 |
|------|---------|------|
| **opencode** | 全自动 | 自动读取已连接的厂商,修改 `baseURL` |
| **Continue.dev** | 全自动 | 修改 `~/.continue/config.json` 中的 `apiBase` |
| **Cline / Roo Code** | 全自动 | 修改 VS Code / Trae / Cursor 等 IDE 的 `settings.json` |
| **Codex** | 全自动 | 修改 `~/.codex/config.toml` 当前 provider 的 `base_url`，并把原始 upstream 写入 `config.yaml`，保证按模型路由后仍然回到原 provider |

以下工具需要**手动改一个 URL**(把 API 地址改为 `http://localhost:19999`)：

| 工具 | 在哪里改 |
|------|---------|
| **Cursor 自带 AI** | 暂不支持自定义 endpoint |
| **Trae 自带 AI（iCube）** | endpoint 硬编码,无法修改。建议装 Continue 或 Cline 插件替代 |
| **GitHub Copilot** | 走微软私有后端,不支持代理 |
| **Dify** | 模型供应商 → OpenAI-API-compatible → API Base |
| **LangChain** | `ChatOpenAI(openai_api_base="http://localhost:19999")` |
| **任意 curl / SDK** | `base_url` / `--url` 参数 |

> **代理会根据请求里的 `model` 字段自动识别目标厂商**（DeepSeek、OpenAI、Anthropic 等 14+）,不需要额外配置。未识别的厂商可通过 `--upstream` 指定 fallback。

> **Codex 说明：** 如果你的 Codex 使用的是第三方 OpenAI-compatible provider，`privacy-guard setup` 会先把“模型 → 原 upstream”写进用户级 `config.yaml`，再把 Codex 的 `base_url` 改成 `http://127.0.0.1:19999`，这样代理接管后仍然会转发回你原来的 provider。

---

## 命令行参考

| 命令 | 作用 |
|------|------|
| `privacy-guard setup` | 一键:启动代理 + 自动配置 opencode / Continue / Cline / Codex |
| `privacy-guard setup --auto-start` | 注册开机自启(Windows/Linux/macOS) |
| `privacy-guard setup --remove-auto-start` | 取消开机自启 |
| `privacy-guard start` | **默认:** 后台 + watchdog (崩溃自动重启) |
| `privacy-guard start --foreground` | 前台,无 watchdog (Ctrl+C 停止,调试用) |
| `privacy-guard start --watchdog` | 前台 watchdog + 日志 (调试 watchdog 用) |
| `privacy-guard stop` | 停止代理(watchdog + proxy 一起停) |
| `privacy-guard status` | 检查 proxy 和 watchdog 是否都在运行 |
| `privacy-guard test` | 验证过滤引擎是否正常工作 |

### 可选参数

| 参数 | 说明 |
|------|------|
| `--port 12345` | 指定代理端口(默认 19999, 也可设环境变量 `PRIVACY_GUARD_PORT`) |
| `--upstream https://...` | 指定默认 fallback 上游地址(也可设环境变量 `PRIVACY_GUARD_UPSTREAM`) |
| `--foreground` | (仅 `start`) 前台模式,无 watchdog |
| `--watchdog` | (仅 `start`) 前台 watchdog + 日志 |
| `--auto-start` / `--remove-auto-start` | (仅 `setup`) 注册/取消开机自启 |
| `--dry-run` | (仅 `setup`) 预览会改什么配置, 不实际修改 |

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

### 崩溃自愈
`privacy-guard start` 默认自带 watchdog。如果 proxy 进程异常退出,watchdog 自动重启,无需人工干预。

### 开机自启
`privacy-guard setup --auto-start` 一条命令注册 Windows/Linux/macOS 开机自启,电脑重启后 proxy 自动运行。

### 多厂商自动路由
根据请求中的 `model` 字段自动识别目标 API，无需指定厂商。支持 14+ 常见厂商。

### 一键配置
`privacy-guard setup` 自动检测并配置 opencode、Continue、Codex 等工具，无需手动改配置。

---

## 架构

```
任何 LLM 客户端（opencode / Continue / Cline / Codex / curl / SDK / …）
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
| `setup_tools.py` | 自动配置：检测并配置 opencode、Continue、Codex 等工具 |
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
  # 自定义 model → upstream 映射（优先于内置映射）
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
