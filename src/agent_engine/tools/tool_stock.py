"""
股票行情查询工具
-----------------
- A股 / 指数：使用东方财富 push2 公开 API
- 美股：使用 Stooq 公开 CSV 接口
均为免费公开数据，无需 API Key。

设计原则：用户输入任意名称或代码，自动通过东财搜索接口解析，
无需维护硬编码映射表。模糊名称（如"埃斯顿"）会返回全部匹配股票。
"""

import re
import csv
import io
import requests


# ============================================================
# akshare 兜底 —— 本地全量股票列表搜索，最可靠
# ============================================================

_AKSHARE_ALL_STOCKS = None  # 延迟加载，只拉一次


def _get_all_stocks():
    """获取 A 股全量代码-名称列表（akshare 缓存，仅成功才缓存）。"""
    global _AKSHARE_ALL_STOCKS
    if _AKSHARE_ALL_STOCKS is not None and len(_AKSHARE_ALL_STOCKS) > 0:
        return _AKSHARE_ALL_STOCKS
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        if df is not None and not df.empty:
            stocks = list(zip(df["code"].tolist(), df["name"].tolist()))
            _AKSHARE_ALL_STOCKS = stocks
            return stocks
    except Exception:
        pass
    # 失败不缓存，下次可以重试
    return []


def _search_akshare(keyword: str) -> list:
    """
    akshare 全量搜索兜底：在所有 A 股中按名称模糊匹配。
    返回: [(code, name, market, sec_type), ...]
    """
    stocks = _get_all_stocks()
    if not stocks:
        return []
    results = []
    kw = keyword.strip().lower()
    for code, name in stocks:
        if kw in name.lower():
            market = "1" if code.startswith(("6", "9")) else "0"
            results.append((code, name, market, "股票"))
    return results


# ============================================================
# 东财搜索接口 —— 自动解析任意名称/代码
# ============================================================

_SEARCH_CACHE = {}  # {keyword: [(code, name, market, type), ...]}


def _search_eastmoney(keyword: str, count: int = 10) -> list:
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
                "count": str(count),
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


def _search_sina(keyword: str) -> list:
    """
    新浪搜索建议接口兜底。
    返回: [(code, name, market, sec_type), ...]
    market: "1"=沪市 "0"=深市
    """
    try:
        resp = requests.get(
            "https://suggest3.sinajs.cn/suggest/",
            params={"type": "11", "key": keyword, "name": "suggestdata"},
            timeout=8,
            headers={"Referer": "https://finance.sina.com.cn/"},
        )
        resp.encoding = "gbk"
        text = resp.text
        if not text or "suggestdata=" not in text:
            return []

        # 格式: var suggestdata="...;...;"
        inner = text.split("suggestdata=", 1)[1].strip().strip('";')
        results = []
        for seg in inner.split(";"):
            parts = seg.split(",")
            if len(parts) < 4:
                continue
            name = parts[0]
            code = parts[2]
            symbol = parts[3] if len(parts) > 3 else ""
            # 根据 symbol 前缀判断交易所：sz→深市, sh→沪市
            if symbol.lower().startswith("sz"):
                mkt = "0"
            elif symbol.lower().startswith("sh"):
                mkt = "1"
            else:
                mkt = "1" if code.startswith(("6", "9")) else "0"
            results.append((code, name, mkt, "股票"))
        return results
    except Exception:
        return []


def _normalize_name(name: str) -> str:
    """去掉常见公司后缀，用于模糊匹配。"""
    suffixes = [
        "股份有限公司", "有限公司", "有限责任公司", "集团公司", "集团",
        "股份公司", "科技有限公司", "自动化", "科技", "智能", "股份",
    ]
    n = name.strip()
    for s in suffixes:
        if n.endswith(s):
            n = n[: -len(s)].strip()
            break
    return n


