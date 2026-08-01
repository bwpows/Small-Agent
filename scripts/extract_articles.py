#!/usr/bin/env python3
"""
深蓝官网 - 深度内容提取
点击文章卡片提取详情，解决 SPA 无 <a> 标签的问题
"""

import json
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "src" / "agent_engine" / "assets"
OUTPUT_FILE = OUTPUT_DIR / "deepal_articles.json"


def extract_text(page) -> str:
    return page.evaluate("""() => {
        const exclude = {SCRIPT:1, STYLE:1, NOSCRIPT:1, SVG:1, IFRAME:1};
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        let lines = [], node;
        while (node = walker.nextNode()) {
            const text = node.textContent.trim();
            if (!text || text.length < 2) continue;
            const parent = node.parentElement;
            if (!parent || exclude[parent.tagName]) continue;
            const style = window.getComputedStyle(parent);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            lines.push(text);
        }
        return lines.join('\\n');
    }""")


def get_clickable_cards(page) -> list:
    """获取所有可点击的文章卡片元素（div 级别）"""
    return page.evaluate("""() => {
        const cards = [];
        // 寻找有标题+日期的元素组合（新闻卡片典型结构）
        const allDivs = document.querySelectorAll('div, article, section');
        for (const el of allDivs) {
            const text = el.textContent.trim();
            // 典型新闻卡片：包含标题 + 日期格式
            if (/\\d{4}-\\d{2}-\\d{2}/.test(text) && text.length > 20 && text.length < 500) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 100 && rect.height > 50 && rect.top < 5000) {
                    cards.push({
                        text: text.substring(0, 200),
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2,
                        width: rect.width,
                        height: rect.height,
                        selector: el.tagName.toLowerCase() + (el.className ? '.' + el.className.split(' ')[0] : ''),
                    });
                }
            }
        }
        // 去重（按文本内容）
        const seen = new Set();
        return cards.filter(c => {
            const key = c.text.substring(0, 50);
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
    }""")


def main():
    print("=" * 60)
    print("深蓝官网 - 深度文章提取")
    print("=" * 60)

    articles = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 4000},  # 高视窗确保内容可见
        )
        page = context.new_page()

        # === 1. 加载新闻页 ===
        print("\n[1] 加载新闻列表...")
        page.goto("https://deepal.com.cn/news", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        # 滚到顶部确保卡片位置正确
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

        # 获取所有文章卡片
        cards = get_clickable_cards(page)
        print(f"  发现 {len(cards)} 个卡片:")
        for i, c in enumerate(cards[:20]):
            print(f"    [{i+1:2d}] {c['text'][:80]} (x={c['x']:.0f}, y={c['y']:.0f})")

        # 保存列表
        articles["news_list"] = cards

        # === 2. 逐一点击卡片获取详情 ===
        print(f"\n[2] 点击前 {min(10, len(cards))} 个卡片获取详情...")

        for i, card in enumerate(cards[:10]):
            print(f"\n  [{i+1}] {card['text'][:60]}")
            print(f"      位置: ({card['x']:.0f}, {card['y']:.0f})")

            try:
                # 先回到列表页（确保不在详情页中）
                page.goto("https://deepal.com.cn/news", wait_until="networkidle", timeout=20000)
                page.wait_for_timeout(2000)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(500)
                # 重新获取卡片（DOM 可能已更新）
                fresh_cards = get_clickable_cards(page)
                if i < len(fresh_cards):
                    card = fresh_cards[i]
                # 移动到卡片位置并点击
                page.mouse.click(card["x"], card["y"])
                page.wait_for_timeout(3000)

                # 检查是否导航到新 URL
                current_url = page.url
                print(f"      URL: {current_url}")

                text = extract_text(page)
                articles[f"article_{i+1}"] = {
                    "title": card["text"],
                    "url": current_url,
                    "text": text,
                    "length": len(text),
                }
                print(f"      提取: {len(text)} 字符")
                # 预览前 200 字
                preview = text.replace('\n', ' ')[:200]
                print(f"      预览: {preview}")

            except Exception as e:
                print(f"      错误: {e}")
                articles[f"article_{i+1}"] = {
                    "title": card["text"],
                    "error": str(e),
                }

        # 首页也提取
        print("\n[3] 提取首页...")
        page.goto("https://deepal.com.cn/", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        articles["home"] = {"text": extract_text(page), "url": "https://deepal.com.cn/"}

        browser.close()

    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"\n\n结果已保存: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
