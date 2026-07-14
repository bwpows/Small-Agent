# 🧠 Agent OS —— Multi-Agent Swarm 智能体集群

> **Plan-and-Solve × ReAct × RAG · 双脑协同 · 安全风控 · 长期记忆 · 可视化主控台**

一个基于 Ollama 本地大模型的全自动智能助理框架。系统将宏观目标拆解为 DAG 任务拓扑，通过向量检索智能匹配专家 Agent，多线程并发执行，并内置严格的防幻觉与安全审批机制。

---

## 🏗️ 架构概览

```
用户输入宏大目标
        │
        ▼
┌───────────────────────────────────────┐
│   🧠 Planner (大脑 / CEO)              │
│   · 注入 Mem0 长期记忆 + 对话上下文      │
│   · RAG 向量检索匹配最佳专家             │
│   · DAG 任务拆解（含 depends_on 依赖）   │
│   · 风险定级（low / medium / high）      │
│   · JSON 格式自愈（最多 3 次带错重试）    │
└──────────────┬────────────────────────┘
               │
               ▼
┌───────────────────────────────────────┐
│   🛡️ HITL 安全风控拦截层               │
│   · 高危操作 → 人类审批 → 授权/驳回      │
│   · 低/中危操作 → 自动放行              │
└──────────────┬────────────────────────┘
               │
               ▼
┌───────────────────────────────────────┐
│   ⚡ Swarm 专家集群并发执行              │
│   ┌──────────┐ ┌──────────┐           │
│   │Researcher│ │  Coder   │  ...      │
│   │(搜索工具) │ │(写入工具) │           │
│   └──────────┘ └──────────┘           │
│   · 工具权限物理隔离（白名单过滤）        │
│   · DAG 拓扑排序 → 批次并发              │
│   · XComs 跨任务数据流转                │
│   · ReAct 循环 + 防幻觉拦截             │
│   · 死循环熔断（max 4 轮）              │
└───────────────────────────────────────┘
```

---

## ✨ 核心特性

### 🕸️ DAG 任务拓扑规划
Planner 拆解任务时自动标注 `depends_on` 依赖关系，系统按拓扑排序分批执行。前置任务结果通过 XComs 机制传递到后续任务，确保情报搜集 → 数据处理 → 动作执行的顺序绝对正确。

### 🧬 RAG 智能专家路由
通过 Ollama Embedding 将用户目标向量化，与所有注册专家的描述向量做余弦相似度匹配，自动捞出 Top-3 最匹配的专家，实现 "按需派单"。

### 🛡️ 物理级工具隔离
每个 Agent 通过 `allowed_tool_names` 白名单严格过滤可用工具。Researcher 只能搜索、Coder 只能读写——权限在内存层面即被物理阻断，杜绝越权操作。

### 🔒 HITL 安全风控
Planner 对每个任务进行三级风险评估（low / medium / high）。高危操作（文件删除、邮件发送、批量写入等）自动挂起，等待用户在 UI 中逐条审阅并授权或驳回。

### 🛡️ 格式自愈与防幻觉
- **Planner 层**：大模型输出非法 JSON 时，系统捕获解析错误原样反馈，逼迫其修正（最多 3 轮）。
- **Worker 层**：实时追踪 `actual_write_success` 状态变量，拦截 "未调工具却谎称执行成功" 的幻觉行为。

### 🔌 动态热插拔工具链
新增工具只需在 `tools/` 目录下创建 `tool_*.py` 文件并声明 `REGISTER_NAME` + `TOOL_DEFINITION`，系统启动时全自动扫描注册。

### ⚡ 多线程并发执行
同一批次的独立任务通过 `ThreadPoolExecutor` 并发执行，每个 Agent 在独立线程中完成 ReAct 循环，互不阻塞。

---

## 🧰 内置工具矩阵

| 工具名称 | 功能描述 | 所属模块 |
|---|---|---|
| `search_web` | DuckDuckGo 联网搜索，支持时间过滤 | `tools/tool_search.py` |
| `auto_drive_manager` | Google Drive 智能建表与追加数据 | `tools/tool_drive.py` |
| `manage_sheet_rows` | Google Sheets 读/删/改/清空 | `tools/tool_drive.py` |
| `list_drive_files` | Google Drive 文件列表与搜索 | `tools/tool_drive.py` |
| `upload_file_to_drive` | 上传本地文件至 Google Drive | `tools/tool_drive.py` |
| `send_notification_email` | SMTP SSL 邮件发送 | `tools/tool_email.py` |
| `manage_local_file` | 沙箱内本地文件读写（防路径穿越） | `tools/tool_file.py` |
| `manage_memory` | Mem0 长期记忆的写入与检索 | `tools/tool_memory.py` |
| `execute_python_code` | 隔离子进程执行 Python（10秒熔断） | `tools/tool_terminal.py` |

---

## 🎭 专家 Agent 集群

