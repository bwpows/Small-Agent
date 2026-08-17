# tools/tool_crawler.py
# 深蓝官网 (deepal.com.cn) 爬虫工具
# 基于 Playwright 渲染抓取，解决 SPA 加密问题

import json
import os
import re
import logging
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

logger = logging.getLogger("tools.crawler")


def _extract_text(page) -> str:
    """提取页面可见文本，排除导航和页脚"""
    return page.evaluate("""() => {
        const excludeTags = ['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'IFRAME', 'NAV', 'HEADER', 'FOOTER', 'ASIDE'];
        const excludeCls = ['nav', 'footer', 'bottom', 'menu', 'sidebar', 'privacy', 'copyright',
                            'contact', 'social', 'qr', 'share', 'scan', 'banner', 'header'];
        const excludeText = ['Copyright', '版权所有', '渝ICP', '公网安备', '隐私政策', '管家中心',
                             '951998', '投诉电话', '打开抖音', '打开微信', '扫一扫', '微博', '返回顶部'];
        const navTexts = ['车系', '品牌', '资讯', '门店', '招商加盟', '预约体验', '首页', '关于我们', '联系我们'];

        const lines = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while (node = walker.nextNode()) {
            const text = node.textContent.trim();
            if (!text || text.length < 3) continue;

            const parent = node.parentElement;
            if (!parent) continue;

            if (excludeTags.includes(parent.tagName)) continue;
            const cls = (parent.className || '').toLowerCase();
            if (excludeCls.some(c => cls.includes(c))) continue;

            const style = window.getComputedStyle(parent);
            if (style.display === 'none' || style.visibility === 'hidden') continue;

            if (navTexts.includes(text)) continue;
            if (excludeText.some(t => text.includes(t))) continue;

            lines.push(text);
        }
        return lines.join('\\n');
    }""")


def _extract_article_data(page) -> Dict:
    """从文章详情页提取结构化数据"""
    return page.evaluate("""() => {
        const result = {title: '', date: '', content: '', url: window.location.href};

        const h1 = document.querySelector('h1');
        if (h1) result.title = h1.textContent.trim();

        if (!result.title) {
            let maxSize = 0, bestText = '';
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
            let node;
            while (node = walker.nextNode()) {
                const parent = node.parentElement;
                if (!parent) continue;
                const style = window.getComputedStyle(parent);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                const fs = parseFloat(style.fontSize);
                if (fs > maxSize && node.textContent.trim().length > 5) {
                    maxSize = fs;
                    bestText = node.textContent.trim();
                }
            }
            result.title = bestText;
        }

        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while (node = walker.nextNode()) {
            const text = node.textContent.trim();
            if (/\\d{4}-\\d{2}-\\d{2}/.test(text)) {
                result.date = text.match(/\\d{4}-\\d{2}-\\d{2}/)[0];
                break;
            }
        }

        return result;
    }""")


class CrawlerResult:
    """爬虫结果"""
    def __init__(self, title: str, url: str, date: str, content: str, article_type: str = "news"):
        self.title = title
        self.url = url
        self.date = date
        self.content = content
        self.article_type = article_type


