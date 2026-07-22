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

> **Monorepo 双包架构：`agent_engine`（大脑层）+ `app_server`（服务/数据层），面向微服务拆分。**

一个多引擎智能助理框架。**推理**默认走 DeepSeek 云端（国内直连、极低成本），也可切换 OpenAI 或本地 Ollama，**向量嵌入**跑硅基流动免费 BGE 模型。前后端完全解耦，前端独立仓库管理。

**启动方式：**
```bash
pip install -e .
uvicorn app_server.main:app --reload --port 8000
```

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
pip install -e .
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入必要的 API Key：

```bash
# 必填：推理引擎
DEEPSEEK_API_KEY=sk-你的key

# 可选：硅基流动嵌入（默认，免费）
SILICONFLOW_API_KEY=sk-你的key

# 可选：JWT 密钥（生产环境请修改）
JWT_SECRET=your-secret-key

# 可选：飞书机器人
FEISHU_APP_ID=xxx
FEISHU_APP_SECRET=xxx
```

### 4. 获取 DeepSeek API Key

去 [platform.deepseek.com](https://platform.deepseek.com) 注册，在 API Keys 页面创建一个 Key。

### 5. （可选）配置硅基流动嵌入

去 [siliconflow.cn](https://siliconflow.cn) 注册，获取免费 API Key。

> 嵌入模型默认走硅基流动（免费），无需任何配置即可使用。也可在 `config.py` 中改为本地 Ollama 嵌入。

### 6. 启动

**后端 API 服务：**
```bash
uvicorn app_server.main:app --reload --host 0.0.0.0 --port 8000
```

浏览器打开 `http://localhost:8000/docs` 查看 API 文档。

**前端 Web 界面：**

前端为独立项目 `small-agent-web`（React + Vite），位于同级目录：

```bash
cd ../small-agent-web && npm install && npm run dev
```

浏览器打开 `http://localhost:3000`，注册登录后即可使用。

---

## 🔌 模型配置

系统包含两个引擎，各自独立配置。统一在 `src/agent_engine/config.py` 中修改，API Key 统一写在 `.env`。

| 引擎 | 做什么 | 通俗理解 |
|---|---|---|
| 🧠 **推理** | 生成文字、思考、规划、调用工具、写答案 | 项目里真正"说话"的 AI 大脑 |
| 🔍 **嵌入** | 把文字转成数字向量，用来做语义搜索 | 帮系统找到"最相关"的专家或记忆 |

---

### 🧠 推理引擎

修改 `src/agent_engine/config.py` 第 13 行 `LLM_PROVIDER`：

**A. DeepSeek（当前默认）**

```python
# src/agent_engine/config.py
LLM_PROVIDER = "deepseek"
```
```bash
# .env
DEEPSEEK_API_KEY=sk-你的key
```
→ [platform.deepseek.com](https://platform.deepseek.com) 注册获取 Key，国内直连，价格极低。默认使用 `deepseek-v4-flash`。

**B. 本地 Ollama**

```python
# src/agent_engine/config.py
LLM_PROVIDER = "ollama"
OLLAMA_MODEL = "qwen3-coder:30b"        # 可替换为任意已拉取的模型
```
无需 API Key，数据不出本地机器。先 `ollama pull qwen3-coder:30b` 拉取模型。

**C. OpenAI / 其他兼容 API**

```python
# src/agent_engine/config.py
LLM_PROVIDER = "cloud"
```
```bash
# .env
LLM_API_KEY=sk-你的key
```
支持 OpenAI、Kimi、智谱、硅基流动等任何 OpenAI 兼容接口。

---

### 🔍 嵌入引擎

修改 `src/agent_engine/config.py` 第 42 行 `EMBED_PROVIDER`：

**A. 硅基流动（免费 · 纯云端 ← 当前默认）**

```python
# src/agent_engine/config.py
EMBED_PROVIDER = "siliconflow"
```
```bash
# .env
SILICONFLOW_API_KEY=sk-你的key
```
→ [siliconflow.cn](https://siliconflow.cn) 注册获取 Key，BGE 中文模型永久免费，1024 维，国内直连。

**B. Ollama 本地**

```python
# src/agent_engine/config.py
EMBED_PROVIDER = "ollama"
```
```bash
ollama pull nomic-embed-text   # 768 维，只需拉一次
```
无需 API Key，向量数据不出本地机器。

**C. OpenAI**

```python
# src/agent_engine/config.py
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
| `search_web` | DuckDuckGo 联网搜索，支持时间过滤 | `agent_engine/tools/tool_search.py` |
| `auto_drive_manager` | Google Drive 智能建表与追加数据 | `agent_engine/tools/tool_drive.py` |
| `manage_sheet_rows` | Google Sheets 读 / 删 / 改 / 清空 | `agent_engine/tools/tool_drive.py` |
| `list_drive_files` | Google Drive 文件列表与搜索 | `agent_engine/tools/tool_drive.py` |
| `upload_file_to_drive` | 上传本地文件至 Google Drive | `agent_engine/tools/tool_drive.py` |
| `send_notification_email` | SMTP SSL 邮件发送 | `agent_engine/tools/tool_email.py` |
| `manage_local_file` | 沙箱内本地文件读写（防路径穿越） | `agent_engine/tools/tool_file.py` |
| `manage_memory` | Mem0 长期记忆写入与检索 | `agent_engine/tools/tool_memory.py` |
| `execute_python_code` | 隔离子进程执行 Python（10s 熔断） | `agent_engine/tools/tool_terminal.py` |

---

## 🎭 专家 Agent

| Agent | 定位 | 授权工具 | 文件 |
|---|---|---|---|
| **Researcher** | 情报分析 · 联网搜索 | `search_web` | `agent_engine/agents/researcher.py` |
| **Coder** | 自动化工程 · 本地执行 | `manage_local_file`, `send_notification_email` | `agent_engine/agents/coder.py` |
| **GoogleDrive** | Drive 管理专家 | 全部 Drive 工具 | `agent_engine/agents/googledrive.py` |

> 扩展：在 `agent_engine/agents/registry.py` 注册 → 创建类文件继承 `BaseAgent` → Planner 自动发现。

---

## 📂 项目结构

```text
Small-Agent/
├── src/
│   ├── agent_engine/              # 🧠 大脑层：核心引擎
│   │   ├── __init__.py            #   公共 API 入口
│   │   ├── config.py              #   LLM / 嵌入 / 沙箱 / tracing 全局配置
│   │   ├── llm_client.py          #   LLM 客户端工厂（Ollama / DeepSeek / OpenAI）
│   │   ├── llm_engine.py          #   核心执行引擎（工具自动发现 + ReAct 循环 + SSE 流式）
│   │   ├── planner.py             #   🧠 DAG 拆解 · RAG 路由 · 风险定级
│   │   ├── retriever.py           #   🔍 专家向量检索（余弦相似度 + Top-K）
│   │   ├── json_utils.py          #   📦 JSON 健壮解析 + Schema 校验
│   │   ├── sandbox.py             #   🏖️ 分层沙箱引擎（五层防御）
│   │   │
│   │   ├── agents/                # 🎭 Swarm 专家集群
│   │   │   ├── base_agent.py      #   基类：ReAct 循环、权限隔离、防幻觉
│   │   │   ├── registry.py        #   专家注册表
│   │   │   ├── researcher.py      #   情报分析师（仅 search_web）
│   │   │   ├── coder.py           #   自动化工程师（本地文件 + 邮件）
│   │   │   └── googledrive.py     #   Google Drive 专家（全部云端工具）
│   │   │
│   │   ├── tools/                 # 🔌 热插拔工具库
│   │   │   ├── tool_search.py     #   DuckDuckGo 搜索
│   │   │   ├── tool_drive.py      #   Google Drive & Sheets
│   │   │   ├── tool_email.py      #   SMTP 邮件
│   │   │   ├── tool_file.py       #   本地文件沙箱
│   │   │   ├── tool_memory.py     #   Mem0 长期记忆
│   │   │   └── tool_terminal.py   #   代码执行沙箱
│   │   │
│   │   ├── business/              # 📋 业务资产层
│   │   │   ├── business_layer.py  #   确定性路由：别名 → file_id 查表
│   │   │   └── asset_registry.py  #   可插拔注册表（JSON / Mem0）
│   │   │
│   │   ├── mcp/                   # 🌐 MCP 协议适配
│   │   │   ├── small_agent_server.py  # MCP Server（stdio / SSE 双模式）
│   │   │   └── tool_adapter.py    #   OpenAI ↔ MCP 格式双向转换
│   │   │
│   │   ├── tracing/               # 📊 调用链追踪引擎
│   │   │   ├── engine.py          #   Trace / Span / 上下文传播 / 存储
│   │   │   └── agent.py           #   AgentTracer（审计日志 + span 管理）
│   │   │
│   │   └── assets/                # 📦 静态资源
│   │       └── business_assets.json  # 业务资产注册数据
│   │
│   └── app_server/                # 🌐 服务/数据层：FastAPI 后端
│       ├── main.py                #   API 路由入口（认证/对话/Drive/IM渠道）
│       ├── auth.py                #   鉴权系统（注册/登录/API Key/JWT/Drive Token）
│       ├── chat_service.py        #   对话服务编排（多租户/流式/渠道适配）
│       ├── config.py              #   服务层配置（数据库/JWT/飞书/Drive/限流）
│       ├── db.py                  #   SQLAlchemy ORM（9 张表）
│       ├── deps.py                #   FastAPI 依赖注入（TenantContext）
│       ├── limiter.py             #   请求限流
│       ├── schemas.py             #   Pydantic 请求/响应 Schema
│       └── channels/              #   IM 渠道适配
│           └── feishu.py          #   飞书事件回调 + OAuth 登录
│
├── alembic/                       # 数据库迁移脚本
│   ├── env.py
│   └── versions/                  # 迁移版本
├── tests/                         # 🧪 单元测试
│   ├── test_sandbox.py
│   ├── test_planner.py
│   └── test_json_utils.py
├── data/                          # 📁 运行时数据
│   ├── app.db                     #   SQLite 数据库
│   └── workspace/                 #   Agent 工作区（文件产物 + 追踪/审计日志）
│       ├── .traces/               #   调用链追踪日志
│       └── .sandbox_audit/        #   文件操作审计日志
├── scripts/                       # 脚本目录
├── pyproject.toml                 # 项目元数据与依赖
├── requirements.txt               # 依赖清单
├── alembic.ini                    # Alembic 配置
├── .env.example                   # 环境变量模板
└── .env                           # 🔑 API Key（gitignore 保护）
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

`data/workspace/` 是 Agent 调工具时的**操作目录**，不是任务管道的一环：

- **`manage_local_file` 工具**：在 `data/workspace/` 沙箱内读写文件（防路径穿越），Agent 可自主选择写入 `.md` 总结、`.py` 脚本等产物
- **`execute_python_code` 工具**：隔离子进程在 `data/workspace/` 中执行 Python 代码
- **`.traces/`**：每轮对话的调用链追踪日志
- **`.sandbox_audit/`**：文件操作安全审计记录

```text
data/workspace/
├── *.py / *.md / *.json     # Agent 通过工具自主写入的产物
├── token.json               # Google OAuth token（自动生成）
├── .traces/                 # 调用链追踪日志
└── .sandbox_audit/          # 文件操作审计日志
```

> 文件是 Agent 完成任务的**可选终端产物**，任务间数据传递始终走 XComs 内存通道。

---

## 🏖️ 分层沙箱引擎

`src/agent_engine/sandbox.py` 提供五层防御的代码执行与文件操作沙箱，无需 Docker：

| 层级 | 机制 | 说明 |
|---|---|---|
| L1 | 资源硬限制 | `RLIMIT_CPU` / `RLIMIT_AS` / `RLIMIT_FSIZE` / `RLIMIT_NPROC` |
| L2 | 模块白名单 | import hook 注入，阻断 `os`/`subprocess`/`socket` 等危险模块 |
| L3 | 文件系统隔离 | 临时目录 + 路径绑定，`FileOperationGuard` 防路径穿越 |
| L4 | 审计日志 | 全量操作写入 `data/workspace/.sandbox_audit/` |
| L5 | 超时熔断 | subprocess timeout，防止死循环 |

**三级强度**：`strict`（仅安全模块，适合公开服务）→ `moderate`（默认，允许常用数据分析库）→ `relaxed`（仅超时保护，开发调试用）

```python
# src/agent_engine/config.py
SANDBOX_LEVEL = "moderate"
ALLOWED_FILE_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ...}
NETWORK_BANNED_DOMAINS = []
```

---

## 📋 业务资产层

`src/agent_engine/business/` 模块解决 LLM "用 sheet_name 模糊搜索 Google Drive 文件经常找错"的痛点：

```python
from agent_engine.business.business_layer import get_business_layer

bl = get_business_layer()
asset = bl.resolve("奖金表")          # 确定性查表 → 返回 file_id
# 找不到直接抛 BusinessNotFoundError，绝不降级为模糊搜索
```

| 组件 | 文件 | 职责 |
|---|---|---|
| **BusinessLayer** | `agent_engine/business/business_layer.py` | 确定性路由 + Planner prompt 注入 + 工具代理（read/append/update/delete） |
| **AssetRegistry** | `agent_engine/business/asset_registry.py` | 可插拔存储后端：LocalJsonRegistry（默认）/ Mem0Registry |
| **business_assets.json** | `agent_engine/assets/business_assets.json` | 本地注册数据，包含"奖金表"、"邀约表"等业务资产 |

`BusinessLayer.get_registry_prompt()` 会在 Planner 的 system prompt 中注入已登记业务清单，让 LLM 直接使用 `sheet_id` 精确定位。

---

## 🌐 MCP 协议支持

`src/agent_engine/mcp/` 将项目所有工具以 **MCP (Model Context Protocol)** 标准对外暴露，可接入 Claude Desktop / Cursor 等客户端：

```bash
# 预览模式（导出工具清单，无需安装 MCP SDK）
python -m agent_engine.mcp.small_agent_server --mode preview

# stdio 模式（Claude Desktop 可直接连接）
python -m agent_engine.mcp.small_agent_server --mode stdio

# SSE HTTP 模式（浏览器/远程客户端）
python -m agent_engine.mcp.small_agent_server --mode sse --port 8000
```

| 组件 | 文件 | 职责 |
|---|---|---|
| **MCP Server** | `agent_engine/mcp/small_agent_server.py` | stdio / SSE 双模式，复用现有工具 + 业务层能力 |
| **格式适配器** | `agent_engine/mcp/tool_adapter.py` | OpenAI function-calling ↔ MCP Tool 双向格式转换 |

> 无需安装 MCP SDK 即可预览工具清单。完整服务需要 `pip install mcp`。

---

## 🔗 API 路由概览

| 路由组 | 端点 | 说明 |
|--------|------|------|
| **Auth** | `/auth/register`, `/auth/login`, `/auth/me`, `/auth/keys` | 用户注册/登录、JWT、API Key 管理 |
| **OpenAI Compatible** | `/v1/models`, `/v1/chat/completions`, `/v1/tools` | OpenAI 兼容接口（支持 SSE 流式） |
| **Conversations** | `/v1/conversations` CRUD + `/messages` | 会话和消息管理 |
| **Feishu Webhook** | `/channels/feishu/webhook` | 飞书事件回调（URL验证+消息处理） |
| **Feishu OAuth** | `/auth/feishu/login`, `/auth/feishu/callback`, `/auth/bind/feishu` | 飞书 OAuth 登录与绑定 |
| **Google Drive** | `/auth/drive/service-account`, `/auth/drive/status`, `/auth/google/*` | Drive 凭证管理 |
| **System** | `/health` | 健康检查 |

---

## 📄 License

MIT
