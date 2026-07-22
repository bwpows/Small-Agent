import json
from agent_engine.retriever import retrieve_top_agents
from agent_engine.json_utils import robust_parse, validate_task_list
from agent_engine.tracing import trace_span, SpanKind
from agent_engine.llm_client import get_llm_client
from agent_engine.llm_engine import get_tools_definition
from agent_engine.business.business_layer import get_business_layer

@trace_span("generate_plan", kind=SpanKind.PLANNER, capture_input=True)
def generate_plan(user_goal: str, recent_history: list = None, parsed_memories: list = None) -> list:
    """
    🧠 究极大脑 (Planner) 模块
    核心升级：启用 Ollama JSON mode + 自动修复引擎 + Schema 校验，确保结构化输出质量。
    """
    tools = get_tools_definition()
    tool_descriptions = "\n".join([f"- **{t['function']['name']}**: {t['function']['description']}" for t in tools])

    # ==========================================
    # 🌟 业务资产层注入（确定性定位，100% 正确）
    # ==========================================
    try:
        business_layer = get_business_layer()
        business_registry_prompt = business_layer.get_registry_prompt()
    except Exception:
        business_registry_prompt = "（业务资产注册表暂不可用）"

    # ==========================================
    # 🌟 提取上下文与长期记忆
    # ==========================================

    history_text = "无近期对话。"
    if recent_history:
        history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in recent_history[-5:]]) 

    memory_text = "无长期记忆。"
    if parsed_memories:
        memory_text = "\n".join([f"- {m['text']}" for m in parsed_memories])

    # ==========================================
    # 🌟 核心魔法：RAG 智能体检索注入
    # ==========================================
    active_roster = retrieve_top_agents(user_goal, top_k=3)
    roster_prompt = "\n".join([f"- `{role_id}`: {info['desc']}" for role_id, info in active_roster.items()])

    # ==========================================
    # 🌟 System Prompt
    # ==========================================
    system_prompt = f"""你是一个顶级的 AI 项目经理兼安全风控官（Planner）。
你的职责是将用户的宏大目标拆解为子任务队列，并对每一个任务进行极其严厉的安全风险评估！

【🧠 用户的长期记忆 (Mem0)】
{memory_text}

【💬 近期的对话上下文】
{history_text}

【🛠️ 可用的工具库】
{tool_descriptions}

【🏢 已登记的业务资产（直接使用 sheet_id 精确定位，绝不用名称搜索）】
{business_registry_prompt}

【⚙️ 专家路由规则（严格按职责分配，禁止跨领域指派）】
- `researcher`：仅限"联网搜索、查找外部资料"类的任务。绝不可分派文件操作！
- `coder`：负责"本地工作区文件读写/列表/删除、执行代码、发送邮件"等落地执行操作。绝不可操作 Google Drive 云端数据！
- `googledrive`：负责**所有** Google Drive 相关操作，包括但不限于：查找云端文件、读取 Google Sheets 表格内容、向表格写入数据、上传文件到云端、删除云端文件等。
- 不匹配以上时填 "general"。

【⚠️ 关键路由准则（违反将导致任务失败）】
- 只要涉及 Google Drive / Google Sheets / 云端表格，agent_role 必须是 "googledrive"。
- 只要涉及本地文件 / 本地代码执行，agent_role 必须是 "coder"。
- googledrive 可以**直接读取**云端表格数据（使用 manage_sheet_rows 工具），无需先下载到本地。
- 绝不允许将 Google Drive 数据的读取/写入任务指派给 coder！

【🚫 绝对禁止的任务拆分模式（Planner 必须遵守）】
- ❌ 禁止：把"查看云端文件 X 的数据"拆成"任务1:查找X → 任务2:读取X"。这是典型错误！googledrive agent 会在单个任务内自动先查找再读取，用 ReAct 循环完成完整链条。
- ❌ 禁止：把"列出所有文件 → 读取某个文件"拆成两个任务。如果用户的意图是最终要读取数据，只创建一个 googledrive 任务。
- ✅ 正确：任何"查询/查看/读取 Google Drive 数据"都是一个单独的 googledrive 任务，不要拆！
- ✅ 正确：只有真正独立的操作（如"同时读取奖金表和写入邀约表"）才需要多个任务。

【🛡️ 风险定级规则】
- "low" (低危)：只读操作、列出文件
- "medium" (中危)：新增文件、轻量级写入
- "high" (高危)：覆盖/修改已有文件、删除数据、发送邮件、批量写入

【⚠️ 核心铁律：绝不擅自加戏】
如果用户的目标仅仅是"查询信息"或"问一个问题"，任务链在"搜集并总结"后就立刻结束！

【📝 JSON 输出格式（严格遵守，每字段必填）】
{{
    "tasks": [
        {{
            "task_id": 1,
            "action": "搜集数据",
            "agent_role": "researcher",
            "depends_on": [],
            "instruction": "具体执行指令",
            "risk_level": "low",
            "risk_details": "一句话说明风险",
            "expected_output": "期望产出"
        }}
    ]
}}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"拆解以下目标，返回 JSON：\n{user_goal}"}
    ]

    client, model_name = get_llm_client()

    print("🧠 大脑 (Planner) 正在结合记忆、上下文并使用 RAG 检索拆解任务...")

    # ==========================================
    # 🌟 带多层容错的请求循环
    # ==========================================
    max_retries = 3
    for attempt in range(max_retries):
        try:
            kwargs = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.05,
                "response_format": {"type": "json_object"},  # OpenAI 标准 JSON mode
            }
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
            content = content.strip()

            # ── 防线 1：智能提取 + 自动修复 ──
            task_list = robust_parse(content, expect_array=False)

            if task_list is None:
                raise ValueError("所有解析策略均失败")

            # JSON mode 下模型输出的是 {"tasks": [...]} 包裹结构
            if isinstance(task_list, dict):
                if "tasks" in task_list:
                    task_list = task_list["tasks"]
                elif len(task_list) > 0:
                    # 可能是单个任务对象（有时候模型偷懒）
                    task_list = [task_list]

            # ── 防线 2：Schema 校验与规范化 ──
            validated = validate_task_list(task_list)

            if not validated:
                raise ValueError("Schema 校验后无有效任务")

            print(f"✅ Planner 成功生成 {len(validated)} 个任务")
            return validated

        except Exception as e:
            error_type = type(e).__name__
            print(f"⚠️ [第{attempt+1}次] 结构化解析失败 ({error_type}): {e}")
            if attempt == max_retries - 1:
                print("🚨 Planner 连续多次无法输出合法 JSON，规划失败。")
                return []

            # 带错重试：把错误信息喂给模型
            error_feedback = (
                f"🚨 第{attempt+1}次输出被系统拒绝。错误: `{e}`。"
                f"请确保输出严格合法的 JSON 对象，包含 'tasks' 数组，"
                f"每个 task 必须含 task_id/action/agent_role/depends_on/instruction/risk_level/risk_details/expected_output。"
            )
            messages.append({"role": "assistant", "content": content[:2000]})
            messages.append({"role": "user", "content": error_feedback})
            continue

    return []