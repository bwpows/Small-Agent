# agents/researcher.py
from agents.base_agent import BaseAgent

class ResearcherAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            agent_name="Researcher",
            role_prompt="""你是一名顶尖的情报分析师与数据挖掘专家。
你的唯一职责是在互联网上搜索最新资讯、查阅资料，并为后续任务提供精准、脱水的情报总结。
绝对不要尝试修改系统文件或执行危险操作。""",
            # 🚨 物理隔离：在这里填入你真实存在的搜索类工具名称
            allowed_tool_names=["search_web"]
        )