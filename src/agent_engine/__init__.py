"""
agent_engine — 大模型/智能体引擎

此包是独立的"大脑"层，管理 LLM 客户端、工具注册、Agent 执行循环、Tracing。
它的公共 API 可供 app_server（或未来任何外部服务）调用。

核心入口:
    from agent_engine import run
    result = run(user_input, recent_history, parsed_memories, web_info)
"""
import os

# ── 仓库根目录（用于定位 data/ 等运行时资源） ──
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 稳定公共 API：对 app_server 暴露的唯一入口 ──
from agent_engine.llm_engine import generate_answer, generate_answer_stream
from agent_engine.llm_engine import get_tools_definition, get_tools_as_mcp, execute_tool

__all__ = [
    "PROJECT_ROOT",
    "generate_answer",
    "generate_answer_stream",
    "get_tools_definition",
    "get_tools_as_mcp",
    "execute_tool",
]
