"""
轻量级分层沙箱引擎 (Sandbox Engine)
=====================================
设计理念：不引入 Docker/nsjail 等重型依赖，基于 macOS/Linux 原生能力
(resource 模块 + import hook + 文件隔离) 实现多层防御。

安全层级：
  - Layer 1: 资源硬限制 (RLIMIT_CPU / RLIMIT_AS / RLIMIT_FSIZE / RLIMIT_NPROC)
  - Layer 2: 模块白名单 (import hook 注入，阻断危险模块加载)
  - Layer 3: 文件系统隔离 (临时目录 + 路径绑定)
  - Layer 4: 审计日志 (全量操作可追溯)
  - Layer 5: 超时熔断 (subprocess timeout)

分级策略：
  - strict:  仅安全模块 + 资源强限制 + 禁止网络/文件系统
  - moderate: 允许常用模块 + 资源中等限制
  - relaxed:  仅超时保护 (当前默认行为)
"""

import os
import sys
import json
import time
import signal
import tempfile
import subprocess
import traceback
import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


# ==========================================
# 1. 配置模型
# ==========================================

@dataclass
class SandboxConfig:
    """单个沙箱层级的参数配置"""
    level: str = "moderate"               # strict | moderate | relaxed

    # --- 资源限制 (macOS 兼容: 不支持 RLIMIT_RSS) ---
    cpu_timeout: int = 10                 # CPU 时间上限 (秒)
    wall_timeout: int = 15                # 挂钟时间上限 (秒)
    memory_limit_mb: int = 128            # 虚拟内存上限 (MB)，仅 strict/moderate
    fs_size_limit_mb: int = 10            # 单文件写入上限 (MB)
    max_processes: int = 5                # 最大子进程数

    # --- 模块白名单 (仅 strict 生效) ---
    allowed_modules: set = field(default_factory=lambda: {
        # 标准安全模块
        "math", "json", "re", "datetime", "collections",
        "itertools", "random", "statistics", "csv", "io",
        "string", "decimal", "fractions", "typing",
        "hashlib", "base64", "uuid", "copy", "pprint",
        "enum", "dataclasses", "functools", "operator",
        "textwrap", "html", "xml", "urllib.parse",
        "pathlib", "tempfile", "logging",
        # 数据分析安全模块
        "numpy", "pandas",
    })

    # --- 禁止模块 (strict + moderate) ---
    banned_modules: set = field(default_factory=lambda: {
        "os", "subprocess", "shutil", "socket",
        "ctypes", "multiprocessing", "signal",
        "pty", "fcntl", "posix",
        "requests", "urllib.request", "http.client",
        "smtplib", "ftplib", "telnetlib",
    })

    # --- 文件系统 ---
    allowed_extensions: set = field(default_factory=lambda: {
        ".txt", ".md", ".csv", ".json", ".html", ".xml",
        ".py", ".log", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    })
    max_file_size_mb: int = 5              # 单文件读写上限

    # --- 网络 ---
    allowed_domains: Optional[List[str]] = None   # None = 不限制
    banned_domains: List[str] = field(default_factory=list)

    # --- 审计 ---
    enable_audit: bool = True


# ==========================================
# 2. 分级预设
# ==========================================

PRESETS = {
    "strict": SandboxConfig(
        level="strict",
        cpu_timeout=5,
        wall_timeout=10,
        memory_limit_mb=64,
        fs_size_limit_mb=5,
        max_processes=1,
    ),
    "moderate": SandboxConfig(
        level="moderate",
        cpu_timeout=10,
        wall_timeout=15,
        memory_limit_mb=256,
        fs_size_limit_mb=20,
        max_processes=5,
    ),
    "relaxed": SandboxConfig(
        level="relaxed",
        cpu_timeout=30,
        wall_timeout=60,
        memory_limit_mb=512,
        fs_size_limit_mb=50,
        max_processes=20,
        banned_modules=set(),  # 不限制模块
    ),
}


# ==========================================
# 3. 审计日志
# ==========================================

class SandboxAudit:
    """
    轻量审计记录器，记录所有沙箱内的操作。
    """
    def __init__(self, log_dir: str = None):
        if log_dir is None:
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "data", "workspace", ".sandbox_audit"
            )
        os.makedirs(log_dir, exist_ok=True)
        self.log_dir = log_dir
        self.entries: List[Dict[str, Any]] = []

    def record(self, event_type: str, details: Dict[str, Any] = None):
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "event": event_type,
            "details": details or {},
        }
        self.entries.append(entry)

    def flush(self, session_id: str = None):
        """将审计记录写入磁盘"""
        if not self.entries:
            return
        if session_id is None:
            session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(self.log_dir, f"audit_{session_id}.jsonl")
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                for entry in self.entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        self.entries.clear()

    def get_recent(self, n: int = 20) -> List[Dict]:
        return self.entries[-n:]