def _name_match_score(query: str, candidate_name: str) -> float:
    """计算查询词与候选名称的匹配分。"""
    q = query.lower().strip()
    c = candidate_name.lower().strip()
    c_norm = _normalize_name(c).lower()
    q_norm = _normalize_name(q).lower()

    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.9
    if q_norm and (q_norm in c_norm or c_norm in q_norm):
        return 0.85

    # 最长公共子串长度
    m, n_len = len(q), len(c)
    if m == 0 or n_len == 0:
        return 0.0
    longest = 0
    dp = [0] * (n_len + 1)
    for i in range(1, m + 1):
        prev = 0
        for j in range(1, n_len + 1):
            temp = dp[j]
            if q[i - 1] == c[j - 1]:
                dp[j] = prev + 1
                longest = max(longest, dp[j])
            else:
                dp[j] = 0
            prev = temp
    return min(longest / max(m, n_len), 1.0)


def _resolve_query(symbol: str) -> list:
    """
    用户输入 → 自动搜索解析 → 返回标准化结构列表。

    输入: "埃斯顿" / "茅台" / "600519" / "AAPL"
    返回: [{"market": "A", "secid": "0.002747", "display_name": "埃斯顿自动化（股票·002747）", "score": 0.85}, ...]

    空列表表示未找到任何匹配。
    """
    raw = symbol.strip()
    if not raw:
        return []

    # 1. 纯字母(1-5位) → 美股代码
    cleaned = raw.strip().upper()
    if cleaned.isalpha() and cleaned.isascii() and 1 <= len(cleaned) <= 5:
        return [{
            "market": "US",
            "code": cleaned,
            "display_name": cleaned,
            "score": 1.0,
        }]

    # 2. 纯数字6位 → A股代码
    code_clean = re.sub(r"^(SH|SZ|sh|sz)", "", raw).strip()
    if code_clean.isdigit() and len(code_clean) == 6:
        if code_clean.startswith(("6", "9")):
            secid = f"1.{code_clean}"
        else:
            secid = f"0.{code_clean}"
        return [{
            "market": "A",
            "secid": secid,
            "display_name": code_clean,
            "score": 1.0,
        }]

    # 3. 多级搜索兜底：东财 → 新浪 → 补后缀 → akshare 全量匹配
    def _try_search(q: str):
        if not q:
            return []
        res = _search_eastmoney(q)
        if res:
            return res
        res = _search_sina(q)
        if res:
            return res
        return _search_akshare(q)

    results = _try_search(raw)
    if not results:
        alt = _normalize_name(raw)
        if alt and alt != raw:
            results = _try_search(alt)
    if not results:
        # 常见简称补全后缀再搜一次
        suffixes = ["自动化", "科技", "智能", "股份", "集团"]
        for s in suffixes:
            results = _try_search(raw + s)
            if results:
                break

    if not results:
        return []

    # 4. 筛选 A 股候选，按名称相似度打分排序
    a_share = [r for r in results if r[2] in ("0", "1")]
    candidates = a_share if a_share else results

    scored = []
    for code, name, market, sec_type in candidates:
        score = _name_match_score(raw, name)
        # 股票优先于指数，略微加分
        if "股票" in (sec_type or ""):
            score += 0.02
        scored.append((score, code, name, market, sec_type))

    scored.sort(key=lambda x: x[0], reverse=True)

    # 5. 取所有分数 > 0 的候选（模糊名称可能匹配多条），至少返回第 1 条
    matches = []
    for score, code, name, market, sec_type in scored:
        if score <= 0:
            continue

        if market in ("0", "1"):
            secid = f"{market}.{code}"
            type_label = sec_type if sec_type else "股票"
            matches.append({
                "market": "A",
                "secid": secid,
                "display_name": f"{name}（{type_label}·{code}）",
                "score": score,
            })
        elif market == "105":
            matches.append({
                "market": "US",
                "code": code.replace(".US", ""),
                "display_name": f"{name}（美股）",
                "score": score,
            })
        # 其他市场（港股等）跳过

    if not matches:
        return []

    return matches


