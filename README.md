<p align="center">
  <h1 align="center">🧠 Agent OS</h1>
  <p align="center"><strong>Multi-Agent Swarm · Plan-and-Solve · ReAct · RAG</strong></p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python">
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
    <img src="https://img.shields.io/badge/Reasoning-DeepSeek_V4-4B9CD3.svg" alt="DeepSeek">
    <img src="https://img.shields.io/badge/Embed-SiliconFlow-8A2BE2.svg" alt="SiliconFlow">
  </p>
</p>

---

> **DAG 任务拆解 · 工具权限隔离 · 防幻觉安全风控 · 可视化主控台 · 推理走云端 + 嵌入跑本地**

一个多引擎智能助理框架。**推理**默认走 DeepSeek 云端（国内直连、极低成本），也可切换 OpenAI 或本地 Ollama，**向量嵌入**跑硅基流动免费 BGE 模型，兼顾性能与成本。系统将宏观目标拆解为 DAG 任务拓扑，通过向量检索智能匹配专家 Agent，多线程并发执行，内置防幻觉、沙箱安全与人工审批机制。

---

## 🏗️ 架构一览

```
                        ┌─────────────┐
                        │   👤 用户    │
                        └──────┬──────┘
                               │  输入目标
                               ▼
┌─────────────────────────────────────────────────────┐
│                  🧠 Planner（大脑）                   │
│  · Mem0 长期记忆 + 对话历史上下文注入                  │
│  · RAG 向量检索 → Top-K 专家智能匹配                  │
│  · DAG 任务拆解（含 depends_on 依赖图）               │
│  · 三级风险定级（low / medium / high）                │
│  · JSON 格式自愈（最多 3 轮带错重试）                  │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│               🛡️ HITL 安全风控层                      │
│  高危操作 → 人类审批 → 授权 / 驳回                    │
│  中低危   → 自动放行                                 │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              ⚡ Swarm 专家集群（多线程并发）            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │Researcher│  │  Coder   │  │  Google  │  ...      │
│  │  搜索    │  │  写入    │  │  Drive   │           │
│  └──────────┘  └──────────┘  └──────────┘           │
│  · 工具权限物理隔离（白名单）   · DAG 拓扑 → 分批并发  │
│  · XComs 跨任务数据流转        · ReAct 循环 + 防幻觉  │
│  · Early Stopping 智能熔断                              │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
      ┌───────────────────────────────┐
      │         双引擎                 │
      │  ☁️ DeepSeek V4 ── 推理       │
      │  ☁️ SiliconFlow ── 向量嵌入   │
      └───────────────────────────────┘
```

---

## ✨ 核心特性

