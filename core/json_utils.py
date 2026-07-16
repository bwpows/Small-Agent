"""
结构化输出保障引擎
--------------------
解决本地小模型输出非法 JSON 的痛点，提供四层防线：
  1. Ollama JSON mode 约束（format: "json"）
  2. 智能提取 —— 从混合文本中捞出 JSON 片段
  3. 自动修复 —— 修复常见的 LLM 输出错误
  4. Schema 校验 —— 确保字段结构与类型正确
"""

import json
import re


# ──────────────────────────────────────────────
# 第一层：从混合文本中提取 JSON
# ──────────────────────────────────────────────

def extract_json(text: str, expect_array: bool = True) -> str:
    """
    从 LLM 的原始输出中提取 JSON 片段。
    支持：```json ...``` 包裹、前后废话、嵌套结构。
    """
    if not text or not text.strip():
        return ""

    # 1. 去掉 Markdown 代码块包裹
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    cleaned = re.sub(r"\n?\s*```$", "", cleaned)

    # 2. 按期望类型找最外层边界
    if expect_array:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end > start:
            return cleaned[start:end + 1]

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        return cleaned[start:end + 1]

    # 3. 兜底：原样返回
    return cleaned.strip()


# ──────────────────────────────────────────────
# 第二层：修复常见 JSON 语法错误
# ──────────────────────────────────────────────

def repair_json(raw: str) -> str:
    """
    修复 LLM 生成 JSON 时的典型错误，按优先级顺序处理。

    处理的错误类型：
      - 尾部多余逗号：{"a": 1,} | [1, 2,]
      - 单引号字符串：{'key': 'value'}
      - 未加引号的键：{key: "value"}
      - JSON 字符串内未转义的换行符（LLM 常犯）
      - 中文全角标点混淆
      - 多行字符串拼接
    """
    s = raw.strip()
    if not s:
        return s

    # ── 修复 1: 中文全角符号 → 英文半角 ──
    s = s.replace("\u201c", '"').replace("\u201d", '"')   # 「 」→ "
    s = s.replace("\u2018", "'").replace("\u2019", "'")   # ' ' → '
    s = s.replace("\uff0c", ",")                          # ， → ,
    s = s.replace("\uff1a", ":")                          # ： → :

    # ── 修复 2: 单引号 JSON → 双引号 JSON ──
    if s.startswith("'") or ("'" in s and '"' not in s):
        s = _convert_single_to_double_quotes(s)

    # ── 修复 3: 未加引号的 key ──
    s = _quote_unquoted_keys(s)

    # ── 修复 4: 尾部多余逗号 ──
    s = re.sub(r",\s*([}\]])", r"\1", s)

    # ── 修复 5: JSON 字符串值内部未转义的换行符 ──
    s = _escape_newlines_in_strings(s)

    # ── 修复 6: 缺失闭合括号，尝试补全 ──
    s = _balance_brackets(s)

    return s


def robust_parse(raw_text: str, expect_array: bool = True) -> list | dict | None:
    """
    主入口：依次尝试 原始解析 → 提取后解析 → 提取+修复后解析。
    返回解析后的 Python 对象，失败返回 None。
    """
    strategies = [
        # 策略 1：直接解析原文本
        lambda: json.loads(raw_text.strip()),
        # 策略 2：提取后直接解析
        lambda: json.loads(extract_json(raw_text, expect_array=expect_array)),
        # 策略 3：提取 + 修复后解析
        lambda: json.loads(repair_json(extract_json(raw_text, expect_array=expect_array))),
    ]

    for i, strategy in enumerate(strategies):
        try:
            result = strategy()
            if result is not None:
                return result
        except (json.JSONDecodeError, ValueError) as e:
            if i == len(strategies) - 1:
                print(f"⚠️ [JSON Utils] 所有解析策略均失败，最后错误: {e}")
            continue

    return None


# ──────────────────────────────────────────────
# 第三层：Schema 校验
# ──────────────────────────────────────────────

