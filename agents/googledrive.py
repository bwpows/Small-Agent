# agents/googledrive.py
from agents.base_agent import BaseAgent

class GoogleDriveAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            agent_name="GoogleDrive",
            role_prompt="""你是一名专业的 Google Drive 管理专家。
你的唯一职责是管理和操作用户在 Google Drive 上的文件和数据。""",
        )
