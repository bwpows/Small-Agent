<p align="center">
  <h1 align="center">🧠 Small-Agent</h1>
  <p align="center"><strong>Multi-Agent · DAG Workflow · ReAct · Plan-and-Solve · RAG</strong></p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python">
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
    <img src="https://img.shields.io/badge/LLM-DeepSeek_V4-4B9CD3.svg" alt="DeepSeek">
    <img src="https://img.shields.io/badge/Embed-SiliconFlow-8A2BE2.svg" alt="SiliconFlow">
  </p>
</p>

---

> **Monorepo 双包架构**：`agent_engine`（大脑层） + `app_server`（服务层），前后端完全解耦。

一个多 Agent 智能助理框架。**推理**默认走 DeepSeek 云端、**向量嵌入**走硅基流动免费 BGE 模型，同时支持 OpenAI / 本地 Ollama。内置 DAG 任务拓扑、HITL 风控、五层沙箱引擎、MCP 协议暴露。

---

## 🚀 快速开始

**环境**：Python 3.10+ · DeepSeek API Key

```bash
git clone <repo-url> && cd Small-Agent
python -m venv venv && source venv/bin/activate
pip install -e .
cp .env.example .env   # 编辑填入 DEEPSEEK_API_KEY
uvicorn app_server.main:app --reload --port 8000
```

浏览器打开 `http://localhost:8000/docs` 查看 API 文档。

前端为独立项目 `small-agent-web`（React + Vite）：

```bash
cd ../small-agent-web && npm install && npm run dev
```

---

## 🏗️ 架构

```
                        ┌─────────────┐
                        │   👤 用户    │
                        └──────┬──────┘
                               ▼
┌──────────────────────────────────────────────────────┐
│                  🧠 Planner（规划器）                   │
│  Mem0 长期记忆 · 对话历史注入 · RAG 专家路由            │
│  DAG 任务拆解（depends_on 依赖图）· 三级风险定级        │
│  JSON 自愈解析（最多 3 轮带错重试）                     │
└────────────────────────┬─────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────┐
│                 🛡️ RiskGate 风控层                     │
│  high → 挂起等待人工审批 · medium/low → 自动放行        │
└────────────────────────┬─────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────┐
│           ⚡ DAG Workflow Runtime（多线程并发）         │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐          │
│  │Researcher│   │  Coder   │   │  Google  │  ...     │
│  │  搜索    │   │   写入   │   │  Drive   │          │
│  └──────────┘   └──────────┘   └──────────┘          │
│  Kahn 拓扑分层 · ThreadPoolExecutor 同层并发            │
│  XComs 内存跨任务数据流转 · 任务级/全局超时熔断          │
│  自动重试 + Token 用量追踪                             │
└────────────────────┬─────────────────────────────────┘
                     ▼
      ┌──────────────────────────────┐
      │         双引擎                 │
      │  ☁️ DeepSeek V4 —— 推理       │
      │  ☁️ SiliconFlow —— 向量嵌入   │
      └──────────────────────────────┘
```

---

## ✨ 核心特性

| 特性 | 说明 |
|---|---|
| 🕸️ **DAG 任务拓扑** | Planner 拆解时标注 `depends_on`，Kahn 拓扑分层并发，XComs 内存数据流转 |
| 🔄 **ReAct 循环** | Thought → Action → Observation 循环，工具调用驱动推理 |
| 🧬 **RAG 智能路由** | 用户目标向量化 → 专家描述余弦相似度匹配 → Top-K 自动路由 |
| 🛡️ **HITL 安全风控** | 高危操作（删除/邮件/批量写）挂起等待人工审批 |
| 🔁 **自动重试** | 任务失败后自动重试 N 次，从 FAILED → PENDING 状态恢复 |
| ⏱️ **超时熔断** | 单任务超时 + 全局 deadline，防止工作流卡死 |
| 📊 **Token 追踪** | 每次 Agent 执行的 token 用量自动收集汇总 |
| 🏖️ **五层沙箱** | 资源限制 → 模块白名单 → 文件隔离 → 审计日志 → 超时熔断 |
| 🚫 **防幻觉拦截** | 追踪工具调用状态，拦截"未调工具却谎称成功" |
| 📋 **业务资产层** | 别名 → file_id 确定性查表，绕过 LLM 模糊匹配 |
| 🌐 **MCP 协议** | 工具以 MCP 标准对外暴露，可对接 Claude Desktop / Cursor |
| 🔌 **工具热插拔** | `tools/` 下新增 `tool_*.py` 自动注册，零配置 |
| ☁️🖥️ **混合引擎** | DeepSeek / OpenAI / Ollama 推理 + SiliconFlow / Ollama 嵌入 |

