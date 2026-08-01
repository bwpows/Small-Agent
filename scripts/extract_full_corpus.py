#!/usr/bin/env python3
"""
深蓝官网 - 最终版：Playwright 交互式内容提取
1. 截图查看页面结构
2. 点击元素获取详情页
3. 提取所有渲染文本
"""

import json
import time
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "src" / "agent_engine" / "assets"
OUTPUT_FILE = OUTPUT_DIR / "deepal_full_corpus.json"


def extract_text(page) -> str:
    """提取页面所有可见文本，按标签分行"""
    return page.evaluate("""() => {
        const excludeTags = {'SCRIPT':1, 'STYLE':1, 'NOSCRIPT':1, 'SVG':1, 'IFRAME':1};
        const walker = document.createTreeWalker(
            document.body, NodeFilter.SHOW_TEXT, null, false
        );
        let prevParent = null;
        let lines = [];
        let node;
        while (node = walker.nextNode()) {
            const text = node.textContent.trim();
            if (!text || text.length < 2) continue;
            const parent = node.parentElement;
            if (!parent) continue;
            if (excludeTags[parent.tagName]) continue;
            
            const style = window.getComputedStyle(parent);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            
            // 按段落/列表/标题换行
            const tag = parent.tagName;
            if (['P','H1','H2','H3','H4','H5','H6','LI','DIV','SECTION','ARTICLE'].includes(tag)) {
                lines.push('\\n' + tag + ': ' + text);
            } else if (!prevParent || prevParent !== parent) {
                lines.push(text);
            }
            prevParent = parent;
        }
        return lines.join('\\n');
    }""")


def extract_all_links(page) -> list:
    """提取页面所有链接（包括 React Router 链接）"""
    return page.evaluate("""() => {
        const links = [];
        const seen = new Set();
        
        // 标准 <a> 标签
        const anchors = document.querySelectorAll('a[href]');
        for (const a of anchors) {
            const href = a.href || a.getAttribute('href') || '';
            const text = a.textContent.trim();
            if (!href || href === '#' || href.startsWith('javascript:') || href.startsWith('tel:')
                || href.startsWith('mailto:') || href.endsWith('.png') || href.endsWith('.jpg')) continue;
            if (seen.has(href) || text.length < 4) continue;
            seen.add(href);
            links.push({url: href, text: text.substring(0, 200), type: 'a'});
        }
        
        // 可点击元素（事件代理）
        const clickables = document.querySelectorAll('[class*="item"], [class*="card"], [class*="article"], [class*="news"], [class*="list"] > div, [class*="list"] > li');
        for (const el of clickables) {
            if (el.tagName === 'A') continue;
            const text = el.textContent.trim().substring(0, 200);
            if (text.length < 10) continue;
            
            // 生成唯一键
            const key = text.substring(0, 50);
            if (seen.has(key)) continue;
            seen.add(key);
            
            const cls = el.className || el.getAttribute('class') || '';
            links.push({url: '(clickable)', text: text, type: 'element', className: cls.substring(0, 100)});
        }
        
        return links;
    }""")


def click_and_extract(page, element_selector: str) -> dict | None:
    """点击指定元素并提取新页面内容"""
    try:
        el = page.locator(element_selector).first
        if not el:
            return None

        current_url = page.url
        el.click()
        page.wait_for_timeout(3000)

        new_url = page.url
        if new_url != current_url:
            text = extract_text(page)
            return {"url": new_url, "text": text, "text_length": len(text)}
        return None
    except Exception as e:
        return {"error": str(e)}


def main():
    print("=" * 60)
    print("深蓝官网 - 最终内容提取")
    print("=" * 60)

    corpus = {"pages": {}, "articles": {}, "extract_time": datetime.now().isoformat()}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # === 1. 首页 ===
        print("\n[1] 首页")
        page.goto("https://deepal.com.cn/", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(5000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

        text_home = extract_text(page)
        corpus["pages"]["首页"] = {"url": "https://deepal.com.cn/", "text": text_home}
        print(f"  提取: {len(text_home)} 字符")

        # 截图查看结构
        page.screenshot(path=str(OUTPUT_DIR / "deepal_home.png"), full_page=True)
        print(f"  截图: {OUTPUT_DIR}/deepal_home.png")

        # === 2. 新闻页 ===
        print("\n[2] 新闻页 - 交互式提取")
        page.goto("https://deepal.com.cn/news", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(5000)

        # 滚动加载更多
        for i in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)

        text_news = extract_text(page)
        corpus["pages"]["新闻资讯"] = {"url": "https://deepal.com.cn/news",
                                        "text": text_news}
        print(f"  提取: {len(text_news)} 字符")

        # 截图
        page.screenshot(path=str(OUTPUT_DIR / "deepal_news.png"), full_page=True)
        print(f"  截图: {OUTPUT_DIR}/deepal_news.png")

        # 提取链接
        links = extract_all_links(page)
        print(f"  链接: {len(links)}")
        for link in links[:15]:
            print(f"    [{link['type']:7s}] {link['text'][:60]} | {link.get('url', '')[:80]}")

        corpus["pages"]["新闻资讯"]["links"] = links

        # 保存页面 HTML 用于分析
        html = page.evaluate("() => document.body.innerHTML.substring(0, 5000)")
        corpus["pages"]["新闻资讯"]["html_snippet"] = html

        # === 3. 尝试逐一点击文章卡片 ===
        print("\n[3] 尝试点击文章链接获取详情...")
        article_texts = {}

        # 获取当前所有可见的文本元素
        for i in range(min(10, len(links))):
            link = links[i]
            if link["type"] != "a":
                continue

            current_url = link["url"]
            if not current_url.startswith("http"):
                continue

            # 跳过非文章链接
            if any(skip in current_url for skip in ["/news", "/car-series", "/configuration", "/brand", "/contact"]):
                if current_url in ("https://deepal.com.cn/news", "https://deepal.com.cn/"):
                    continue

            print(f"\n  [{i+1}] {link['text'][:60]}")
            print(f"      URL: {current_url[:100]}")

            try:
                page.goto(current_url, wait_until="networkidle", timeout=20000)
                page.wait_for_timeout(3000)

                text = extract_text(page)
                article_texts[current_url] = {
                    "title": link["text"],
                    "url": current_url,
                    "text": text,
                    "length": len(text),
                }
                print(f"      提取: {len(text)} 字符")
                print(f"      预览: {text[:200].replace(chr(10), ' ')}")
            except Exception as e:
                print(f"      错误: {e}")
                article_texts[current_url] = {"title": link["text"], "url": current_url, "error": str(e)}

        corpus["articles"] = article_texts

        browser.close()

    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, indent=2)

    print(f"\n\n完整语料: {OUTPUT_FILE}")
    print(f"\n总结:")
    print(f"  页面: {len(corpus['pages'])} 个")
    for name, pd in corpus["pages"].items():
        print(f"    {name}: {len(pd['text'])} 字符")
    print(f"  文章: {len(article_texts)} 篇")
    for url, at in article_texts.items():
        print(f"    {at.get('title', url)[:60]}: {at.get('length', at.get('error', ''))}")


if __name__ == "__main__":
    main()
