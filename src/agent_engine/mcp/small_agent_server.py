# Small-Agent MCP Server — 将现有工具以 MCP 协议对外暴露
#
# 前提：安装 MCP Python SDK
#   pip install mcp
#
# 用法：
#   1. 直接运行（stdio 模式，供 Claude Desktop 等客户端调用）：
#      python -m agent_engine.mcp.small_agent_server
#
#   2. Claude Desktop 配置示例（claude_desktop_config.json）：
#      {
#        "mcpServers": {
#          "small-agent": {
#            "command": "python",
#            "args": ["-m", "agent_engine.mcp.small_agent_server"],
#            "cwd": "/path/to/Small-Agent"
#          }
#        }
#      }
#
# 核心亮点：
#   - 工具逻辑零重复：直接复用 tools/ 下的现有函数
#   - 业务层同样可暴露：BusinessLayer 的 resolve/read/append 等也可作为 MCP Tool
#   - 格式双兼容：同时支持 OpenAI function-calling（内部）和 MCP（外部）

import json
import sys
import os


def build_mcp_tools_from_registry():
    """从项目工具注册表构建 MCP Tool 定义列表（无需引入 mcp SDK 即可预览）"""
    from agent_engine.llm_engine import get_tools_definition
    from agent_engine.mcp.tool_adapter import openai_to_mcp_list
    return openai_to_mcp_list(get_tools_definition())


def build_mcp_tools_with_business_layer():
    """构建包含业务层能力的 MCP Tool 列表"""
    from agent_engine.llm_engine import get_tools_definition
    from agent_engine.mcp.tool_adapter import openai_to_mcp_list

    tools = openai_to_mcp_list(get_tools_definition())

    # 追加业务层专用工具
    business_tools = [
        {
            "name": "business_resolve",
            "description": "精确解析业务别名 → Google Drive 文件 ID。输入业务名（如'奖金表'），返回 file_id，保证 100% 定位准确。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "biz_name": {"type": "string", "description": "业务别名，如 '奖金表'、'邀约表'"}
                },
                "required": ["biz_name"]
            }
        },
        {
            "name": "business_list",
            "description": "列出所有已登记的业务资产（表格清单）。",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "business_sync_drive",
            "description": "从 Google Drive 自动同步表格清单到业务资产注册表。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "最多同步数量，默认 50"}
                },
                "required": []
            }
        },
    ]
    tools.extend(business_tools)
    return tools


def execute_mcp_tool(name: str, args: dict) -> str:
    """
    MCP 工具执行入口 —— 路由到项目现有工具或业务层。
    """
    # ── 业务层工具 ──
    if name == "business_resolve":
        from agent_engine.business.business_layer import get_business_layer, BusinessNotFoundError
        bl = get_business_layer()
        try:
            asset = bl.resolve(args["biz_name"])
            return json.dumps({
                "alias": asset.alias,
                "type": asset.type,
                "drive_file_id": asset.drive_file_id,
                "columns": asset.columns,
                "description": asset.description,
            }, ensure_ascii=False)
        except BusinessNotFoundError as e:
            return f"❌ {e}"

    elif name == "business_list":
        from agent_engine.business.business_layer import get_business_layer
        bl = get_business_layer()
        names = bl.list_business_names()
        return f"已登记业务: {', '.join(names)}" if names else "暂无已登记业务。"

    elif name == "business_sync_drive":
        from agent_engine.business.business_layer import get_business_layer
        bl = get_business_layer()
        limit = args.get("limit", 50)
        new_assets = bl.sync_from_drive(limit)
        if new_assets:
            return f"✅ 从 Drive 同步了 {len(new_assets)} 个新业务: {', '.join(a.alias for a in new_assets)}"
        return "✅ 同步完成，未发现新业务。"

    # ── 通用工具（代理到现有 tool 引擎） ──
    from agent_engine.llm_engine import execute_tool
    return execute_tool(name, args)


# ==========================================
# MCP Server 入口（需安装 mcp SDK：pip install mcp）
# ==========================================

try:
    from mcp.server import Server
    import mcp.types as types
    HAS_MCP_SDK = True
except ImportError:
    HAS_MCP_SDK = False


def create_mcp_server():
    """创建 MCP Server 实例 — 复用项目现有工具逻辑"""
    if not HAS_MCP_SDK:
        raise ImportError(
            "需要安装 MCP SDK: pip install mcp\n"
            "当前仅为预览模式，可用 python -m mcp_servers.tool_adapter 导出工具清单。"
        )

    app = Server("small-agent-tools")

    @app.list_tools()
    async def list_tools():
        """MCP 标准: 返回可用工具清单"""
        mcp_tools = build_mcp_tools_with_business_layer()
        return [types.Tool(**t) for t in mcp_tools]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict):
        """MCP 标准: 执行工具调用"""
        result = execute_mcp_tool(name, arguments)
        return [types.TextContent(type="text", text=str(result))]

    return app


def run_stdio():
    """以 stdio 模式启动 MCP Server（供 Claude Desktop 等客户端连接）"""
    if not HAS_MCP_SDK:
        print("❌ 未安装 MCP SDK。请先执行: pip install mcp", file=sys.stderr)
        print("💡 可先导出工具清单预览: python -m mcp_servers.tool_adapter", file=sys.stderr)
        sys.exit(1)

    import asyncio
    from mcp.server.stdio import stdio_server

    app = create_mcp_server()

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(main())


def run_sse(host: str = "0.0.0.0", port: int = 8000):
    """以 SSE (HTTP) 模式启动 MCP Server（供浏览器/远程客户端连接）"""
    if not HAS_MCP_SDK:
        print("❌ 未安装 MCP SDK。请先执行: pip install mcp", file=sys.stderr)
        sys.exit(1)

    import asyncio
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    import uvicorn

    app = create_mcp_server()
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await app.run(
                streams[0], streams[1], app.create_initialization_options()
            )

    async def handle_messages(request):
        await sse.handle_post_message(
            request.scope, request.receive, request._send
        )

    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages/", endpoint=handle_messages, methods=["POST"]),
        ]
    )

    print(f"🚀 Small-Agent MCP Server 启动 (SSE 模式): http://{host}:{port}/sse")
    uvicorn.run(starlette_app, host=host, port=port)


# ── 命令行入口 ──
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Small-Agent MCP Server")
    parser.add_argument("--mode", choices=["stdio", "sse", "preview"], default="preview",
                        help="运行模式: stdio (Claude Desktop), sse (HTTP), preview (仅打印工具清单)")
    parser.add_argument("--host", default="0.0.0.0", help="SSE 模式监听地址")
    parser.add_argument("--port", type=int, default=8000, help="SSE 模式监听端口")
    args = parser.parse_args()

    if args.mode == "preview":
        tools = build_mcp_tools_with_business_layer()
        manifest = {"tools": tools}
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        print(f"\n✅ 共 {len(tools)} 个工具（含 {len(tools) - len([t for t in tools if not t['name'].startswith('business_')])} 个业务层工具）")
        print("💡 安装 MCP SDK 后可通过 --mode stdio 或 --mode sse 启动完整服务: pip install mcp")
    elif args.mode == "stdio":
        run_stdio()
    elif args.mode == "sse":
        run_sse(host=args.host, port=args.port)
