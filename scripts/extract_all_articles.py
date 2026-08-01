#!/usr/bin/env python3
"""
深蓝官网 - 最终结构化内容提取
提取所有新闻文章 + 车型信息，结构化保存
"""

import json
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "src" / "agent_engine" / "assets"
OUTPUT_FILE = OUTPUT_DIR / "deepal_corpus_final.json"


def extract_structured_article(page) -> dict:
    """从文章详情页提取结构化数据"""
    return page.evaluate("""() => {
        const result = {title: '', date: '', content: '', url: window.location.href};
        
        // 1. 标题 - 优先 h1，然后找页面中字号最大的可见文本
        const h1 = document.querySelector('h1');
        if (h1) {
            result.title = h1.textContent.trim();
        } else {
            // 找字号最大的文本
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
        
        // 2. 日期 - 找时间戳或日期格式文本
        const timeEl = document.querySelector('time, [class*="time"], [class*="date"], [class*="publish"]');
        if (timeEl) {
            result.date = timeEl.textContent.trim();
        } else {
            // 从文本中找日期格式
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
            let node;
            while (node = walker.nextNode()) {
                const text = node.textContent.trim();
                if (/\\d{4}-\\d{2}-\\d{2}/.test(text)) {
                    result.date = text.match(/\\d{4}-\\d{2}-\\d{2}/)[0];
                    break;
                }
            }
        }
        
        // 3. 正文 - 提取所有段落，排除导航和页脚
        const excludeTags = ['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'IFRAME', 'NAV', 'HEADER', 'FOOTER', 'ASIDE'];
        const excludeClasses = ['nav', 'footer', 'bottom', 'menu', 'sidebar', 'privacy', 'copyright', 
                                'contact', 'social', 'qr', 'share', 'scan', 'banner', 'header'];
        
        const lines = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while (node = walker.nextNode()) {
            const text = node.textContent.trim();
            if (!text || text.length < 3) continue;
            
            const parent = node.parentElement;
            if (!parent) continue;
            
            const tag = parent.tagName;
            if (excludeTags.includes(tag)) continue;
            
            const cls = (parent.className || '').toLowerCase();
            if (excludeClasses.some(c => cls.includes(c))) continue;
            
            const style = window.getComputedStyle(parent);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            
            // 排除页脚相关文字
            if (text.includes('Copyright') || text.includes('版权所有') || 
                text.includes('渝ICP') || text.includes('公网安备') ||
                text.includes('隐私政策') || text.includes('管家中心') ||
                text.includes('951998') || text.includes('打开抖音') ||
                text.includes('打开微信') || text.includes('扫一扫') ||
                text.includes('投诉电话')) continue;
            
            // 排除导航文字
            if (['车系', '品牌', '资讯', '门店', '招商加盟', '预约体验',
                 '首页', '新闻', '关于我们', '联系我们', '服务', '产品'].includes(text)) continue;
            
            lines.push(text);
        }
        
        result.content = lines.join('\\n');
        return result;
    }""")


def extract_car_models(page) -> list[dict]:
    """从车型页提取车型信息"""
    return page.evaluate("""() => {
        const models = [];
        
        // 寻找包含车型名称和描述的卡片/区块
        const cards = document.querySelectorAll('div, article, section, [class*="card"], [class*="model"]');
        for (const card of cards) {
            const text = card.textContent.trim();
            if (text.length < 20) continue;
            
            // 找车型名称（如 S07, S05, L07, L06 等）
            const modelMatch = text.match(/深蓝[SL]\\d{2,3}|S\\d{2,3}|L\\d{2,3}|C\\d{2,3}/);
            if (!modelMatch) continue;
            
            const modelName = modelMatch[0];
            
            // 提取该卡片的主要文本
            const paragraphs = card.querySelectorAll('p, h2, h3, h4, span, div');
            const lines = [];
            for (const p of paragraphs) {
                const t = p.textContent.trim();
                if (t.length > 5 && t.length < 500) {
                    lines.push(t);
                }
            }
            
            models.push({
                model: modelName,
                text: lines.join('\\n'),
                length: lines.join('\\n').length,
            });
        }
        
        // 去重
        const seen = new Set();
        return models.filter(m => {
            if (seen.has(m.model)) return false;
            seen.add(m.model);
            return m.length > 20;
        });
    }""")