---

## 📂 项目结构

```text
Small-Agent/
├── src/
│   ├── agent_engine/                  # 🧠 大脑层
│   │   ├── config.py                  #   LLM / 嵌入 / 沙箱全局配置
│   │   ├── llm_client.py              #   LLM 客户端工厂（Ollama / DeepSeek / OpenAI）
│   │   ├── llm_engine.py              #   核心执行引擎（工具发现 + ReAct + SSE 流式）
│   │   ├── planner.py                 #   DAG 拆解 · RAG 路由 · 风险定级
│   │   ├── retriever.py               #   专家向量检索（余弦相似度 + Top-K）
│   │   ├── json_utils.py              #   JSON 健壮解析 + Schema 校验
│   │   ├── sandbox.py                 #   分层沙箱引擎（五层防御）
│   │   │
│   │   ├── workflow/                  # 🕸️ DAG 工作流运行时
│   │   │   ├── plan.py                #   Task / WorkflowPlan（计划模型 + 校验）
│   │   │   ├── state.py               #   TaskStatus / TaskState（状态机）
│   │   │   ├── scheduler.py           #   DAGScheduler（拓扑分层 + 线程池并发）
│   │   │   ├── runtime.py             #   WorkflowRuntime（总编排器）
│   │   │   ├── context.py             #   GlobalContext / TaskContext
│   │   │   ├── artifact.py            #   Artifact / ArtifactStore（线程安全产物）
│   │   │   └── risk_gate.py           #   HITL 风控闸门
│   │   │
│   │   ├── agents/                    # 🎭 专家集群
│   │   │   ├── base_agent.py          #   基类（ReAct 循环 · 权限隔离 · 防幻觉）
│   │   │   ├── registry.py            #   注册表（工厂 + 缓存）
│   │   │   ├── researcher.py          #   情报分析师（search_web）
│   │   │   ├── coder.py               #   自动化工程师（文件 + 邮件）
│   │   │   └── googledrive.py         #   Google Drive 专家（全部云端工具）
│   │   │
│   │   ├── tools/                     # 🔌 热插拔工具库
│   │   │   ├── tool_search.py         #   DuckDuckGo 搜索
│   │   │   ├── tool_drive.py          #   Google Drive & Sheets
│   │   │   ├── tool_email.py          #   SMTP 邮件
│   │   │   ├── tool_file.py           #   本地文件沙箱
│   │   │   ├── tool_memory.py         #   Mem0 长期记忆
│   │   │   └── tool_terminal.py       #   代码执行沙箱
│   │   │
│   │   ├── business/                  # 📋 业务资产层
│   │   │   ├── business_layer.py      #   确定性路由（别名 → file_id）
│   │   │   └── asset_registry.py      #   可插拔注册表（JSON / Mem0）
│   │   │
│   │   ├── mcp/                       # 🌐 MCP 协议适配
│   │   │   ├── small_agent_server.py  #   MCP Server（stdio / SSE）
│   │   │   └── tool_adapter.py        #   OpenAI ↔ MCP 格式转换
│   │   │
│   │   ├── tracing/                   # 📊 调用链追踪
│   │   │   ├── engine.py              #   Trace / Span / 上下文传播
│   │   │   └── agent.py               #   AgentTracer（审计日志）
│   │   │
│   │   └── assets/                    # 📦 静态资源
│   │       └── business_assets.json   #   业务资产数据
│   │
│   └── app_server/                    # 🌐 FastAPI 服务层
│       ├── main.py                    #   路由入口（认证 / 对话 / Drive / IM）
│       ├── auth.py                    #   鉴权（JWT / API Key / OAuth）
│       ├── chat_service.py            #   对话编排（租户 / 流式 / 渠道）
│       ├── db.py                      #   SQLAlchemy ORM（9 张表）
│       ├── deps.py                    #   依赖注入（TenantContext）
│       ├── config.py                  #   服务层配置（DB / JWT / 限流）
│       ├── schemas.py                 #   Pydantic Schema
│       ├── limiter.py                 #   请求限流
│       └── channels/                  #   IM 渠道
│           └── feishu.py              #   飞书事件回调 + OAuth
│
├── tests/                             # 🧪 单元测试
│   ├── test_dag_runtime.py            #   DAG 工作流运行时测试
│   ├── test_sandbox.py                #   沙箱引擎测试
│   ├── test_planner.py                #   Planner 测试
│   └── test_json_utils.py             #   JSON 解析测试
│
├── data/                              # 📁 运行时数据
│   ├── app.db                         #   SQLite 数据库
│   └── workspace/                     #   Agent 工作区（产物 + 审计日志）
│
├── deploy/                            # 🚢 部署配置
│   ├── nginx.conf                     #   Nginx 反向代理
│   └── small-agent.service            #   systemd 服务
│
├── alembic/                           # 数据库迁移
├── pyproject.toml                     # 项目元数据
├── requirements.txt                   # 依赖清单
├── Dockerfile                         # Docker 镜像
└── docker-compose.yml                 # 容器编排
```

