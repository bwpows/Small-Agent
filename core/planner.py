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
    # 🌟 极限施压的 System Prompt
    # ==========================================
    system_prompt = f"""你是一个顶级的 AI 项目经理（Planner）。
你的唯一职责是将用户的宏大目标，拆解为符合逻辑、有先后顺序的子任务队列。
你**不需要也不允许**亲自去调用工具执行，你只需要做好规划。

【🧠 用户的长期记忆 (Mem0)】
{memory_text}

【💬 近期的对话上下文】
{history_text}

【🛠️ 当前小脑 (Worker) 拥有的工具库】
{tool_descriptions}
- 注意：如果没有合适的工具，请规划为依赖 LLM 自身知识生成的文本任务。

【⚙️ 核心输出铁律 (最高优先级)】
1. 必须是纯净 JSON：你必须且只能输出一个合法的 JSON 数组！绝对不允许输出任何问候语、分析过程！
2. 引入 DAG 依赖机制：如果当前任务必须等待前面的任务完成（例如需要引用前置任务搜集的数据），必须在 `depends_on` 数组中标明前置任务的 `task_id`。如果没有依赖，填空数组 `[]`。

【📝 输出格式模板】
[
    {{
        "task_id": 1,
        "action": "搜集情报",
        "depends_on": [], 
        "instruction": "使用 search_web 工具，搜索今天关于 Apple 的最新新闻。",
        "expected_output": "一段包含核心新闻事件的文本摘要。"
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