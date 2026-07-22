# tool_terminal.py
"""
Python 代码沙箱执行工具
------------------------
现在接入 core/sandbox.py 的分层沙箱引擎，提供：
  - 资源硬限制 (CPU/内存/文件大小/子进程数)
  - 模块白名单/黑名单 (strict 级别阻断 os/subprocess 等)
  - 临时目录隔离 (用完即焚)
  - 审计日志

可通过环境变量 SANDBOX_LEVEL 控制级别: strict | moderate | relaxed (默认 moderate)
"""

from agent_engine.sandbox import get_executor, get_sandbox_level


def execute_python_code(code: str, timeout: int = 10) -> str:
    """
    在多层沙箱中安全执行 Python 代码，并捕获标准输出。

    :param code: 要执行的 Python 代码字符串
    :param timeout: 保留参数以兼容旧接口 (实际超时由 SandboxConfig 控制)
    """
    try:
        executor = get_executor()
        return executor.run(code)
    except Exception as e:
        import traceback
        return (
            f"❌ 沙箱底层异常:\n"
            f"```\n{traceback.format_exc()}\n```\n"
            f"当前沙箱级别: `{get_sandbox_level()}` | "
            f"可通过环境变量 `SANDBOX_LEVEL` 调整为 strict/moderate/relaxed。"
        )
    

# ======= 动态路由注册声明 =======

REGISTER_NAME = "execute_python_code"  # 👈 确保这里和你的真实函数名一致！

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "execute_python_code",
        "description": (
            "沙箱化的 Python 代码执行环境。"
            "当遇到复杂的数学计算、数据分析或需要写代码验证的问题时使用。"
            "注意：沙箱会限制危险操作（如文件系统访问、网络请求、系统命令），"
            "请使用纯计算/数据处理代码。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "要执行的安全 Python 代码。禁止使用 os/subprocess/socket 等系统模块。"
                }
            },
            "required": ["code"]
        }
    }
}