| 特性 | 说明 |
|---|---|
| 🕸️ **DAG 任务拓扑** | Planner 拆解任务时标注 `depends_on`，按拓扑排序分批执行，XComs 跨任务数据流转 |
| 🧬 **RAG 智能路由** | 用户目标向量化 → 与专家描述余弦相似度匹配 → 自动捞出 Top-3 专家 |
| 🛡️ **物理级工具隔离** | 每个 Agent 白名单过滤工具，权限在内存层面物理阻断 |
| 🏖️ **分层沙箱引擎** | 五层防御：资源硬限制 + 模块白名单 + 文件隔离 + 审计日志 + 超时熔断 |
| 🔒 **HITL 安全风控** | 高危操作（删除/邮件/批量写）自动挂起，等待 UI 人工审批 |
| 🚫 **防幻觉拦截** | 追踪工具调用状态，拦截"未调工具却谎称成功" |
| 🛑 **智能熔断 + Early Stopping** | 同工具重复 3 次熔断，循环耗尽时 LLM 基于已有数据做最终总结 |
| 📋 **业务资产层** | 业务别名 → file_id 确定性查表，100% 精确定位，绕过 LLM 模糊匹配 |
| 🌐 **MCP 协议支持** | 工具以 MCP 标准对外暴露，可接入 Claude Desktop / Cursor 等客户端 |
| 🔌 **工具热插拔** | `tools/` 目录下新增 `tool_*.py` 自动扫描注册，零配置 |
| ⚡ **多线程并发** | 同批次独立任务 `ThreadPoolExecutor` 并发，互不阻塞 |
| ☁️🖥️ **混合引擎** | 推理默认 DeepSeek 云端（可切换本地 Ollama / OpenAI），嵌入跑硅基流动免费 BGE 模型 |

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.10+
- DeepSeek API Key（推理，默认引擎）
- （可选）[Ollama](https://ollama.com) 本地安装 → 用于向量嵌入或本地推理

### 2. 安装依赖

```bash
git clone <your-repo-url>
cd Small-Agent

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 获取 DeepSeek API Key

去 [platform.deepseek.com](https://platform.deepseek.com) 注册，在 API Keys 页面创建一个 Key。

```bash
# .env
DEEPSEEK_API_KEY=sk-你的key
```

### 4. （可选）配置硅基流动嵌入

去 [siliconflow.cn](https://siliconflow.cn) 注册，获取免费 API Key。

```bash
# .env
SILICONFLOW_API_KEY=sk-你的key
```

> 嵌入模型默认走硅基流动（免费），无需任何配置即可使用。也可在 `config.py` 中改为本地 Ollama 嵌入。

### 5. 启动

```bash
streamlit run app.py
```

浏览器打开 `http://localhost:8501`，输入一句复合指令，观察 Planner 拆解 → 风控审批 → Swarm 并发的完整流水线。

---

## 🔌 模型配置

系统包含两个引擎，各自独立配置。统一在 `config/config.py` 中修改，API Key 统一写在 `.env`。

| 引擎 | 做什么 | 通俗理解 |
|---|---|---|
| 🧠 **推理** | 生成文字、思考、规划、调用工具、写答案 | 项目里真正"说话"的 AI 大脑 |
| 🔍 **嵌入** | 把文字转成数字向量，用来做语义搜索 | 帮系统找到"最相关"的专家或记忆 |

---

### 🧠 推理引擎

修改 `config/config.py` 第 13 行 `LLM_PROVIDER`：

**A. DeepSeek（← 当前默认）**

```python
# config/config.py
LLM_PROVIDER = "deepseek"
```
```bash
# .env
DEEPSEEK_API_KEY=sk-你的key
```
→ [platform.deepseek.com](https://platform.deepseek.com) 注册获取 Key，国内直连，价格极低。默认使用 `deepseek-v4-flash`。

**B. 本地 Ollama**

```python
# config/config.py
LLM_PROVIDER = "ollama"
```
```python
OLLAMA_MODEL = "qwen3-coder:30b"        # 可替换为任意已拉取的模型
```
无需 API Key，数据不出本地机器。先 `ollama pull qwen3-coder:30b` 拉取模型。

**C. OpenAI / 其他兼容 API**

```python
# config/config.py
LLM_PROVIDER = "cloud"
```
```bash
# .env
LLM_API_KEY=sk-你的key
```
支持 OpenAI、Kimi、智谱、硅基流动等任何 OpenAI 兼容接口。

---

### 🔍 嵌入引擎

修改 `config/config.py` 第 42 行 `EMBED_PROVIDER`：

**A. 硅基流动（免费 · 纯云端 ← 当前默认）**

```python
# config/config.py
EMBED_PROVIDER = "siliconflow"
```
```bash
# .env
SILICONFLOW_API_KEY=sk-你的key
```
→ [siliconflow.cn](https://siliconflow.cn) 注册获取 Key，BGE 中文模型永久免费，1024 维，国内直连。

**B. Ollama 本地**

```python
# config/config.py
EMBED_PROVIDER = "ollama"
```
```bash
ollama pull nomic-embed-text   # 768 维，只需拉一次
```
无需 API Key，向量数据不出本地机器。

**C. OpenAI**

```python
# config/config.py
EMBED_PROVIDER = "openai"
```
```bash
# .env
OPENAI_API_KEY=sk-你的key
```
1536 维，需能访问 OpenAI 官方 API。

---

### ⚠️ 注意

- **切换嵌入源后，旧向量库不兼容**（维度不同：Ollama 768 / SiliconFlow 1024 / OpenAI 1536）。直接改 `EMBED_PROVIDER` 运行即可，系统会自动创建新库。
- **DeepSeek `deepseek-chat` 旧模型名将于 2026-07-24 停用**，请使用 `deepseek-v4-flash` 或 `deepseek-v4-pro`。

---

## 🧰 内置工具

| 工具 | 功能 | 模块 |
|---|---|---|
| `search_web` | DuckDuckGo 联网搜索，支持时间过滤 | `tools/tool_search.py` |
| `auto_drive_manager` | Google Drive 智能建表与追加数据 | `tools/tool_drive.py` |
| `manage_sheet_rows` | Google Sheets 读 / 删 / 改 / 清空 | `tools/tool_drive.py` |
| `list_drive_files` | Google Drive 文件列表与搜索 | `tools/tool_drive.py` |
| `upload_file_to_drive` | 上传本地文件至 Google Drive | `tools/tool_drive.py` |
| `send_notification_email` | SMTP SSL 邮件发送 | `tools/tool_email.py` |
| `manage_local_file` | 沙箱内本地文件读写（防路径穿越） | `tools/tool_file.py` |
| `manage_memory` | Mem0 长期记忆写入与检索 | `tools/tool_memory.py` |
| `execute_python_code` | 隔离子进程执行 Python（10s 熔断） | `tools/tool_terminal.py` |

---

## 🎭 专家 Agent

| Agent | 定位 | 授权工具 | 文件 |
|---|---|---|---|
| **Researcher** | 情报分析 · 联网搜索 | `search_web` | `agents/researcher.py` |
| **Coder** | 自动化工程 · 本地执行 | `manage_local_file`, `send_notification_email` | `agents/coder.py` |
| **GoogleDrive** | Drive 管理专家 | 全部 Drive 工具 | `agents/googledrive.py` |

> 扩展：在 `agents/registry.py` 注册 → 创建类文件继承 `BaseAgent` → Planner 自动发现。

---

## 📂 项目结构

```text
Small-Agent/
├── agents/                 # 🎭 Swarm 专家集群
│   ├── base_agent.py       #   基类：ReAct 循环、权限隔离、防幻觉
│   ├── registry.py         #   专家注册表
│   ├── researcher.py       #   情报分析师（仅 search_web）
│   ├── coder.py            #   自动化工程师（本地文件 + 邮件）
│   └── googledrive.py      #   Google Drive 专家（全部云端工具）
│
├── business/               # 📋 业务资产层
│   ├── business_layer.py   #   确定性路由：别名 → file_id 查表
│   └── asset_registry.py   #   可插拔注册表（JSON / Mem0）
│
├── mcp_servers/            # 🌐 MCP 协议适配
│   ├── small_agent_server.py  # MCP Server（stdio / SSE 双模式）
│   └── tool_adapter.py     #   OpenAI ↔ MCP 格式双向转换
│
├── core/                   # ⚙️ 核心引擎
│   ├── planner.py          #   🧠 DAG 拆解 · RAG 路由 · 风险定级
│   ├── llm_engine.py       #   🔧 工具自动加载 · ReAct 循环
│   ├── llm_client.py       #   🔌 客户端工厂（Ollama / DeepSeek / OpenAI）
│   ├── retriever.py        #   🔍 专家向量检索（余弦相似度 + Top-K）
│   ├── json_utils.py       #   📦 JSON 健壮解析
│   ├── sandbox.py          #   🏖️ 分层沙箱引擎（五层防御）
│   └── tracing/            #   📊 调用链追踪引擎
│       ├── engine.py       #      Trace / Span / 上下文传播 / 存储
│       └── agent.py        #      AgentTracer（审计日志 + span 管理）
│
├── agent_workspace/        # 📁 工具操作目录（文件产物 + 追踪/审计日志）
│
├── tools/                  # 🔌 热插拔工具库
│   ├── tool_search.py      #   DuckDuckGo 搜索
│   ├── tool_drive.py       #   Google Drive & Sheets
│   ├── tool_email.py       #   SMTP 邮件
│   ├── tool_file.py        #   本地文件沙箱
│   ├── tool_memory.py      #   Mem0 长期记忆
│   └── tool_terminal.py    #   代码执行沙箱
│
├── config/                 # 🔧 全局配置
│   ├── config.py           #   模型端点、后端开关、沙箱参数
│   └── business_assets.json  # 业务资产注册数据
│
├── .env                    # 🔑 API Key（gitignore 保护）
├── app.py                  # 🖥️ Streamlit 主控台
├── chat_manager.py         # 💬 多会话管理 + AI 自动标题
├── ui_components.py        # 🎨 侧边栏 UI 组件
├── tests/                  # 🧪 测试
└── requirements.txt
```

---

## 🧪 一条指令的完整旅程

**输入：**
> "搜索今天 Apple 最新新闻，写入「苹果简报」表格，发邮件给 boss@example.com"

```
  👤 用户 ──▶ 🧠 Planner ──▶ 🛡️ 风控 ──▶ ⚡ Swarm 并发

  Planner 拆解:
  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
  │  ① 搜索新闻  │ ──▶ │  ② 写入表格  │ ──▶ │  ③ 发送邮件  │
  │  Researcher │     │ GoogleDrive │     │    Coder    │
  │  search_web │     │auto_drive   │     │send_email   │
  └─────────────┘     └─────────────┘     └─────────────┘
       │                     │                    │
       ▼                     ▼                    ▼
   3 条头条             表格已更新            邮件已发送
```

---

## 🔗 XComs：跨任务数据流转

Swarm 集群中各任务**不通过文件传递数据**，而是通过 **XComs（内存字符串）**：

```
Task 1: Researcher 搜索 → 返回文本结果字符串
                               ↓
                     task_results_store["task_1"] = result
                               ↓
Task 2: Coder 执行 → prior_context = "【前置任务 task_1 的结果】: ..."
                               ↓
                     LLM 基于 prior_context 继续工作
```

Planner 拆解 DAG 时标注 `depends_on` 依赖关系，执行器按拓扑排序分批并发。前置任务完成后，其结果文本被拼接进下游 Agent 的 System Prompt 中作为 `prior_context`。全程在内存中流转，无中间文件 I/O 开销。

---

## 📁 Agent 工作区

`agent_workspace/` 是 Agent 调工具时的**操作目录**，不是任务管道的一环：

- **`manage_local_file` 工具**：在 `agent_workspace/` 沙箱内读写文件（防路径穿越），Agent 可自主选择写入 `.md` 总结、`.py` 脚本等产物
- **`execute_python_code` 工具**：隔离子进程在 `agent_workspace/` 中执行 Python 代码
- **`.traces/`**：每轮对话的调用链追踪日志
- **`.sandbox_audit/`**：文件操作安全审计记录

```text
agent_workspace/
├── *.py / *.md / *.json     # Agent 通过工具自主写入的产物
├── token.json               # Google OAuth token（自动生成）
├── .traces/                 # 调用链追踪日志
└── .sandbox_audit/          # 文件操作审计日志
```

> 文件是 Agent 完成任务的**可选终端产物**，任务间数据传递始终走 XComs 内存通道。

---

## 🏖️ 分层沙箱引擎

`core/sandbox.py` 提供五层防御的代码执行与文件操作沙箱，无需 Docker：

| 层级 | 机制 | 说明 |
|---|---|---|
| L1 | 资源硬限制 | `RLIMIT_CPU` / `RLIMIT_AS` / `RLIMIT_FSIZE` / `RLIMIT_NPROC` |
| L2 | 模块白名单 | import hook 注入，阻断 `os`/`subprocess`/`socket` 等危险模块 |
| L3 | 文件系统隔离 | 临时目录 + 路径绑定，`FileOperationGuard` 防路径穿越 |
| L4 | 审计日志 | 全量操作写入 `agent_workspace/.sandbox_audit/` |
| L5 | 超时熔断 | subprocess timeout，防止死循环 |

**三级强度**：`strict`（仅安全模块，适合公开服务）→ `moderate`（默认，允许常用数据分析库）→ `relaxed`（仅超时保护，开发调试用）

```python
# config/config.py
SANDBOX_LEVEL = "moderate"
ALLOWED_FILE_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ...}
NETWORK_BANNED_DOMAINS = []
```

---

## 📋 业务资产层

`business/` 模块解决 LLM "用 sheet_name 模糊搜索 Google Drive 文件经常找错"的痛点：

```python
from business.business_layer import get_business_layer

bl = get_business_layer()
asset = bl.resolve("奖金表")          # 确定性查表 → 返回 file_id
# 找不到直接抛 BusinessNotFoundError，绝不降级为模糊搜索
```

| 组件 | 文件 | 职责 |
|---|---|---|
| **BusinessLayer** | `business/business_layer.py` | 确定性路由 + Planner prompt 注入 + 工具代理（read/append/update/delete） |
| **AssetRegistry** | `business/asset_registry.py` | 可插拔存储后端：LocalJsonRegistry（默认）/ Mem0Registry |
| **business_assets.json** | `config/business_assets.json` | 本地注册数据，包含"奖金表"、"邀约表"等业务资产 |

`BusinessLayer.get_registry_prompt()` 会在 Planner 的 system prompt 中注入已登记业务清单，让 LLM 直接使用 `sheet_id` 精确定位。

---

## 🌐 MCP 协议支持

`mcp_servers/` 将项目所有工具以 **MCP (Model Context Protocol)** 标准对外暴露，可接入 Claude Desktop / Cursor 等客户端：

```bash
# 预览模式（导出工具清单，无需安装 MCP SDK）
python -m mcp_servers.small_agent_server --mode preview

# stdio 模式（Claude Desktop 可直接连接）
python -m mcp_servers.small_agent_server --mode stdio

# SSE HTTP 模式（浏览器/远程客户端）
python -m mcp_servers.small_agent_server --mode sse --port 8000
```

| 组件 | 文件 | 职责 |
|---|---|---|
| **MCP Server** | `mcp_servers/small_agent_server.py` | stdio / SSE 双模式，复用现有工具 + 业务层能力 |
| **格式适配器** | `mcp_servers/tool_adapter.py` | OpenAI function-calling ↔ MCP Tool 双向格式转换 |

> 无需安装 MCP SDK 即可预览工具清单。完整服务需要 `pip install mcp`。

---

## 📄 License

MIT
