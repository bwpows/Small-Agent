"""
联网搜索工具
---------------
接入 core/sandbox.py 的 NetworkGuard，提供搜索结果域名过滤。
"""

from ddgs import DDGS
from agent_engine.sandbox import get_network_guard


def search_web(query: str, time_range: str = "anytime", region: str = "wt-wt") -> str:
    """
    带时间过滤、区域偏好和域名安全守卫的高级搜索。
    region 为可选的搜索区域偏好（如 "zh-cn" 偏中文、"wt-wt" 全球无偏好）。
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
            for r in ddgs.text(query, region=region, timelimit=ddg_time, max_results=5):
                # 域名安全检查：过滤掉黑名单/非白名单域名的结果
                href = r.get("href", "")
                if href and not guard.check_url(href):
                    continue
                results.append(
                    f"【标题】: {r['title']}\n【摘要】: {r['body']}\n【链接】: {href}"
                )

        if not results:
            return ("🔍 搜索完毕，未找到相关结果。\n"
                    "建议：请用更简短的关键词重试（不要输入完整句子或 URL），"
                    "或告知用户当前搜索引擎无法获取该信息，建议用户直接访问相关官方网站。")

        return "\n\n".join(results)
    except Exception as e:
        return f"❌ 搜索接口调用失败: {str(e)}"

# ======= 动态路由注册声明 =======
REGISTER_NAME = "search_web"

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "联网搜索引擎，用于获取外部知识、实时新闻、天气等信息。"
            "每个关键词最多搜索 2 次；若仍未获得所需的精确数据，请基于已有搜索结果如实总结，"
            "告知用户当前能获取的信息范围，不要反复更换关键词继续搜索。"
        ),
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
                },
                "region": {
                    "type": "string",
                    "enum": ["wt-wt", "zh-cn", "us-en", "jp-jp", "kr-kr"],
                    "description": "搜索区域偏好。中文问题选 zh-cn，英文/代码/技术问题选 wt-wt 或 us-en，日文问题选 jp-jp，韩文问题选 kr-kr。默认 wt-wt。"
                }
            },
            "required": ["query", "time_range"]
        }
    }
}