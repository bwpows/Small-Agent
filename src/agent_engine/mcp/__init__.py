# mcp_servers/__init__.py
# MCP Server 壳 — 渐进式 MCP 化
# 将现有 tool 逻辑用 MCP 协议重新暴露，不改动原有实现
# 用法（暂注释，待安装 mcp SDK 后启用）：
#   python -m mcp_servers.small_agent_server

from agent_engine.mcp.tool_adapter import (
    openai_to_mcp_tool,
    openai_to_mcp_list,
    export_mcp_manifest,
)

__all__ = [
    "openai_to_mcp_tool",
    "openai_to_mcp_list",
    "export_mcp_manifest",
]
