# tools/tool_crawler.py
# 深蓝官网 (deepal.com.cn) 爬虫工具
# 基于 Playwright 渲染抓取，解决 SPA 加密问题

import json
import os
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright


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


def _get_clickable_cards(page) -> List[Dict]:
    """获取新闻列表中所有可点击的文章卡片"""
    return page.evaluate("""() => {
        const cards = [];
        const allDivs = document.querySelectorAll('div, article, section');
        for (const el of allDivs) {
            const text = el.textContent.trim();
            if (/\\d{4}-\\d{2}-\\d{2}/.test(text) && text.length > 20 && text.length < 500) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 150 && rect.height > 50 && rect.top < 6000) {
                    cards.push({
                        text: text.substring(0, 200),
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2,
                    });
                }
            }
        }
        const seen = new Set();
        return cards.filter(c => {
            const key = c.text.substring(0, 50);
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
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
    print("🕷️  [tool_crawler] 启动深蓝官网抓取...")

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

        # === 1. 抓取新闻列表 ===
        print("  [crawler] 加载新闻列表...")
        page.goto("https://deepal.com.cn/news", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # 滚动加载更多
        for _ in range(5):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)

        cards = _get_clickable_cards(page)
        print(f"  [crawler] 发现 {len(cards)} 个新闻卡片")

        # 逐一点击获取 URL
        article_urls = []
        for i, card in enumerate(cards[:20]):
            try:
                page.goto("https://deepal.com.cn/news", wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(2000)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(500)
                page.mouse.click(card["x"], card["y"])
                page.wait_for_timeout(3000)

                url = page.url
                if url != "https://deepal.com.cn/news" and "id=" in url:
                    article_urls.append({
                        "title": card["text"],
                        "url": url,
                    })
                    if len(article_urls) >= 15:
                        break
            except Exception as e:
                print(f"    ⚠ 点击卡片 {i} 失败: {e}")

        # 去重
        seen = set()
        unique_urls = []
        for u in article_urls:
            if u["url"] not in seen:
                seen.add(u["url"])
                unique_urls.append(u)

        print(f"  [crawler] 共 {len(unique_urls)} 个唯一文章链接")

        # === 2. 提取文章详情 ===
        print(f"  [crawler] 提取 {len(unique_urls)} 篇文章详情...")
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

                print(f"    [{i+1:2d}] {data['title'][:40] or article['title'][:40]} ({len(content)} 字)")

            except Exception as e:
                print(f"    ⚠ 文章提取失败: {e}")

        # === 3. 提取车型信息 ===
        print("  [crawler] 提取车型信息...")
        try:
            page.goto("https://deepal.com.cn/car-series", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)

            car_text = _extract_text(page)
            if car_text and len(car_text) > 100:
                results.append(CrawlerResult(
                    title="深蓝汽车车型系列",
                    url="https://deepal.com.cn/car-series",
                    date="",
                    content=car_text,
                    article_type="car_series",
                ))
                print(f"    车型信息: {len(car_text)} 字")

            # 尝试提取每个车型的详细信息
            car_models = page.evaluate("""() => {
                const models = [];
                const elements = document.querySelectorAll('div, article, section');
                for (const el of elements) {
                    const text = el.textContent.trim();
                    if (text.length < 30) continue;
                    const match = text.match(/深蓝[SL]\\d{2,3}|S\\d{2,3}|L\\d{2,3}/);
                    if (match) {
                        models.push({model: match[0], text: text.substring(0, 300)});
                    }
                }
                const seen = new Set();
                return models.filter(m => { if (seen.has(m.model)) return false; seen.add(m.model); return true; });
            }""")

            for m in car_models[:10]:
                results.append(CrawlerResult(
                    title=f"深蓝车型: {m['model']}",
                    url="https://deepal.com.cn/car-series",
                    date="",
                    content=m["text"],
                    article_type="car_model",
                ))
                print(f"    车型: {m['model']}")

        except Exception as e:
            print(f"    ⚠ 车型提取失败: {e}")

        browser.close()

    print(f"🎉 [tool_crawler] 抓取完成: {len(results)} 条数据")
    return results


def crawl_to_chunks(config: Optional[Dict] = None) -> List[Dict]:
    """
    抓取并返回符合 business_vector_store 接口的 chunk 列表。
    每个 chunk 包含 {text, url, title, model, date} 字段。
    """
    results = crawl_deepal(config)
    chunks = []
    for r in results:
        text = r.content.strip()
        if not text or len(text) < 20:
            continue
        chunks.append({
            "text": text,
            "url": r.url,
            "title": r.title,
            "model": r.article_type,
            "date": r.date,
        })
    return chunks
