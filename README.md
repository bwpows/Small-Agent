<p align="center">
  <h1 align="center">🧠 Agent OS</h1>
  <p align="center"><strong>Multi-Agent Swarm · Plan-and-Solve · ReAct · RAG</strong></p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python">
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
    <img src="https://img.shields.io/badge/Reasoning-DeepSeek_V4-4B9CD3.svg" alt="DeepSeek">
    <img src="https://img.shields.io/badge/Embed-Ollama-000000.svg" alt="Ollama">
  </p>
</p>

---

> **DAG 任务拆解 · 工具权限隔离 · 防幻觉安全风控 · 可视化主控台 · 推理走云端 + 嵌入跑本地**

一个双引擎智能助理框架。**推理**走 DeepSeek V4 云端 API，**向量嵌入**跑本地 Ollama，兼顾性能与隐私。系统将宏观目标拆解为 DAG 任务拓扑，通过向量检索智能匹配专家 Agent，多线程并发执行，内置防幻觉与安全审批机制。

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
└─────────────────────────────────────────────────────┘
                         │
                         ▼
         ┌───────────────────────────────┐
         │         双引擎                 │
         │  ☁️ DeepSeek V4  ── 推理      │
         │  🖥️ Ollama Local ── 向量嵌入  │
         └───────────────────────────────┘
```

---

## ✨ 核心特性

| 特性 | 说明 |
|---|---|
| 🕸️ **DAG 任务拓扑** | Planner 拆解任务时标注 `depends_on`，按拓扑排序分批执行，XComs 跨任务数据流转 |
| 🧬 **RAG 智能路由** | 用户目标向量化 → 与专家描述余弦相似度匹配 → 自动捞出 Top-3 专家 |
| 🛡️ **物理级工具隔离** | 每个 Agent 白名单过滤工具，权限在内存层面物理阻断 |
| 🔒 **HITL 安全风控** | 高危操作（删除/邮件/批量写）自动挂起，等待 UI 人工审批 |
| 🚫 **防幻觉拦截** | 追踪 `actual_write_success` 状态，拦截"未调工具却谎称成功" |
| 🔌 **工具热插拔** | `tools/` 目录下新增 `tool_*.py` 自动扫描注册，零配置 |
| ⚡ **多线程并发** | 同批次独立任务 `ThreadPoolExecutor` 并发，互不阻塞 |
| ☁️🖥️ **混合引擎** | 推理走 DeepSeek 云端（无需 GPU），嵌入跑 Ollama 本地（数据不出机器） |

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.10+
- [Ollama](https://ollama.com) 本地安装并运行（用于向量嵌入）
- DeepSeek API Key（用于推理）

### 2. 安装依赖

```bash
git clone <your-repo-url>
cd Small-Agent

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 启动 Ollama 并拉取嵌入模型

```bash
ollama serve                      # 启动 Ollama 服务
ollama pull nomic-embed-text      # 拉取嵌入模型（768 维）
```

### 4. 获取 DeepSeek API Key

去 [platform.deepseek.com](https://platform.deepseek.com) 注册，在 API Keys 页面创建一个 Key。

### 5. 配置 `.env`

```bash
# 编辑项目根目录的 .env 文件：
DEEPSEEK_API_KEY=sk-你的deepseek-key
```

> `.env` 已在 `.gitignore` 中，不会被提交到 Git。

### 6. 启动

```bash
streamlit run app.py
```

浏览器打开 `http://localhost:8501`，输入一句复合指令，观察 Planner 拆解 → 风控审批 → Swarm 并发的完整流水线。

---

## 🔌 模型配置

系统包含两个引擎：**推理**（生成文本）和**嵌入**（文本转向量），各自独立配置。统一在 `config/config.py` 中修改，API Key 统一写在 `.env`。

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
→ [platform.deepseek.com](https://platform.deepseek.com) 注册获取 Key，国内直连，价格极低。

**B. 本地 Ollama**

```python
# config/config.py
LLM_PROVIDER = "ollama"
```
无需 API Key，前提是本地装了 Ollama 并已拉取模型。

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

**A. Ollama 本地（← 当前默认）**

```python
# config/config.py
EMBED_PROVIDER = "ollama"
```
```bash
ollama pull nomic-embed-text   # 768 维，只需拉一次
```
无需 API Key，向量数据不出本地机器。

**B. 硅基流动（免费 · 纯云端）**

```python
# config/config.py
EMBED_PROVIDER = "siliconflow"
```
```bash
# .env
SILICONFLOW_API_KEY=sk-你的key
```
→ [siliconflow.cn](https://siliconflow.cn) 注册获取 Key，BGE 中文模型永久免费，1024 维，国内直连。

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
| **Coder** | 自动化工程 · 云端写入 | `manage_sheet_rows`, `manage_local_file`, `send_notification_email` | `agents/coder.py` |
| **GoogleDrive** | Drive 管理专家 | 全部 Drive 工具 | `agents/googledrive.py` |
| **General Worker** | 全能兜底替补 | 全部工具 | `agents/base_agent.py` |

> 扩展：在 `agents/registry.py` 注册 → 创建类文件继承 `BaseAgent` → Planner 自动发现。

---

## 📂 项目结构

```text
Small-Agent/
├── agents/                 # 🎭 Swarm 专家集群
│   ├── base_agent.py       #   基类：ReAct 循环、权限隔离、防幻觉
│   ├── registry.py         #   专家注册表
│   ├── researcher.py       #   情报分析师
│   ├── coder.py            #   自动化工程师
│   └── googledrive.py      #   Google Drive 专家
│
├── core/                   # ⚙️ 核心引擎
│   ├── planner.py          #   🧠 DAG 拆解 · RAG 路由 · 风险定级
│   ├── llm_engine.py       #   🔧 工具自动加载 · 通用 ReAct 循环
│   ├── llm_client.py       #   🔌 客户端工厂（DeepSeek / OpenAI / Ollama 统一适配）
│   ├── retriever.py        #   🔍 专家向量检索（余弦相似度 + Top-K）
│   ├── json_utils.py       #   📦 JSON 健壮解析
│   └── tracing.py          #   📊 调用链追踪
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
│   └── config.py           #   模型端点、后端开关、向量库参数
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
  │  Researcher │     │    Coder    │     │    Coder    │
  │  search_web │     │ auto_drive  │     │send_email   │
  └─────────────┘     └─────────────┘     └─────────────┘
       │                     │                    │
       ▼                     ▼                    ▼
   3 条头条             表格已更新            邮件已发送
```

---

## 📄 License

MIT