def _fetch_a_stock(secid: str, display_name: str) -> str:
    """查询 A 股 / 指数行情：东财优先，新浪兜底。"""
    # ── 东财 push2 ──
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
        if data:
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
    except Exception:
        pass  # 东财失败，走新浪兜底

    # ── 新浪兜底 ──
    # secid: "0.002747" → "sz002747",  "1.600519" → "sh600519"
    try:
        parts = secid.split(".", 1)
        if len(parts) == 2:
            market_prefix, code = parts
            sina_symbol = f"sz{code}" if market_prefix == "0" else f"sh{code}"
        else:
            return f"❌ 无法查询「{display_name}」的行情（所有数据源均不可用）。"

        resp = requests.get(
            f"https://hq.sinajs.cn/list={sina_symbol}",
            timeout=8,
            headers={"Referer": "https://finance.sina.com.cn/"},
        )
        resp.encoding = "gbk"
        text = resp.text
        if not text or '=""' in text or sina_symbol not in text:
            return f"❌ 未查询到「{display_name}」的行情数据，请稍后重试。"

        # 格式: var hq_str_sz002747="name,open,prev,price,high,low, ..."
        inner = text.split('"')[1] if '"' in text else ""
        if not inner:
            return f"❌ 未查询到「{display_name}」的行情数据。"

        fields_list = inner.split(",")
        if len(fields_list) < 6:
            return f"❌ 未查询到「{display_name}」的行情数据。"

        name = fields_list[0]
        open_price = fields_list[1]
        prev_close = fields_list[2]
        price = fields_list[3]
        high = fields_list[4]
        low = fields_list[5]
        # 成交量(股)和成交额(元)
        volume = fields_list[8] if len(fields_list) > 8 else "N/A"
        turnover = fields_list[9] if len(fields_list) > 9 else "N/A"

        # 计算涨跌幅
        try:
            p = float(price)
            prev = float(prev_close)
            if prev != 0:
                change_pct = round((p - prev) / prev * 100, 2)
                change_amt = round(p - prev, 2)
            else:
                change_pct = "N/A"
                change_amt = "N/A"
        except (ValueError, TypeError):
            change_pct = "N/A"
            change_amt = "N/A"

        direction = "📈"
        if isinstance(change_pct, (int, float)) and change_pct < 0:
            direction = "📉"

        return (
            f"{direction} **{name}**\n"
            f"{'─' * 30}\n"
            f"💰 最新价：{price}\n"
            f"📊 涨跌额：{change_amt}　｜　涨跌幅：{change_pct}%\n"
            f"📈 今开：{open_price}　｜　最高：{high}　｜　最低：{low}\n"
            f"📋 成交量：{volume} 股　｜　成交额：{turnover} 元\n"
            f"{'─' * 30}\n"
            f"数据来源：新浪财经（实时行情）"
        )

    except Exception as e:
        return f"❌ 所有行情源均不可用: {str(e)}"


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
    - 精确代码/美股 → 直接返回该股票行情
    - 模糊名称（如「埃斯顿」「茅台」）→ 返回全部匹配股票的行情
    """
    matches = _resolve_query(symbol)

    if not matches:
        return (
            f"❌ 未找到「{symbol}」的匹配结果。\n"
            "请检查名称拼写，或尝试输入 6 位代码 / 美股字母代码。"
        )

    # 逐条查询
    lines = []
    for i, m in enumerate(matches):
        if i > 0:
            lines.append("")   # 股票之间空行分隔

        if m["market"] == "A":
            lines.append(_fetch_a_stock(m["secid"], m["display_name"]))
        elif m["market"] == "US":
            lines.append(_fetch_us_stock(m["code"], m["display_name"]))
        else:
            lines.append(f"❌ 未知行情类型: {m.get('display_name', '')}")

    return "\n".join(lines)


# ======= 动态路由注册声明 =======
REGISTER_NAME = "get_stock"

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_stock",
        "description": (
            "查询股票或指数的实时行情。输入任意中文名称、简称、拼音或代码即可，工具内部会自动解析并返回行情。\n"
            "- A 股个股：如「贵州茅台」「宁德时代」「比亚迪」「茅台」「埃斯顿」\n"
            "- 大盘指数：如「上证指数」「创业板」「沪深300」「科创50」\n"
            "- 美股：如「苹果」「特斯拉」「AAPL」「TSLA」\n"
            "无需记忆任何代码，支持自然语言输入。当输入模糊名称时，会自动返回所有匹配股票。"
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
