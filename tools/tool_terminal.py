# tool_terminal.py
import subprocess
import tempfile
import os
import sys

def execute_python_code(code_string, timeout=10):
    """
    在隔离的临时文件中安全执行 Python 代码，并捕获标准输出
    """
    try:
        # 1. 动态创建一个临时 Python 文件 (用完即焚)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as temp_file:
            # 自动注入 utf-8 声明，防止 Windows/Mac 编码报错
            temp_file.write("# -*- coding: utf-8 -*-\n" + code_string)
            temp_file_path = temp_file.name

        # 2. 启动子进程执行代码，设定严格的超时时间，防止死循环
        result = subprocess.run(
            [sys.executable, temp_file_path],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        output = result.stdout.strip()
        error = result.stderr.strip()
        
        # 3. 清理现场
        os.remove(temp_file_path)

        if result.returncode == 0:
            return f"✅ 代码执行成功:\n{output if output else '[无终端输出，请确保代码使用了 print()]'}"
        else:
            return f"❌ 代码执行报错:\n{error}"
            
    except subprocess.TimeoutExpired:
        os.remove(temp_file_path)
        return "❌ 强制熔断：代码执行超过 10 秒，已自动终止（可能存在死循环或无响应请求）。"
    except Exception as e:
        return f"❌ 终端系统底层错误: {e}"
    

# ======= 动态路由注册声明 =======

REGISTER_NAME = "execute_python_code"  # 👈 确保这里和你的真实函数名一致！

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "execute_python_code",
        "description": "Python代码执行环境。当遇到复杂的数学计算、数据分析或需要写代码验证的问题时，通过此工具运行Python代码并获取结果。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "要执行的合法Python代码字符串"}
            },
            "required": ["code"]
        }
    }
}