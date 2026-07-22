"""
本地文件安全操作工具
------------------------
通过 core/sandbox.py 的 FileOperationGuard 提供：
  - 路径穿越防护（强制锁定在 data/workspace/ 内）
  - 文件扩展名白名单
  - 文件大小上限检查
  - 操作审计日志
  - 文件列表 / 删除
"""

import os
from agent_engine.sandbox import get_file_guard


def manage_local_file(action: str, file_path: str = "", content: str = "") -> str:
    """
    将内容安全地读取、列出或保存到本地工作区沙箱。
    """
    try:
        guard = get_file_guard()

        if action == "write":
            return guard.safe_write(file_path, content)
        elif action == "read":
            return guard.safe_read(file_path)
        elif action == "list":
            return _list_files()
        elif action == "delete":
            safe_path = guard.resolve_safe_path(file_path)
            if not os.path.exists(safe_path):
                return f"❌ 文件不存在: {safe_path}"
            os.remove(safe_path)
            guard.audit.record("file_delete", {"path": safe_path})
            return f"✅ 文件已删除: {safe_path}"
        else:
            return "❌ 未知操作，仅支持 read / write / list / delete。"

    except PermissionError as e:
        return f"❌ 沙箱拒绝操作 (安全策略): {e}"
    except ValueError as e:
        return f"❌ 参数校验失败: {e}"
    except Exception as e:
        return f"❌ 文件操作失败: {e}"


def _list_files() -> str:
    """列出沙箱工作区内的所有文件"""
    guard = get_file_guard()
    try:
        items = sorted(os.listdir(guard.workspace_dir))
        # 过滤掉隐藏文件/目录（如 .sandbox_audit）
        visible = [f for f in items if not f.startswith(".")]
        if not visible:
            return "📂 工作区当前为空，没有任何文件。"
        lines = [f"📂 工作区共有 {len(visible)} 个文件/目录：", ""]
        for f in visible:
            full_path = os.path.join(guard.workspace_dir, f)
            if os.path.isdir(full_path):
                lines.append(f"  📁 {f}/")
            else:
                size = os.path.getsize(full_path)
                lines.append(f"  📄 {f}  ({_format_size(size)})")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 列出文件失败: {e}"


def _format_size(size_bytes: int) -> str:
    """人类可读的文件大小"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} B"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
    
# ======= 动态路由注册声明 =======

REGISTER_NAME = "manage_local_file"  # 👈 现在这里和上面的 def 名字一模一样了！

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "manage_local_file",
        "description": (
            "本地文件操作助手。在沙箱工作区内安全地读取、写入、列出或删除文件。"
            "支持 .txt/.md/.csv/.json/.html/.py/.log 等常见格式。"
            "list 操作无需 file_path 参数，将列出所有工作区文件。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "list", "delete"],
                    "description": "操作类型：read=读取, write=写入, list=列出所有文件, delete=删除"
                },
                "file_path": {
                    "type": "string",
                    "description": "文件名（自动隔离到沙箱目录）。list 操作可忽略此参数。"
                },
                "content": {
                    "type": "string",
                    "description": "写入时的文件内容，其他操作可留空"
                }
            },
            "required": ["action"]
        }
    }
}