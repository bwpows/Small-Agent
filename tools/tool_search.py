"""
联网搜索工具
---------------
接入 core/sandbox.py 的 NetworkGuard，提供搜索结果域名过滤。
"""

from ddgs import DDGS
from core.sandbox import get_network_guard


def search_web(query: str, time_range: str = "anytime") -> str:
    """
    带时间过滤和域名安全守卫的高级搜索。
    """
    try:
        time_map = {
            "past_day": "d",
            "past_week": "w",
            "past_month": "m",
            "past_year": "y",
            "anytime": None
        }
        ddg_time = time_map.get(time_range)

        guard = get_network_guard()
        results = []

        with DDGS() as ddgs:
            for r in ddgs.text(query, timelimit=ddg_time, max_results=5):
                # 域名安全检查：过滤掉黑名单/非白名单域名的结果
                href = r.get("href", "")
                if href and not guard.check_url(href):
                    continue
                results.append(
                    f"【标题】: {r['title']}\n【摘要】: {r['body']}\n【链接】: {href}"
                )

        if not results:
            return "🔍 搜索完毕，未找到相关结果。请尝试更换关键词或放宽时间限制。"

        return "\n\n".join(results)
    except Exception as e:
        return f"❌ 搜索接口调用失败: {str(e)}"

# ======= 动态路由注册声明 =======
REGISTER_NAME = "search_web"

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "高级联网搜索引擎。用于获取外部知识、实时新闻、天气或任何你不知道的信息。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string", 
                    "description": "搜索引擎的精准关键词。不要包含多余的自然语言。"
                },
                "time_range": {
                    "type": "string",
                    "enum": ["past_day", "past_week", "past_month", "past_year", "anytime"],
                    "description": "时间筛选条件。如果用户询问【今天、最新】选 past_day；【本周】选 past_week；【最近】选 past_month；如果是历史知识或无时间要求选 anytime。"
                }
            },
            "required": ["query", "time_range"]
        }
    }
}