| Agent | 角色定位 | 授权工具 | 文件 |
|---|---|---|---|
| **Researcher** | 情报分析师，联网搜索与数据挖掘 | `search_web` | `agents/researcher.py` |
| **Coder** | 自动化工程师，本地操作与云端写入 | `manage_sheet_rows`, `manage_local_file`, `send_notification_email` | `agents/coder.py` |
| **GoogleDrive** | Google Drive 管理专家 | 全部 Drive 工具 | `agents/googledrive.py` |
| **General Worker** | 全能替补，未被匹配时的兜底执行者 | 全部工具 | `agents/base_agent.py` |

> 扩展方式：在 `agents/registry.py` 注册新专家，创建对应类文件继承 `BaseAgent`，Planner 的 RAG 检索会自动发现并匹配。

---

## 📂 项目结构

```text
Small-Agent/
├── agents/                 # 🎭 Swarm 专家集群
│   ├── base_agent.py       #   基类：ReAct 循环、工具权限隔离、防幻觉
│   ├── registry.py         #   专家注册表（百人级架构底座）
│   ├── researcher.py       #   情报分析师
│   ├── coder.py            #   自动化工程师
│   └── googledrive.py      #   Google Drive 专家
│
├── core/                   # ⚙️ 核心引擎
│   ├── planner.py          #   🧠 大脑：DAG 拆解、RAG 路由、风险定级、格式自愈
│   ├── llm_engine.py       #   🔧 工具自动加载与通用 ReAct 引擎
│   └── retriever.py        #   🔍 专家向量检索（余弦相似度 + Top-K 匹配）
│
├── tools/                  # 🔌 热插拔工具库（自动扫描注册）
│   ├── tool_search.py      #   DuckDuckGo 联网搜索
│   ├── tool_drive.py       #   Google Drive & Sheets 全套操作
│   ├── tool_email.py       #   SMTP SSL 邮件引擎
│   ├── tool_file.py        #   本地文件沙箱读写
│   ├── tool_memory.py      #   Mem0 + Qdrant 长期记忆
│   └── tool_terminal.py    #   隔离式 Python 代码执行
│
├── config/                 # 🔧 全局配置
│   ├── config.py           #   模型端点、Embedding 参数、向量库配置
│   └── env_config.py       #   邮件 SMTP 等敏感凭证
│
├── agent_workspace/        # 💾 工作区（Google 凭证、生成文件）
├── app.py                  # 🖥️ Streamlit 主控台
├── chat_manager.py         # 💬 多会话管理与 AI 自动标题
├── ui_components.py        # 🎨 侧边栏卡片 UI 与聊天历史渲染
├── tests/
│   └── test_planner.py     # 🧪 Planner 独立拆解能力测试
├── chat_history_db.json    # 📦 对话持久化数据库
└── requirements.txt
```

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.10+
- [Ollama](https://ollama.com) 已安装并拉取所需模型

### 2. 安装依赖

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 拉取模型

```bash
ollama pull qwen3-coder:30b          # 主推理模型
ollama pull nomic-embed-text         # 向量嵌入模型（RAG 必需）
```

### 4. 配置环境变量

编辑 `config/config.py`，确认模型端点与名称：

```python
OLLAMA_BASE_URL = "http://localhost:11434"
LLM_MODEL = "qwen3-coder:30b"        # 替换为你运行的模型名称
EMBEDDING_MODEL = "nomic-embed-text"
```

如需使用邮件功能，在 `config/env_config.py` 配置 SMTP 凭证；如需使用 Google Drive，将 `credentials.json` 放入 `agent_workspace/` 目录。

### 5. 运行测试（可选）

```bash
python tests/test_planner.py
```

这会向 Planner 发送一个包含搜索、写表、发邮件的复合指令，验证任务拆解与 JSON 输出是否正常。

### 6. 启动主控台

```bash
streamlit run app.py
```

浏览器打开 `http://localhost:8501`，尝试输入一句复合型指令，观察 Planner 拆解 → 风控审批 → Swarm 并发的完整执行流水线。

---

## 🧪 示例：一条指令的完整执行过程

**用户输入：**
> "帮我搜索今天关于 Apple 的最新新闻，把核心内容写入 Google Drive 的「苹果简报」表格，然后发邮件给 boss@example.com。"

**系统执行流程：**

1. **Planner 拆解** → 生成 3 个子任务（搜索 → 写表 → 发邮件），标记 `depends_on` 链，Researcher / Coder 分工派发
2. **风控审查** → 检测到 "发邮件" 为高危，挂起审批 → 用户在 UI 点击 "授权执行"
3. **第 1 批次** → Researcher Agent 调用 `search_web("Apple news", time_range="past_day")` 获取 3 条头条
4. **第 2 批次** → Coder Agent 基于搜索结果调用 `auto_drive_manager("苹果简报", data_array=[...])` 写入云端表格
5. **第 3 批次** → Coder Agent 调用 `send_notification_email(subject="苹果今日简报", content=...)` 发送邮件
6. **汇总报告** → 各 Agent 结果整合输出，对话自动保存

---

## 📄 许可证

MIT License
