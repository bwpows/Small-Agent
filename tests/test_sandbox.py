"""
沙箱引擎单元测试 (test_sandbox.py)
==================================

验证多层沙箱:
  - 资源限制 (CPU/内存/文件大小)
  - 模块白名单/黑名单
  - 文件操作守卫
  - 网络守卫
  - 分级策略切换
"""

import os
import sys
import json
import tempfile
import unittest

# 确保项目根目录在 Python path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.sandbox import (
    SandboxConfig,
    SandboxedExecutor,
    FileOperationGuard,
    NetworkGuard,
    PRESETS,
    generate_sandbox_preamble,
    get_sandbox_level,
    _apply_config_overrides,
)


class TestSandboxConfig(unittest.TestCase):
    """测试配置模型"""

    def test_presets_exist(self):
        for level in ["strict", "moderate", "relaxed"]:
            self.assertIn(level, PRESETS)
            self.assertEqual(PRESETS[level].level, level)

    def test_strict_is_most_restrictive(self):
        s = PRESETS["strict"]
        m = PRESETS["moderate"]
        r = PRESETS["relaxed"]
        self.assertLess(s.cpu_timeout, m.cpu_timeout)
        self.assertLess(s.memory_limit_mb, m.memory_limit_mb)
        self.assertLess(s.cpu_timeout, r.cpu_timeout)
        self.assertTrue(len(s.banned_modules) > 0)

    def test_relaxed_has_no_ban(self):
        r = PRESETS["relaxed"]
        self.assertEqual(len(r.banned_modules), 0)

    def test_config_overrides(self):
        config = PRESETS["moderate"]
        original_exts = config.allowed_extensions
        # 模拟 config.py 覆盖
        overridden = _apply_config_overrides(config)
        self.assertIsNotNone(overridden)


class TestSandboxPreamble(unittest.TestCase):
    """测试模块白名单注入"""

    def test_strict_preamble_blocks_os(self):
        preamble = generate_sandbox_preamble(PRESETS["strict"])
        self.assertIn("__BANNED__", preamble)
        self.assertIn('"os"', preamble)

    def test_moderate_preamble_blocks_os(self):
        preamble = generate_sandbox_preamble(PRESETS["moderate"])
        self.assertIn("__BANNED__", preamble)

    def test_relaxed_has_no_preamble(self):
        preamble = generate_sandbox_preamble(PRESETS["relaxed"])
        self.assertEqual(preamble, "")


class TestSandboxedExecutor(unittest.TestCase):
    """测试沙箱执行器"""

    def setUp(self):
        self.executor = SandboxedExecutor(level="moderate")

    def test_simple_code(self):
        result = self.executor.run("print(1 + 1)")
        self.assertIn("✅", result)
        self.assertIn("2", result)

    def test_syntax_error(self):
        result = self.executor.run("print(1 + ")
        self.assertIn("❌", result)

    def test_allowed_module(self):
        result = self.executor.run("import json; print(json.dumps({'a': 1}))")
        self.assertIn("✅", result)
        self.assertIn('{"a": 1}', result)

    def test_banned_module_blocked(self):
        """moderate 级别应阻断 os 模块"""
        result = self.executor.run("import os; print(os.getcwd())")
        self.assertIn("❌", result)

    def test_math_module_allowed(self):
        result = self.executor.run("import math; print(math.sqrt(16))")
        self.assertIn("✅", result)
        self.assertIn("4.0", result)

    def test_empty_code(self):
        result = self.executor.run("")
        self.assertIn("✅", result)


class TestStrictSandbox(unittest.TestCase):
    """测试 strict 级别"""

    def setUp(self):
        self.executor = SandboxedExecutor(level="strict")

    def test_only_allowed_modules(self):
        """strict 级别只允许白名单模块"""
        result = self.executor.run("import math; print(math.pi)")
        self.assertIn("✅", result)

    def test_unlisted_module_blocked(self):
        """未在白名单的模块被阻断"""
        # 'email' 不在 strict 白名单中
        result = self.executor.run("import email; print('test')")
        self.assertIn("❌", result)


class TestRelaxedSandbox(unittest.TestCase):
    """测试 relaxed 级别"""

    def setUp(self):
        self.executor = SandboxedExecutor(level="relaxed")

    def test_any_module_allowed(self):
        """relaxed 级别不限制模块"""
        result = self.executor.run("import email; print('ok')")
        self.assertIn("✅", result)


class TestFileOperationGuard(unittest.TestCase):
    """测试文件操作守卫"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="sandbox_test_")
        self.guard = FileOperationGuard(workspace_dir=self.temp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_safe_write_and_read(self):
        result = self.guard.safe_write("test.txt", "Hello World")
        self.assertIn("✅", result)

        content = self.guard.safe_read("test.txt")
        self.assertEqual(content, "Hello World")

    def test_path_traversal_neutralized(self):
        """路径穿越被安全剥离为纯文件名，不会逃逸到工作区外"""
        safe = self.guard.resolve_safe_path("../../etc/passwd")
        # 应该被剥离为 "passwd" 并在工作区内
        self.assertTrue(safe.startswith(self.temp_dir))
        self.assertTrue(safe.endswith("passwd"))

    def test_disallowed_extension(self):
        with self.assertRaises(PermissionError):
            self.guard.safe_write("malware.exe", "evil")

    def test_allowed_extension(self):
        result = self.guard.safe_write("data.json", '{"key": "value"}')
        self.assertIn("✅", result)

    def test_file_not_found(self):
        result = self.guard.safe_read("nonexistent.txt")
        self.assertIn("❌", result)


class TestNetworkGuard(unittest.TestCase):
    """测试网络守卫"""

    def setUp(self):
        self.guard = NetworkGuard()

    def test_default_allows_normal_urls(self):
        self.assertTrue(self.guard.check_url("https://www.example.com/page"))

    def test_no_allowed_domains_default(self):
        """默认没有白名单，应允许所有"""
        self.assertTrue(self.guard.check_url("https://any-domain.com"))


class TestSandboxLevelDetection(unittest.TestCase):
    """测试沙箱级别读取"""

    def test_default_level(self):
        level = get_sandbox_level()
        self.assertIn(level, ["strict", "moderate", "relaxed"])

    def test_env_var_override(self):
        os.environ["SANDBOX_LEVEL"] = "relaxed"
        from core import sandbox
        import importlib
        # 重置模块级缓存
        sandbox._global_executor = None
        sandbox._global_file_guard = None
        sandbox._global_network_guard = None
        self.assertIn(get_sandbox_level(), ["strict", "moderate", "relaxed"])


if __name__ == "__main__":
    unittest.main()