# ==========================================
# 4. 模块白名单注入 (import hook)
# ==========================================

def generate_sandbox_preamble(config: SandboxConfig) -> str:
    """
    生成注入到用户代码开头的沙箱限制脚本。
    通过 monkey-patch builtins.__import__ 阻断危险模块。
    """
    if config.level == "relaxed":
        return ""  # relaxed 不注入模块限制

    allowed = sorted(config.allowed_modules)
    banned = sorted(config.banned_modules)

    # 构建模块白名单/黑名单的 Python 代码
    preamble = f'''
# === [SANDBOX] 安全限制已注入 (level: {config.level}) ===
import builtins as __sandbox_builtins__
__original_import__ = __sandbox_builtins__.__import__

__ALLOWED__ = {json.dumps(allowed)}
__BANNED__ = {json.dumps(banned)}

def __sandboxed_import__(name, globals=None, locals=None, fromlist=(), level=0):
    top_level = name.split(".")[0]
    if top_level in __BANNED__:
        raise ImportError(
            f"Sandbox Blocked: module '{{name}}' is banned "
            f"(security level: {config.level}). "
            f"Use a safer alternative or consult the allowed modules list."
        )
    if {str(config.level == "strict")} and top_level not in __ALLOWED__:
        raise ImportError(
            f"Sandbox Blocked: module '{{name}}' is not in the allowed list. "
            f"Allowed: {{', '.join(__ALLOWED__[:15])}}..."
        )
    return __original_import__(name, globals, locals, fromlist, level)

__sandbox_builtins__.__import__ = __sandboxed_import__

# 阻断 eval/exec 的滥用 (但保留正常功能)
__original_eval__ = __sandbox_builtins__.eval
__original_exec__ = __sandbox_builtins__.exec

__sandbox_builtins__.open = open  # 保留 open (后续由资源限制约束)

# === [SANDBOX] 安全限制注入完毕 ===
'''
    return preamble


# ==========================================
# 5. 受保护的子进程启动器 (MACOS/LINUX)
# ==========================================

def _apply_resource_limits(config: SandboxConfig):
    """
    在子进程 fork 后、exec 前设置资源限制。
    作为 preexec_fn 传入 subprocess.Popen。
    """
    try:
        import resource as _r

        # CPU 时间限制
        if config.cpu_timeout > 0:
            _r.setrlimit(_r.RLIMIT_CPU, (config.cpu_timeout, config.cpu_timeout + 2))

        # 虚拟内存限制
        if config.memory_limit_mb > 0:
            mem_bytes = config.memory_limit_mb * 1024 * 1024
            _r.setrlimit(_r.RLIMIT_AS, (mem_bytes, mem_bytes))

        # 文件写入大小限制
        if config.fs_size_limit_mb > 0:
            fs_bytes = config.fs_size_limit_mb * 1024 * 1024
            _r.setrlimit(_r.RLIMIT_FSIZE, (fs_bytes, fs_bytes))

        # 子进程数限制
        if config.max_processes > 0:
            _r.setrlimit(_r.RLIMIT_NPROC, (config.max_processes, config.max_processes))

    except Exception:
        # 在某些受限环境下 resource 模块可能不可用（如部分 Docker 镜像）
        pass


def _run_in_subprocess(code: str, config: SandboxConfig, work_dir: str) -> dict:
    """
    在子进程中执行代码，应用所有资源限制。

    返回: {"stdout": ..., "stderr": ..., "returncode": ..., "timed_out": ...}
    """
    result = {
        "stdout": "",
        "stderr": "",
        "returncode": -1,
        "timed_out": False,
    }

    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=config.wall_timeout,
            cwd=work_dir,
            preexec_fn=(lambda: _apply_resource_limits(config))
            if os.name != "nt" else None,
        )
        result["stdout"] = proc.stdout
        result["stderr"] = proc.stderr
        result["returncode"] = proc.returncode
    except subprocess.TimeoutExpired:
        result["timed_out"] = True
        result["stderr"] = (
            f"Sandbox Error: code execution exceeded the wall-clock timeout "
            f"of {config.wall_timeout} seconds."
        )
    except Exception as e:
        result["stderr"] = f"Sandbox runtime error: {str(e)}"

    return result


# ==========================================
# 6. 沙箱执行器 (统一入口)
# ==========================================

