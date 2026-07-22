# agents/coder.py
from agent_engine.agents.base_agent import BaseAgent

class CoderAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            agent_name="Coder",
            role_prompt="""你是一名资深的自动化工程师与数据处理专家。
你的职责是接收情报，并严格按照要求执行【本地工作区】的操作（如读写文件、执行代码、发送邮件等）。
重要：如果前置任务提供了 Google Drive 的数据结果，你可以加工这些数据，但你绝不可自行调用 Google Drive 工具去查找或修改云端文件。""",
            # 🛡️ 物理隔离：Coder 只能操作本地文件，绝不可越权访问云端
            allowed_tool_names=["manage_local_file", "send_notification_email"] 
        )