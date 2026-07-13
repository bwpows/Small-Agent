# 🧠 Agent OS (Plan-and-Solve 双脑架构版)

一个具备纯血自主智能、全自动纠错自愈以及长期记忆的本地化超级助理框架。

本项目现已正式从“单体 ReAct”架构跃迁为 **“Planner-Worker 双脑协同”** 架构，彻底解决了复杂长线任务中的大模型“失忆”、“死循环”与“逻辑崩塌”问题。

## 📖 架构演进说明
传统的 Agent 往往像一个蒙眼摸象的工人，只能“走一步看一步”。
本系统引入了业界顶级的 **Plan-and-Solve (规划与执行)** 范式，将系统一分为二：
1. **🧠 大脑 (Planner/CEO)**：绝对不碰工具，专注读取长期记忆与全局上下文，将模糊的宏大目标拆解为带有依赖关系（DAG）的严谨 JSON 任务流。
2. **🦾 小脑 (Worker/业务骨干)**：接手单一任务，基于底层 ReAct 引擎和 `While` 容错循环，死磕工具调用直到成功，最后向上级汇报。

## ✨ 史诗级核心特性

* **🕸️ DAG 任务拓扑规划**：大脑在拆解任务时，会自动标明 `depends_on` 依赖关系。确保情报搜集、数据处理、动作执行的顺序绝对正确。
* **🧬 双态记忆融合 (Mem0 + Context)**：大脑在排期前，会自动读取用户的 **Mem0 长期记忆**（喜好、关键实体）以及 **近期短对话上下文**，真正做到“懂你”的私人定制排期。
* **🛡️ 格式自愈与防幻觉机制 (Self-Healing)**：
    * **大脑层**：带有暴力正则清洗与“带错重试”机制，大模型输出错误 JSON 时，系统会自动反哺错误日志逼迫其修正。
    * **小脑层**：底层直接核对工具调用的真实状态变量，彻底封杀大模型“未调工具却谎称执行成功”的幻觉。
* **🔌 动态热插拔工具链**：支持显式工具路由（强制锁定），新增工具只需丢入 `tools/` 目录即刻自动挂载。现已集成：联网搜索、Google Drive、邮件发送等。
* **👁️ 沉浸式思考 UI (Visualized Execution)**：前端全面升级，通过嵌套的动态折叠面板，实时转播“CEO 规划图纸 -> Worker 疯狂调工具 -> 报错拦截堆栈 -> 最终汇报”的完整内幕。

---

## 📂 系统目录结构

```text
MY_MEMORY_AGENT/
├── agent_workspace/        # 工作区凭证与授权缓存 (Google API等)
├── config/                 # 全局配置模块
│   └── config.py           # 环境变量与核心业务参数
├── core/                   # 核心双脑引擎
│   ├── planner.py          # 🧠 大脑：负责 DAG 任务拆解、记忆读取与格式自愈
│   └── llm_engine.py       # 🦾 小脑：负责 ReAct 循环、工具调用与防幻觉拦截
├── tools/                  # 扩展工具库 (全自动扫描注册)
│   ├── tool_drive.py       # Google Drive 读写
│   ├── tool_search.py      # DuckDuckGo 联网情报搜集
│   └── tool_email.py       # 自动化邮件引擎
│   └── ... (更多工具)
├── tests/                  # 单元测试模块
│   └── test_planner.py     # 大脑独立拆解能力高压测试脚本
├── .env                    # 环境变量配置文件 (API Keys, 模型端点等)
├── app.py                  # Streamlit 前端主控台 (双脑接力与 UI 渲染)
├── chat_manager.py         # 多会话频道管理与持久化
└── ui_components.py        # 自定义侧边栏与历史渲染组件


---

## 🚀 快速开始

### 1. 环境准备

建议使用 Python 3.10+。克隆仓库并安装依赖：

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

```

### 2. 环境与密钥配置

在项目根目录创建 `.env` 文件，配置你的核心端点与记忆库 API：

```env
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=你的大模型名称
# Mem0 API Key 及其他工具所需的授权凭证

```

### 3. 运行独立模块测试 (可选但推荐)

在启动整个系统前，可以先单独测试大脑的任务拆解能力：

```bash
python tests/test_planner.py

```

### 4. 启动 Agent OS 主控台

执行以下命令启动图形化双脑交互界面：

```bash
streamlit run app.py

```

浏览器将自动打开 `http://localhost:8501`。尝试发送一句包含“搜集、整理、发送”的复合型宏大指令，欣赏它极其优雅的执行接力赛吧！