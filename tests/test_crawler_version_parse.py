"""针对配置表解析逻辑的单元测试。

覆盖：
- _extract_version_names：版本名行识别（含 Max/Ultra/Pro/激光/版 等关键词，排除长参数行误命中）
- _build_version_chunks：列式重组对齐（合并单元格占位、死代码已移除、不丢参数）
"""
import os
import sys
import importlib.util
import unittest

# tool_crawler 顶层依赖 playwright（仅爬虫运行时需要），但版本解析函数本身是纯逻辑。
# 为避免 import 整个模块时拉起 playwright，这里把 playwright stub 掉后从文件直接加载模块。
_ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _ROOT)

sys.modules.setdefault("playwright", type(sys)("playwright"))
_playwright_stub = type(sys)("playwright.sync_api")
_playwright_stub.sync_playwright = lambda: None
sys.modules["playwright.sync_api"] = _playwright_stub

_SPEC = importlib.util.spec_from_file_location(
    "tool_crawler_standalone",
    os.path.join(_ROOT, "agent_engine", "tools", "tool_crawler.py"),
)
_tool_crawler = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_tool_crawler)

_extract_version_names = _tool_crawler._extract_version_names
_build_version_chunks = _tool_crawler._build_version_chunks


# 模拟深蓝 L06 参数配置表的列式文本（真实结构高度还原）
L06_SAMPLE = """深蓝L06参数配置表
纯电版
增程版
510Max
530Ultra
560Max
610Ultra
550Pro
570Pro
CLTC纯电续航里程（km）
550
580
600
650
600
620
电池类型
磷酸铁锂
磷酸铁锂
三元锂
三元锂
磷酸铁锂
三元锂
快充时间（分钟）
20
20
25
25
20
25
智能驾驶辅助
全系标配
车道保持辅助
标配
标配
标配
标配
标配
标配
市场指导价（万元）
13.59
14.99
15.99
17.69
14.29
15.29
"""


class TestExtractVersionNames(unittest.TestCase):
    def test_extract_l06_versions(self):
        versions = _extract_version_names(L06_SAMPLE)
        # 6 个版本都应被识别，且不应误把参数行当版本
        self.assertEqual(
            versions,
            ["510Max", "530Ultra", "560Max", "610Ultra", "550Pro", "570Pro"],
        )

    def test_no_false_positive_on_param_lines(self):
        versions = _extract_version_names(L06_SAMPLE)
        # 参数行（如 CLTC纯电续航里程）不得进入版本列表
        self.assertNotIn("CLTC纯电续航里程（km）", versions)
        self.assertNotIn("市场指导价（万元）", versions)


class TestBuildVersionChunks(unittest.TestCase):
    def test_version_count_and_tag(self):
        chunks = _build_version_chunks(L06_SAMPLE, "L06", "http://example.com")
        self.assertTrue(chunks, "应生成版本级 chunk")
        # 每个版本应有对应 chunk，且 version 标签正确
        versions_in_chunks = {c["version"] for c in chunks}
        self.assertEqual(
            versions_in_chunks,
            {"510Max", "530Ultra", "560Max", "610Ultra", "550Pro", "570Pro"},
        )
        for c in chunks:
            self.assertEqual(c["model"], "L06")
            self.assertTrue(c["text"].startswith("深蓝L06"))
            # 死代码已移除：不再出现永远为真的判断残留，且文本至少包含版本名
            self.assertIn(c["version"], c["text"])

    def test_merged_cell_no_misalign(self):
        """合并单元格（'全系标配'只占一格）不应污染后续对齐。"""
        chunks = _build_version_chunks(L06_SAMPLE, "L06", "http://example.com")
        # 按版本分组拼接完整文本
        by_ver = {}
        for c in chunks:
            by_ver.setdefault(c["version"], [])
            by_ver[c["version"]].append(c["text"])
        full = {v: "\n".join(t) for v, t in by_ver.items()}

        # 样本中"智能驾驶辅助"下为"全系标配"（合并单元格单值），应广播为全系标配
        self.assertIn("智能驾驶辅助：全系标配", full["510Max"])
        # 全系标配不应污染其他参数：车道保持辅助仍按各自版本对齐
        self.assertIn("车道保持辅助：标配", full["510Max"])
        # 续航参数正确对齐到各自版本
        self.assertIn("CLTC纯电续航里程（km）：550", full["510Max"])
        self.assertIn("CLTC纯电续航里程（km）：600", full["560Max"])
        # 不允许出现整段错位：某版本文本不得混入另一版本的续航数字
        # 例如 560Max 不应含 510Max 的 550
        self.assertNotIn("CLTC纯电续航里程（km）：550", full["560Max"])

    def test_no_parameter_dropped(self):
        """参数行不应因值数量不足 N 而被整行丢弃。"""
        chunks = _build_version_chunks(L06_SAMPLE, "L06", "http://example.com")
        by_ver = {}
        for c in chunks:
            by_ver.setdefault(c["version"], [])
            by_ver[c["version"]].append(c["text"])
        full = {v: "\n".join(t) for v, t in by_ver.items()}
        # "电池类型" 参数在样本中每个版本都有值，必须出现
        for v in full:
            self.assertIn("电池类型：", full[v], f"版本 {v} 缺少电池类型参数（参数被丢弃）")

    def test_empty_config(self):
        self.assertEqual(_build_version_chunks("", "L06", "u"), [])


if __name__ == "__main__":
    unittest.main()
