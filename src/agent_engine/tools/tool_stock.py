"""
股票行情查询工具
-----------------
- A股 / 指数：使用东方财富 push2 公开 API
- 美股：使用 Stooq 公开 CSV 接口
均为免费公开数据，无需 API Key。

设计原则：用户输入任意名称或代码，自动通过东财搜索接口解析，
无需维护硬编码映射表。
"""

import re
import csv
import io
import requests


# ============================================================
# 东财搜索接口 —— 自动解析任意名称/代码
# ============================================================

_SEARCH_CACHE = {}  # {keyword: [(code, name, market, type), ...]}


def _search_eastmoney(keyword: str) -> list:
    """
    调用东方财富搜索建议接口，返回匹配列表。
    每项: (code, name, market_prefix, security_type)
    market_prefix: "1"=沪市 "0"=深市 "116"=港股 "105"=美股
    """
    if keyword in _SEARCH_CACHE:
        return _SEARCH_CACHE[keyword]

    try:
        resp = requests.get(
            "https://searchapi.eastmoney.com/api/suggest/get",
            params={
                "input": keyword,
                "type": "14",      # 全部类型
                "token": "D43BF722C8E33BDC906FB84D85E326E8",
                "count": "5",
            },
            timeout=8,
            headers={"Referer": "https://www.eastmoney.com/"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("ErrCode") != 0:
            return []

        results = []
        for item in data.get("QuotationCodeTable", {}).get("Data", []):
            code = item.get("Code", "")
            name = item.get("Name", "")
            market = item.get("MktNum", "")      # "1" "0" "116" "105"
            sec_type = item.get("SecurityTypeName", "")

            if not code or not name:
                continue

            results.append((code, name, market, sec_type))

        _SEARCH_CACHE[keyword] = results
        return results

    except Exception:
        return []


def _resolve_query(symbol: str) -> dict:
    """
    用户输入 → 自动搜索解析 → 返回标准化结构。
    返回: {"market": "A"|"US", "secid": "...", "display_name": "..."}
    失败: {"error": "..."}
    """
    raw = symbol.strip()
    if not raw:
        return {"error": "请提供股票名称或代码。例如：「贵州茅台」「上证指数」「AAPL」"}

    # 1. 直接判断是否为美股字母代码（1-5 位纯字母）
    cleaned = raw.strip().upper()
    if cleaned.isalpha() and cleaned.isascii() and 1 <= len(cleaned) <= 5:
        # 可能是美股，直接用 Stooq
        return {
            "market": "US",
            "code": cleaned,
            "display_name": cleaned,
        }

    # 2. 调用东财搜索
    results = _search_eastmoney(raw)

    if not results:
        # 东财搜不到，再尝试作为 A 股代码
        code_clean = re.sub(r"^(SH|SZ|sh|sz)", "", raw).strip()
        if code_clean.isdigit() and len(code_clean) == 6:
            if code_clean.startswith(("6", "9")):
                secid = f"1.{code_clean}"
            else:
                secid = f"0.{code_clean}"
            return {
                "market": "A",
                "secid": secid,
                "display_name": code_clean,
            }
        return {
            "error": (
                f"未找到「{raw}」的匹配结果。\n"
                "请检查名称拼写，或尝试输入 6 位代码 / 美股字母代码。"
            )
        }

    # 3. 优先 A 股（market "0" 或 "1"），其次港股/美股
    best = None
    for code, name, market, sec_type in results:
        if market in ("0", "1"):
            best = (code, name, market, sec_type)
            break

    if best is None:
        best = results[0]

    code, name, market, sec_type = best

    if market in ("0", "1"):
        # A 股或指数
        secid = f"{market}.{code}"
        type_label = sec_type if sec_type else "股票"
        return {
            "market": "A",
            "secid": secid,
            "display_name": f"{name}（{type_label}·{code}）",
        }

    elif market == "105":
        # 美股（东财有数据）
        return {
            "market": "US",
            "code": code.replace(".US", ""),
            "display_name": f"{name}（美股）",
        }

    else:
        # 其他市场 → 提示用户
        return {
            "error": (
                f"找到「{name}」（{code}），但暂不支持该市场行情查询。"
            )
        }


def _fetch_a_stock(secid: str, display_name: str) -> str:
    """查询 A 股 / 指数行情。"""
    fields = "f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,f57,f58,f115,f116,f117,f169,f170"
    try:
        resp = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={"secid": secid, "fields": fields, "invt": "2"},
            timeout=10,
            headers={"Referer": "https://quote.eastmoney.com/"},
        )
        resp.raise_for_status()
        data = resp.json().get("data")
        if not data:
            return f"❌ 未查询到「{display_name}」的行情数据，请稍后重试。"

        name = data.get("f58", display_name)
        price = data.get("f43", "N/A")
        high = data.get("f44", "N/A")
        low = data.get("f45", "N/A")
        volume = data.get("f47", "N/A")
        turnover = data.get("f48", "N/A")
        change_pct = data.get("f170", "N/A")
        change_amt = data.get("f169", "N/A")
        open_price = data.get("f46", "N/A")
        pe = data.get("f115", "N/A")
        total_value = data.get("f116", "N/A")

        direction = "📈"
        if isinstance(change_pct, (int, float)) and change_pct < 0:
            direction = "📉"

        return (
            f"{direction} **{name}**\n"
            f"{'─' * 30}\n"
            f"💰 最新价：{price}\n"
            f"📊 涨跌额：{change_amt}　｜　涨跌幅：{change_pct}%\n"
            f"📈 今开：{open_price}　｜　最高：{high}　｜　最低：{low}\n"
            f"📋 成交量：{volume} 手　｜　成交额：{turnover}\n"
            f"🏢 总市值：{total_value}　｜　PE(TTM)：{pe}\n"
            f"{'─' * 30}\n"
            f"数据来源：东方财富（实时行情）"
        )

    except Exception as e:
        return f"❌ 行情查询失败: {str(e)}"


def _fetch_us_stock(symbol: str, display_name: str) -> str:
    """查询美股行情（Stooq）。"""
    sym = symbol.strip().upper()
    try:
        resp = requests.get(
            f"https://stooq.com/q/l/?s={sym}.us&f=sd2t2ohlcvn&h&e=csv",
            timeout=10,
        )
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        if not rows:
            return f"❌ 未查询到「{display_name}」的美股行情。"

        row = rows[0]
        name = row.get("Name", display_name)
        price = row.get("Close", "N/A")
        change_pct = row.get("Change", "N/A")
        open_price = row.get("Open", "N/A")
        high = row.get("High", "N/A")
        low = row.get("Low", "N/A")
        volume = row.get("Volume", "N/A")

        direction = "📈"
        if change_pct and change_pct.startswith("-"):
            direction = "📉"

        return (
            f"{direction} **{name}**（{sym}·美股）\n"
            f"{'─' * 30}\n"
            f"💰 最新价：{price} USD\n"
            f"📊 涨跌幅：{change_pct}\n"
            f"📈 今开：{open_price}　｜　最高：{high}　｜　最低：{low}\n"
            f"📋 成交量：{volume}\n"
            f"{'─' * 30}\n"
            f"数据来源：Stooq（延时约 15 分钟）"
        )

    except Exception as e:
        return f"❌ 美股查询失败: {str(e)}"


def get_stock(symbol: str) -> str:
    """
    查询股票或指数的实时行情。
    输入任意名称或代码，自动搜索解析：
    - A 股：中文名（如「贵州茅台」）、简称（如「茅台」）、6 位代码
    - 指数：如「上证指数」「创业板」「沪深300」
    - 美股：中文名（如「苹果」）、字母代码（如 AAPL、TSLA）
    无需记忆任何代码，无需维护映射表。
    """
    parsed = _resolve_query(symbol)
    if "error" in parsed:
        return f"❌ {parsed['error']}"

    if parsed["market"] == "A":
        return _fetch_a_stock(parsed["secid"], parsed["display_name"])
    elif parsed["market"] == "US":
        return _fetch_us_stock(parsed["code"], parsed["display_name"])
    else:
        return f"❌ 未知的行情类型"


# ======= 动态路由注册声明 =======
REGISTER_NAME = "get_stock"

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_stock",
        "description": (
            "查询股票或指数的实时行情。输入任意中文名称、简称、拼音或代码即可。\n"
            "- A 股个股：如「贵州茅台」「宁德时代」「比亚迪」「茅台」\n"
            "- 大盘指数：如「上证指数」「创业板」「沪深300」「科创50」\n"
            "- 美股：如「苹果」「特斯拉」「AAPL」「TSLA」\n"
            "无需记忆任何代码，支持自然语言输入。"
            "当用户问「今天A股怎么样」「大盘」时，应分别查询「上证指数」「深证成指」「创业板指」。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": (
                        "股票或指数的名称/代码。无需精确，模糊匹配即可，"
                        "如「茅台」会匹配「贵州茅台」，"
                        "「宁王」「宁德」会匹配「宁德时代」。"
                    ),
                }
            },
            "required": ["symbol"],
        },
    },
}