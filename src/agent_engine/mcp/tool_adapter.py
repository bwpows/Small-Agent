# mcp_servers/tool_adapter.py
# OpenAI function-calling 格式 ↔ MCP Tool 格式 双向适配器
# 无需改动任何原有 tool 代码，纯粹是格式转换层

import json
from typing import Dict, List, Any


def openai_to_mcp_tool(openai_tool: dict) -> dict:
    """
    将单个 OpenAI function-calling 工具定义转为 MCP Tool 格式。

    OpenAI 格式:
      {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}

    MCP 格式:
      {"name": "...", "description": "...", "inputSchema": {...}}
    """
    func = openai_tool.get("function", openai_tool)
    return {
        "name": func["name"],
        "description": func.get("description", ""),
        "inputSchema": func.get("parameters", {"type": "object", "properties": {}}),
    }


def openai_to_mcp_list(openai_tools: List[dict]) -> List[dict]:
    """批量转换 OpenAI 工具定义 → MCP 格式"""
    return [openai_to_mcp_tool(t) for t in openai_tools]


def mcp_to_openai_tool(mcp_tool: dict) -> dict:
    """
    将 MCP Tool 格式转回 OpenAI function-calling 格式。
    反向兼容：如果已有 MCP 工具定义，也能在 Small-Agent 内使用。
    """
    return {
        "type": "function",
        "function": {
            "name": mcp_tool["name"],
            "description": mcp_tool.get("description", ""),
            "parameters": mcp_tool.get("inputSchema", {"type": "object", "properties": {}}),
        }
    }


def export_mcp_manifest(output_path: str = None) -> str:
    """
    导出 MCP 工具清单 JSON 文件。
    可被 Claude Desktop / Cursor 等 MCP 客户端直接读取。

    :param output_path: 输出文件路径（可选，默认打印到 stdout）
    :return: JSON 字符串
    """
    from agent_engine.llm_engine import get_tools_definition
    openai_tools = get_tools_definition()
    mcp_tools = openai_to_mcp_list(openai_tools)
    manifest = {"tools": mcp_tools}

    json_str = json.dumps(manifest, ensure_ascii=False, indent=2)

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(json_str)
        print(f"✅ MCP 工具清单已导出到: {output_path}")

    return json_str


# ── 便捷命令行导出 ──
if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    manifest = export_mcp_manifest(path)
    if not path:
        print(manifest)
