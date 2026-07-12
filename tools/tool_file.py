import os

# ✅ 获取当前项目根目录的绝对路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ✅ 将沙箱锁定在根目录下的 agent_workspace
WORKSPACE_DIR = os.path.join(PROJECT_ROOT, "agent_workspace")

def manage_local_file(action, file_path, content=""):
    """
    将内容安全地读取或保存到本地工作区（带防路径穿越安全机制）
    """
    try:
        # 如果沙箱目录不存在，先创建它
        if not os.path.exists(WORKSPACE_DIR):
            os.makedirs(WORKSPACE_DIR)
            
        # 核心安全机制：剥离路径符号，防止路径穿越攻击（如 ../../app.py）
        safe_filename = os.path.basename(file_path)
        safe_file_path = os.path.join(WORKSPACE_DIR, safe_filename)
        
        if action == "write":
            # 写入文件
            with open(safe_file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"✅ 文件已成功生成: {safe_file_path}"
            
        elif action == "read":
            # 读取文件
            if not os.path.exists(safe_file_path):
                return f"❌ 文件不存在: {safe_file_path}"
            with open(safe_file_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            return "❌ 未知操作，仅支持 read 或 write。"
            
    except Exception as e:
        return f"❌ 文件保存/读取失败: {e}"
    
# ======= 动态路由注册声明 =======

REGISTER_NAME = "manage_local_file"  # 👈 现在这里和上面的 def 名字一模一样了！

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "manage_local_file",
        "description": "本地文件操作助手。用于安全地读取、写入本地工作区（沙箱）上的文件内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["read", "write"], "description": "操作类型：读取或写入"},
                "file_path": {"type": "string", "description": "文件的名称（系统会自动隔离到沙箱中）"},
                "content": {"type": "string", "description": "写入文件时的内容，读取时可留空"}
            },
            "required": ["action", "file_path"]
        }
    }
}