---

## 🧪 一条指令的旅程

> "搜索今天 Apple 最新新闻，写入「苹果简报」表格，发邮件给 boss@example.com"

```
  Planner 拆解 → RiskGate 风控 → DAG 拓扑分层 → 分批并发执行

  Layer 0:  ┌─────────────────┐
            │  ① 搜索新闻      │  Researcher · search_web
            │  depends_on: []  │
            └────────┬────────┘
                     │ 产出 → XComs
                     ▼
  Layer 1:  ┌─────────────────┐     ┌─────────────────┐
            │  ② 写入表格      │────▶│  ③ 发送邮件      │
            │  GoogleDrive     │     │     Coder        │
            │  auto_drive      │     │  send_email      │
            └─────────────────┘     └─────────────────┘
            depends_on: [1]          depends_on: [1]
            Layer 1 同层并发 → ThreadPoolExecutor
```

Layer 0 先执行 Researcher 搜索任务，完成后结果通过 XComs 注入 Layer 1 的两个下游任务的 `prior_context`，Layer 1 内的两个任务并发执行。

---

## 🔌 模型配置

### 🧠 推理引擎

修改 `src/agent_engine/config.py`：

| 引擎 | 配置值 | 说明 |
|---|---|---|
| **DeepSeek** | `LLM_PROVIDER = "deepseek"` | 默认，国内直连，极低成本 |
| **本地 Ollama** | `LLM_PROVIDER = "ollama"` | 数据不出本地 |
| **OpenAI / 兼容** | `LLM_PROVIDER = "cloud"` | OpenAI、Kimi、智谱等 |

### 🔍 嵌入引擎

修改 `src/agent_engine/config.py`：

| 引擎 | 配置值 | 维度 | 说明 |
|---|---|---|---|
| **硅基流动** | `EMBED_PROVIDER = "siliconflow"` | 1024 | 默认，BGE 模型免费 |
| **本地 Ollama** | `EMBED_PROVIDER = "ollama"` | 768 | 数据不出本地 |
| **OpenAI** | `EMBED_PROVIDER = "openai"` | 1536 | 需 OpenAI API |

> 切换嵌入源后向量维度不同，旧向量库不兼容，系统会自动创建新库。

---

## 🧰 内置工具

| 工具 | 功能 | 模块 |
|---|---|---|
| `search_web` | DuckDuckGo 联网搜索 | `tool_search.py` |
| `auto_drive_manager` | Google Drive 智能建表追加 | `tool_drive.py` |
| `manage_sheet_rows` | Google Sheets 读 / 删 / 改 | `tool_drive.py` |
| `list_drive_files` | Google Drive 文件搜索 | `tool_drive.py` |
| `upload_file_to_drive` | 上传文件至 Drive | `tool_drive.py` |
| `send_notification_email` | SMTP SSL 邮件 | `tool_email.py` |
| `manage_local_file` | 沙箱内文件读写 | `tool_file.py` |
| `manage_memory` | Mem0 长期记忆 | `tool_memory.py` |
| `execute_python_code` | 隔离子进程执行 Python | `tool_terminal.py` |

