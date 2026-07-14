# agents/coder.py
from agents.base_agent import BaseAgent

class CoderAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            agent_name="Coder",
            role_prompt="""你是一名资深的自动化工程师与数据处理专家。
你的职责是接收情报，并严格按照要求执行本地操作（如读写文件、更新 Google Drive 网盘表格等）。
请保持极客精神，用最少的废话完成操作。""",
            # 🚨 物理隔离：只给它赋予本地操作和写入的工具权限
            allowed_tool_names=["manage_sheet_rows", "file_manager", "email_sender"] 
        )