PLAN_TASK_SCHEMA = {
    "task_id":        {"type": int,   "required": True},
    "action":         {"type": str,   "required": True},
    "agent_role":     {"type": str,   "required": True},
    "depends_on":     {"type": list,  "required": False, "default": []},
    "instruction":    {"type": str,   "required": True},
    "risk_level":     {"type": str,   "required": True, "enum": ["low", "medium", "high"]},
    "risk_details":   {"type": str,   "required": True},
    "expected_output":{"type": str,   "required": False, "default": ""},
}


def validate_task_list(task_list: list) -> list:
    """
    校验并规范化任务列表。
    - 补全缺失的默认字段
    - 过滤掉无效任务
    - 修正 risk_level 非法值
    """
    if not isinstance(task_list, list):
        return []

    validated = []
    for i, task in enumerate(task_list):
        if not isinstance(task, dict):
            continue

        clean = {}
        for field, rules in PLAN_TASK_SCHEMA.items():
            value = task.get(field)

            # 默认值
            if value is None and "default" in rules:
                value = rules["default"]

            # 必填字段检查
            if rules.get("required") and (value is None or (isinstance(value, str) and not value.strip())):
                # 尝试修复部分字段
                if field == "task_id" and "task_id" not in task:
                    value = i + 1
                elif field == "agent_role":
                    value = "general"
                elif field == "risk_level":
                    value = "low"
                elif field == "action" or field == "instruction":
                    value = task.get("expected_output", "执行任务") if field == "action" else task.get("action", "请执行此任务")
                else:
                    value = "" if field != "depends_on" else []

            # 枚举校验
            if "enum" in rules and value not in rules["enum"]:
                value = rules["enum"][0]  # 兜底取第一个合法值

            # 类型强制转换
            expected_type = rules["type"]
            try:
                if expected_type == int and not isinstance(value, int):
                    value = int(value)
                elif expected_type == str and not isinstance(value, str):
                    value = str(value)
                elif expected_type == list and not isinstance(value, list):
                    value = [value] if value else []
            except (ValueError, TypeError):
                value = rules.get("default", "" if expected_type == str else 0)

            clean[field] = value

        validated.append(clean)

    return validated


# ──────────────────────────────────────────────
# 内部辅助函数
# ──────────────────────────────────────────────

def _convert_single_to_double_quotes(s: str) -> str:
    """将单引号 JSON 转为双引号 JSON（简单启发式）"""
    result = []
    in_string = False
    quote_char = None
    escape_next = False

    for ch in s:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            result.append(ch)
            continue
        if ch in ("'", '"') and not in_string:
            in_string = True
            quote_char = ch
            result.append('"')
            continue
        if ch == quote_char and in_string:
            in_string = False
            quote_char = None
            result.append('"')
            continue
        result.append(ch)

    return "".join(result)


def _quote_unquoted_keys(s: str) -> str:
    """为 JSON 对象中未加引号的 key 添加双引号"""
    # 匹配 { 或 , 后跟着未加引号的标识符然后跟 :
    return re.sub(
        r'([\{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:',
        r'\1"\2":',
        s
    )


def _escape_newlines_in_strings(s: str) -> str:
    """
    将 JSON 字符串值内部的裸换行符替换为 \\n。
    采用状态机跟踪当前位置是在字符串内部还是外部。
    """
    result = []
    in_string = False
    escape_next = False

    for ch in s:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            result.append(ch)
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ch in ('\n', '\r'):
            result.append('\\n')
            continue
        result.append(ch)

    return "".join(result)


def _balance_brackets(s: str) -> str:
    """补全缺失的闭合括号"""
    stack = []
    pairs = {'[': ']', '{': '}'}
    for ch in s:
        if ch in pairs:
            stack.append(pairs[ch])
        elif stack and ch == stack[-1]:
            stack.pop()

    return s + "".join(reversed(stack))