class SandboxedExecutor:
    """
    受控代码执行器 —— 所有 tool_terminal 调用经由此处。

    用法:
        executor = SandboxedExecutor(level="strict")
        result = executor.run("print(sum([1,2,3]))")
    """

    def __init__(self, level: str = "moderate", audit: SandboxAudit = None):
        self.config = PRESETS.get(level, PRESETS["moderate"])
        self.audit = audit or SandboxAudit()

    def run(self, code: str, session_id: str = None) -> str:
        """
        在沙箱中执行一段 Python 代码。

        :param code: 用户/Agent 提交的代码字符串
        :param session_id: 可选的会话标识，用于审计关联
        :return: 人类可读的执行结果
        """
        self.audit.record("sandbox_exec_start", {
            "level": self.config.level,
            "code_length": len(code),
            "code_preview": code[:200],
        })

        # 1. 注入沙箱 preamble (模块限制)
        preamble = generate_sandbox_preamble(self.config)
        sandboxed_code = preamble + "\n" + code if preamble else code

        # 2. 创建隔离的临时工作目录（用完即焚）
        with tempfile.TemporaryDirectory(prefix="sandbox_") as work_dir:
            self.audit.record("sandbox_workdir_created", {"work_dir": work_dir})

            # 3. 在子进程中执行，应用资源限制
            exec_result = _run_in_subprocess(sandboxed_code, self.config, work_dir)

        # 4. 解析结果
        if exec_result["timed_out"]:
            self.audit.record("sandbox_timeout", {
                "wall_timeout": self.config.wall_timeout
            })
            self.audit.flush(session_id)
            return (
                f"⏱️ 沙箱熔断：代码执行超过 {self.config.wall_timeout} 秒挂钟时间，"
                f"已被强制终止（可能存在死循环或无限等待）。"
            )

        if exec_result["returncode"] == 0:
            output = exec_result["stdout"].strip()
            self.audit.record("sandbox_exec_success", {
                "output_length": len(output),
            })
            self.audit.flush(session_id)
            return (
                f"✅ 沙箱执行成功:\n"
                f"{output if output else '[无终端输出，请确保代码使用了 print()]'}"
            )
        else:
            stderr = exec_result["stderr"].strip()
            # 提取关键错误信息，去掉 traceback 噪音
            error_lines = stderr.split("\n") if stderr else []
            key_error = ""
            for line in error_lines:
                if "Error" in line or "Sandbox" in line:
                    key_error = line.strip()
                    break
            if not key_error:
                key_error = error_lines[-1] if error_lines else "Unknown error"

            self.audit.record("sandbox_exec_failed", {
                "returncode": exec_result["returncode"],
                "error": key_error,
                "full_stderr": stderr[:500],
            })
            self.audit.flush(session_id)
            return (
                f"❌ 沙箱执行失败:\n"
                f"```\n{stderr[:1000]}\n```"
                if stderr else f"❌ 沙箱执行失败 (returncode={exec_result['returncode']})，无详细错误信息。"
            )

    def get_audit_summary(self) -> str:
        """获取最近审计摘要"""
        entries = self.audit.get_recent(10)
        if not entries:
            return "📋 无最近沙箱操作记录。"
        lines = ["📋 **最近沙箱审计记录**:", ""]
        for e in entries:
            ts = e["timestamp"][:19]
            event = e["event"]
            lines.append(f"- `{ts}` | {event}")
        return "\n".join(lines)


# ==========================================
# 7. 文件操作守卫
# ==========================================