def main():
    print("=" * 60)
    print("深蓝官网 - 全面语料提取 v2")
    print("=" * 60)

    corpus = {
        "source": "deepal.com.cn",
        "extracted_at": datetime.now().isoformat(),
        "articles": [],
        "car_models": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 4000})
        page = context.new_page()

        # === 新闻列表 - 先提取所有卡片信息和 URL ===
        print("\n[1] 加载新闻列表...")
        page.goto("https://deepal.com.cn/news", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # 滚动加载更多
        for _ in range(5):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)

        # 提取所有可见卡片
        cards = page.evaluate("""() => {
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
            // 去重
            const seen = new Set();
            return cards.filter(c => {
                const key = c.text.substring(0, 50);
                if (seen.has(key)) return false;
                seen.add(key);
                return true;
            });
        }""")
        print(f"  发现 {len(cards)} 个卡片")

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
                    print(f"  [{len(article_urls):2d}] {card['text'][:60]} → {url}")
            except Exception as e:
                print(f"  ⚠ 点击失败: {e}")

        # 去重 URL
        seen_urls = set()
        unique_urls = []
        for u in article_urls:
            if u["url"] not in seen_urls:
                seen_urls.add(u["url"])
                unique_urls.append(u)

        print(f"\n  共 {len(unique_urls)} 个唯一文章链接")

        # === 提取文章详情 ===
        print(f"\n[2] 提取 {len(unique_urls)} 篇文章详情...")
        for i, article in enumerate(unique_urls):
            print(f"\n  [{i+1}/{len(unique_urls)}] {article['title'][:60]}")
            try:
                page.goto(article["url"], wait_until="networkidle", timeout=20000)
                page.wait_for_timeout(3000)

                data = extract_structured_article(page)
                data["source_url"] = article["url"]
                data["card_title"] = article["title"]
                data["id"] = article["url"].split("id=")[-1] if "id=" in article["url"] else ""

                corpus["articles"].append(data)
                print(f"      标题: {data['title'][:60]}")
                print(f"      日期: {data['date']}")
                print(f"      内容: {len(data['content'])} 字符")

            except Exception as e:
                print(f"      错误: {e}")
                corpus["articles"].append({
                    "source_url": article["url"],
                    "card_title": article["title"],
                    "error": str(e),
                })

        # === 提取车型信息 ===
        print("\n[3] 提取车型系列信息...")
        page.goto("https://deepal.com.cn/car-series", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

        models = extract_car_models(page)
        corpus["car_models"] = models
        print(f"  发现 {len(models)} 个车型:")
        for m in models:
            print(f"    {m['model']}: {m['length']} 字符")
            print(f"      {m['text'][:200]}")

        browser.close()

    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, indent=2)

    # 统计
    total = len(corpus["articles"])
    long_articles = [a for a in corpus["articles"] if len(a.get("content", "")) > 1000]
    medium_articles = [a for a in corpus["articles"] if 100 <= len(a.get("content", "")) <= 1000]
    short_articles = [a for a in corpus["articles"] if 0 < len(a.get("content", "")) < 100]

    print(f"\n{'='*60}")
    print("统计")
    print(f"{'='*60}")
    print(f"  文章: {total}")
    print(f"  长文 (>1000字): {len(long_articles)}")
    print(f"  中篇 (100-1000字): {len(medium_articles)}")
    print(f"  短文 (<100字): {len(short_articles)}")
    print(f"  车型: {len(models)}")

    print(f"\n{'='*60}")
    print("长文章列表")
    print(f"{'='*60}")
    for a in long_articles:
        print(f"  - {a['title'][:60]} ({a['date']}) - {len(a['content'])} 字")

    print(f"\n结果: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