def crawl_deepal(config: Optional[Dict] = None) -> List[CrawlerResult]:
    """
    抓取深蓝官网 (deepal.com.cn) 全部内容。

    返回: List[CrawlerResult] — 包含所有文章和车型信息的结构化数据
    """
    logger.info("🕷️  [tool_crawler] 启动深蓝官网抓取...")

    results: List[CrawlerResult] = []
    config = config or {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 4000},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # === 1. 抓取新闻列表（最新新闻）===
        # 深蓝官网新闻为 SPA 路由，列表项含「日期+标题」，点击后跳转到 /policy?id=xxx 详情页
        logger.info("  [crawler] 加载新闻列表...")
        page.goto("https://deepal.com.cn/news", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # 滚动加载更多
        for _ in range(5):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)

        # 定位含日期的新闻卡片（标题 + YYYY-MM-DD），取中心坐标用于点击
        cards = page.evaluate("""() => {
            const out = [];
            const els = document.querySelectorAll('div, li, article, a, section');
            const dateRe = /\\d{4}-\\d{2}-\\d{2}/;
            for (const el of els) {
                const t = el.textContent || '';
                const m = t.match(dateRe);
                if (!m) continue;
                // 标题行：日期之前的部分且长度适中
                const titlePart = t.replace(dateRe, '').replace(/\\s+/g, ' ').trim();
                if (titlePart.length < 6 || titlePart.length > 60) continue;
                const r = el.getBoundingClientRect();
                if (r.width > 100 && r.height > 20 && r.top > 0 && r.top < 8000) {
                    out.push({
                        title: titlePart.slice(0, 50),
                        x: r.left + r.width / 2,
                        y: r.top + r.height / 2,
                    });
                }
            }
            // 去重（按标题）
            const seen = new Set();
            return out.filter(c => {
                if (seen.has(c.title)) return false;
                seen.add(c.title);
                return true;
            });
        }""")
        logger.info(f"  [crawler] 发现 {len(cards)} 个新闻卡片")

        # 逐一点击获取详情 URL（路由 /policy?id=）
        article_urls = []
        for i, card in enumerate(cards[:20]):
            try:
                page.goto("https://deepal.com.cn/news", wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(1500)
                page.mouse.click(card["x"], card["y"])
                page.wait_for_timeout(3000)
                url = page.url
                if "id=" in url and url != "https://deepal.com.cn/news":
                    article_urls.append({"title": card["title"], "url": url})
            except Exception as e:
                logger.info(f"    ⚠ 点击卡片 {i} 失败: {e}")

        # 去重
        seen = set()
        unique_urls = []
        for u in article_urls:
            if u["url"] not in seen:
                seen.add(u["url"])
                unique_urls.append(u)

        logger.info(f"  [crawler] 共 {len(unique_urls)} 个唯一新闻链接")

        # === 2. 提取文章详情 ===
        logger.info(f"  [crawler] 提取 {len(unique_urls)} 篇文章详情...")
        for i, article in enumerate(unique_urls):
            try:
                page.goto(article["url"], wait_until="networkidle", timeout=20000)
                page.wait_for_timeout(3000)

                data = _extract_article_data(page)
                content = _extract_text(page)

                # 如果提取内容太短，使用标题作为内容
                if len(content) < 50 and data["title"]:
                    content = f"{data['title']}\n{article['title']}\n{data['date'] or ''}"

                results.append(CrawlerResult(
                    title=data["title"] or article["title"],
                    url=article["url"],
                    date=data["date"] or "",
                    content=content,
                    article_type="news",
                ))

                logger.info(f"    [{i+1:2d}] {data['title'][:40] or article['title'][:40]} ({len(content)} 字)")

            except Exception as e:
                logger.info(f"    ⚠ 文章提取失败: {e}")

        # === 3. 提取每个车型的详细配置表 ===
        # 直接抓取官方"参数配置表"页（car/configuration），内含完整规格参数：
        # 基础参数（长宽高/轴距）、各版本市场指导价、动力/电池/续航、底盘与配置清单。
        CAR_CONFIG_URLS = [
            ("S05", "https://deepal.com.cn/car/configuration?car=S05&source=1&sort=1"),
            ("L06", "https://deepal.com.cn/car/configuration?car=L06&source=1&sort=1"),
            ("S07", "https://deepal.com.cn/car/configuration?car=S07&source=1&sort=1"),
            ("S09", "https://deepal.com.cn/car/configuration?car=S09&source=1&sort=1"),
            ("L07", "https://deepal.com.cn/car/configuration?car=L07&source=1&sort=1"),
            ("G318", "https://deepal.com.cn/car/configuration?car=G318&source=1&sort=1"),
        ]
        # 顶部导航噪声（参数配置页特有，非规格内容）
        NAV_NOISE = {
            "车系", "品牌", "资讯", "门店", "招商加盟", "预约体验",
            "全新深蓝S07参数配置表", "全新深蓝S05参数配置表",
            "全新深蓝S09参数配置表", "全新深蓝L07参数配置表",
            "全新深蓝L06参数配置表", "全新深蓝G318参数配置表",
            "−无", "标配", "选配",
        }
        logger.info("  [crawler] 提取各车型详细配置表...")
        for model, cfg_url in CAR_CONFIG_URLS:
            try:
                page.goto(cfg_url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(4500)
                raw = page.evaluate("() => document.body.innerText")
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
                # 过滤掉导航噪声；保留真实的车型版本名与参数行
                cleaned = []
                for ln in lines:
                    if ln in NAV_NOISE and not re.search(r"(Max|Ultra|Pro|标准|经典|精英|豪华|型|版|激光|视觉)", ln):
                        continue
                    cleaned.append(ln)
                config_text = "\n".join(cleaned).strip()
                if config_text and len(config_text) > 300:
                    # article_type 设为车型代号，便于检索时按 model 过滤
                    results.append(CrawlerResult(
                        title=f"深蓝{model}参数配置表",
                        url=cfg_url,
                        date="",
                        content=config_text,
                        article_type=model,
                    ))
                    logger.info(f"    ✅ {model} 配置表: {len(config_text)} 字")
                else:
                    logger.info(f"    ⚠ {model} 配置表文本过短")
            except Exception as e:
                logger.info(f"    ⚠ {model} 配置提取失败: {e}")

        # === 4. 提取车型一句话卖点（列表页）===
        try:
            page.goto("https://deepal.com.cn/car-series", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            car_text = _extract_text(page)
            if car_text and len(car_text) > 100:
                results.append(CrawlerResult(
                    title="深蓝汽车车型系列",
                    url="https://deepal.com.cn/car-series",
                    date="",
                    content=car_text,
                    article_type="car_series",
                ))
                logger.info(f"    车型系列卖点: {len(car_text)} 字")
        except Exception as e:
            logger.info(f"    ⚠ 车型系列提取失败: {e}")

        browser.close()

    logger.info(f"🎉 [tool_crawler] 抓取完成: {len(results)} 条数据")
    return results


def _split_long_text(text: str, max_len: int = 400) -> List[str]:
    """把超长文本按自然边界切成 <= max_len 的小段，避免 embedding 接口超长报错。"""
    if len(text) <= max_len:
        return [text]
    parts = []
    # 优先按换行切块，再对仍超长的块按字符滑动切
    paras = [p for p in text.split("\n") if p.strip()]
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 1 <= max_len:
            buf += ("\n" if buf else "") + p
        else:
            if buf:
                parts.append(buf)
            if len(p) > max_len:
                # 单段仍超长，按字符硬切
                for i in range(0, len(p), max_len):
                    parts.append(p[i:i + max_len])
                buf = ""
            else:
                buf = p
    if buf:
        parts.append(buf)
    return parts


# 车型版本名特征：含车型后缀关键词（Max/Ultra/Pro/版/激光/乾崑/舒享 等）
_VERSION_KW = re.compile(r"(Max|Ultra|Pro|版|激光|乾崑|舒享|豪华|精英|型|Plus|\+|\+华为|\+激光)")
# 应排除的非版本串：尺寸(长*宽*高)、整行纯数字（轴距等）、CLTC 等工况说明
_NON_VERSION_RE = re.compile(r"^(\d+\*\d+\*\d+|\d+$|CLTC|WLTC|工况|数据基于)")
# 版本名区块启动行：能源分类行（纯电版/增程版/激光版/视觉版）或 “XXX参数配置表”标题行
_START_RE = re.compile(r"^(纯电版|增程版|激光版|视觉版|.*参数配置表)$")


def _extract_version_names(config_text: str) -> List[str]:
    """从配置表文本中识别版本名列表。

    版本名区块出现在以下行之后，是一组连续行，直到遇到「市场指导价」
    或首个参数标签行（不含版本关键词）为止：
      - 「纯电版 / 增程版」分类行
      - 「XXX参数配置表」标题行
    仅在该捕获块内收集，避免把选装包、参数标签误当版本。
    """
    lines = [ln.strip() for ln in config_text.split("\n") if ln.strip()]
    versions: List[str] = []
    capture = False
    for ln in lines:
        if _START_RE.match(ln):
            capture = True
            continue
        if ln == "市场指导价":
            capture = False
            continue
        if not capture:
            continue
        # 捕获块内：遇到参数标签行（不含版本关键词）即结束本组
        if not _VERSION_KW.search(ln):
            capture = False
            continue
        # 排除尺寸/纯数字/工况说明
        if _NON_VERSION_RE.match(ln):
            continue
        if ln not in versions:
            versions.append(ln)
    return versions


def _is_param_label(line: str, versions: List[str]) -> bool:
    """判断一行是否为参数标签行（而非配置值）。

    配置值可能是短词（磷酸铁锂/三元锂）或数字（550），与标签行（车道保持辅助/
    CLTC纯电续航里程（km））仅靠字面难以区分，这里用「参数名特征词 + 长度」启发式：
    - 含参数名特征后缀（里程/（km）/（分钟）/类型/辅助/系统/时间/续航/电池...）
    - 或长度 > 10（长参数名）
    - 且不是纯数字/数字+单位、不是值词表（标配/选配/磷酸铁锂...）、不是版本名
    """
    if line in versions:
        return False
    if line in ("标配", "选配", "无", "−无", "—", "-", "磷酸铁锂", "三元锂"):
        return False
    if re.fullmatch(r"[\d\.\-\+]+[a-zA-Z%℃°kmKmKgWh]*", line):
        return False  # 纯数字/数字+单位视为值
    _LABEL_HINTS = ("（km）", "（分钟）", "（kW）", "（mm）", "（L）", "（kWh）", "：",
                    "率", "量", "距", "间", "辅助", "系统", "类型", "时间", "续航",
                    "电池", "驱动", "悬架", "配置", "功能", "模式", "标准", "版",
                    "功率", "扭矩", "容积", "质量", "尺寸", "宽度", "高度", "长度")
    if any(h in line for h in _LABEL_HINTS):
        return True
    return len(line) > 10


def _build_version_chunks(config_text: str, model: str, url: str) -> List[Dict]:
    """把列式配置表重组为「每个版本一段」的结构化 chunk，便于版本级精确检索。

    配置表为「标签行 + N 个值行」的列式结构（N = 版本数）。逐参数块拆分：当前行
    作为标签，向后收集值行，直到遇到下一个「看起来像参数标签」的行或版本名/分类标题。

    对合并单元格（全系标配等只占 1 格的值）的处理：
    - 若值区第 0 个值含「全系」语义（如「全系标配」），则广播到所有版本；
    - 否则按位置对齐到版本 k，不足 N 的版本用「—」占位，避免单参数错位污染整段。

    关键修复点：
    - 去掉原永远为真的死代码判断（re.match(..., lines[j] if False else lines[j])）
    - 用标签识别启发式取代原「遇到非值行就 break」的脆弱逻辑（原逻辑会把参数标签行误当值）
    - 值数量不足 N 时不再整段丢弃该参数，而是对齐填充（兼容合并单元格）
    """
    versions = _extract_version_names(config_text)
    if not versions:
        return []
    n = len(versions)
    per_version: List[List[str]] = [[] for _ in range(n)]

    _SKIP_LABELS = ("纯电版", "增程版", "激光版", "视觉版", "市场指导价")
    _ALL_SYS = ("全系标配", "全系选配", "全系-", "全系无")

    lines = [ln.strip() for ln in config_text.split("\n") if ln.strip()]
    i = 0
    while i < len(lines):
        label = lines[i]
        # 跳过非参数行（分类标题、版本名行、顶部页标题）
        if label in _SKIP_LABELS or label in versions or label == f"深蓝{model}参数配置表":
            i += 1
            continue
        # 若当前行不像参数标签（可能是游离值），跳过避免误当标签
        if not _is_param_label(label, versions):
            i += 1
            continue
        vals: List[str] = []
        j = i + 1
        while j < len(lines):
            v = lines[j]
            if v in versions or v in _SKIP_LABELS:
                break
            # 合并单元格：值区第 0 个即「全系X」语义 → 广播并结束该块
            if (not vals) and ("全系" in v or v in _ALL_SYS):
                vals = [v] * n
                j += 1
                break
            # 遇到下一个参数标签行 → 当前块结束
            if _is_param_label(v, versions):
                break
            vals.append(v)
            j += 1
        # 把收集到的值按位置对齐到各版本；不足 N 的版本用占位符
        for k in range(n):
            v = vals[k] if k < len(vals) else "—"
            per_version[k].append(f"{label}：{v}")
        i = j if vals else i + 1

    chunks = []
    for idx, ver in enumerate(versions):
        body = "\n".join(per_version[idx])
        if not body.strip():
            continue
        full_text = f"深蓝{model} {ver} 版本配置：\n{body}"
        # 版本配置可能较长，按安全长度切片以保证 embedding 不超限
        segs = _split_long_text(full_text)
        for si, seg in enumerate(segs):
            suffix = f" (#{si+1})" if len(segs) > 1 else ""
            chunks.append({
                "doc_id": f"{model}-{ver}" + (f"-{si+1}" if len(segs) > 1 else ""),
                "text": seg,
                "url": url,
                "title": f"深蓝{model} {ver} 配置" + suffix,
                "model": model,
                "version": ver,
                "date": "",
            })
    return chunks


def crawl_to_chunks(config: Optional[Dict] = None) -> List[Dict]:
    """
    抓取并返回符合 business_vector_store 接口的 chunk 列表。
    每个 chunk 包含 {text, url, title, model, date, version} 字段。
    车型配置表除保留整表切片（version 为空，用于回答"有几个版本"）外，
    还会额外生成「每个版本一段」的结构化 chunk（带 version 标签），
    支持版本级精确检索。
    """
    results = crawl_deepal(config)
    chunks = []
    for r in results:
        text = r.content.strip()
        if not text or len(text) < 20:
            continue
        # 车型配置表：生成 per-version 结构化 chunk
        if r.article_type not in ("news", "car_series"):
            version_chunks = _build_version_chunks(text, r.article_type, r.url)
            chunks.extend(version_chunks)
        # 整表切片（保留总览，便于"有几个版本/指导价"类问题）
        segs = _split_long_text(text)
        for i, seg in enumerate(segs):
            suffix = f" (#{i+1})" if len(segs) > 1 else ""
            chunks.append({
                "text": seg,
                "url": r.url,
                "title": r.title + suffix,
                "model": r.article_type,
                "version": "",
                "date": r.date,
            })
    return chunks
