from ddgs import DDGS

def search_web(query, time_range="anytime"):
    """
    带时间过滤的高级搜索实现
    """
    try:
        # 将大模型传来的时间区间，映射为搜索引擎的底层参数
        time_map = {
            "past_day": "d",
            "past_week": "w",
            "past_month": "m",
            "past_year": "y",
            "anytime": None
        }
        ddg_time = time_map.get(time_range)
        
        results = []
        with DDGS() as ddgs:
            # 调用搜索引擎，传入时间限制，取前 3 条最相关的结果
            for r in ddgs.text(query, timelimit=ddg_time, max_results=3):
                results.append(f"【标题】: {r['title']}\n【摘要】: {r['body']}\n【链接】: {r['href']}")
                
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