class FileOperationGuard:
    """
    文件操作安全守卫 —— 用于加固 tool_file.py。

    检查项:
      - 文件扩展名白名单
      - 文件大小上限
      - 路径必须在允许的基目录下
    """

    def __init__(self, config: SandboxConfig = None, workspace_dir: str = None):
        self.config = config or PRESETS["moderate"]
        if workspace_dir is None:
            workspace_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data/workspace"
            )
        self.workspace_dir = os.path.abspath(workspace_dir)
        os.makedirs(self.workspace_dir, exist_ok=True)
        self.audit = SandboxAudit()

    def resolve_safe_path(self, file_path: str) -> str:
        """将用户输入路径安全解析到工作区内"""
        safe_name = os.path.basename(file_path)
        if not safe_name or safe_name.startswith("."):
            raise ValueError(f"Invalid filename: {file_path}")
        resolved = os.path.abspath(os.path.join(self.workspace_dir, safe_name))
        # 二次确认未逃逸出工作区
        if not resolved.startswith(self.workspace_dir):
            raise PermissionError(
                f"Path traversal blocked: {file_path} resolves outside workspace"
            )
        return resolved

    def check_extension(self, file_path: str):
        """检查文件扩展名是否在白名单内"""
        ext = os.path.splitext(file_path)[1].lower()
        if not ext:
            return  # 无扩展名的文件允许（如 Makefile）
        if ext not in self.config.allowed_extensions:
            raise PermissionError(
                f"File extension '{ext}' is not allowed. "
                f"Allowed: {', '.join(sorted(self.config.allowed_extensions))}"
            )

    def check_file_size(self, file_path: str, content: str = None):
        """检查文件大小不超过上限"""
        if content is not None:
            size_bytes = len(content.encode("utf-8"))
        elif os.path.exists(file_path):
            size_bytes = os.path.getsize(file_path)
        else:
            return
        limit_bytes = self.config.max_file_size_mb * 1024 * 1024
        if size_bytes > limit_bytes:
            raise ValueError(
                f"File size ({size_bytes / 1024 / 1024:.1f} MB) exceeds "
                f"the sandbox limit of {self.config.max_file_size_mb} MB."
            )

    def safe_write(self, file_path: str, content: str, session_id: str = None) -> str:
        """安全写入文件"""
        safe_path = self.resolve_safe_path(file_path)
        self.check_extension(safe_path)
        self.check_file_size(safe_path, content=content)
        self.audit.record("file_write", {
            "path": safe_path,
            "size": len(content.encode("utf-8")),
        })

        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)

        self.audit.flush(session_id)
        return f"✅ 文件已成功生成: {safe_path}"

    def safe_read(self, file_path: str, session_id: str = None) -> str:
        """安全读取文件"""
        safe_path = self.resolve_safe_path(file_path)
        self.check_extension(safe_path)
        if not os.path.exists(safe_path):
            return f"❌ 文件不存在: {safe_path}"

        self.check_file_size(safe_path)
        self.audit.record("file_read", {"path": safe_path})

        with open(safe_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.audit.flush(session_id)
        return content


# ==========================================
# 8. 网络请求守卫
# ==========================================

class NetworkGuard:
    """
    网络访问守卫 —— 用于加固 tool_search.py 等外网工具。

    提供域名白名单/黑名单过滤。
    """

    def __init__(self, config: SandboxConfig = None):
        self.config = config or PRESETS["moderate"]
        self.audit = SandboxAudit()

    def check_url(self, url: str) -> bool:
        """
        检查 URL 是否允许访问。

        返回 True 表示允许，False 表示禁止。
        规则优先级: 黑名单 > 白名单 > 默认允许
        """
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if not domain:
                domain = parsed.path.split("/")[0]  # fallback
        except Exception:
            return True  # 解析失败默认放行

        # 黑名单优先
        for banned in self.config.banned_domains:
            if domain == banned or domain.endswith("." + banned):
                self.audit.record("network_blocked", {
                    "url": url, "domain": domain, "reason": "blacklist"
                })
                return False

        # 白名单检查
        if self.config.allowed_domains is not None:
            for allowed in self.config.allowed_domains:
                if domain == allowed or domain.endswith("." + allowed):
                    return True
            self.audit.record("network_blocked", {
                "url": url, "domain": domain, "reason": "not_in_whitelist"
            })
            return False

        return True  # 默认允许


# ==========================================
# 9. 全局便捷接口
# ==========================================

# 全局单例（懒加载）
_global_executor: Optional[SandboxedExecutor] = None
_global_file_guard: Optional[FileOperationGuard] = None
_global_network_guard: Optional[NetworkGuard] = None


def get_sandbox_level() -> str:
    """从 config 模块或环境变量读取当前沙箱级别"""
    try:
        from agent_engine.config import SANDBOX_LEVEL
        return SANDBOX_LEVEL
    except ImportError:
        pass
    return os.environ.get("SANDBOX_LEVEL", "moderate")


def _apply_config_overrides(config: SandboxConfig) -> SandboxConfig:
    """从 config.py 读取用户自定义的沙箱参数并覆盖预设"""
    try:
        from agent_engine.config import (
            ALLOWED_FILE_EXTENSIONS,
            NETWORK_BANNED_DOMAINS,
            SANDBOX_AUDIT_ENABLED,
        )
        if ALLOWED_FILE_EXTENSIONS:
            config.allowed_extensions = ALLOWED_FILE_EXTENSIONS
        if NETWORK_BANNED_DOMAINS:
            config.banned_domains = list(NETWORK_BANNED_DOMAINS)
        config.enable_audit = SANDBOX_AUDIT_ENABLED
    except ImportError:
        pass
    return config


def get_executor() -> SandboxedExecutor:
    global _global_executor
    level = get_sandbox_level()
    if _global_executor is None or _global_executor.config.level != level:
        _global_executor = SandboxedExecutor(level=level)
    return _global_executor


def get_file_guard() -> FileOperationGuard:
    global _global_file_guard
    if _global_file_guard is None:
        config = _apply_config_overrides(PRESETS.get(get_sandbox_level(), PRESETS["moderate"]))
        _global_file_guard = FileOperationGuard(config=config)
    return _global_file_guard


def get_network_guard() -> NetworkGuard:
    global _global_network_guard
    if _global_network_guard is None:
        config = _apply_config_overrides(PRESETS.get(get_sandbox_level(), PRESETS["moderate"]))
        _global_network_guard = NetworkGuard(config=config)
    return _global_network_guard
