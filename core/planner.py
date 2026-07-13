import json
import requests
import re

# 兼容不同的配置导入路径
try:
    from config.env_config import OLLAMA_BASE_URL, LLM_MODEL
except ImportError:
    from config.config import OLLAMA_BASE_URL, LLM_MODEL
    
from core.llm_engine import get_tools_definition

def generate_plan(user_goal: str, recent_history: list = None, parsed_memories: list = None) -> list:
    """
    🧠 究极大脑 (Planner) 模块：支持 DAG拓扑、Mem0记忆注入、格式自愈
    """
    tools = get_tools_definition()
    tool_descriptions = "\n".join([f"- **{t['function']['name']}**: {t['function']['description']}" for t in tools])

    # ==========================================
    # 🌟 提取上下文与长期记忆
    # ==========================================
    history_text = "无近期对话。"
    if recent_history:
        # 只取最近 5 条防止上下文过载
        history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in recent_history[-5:]]) 

    memory_text = "无长期记忆。"
    if parsed_memories:
        memory_text = "\n".join([f"- {m['text']}" for m in parsed_memories])

    # ==========================================
    # 🌟 带有风控审计的 System Prompt
    # ==========================================
    system_prompt = f"""你是一个顶级的 AI 项目经理兼安全风控官（Planner）。
你的职责是将用户的宏大目标拆解为子任务队列，并对每一个任务进行极其严厉的安全风险评估！
你不需要亲自执行，只需做好规划和审查。

【🧠 用户的长期记忆 (Mem0)】
{memory_text}

【💬 近期的对话上下文】
{history_text}

【🛠️ 小脑 (Worker) 拥有的工具库】
{tool_descriptions}

【🛡️ 风险定级规则 (极其重要)】
你必须为每个任务评定 `risk_level` 并说明 `risk_details`：
- "low" (低危)：只读操作（搜索网页、读取本地文件、计算分析）。
- "medium" (中危)：新增单个无关紧要的文件、轻量级调用。
- "high" (高危)：覆盖/修改已存在的文件、删除任何数据、发送外部邮件、批量创建大量文件。
`risk_details` 必须用一句话极其具体地说明要干什么。

【⚠️ 核心铁律：绝不擅自加戏】
如果用户的目标仅仅是“查询信息”或“问一个问题”，你的任务链应该在“搜集并总结”后就立刻结束！
绝对不允许擅自添加用户没有要求的操作（例如：未经允许去建表格、写文件、发邮件等）！

【⚙️ 输出格式要求】
必须输出纯净的 JSON 数组，严禁包含任何 Markdown 代码块包裹。

【📝 输出格式模板 (仅供结构参考，不要照搬动作！)】
[
    {{
        "task_id": 1,
        "action": "搜集数据",
        "depends_on": [], 
        "instruction": "使用合适的工具获取用户需要的信息。",
        "risk_level": "low",
        "risk_details": "仅调用工具获取信息，无本地数据修改。",
        "expected_output": "获取到的信息总结。"
    }}
]
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"请结合以上记忆与上下文，拆解以下目标：\n{user_goal}"}
    ]

    payload = {
        "model": LLM_MODEL,
        "stream": False,
        "options": {"temperature": 0.1} # 极致低温，杜绝幻觉
    }

    print("🧠 大脑 (Planner) 正在结合记忆与上下文拆解任务...")
    
    # ==========================================
    # 🌟 带格式自愈的请求循环
    # ==========================================
    max_retries = 3
    for attempt in range(max_retries):
        payload["messages"] = messages
        try:
            response = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=60)
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "").strip()
            
            # 暴力清洗 Markdown 护甲 (防止大模型手贱加上 ```json)
            content = re.sub(r"^```(?:json)?\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
            
            task_list = json.loads(content)
            return task_list
            
        except json.JSONDecodeError as e:
            print(f"⚠️ [第{attempt+1}次] 格式解析失败，系统触发自愈重试机制: {e}")
            # 抓到解析错误，直接把错误拍在大模型脸上让它自己改！
            error_feedback = f"🚨 格式严重错误：你的输出无法被系统解析为 JSON。Python 报错信息为 `{str(e)}`。请立刻检查逗号、括号和引号的匹配情况，并重新输出纯净的 JSON 数组！"
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": error_feedback})
            continue 
            
        except Exception as e:
            print(f"❌ Planner 运行遭遇网络或底层异常: {e}")
            return []

    print("🚨 Planner 连续多次输出非法格式，规划宣告失败。")
    return []