---

## 🎭 专家 Agent

| Agent | 定位 | 授权工具 | 文件 |
|---|---|---|---|
| **Researcher** | 情报分析 · 联网搜索 | `search_web` | `agents/researcher.py` |
| **Coder** | 自动化工程 · 本地执行 | `manage_local_file`, `send_notification_email` | `agents/coder.py` |
| **GoogleDrive** | Drive 管理专家 | 全部 Drive 工具 | `agents/googledrive.py` |

> 扩展：在 `agents/registry.py` 注册 → 继承 `BaseAgent` → Planner 自动发现。

---

## 🛡️ 沙箱引擎

`src/agent_engine/sandbox.py` 五层防御，无需 Docker：

| 层级 | 机制 | 说明 |
|---|---|---|
| L1 | 资源硬限制 | RLIMIT_CPU / AS / FSIZE / NPROC |
| L2 | 模块白名单 | import hook 阻断 `os`/`subprocess`/`socket` |
| L3 | 文件隔离 | 临时目录 + `FileOperationGuard` 防路径穿越 |
| L4 | 审计日志 | 全量写入 `data/workspace/.sandbox_audit/` |
| L5 | 超时熔断 | subprocess timeout 防死循环 |

三级强度：`strict` → `moderate`（默认）→ `relaxed`

---

## 📋 业务资产层

解决 LLM "用 sheet_name 模糊搜索经常找错"的痛点：

```python
from agent_engine.business.business_layer import get_business_layer

bl = get_business_layer()
asset = bl.resolve("奖金表")  # 确定性查表 → 返回 file_id，找不到直接报错
```

`BusinessLayer.get_registry_prompt()` 自动注入 Planner system prompt，让 LLM 直接用 ID 定位。

---

## 🌐 MCP 协议

工具以 MCP 标准对外暴露，可对接 Claude Desktop / Cursor：

```bash
python -m agent_engine.mcp.small_agent_server --mode preview   # 预览工具清单
python -m agent_engine.mcp.small_agent_server --mode stdio     # Claude Desktop
python -m agent_engine.mcp.small_agent_server --mode sse --port 8000  # HTTP
```

---

## 🔗 API 路由

| 路由组 | 端点 | 说明 |
|---|---|---|
| **Auth** | `/auth/register`, `/auth/login`, `/auth/me`, `/auth/keys` | 注册/登录、JWT、API Key |
| **OpenAI 兼容** | `/v1/models`, `/v1/chat/completions` | 支持 SSE 流式 |
| **Conversations** | `/v1/conversations` CRUD | 会话与消息管理 |
| **Feishu** | `/channels/feishu/webhook` | 飞书回调 + OAuth |
| **Google Drive** | `/auth/drive/service-account`, `/auth/google/*` | OAuth + 凭证管理 |
| **System** | `/health` | 健康检查 |

---

## 📊 DAG 工作流执行流程

```python
from agent_engine.workflow.runtime import WorkflowRuntime
from agent_engine.workflow.plan import WorkflowPlan
from agent_engine.agents.registry import AgentRegistry

registry = AgentRegistry(use_cache=True)
plan = WorkflowPlan.from_planner_output(planner_result)

runtime = WorkflowRuntime(
    plan=plan,
    registry=registry,
    user_query="搜索 Apple 最新新闻并整理成报告",
    history="用户: 昨天也问过类似问题...",
    max_workers=4,
    task_timeout=300.0,
    max_retries=1,
)

result = runtime.execute()
# {
#     "success": True,
#     "summary": "📋 **任务执行摘要**\n\n✅...",
#     "task_results": [...],
#     "total_usage": {"prompt_tokens": 1523, "completion_tokens": 421, "total_tokens": 1944},
# }
```

---

## 📄 License

MIT
