#!/usr/bin/env python3
"""
深蓝官网 API 接口探测脚本
使用 Playwright 无头浏览器打开各页面，拦截所有 XHR/fetch 请求，
找出真实数据接口（baseURL + 路径 + 参数 + 响应结构）。
"""

import json
import re
import os
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

# 输出文件
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "src" / "agent_engine" / "assets"
OUTPUT_FILE = OUTPUT_DIR / "deepal_api_results.json"

# 要探测的页面路径
PAGES_TO_VISIT = [
    {"name": "首页", "url": "https://deepal.com.cn/"},
    {"name": "新闻资讯", "url": "https://deepal.com.cn/news"},
    {"name": "车型系列", "url": "https://deepal.com.cn/car-series"},
    {"name": "车型配置", "url": "https://deepal.com.cn/configuration"},
    {"name": "关于深蓝", "url": "https://deepal.com.cn/about"},
    {"name": "联系我们", "url": "https://deepal.com.cn/contact"},
]

# 额外尝试的路由 chunk 文件
CHUNK_FILES = [
    "https://deepal.com.cn/20260715149/p__news__index.async.js",
    "https://deepal.com.cn/20260715149/p__car-series__index.async.js",
    "https://deepal.com.cn/20260715149/p__configuration__index.async.js",
]

# API 关键词用于过滤 chunk 中的噪音
API_KEYWORDS = ["api", "gateway", "cms", "news", "car", "model", "config", "article",
                "vehicle", "series", "product", "content", "data", "list", "detail",
                "query", "search", "graphql"]


def truncate_json(obj, max_items=3, max_str=200):
    """递归截断 JSON，仅保留少量样本"""
    if isinstance(obj, dict):
        t = {}
        for i, (k, v) in enumerate(obj.items()):
            if i >= max_items:
                t["..."] = f"[+{len(obj) - max_items} more keys]"
                break
            t[k] = truncate_json(v, max_items, max_str)
        return t
    elif isinstance(obj, list):
        if not obj:
            return []
        sample = [truncate_json(obj[0], max_items, max_str)]
        if len(obj) > 1:
            sample.append(f"[+{len(obj) - 1} more items]")
        return sample
    elif isinstance(obj, str) and len(obj) > max_str:
        return obj[:max_str] + "..."
    return obj


def extract_keys(obj, prefix=""):
    """提取 JSON 所有 key 路径"""
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            keys.add(path)
            if isinstance(v, dict):
                keys |= extract_keys(v, path)
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                keys |= extract_keys(v[0], f"{path}[0]")
    return sorted(keys)


def capture_page_apis(page, page_url: str, page_name: str) -> dict:
    """打开页面捕获所有 XHR/fetch 请求及响应"""
    captured = {}  # url -> info dict

    def on_response(response):
        req = response.request
        if req.resource_type not in ("xhr", "fetch"):
            return
        url = req.url
        try:
            body_text = response.text()
        except Exception:
            body_text = None

        info = {
            "url": url,
            "method": req.method,
            "resource_type": req.resource_type,
            "request_headers": dict(req.headers),
            "post_data": req.post_data if req.method in ("POST", "PUT", "PATCH") else None,
            "status": response.status,
            "response_headers": dict(response.headers),
        }

        if body_text and response.status < 400:
            try:
                body_json = json.loads(body_text)
                info["response_is_json"] = True
                info["response_sample"] = truncate_json(body_json)
                info["response_keys"] = extract_keys(body_json)
            except (json.JSONDecodeError, ValueError):
                info["response_is_json"] = False
                info["response_preview"] = body_text[:500]

        captured[url] = info

    page.on("response", on_response)

    try:
        print(f"  -> 加载: {page_url}")
        page.goto(page_url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)  # 等待懒加载

        # 滚动触发更多请求
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

    except Exception as e:
        print(f"    ⚠ 加载出错: {e}")

    page.remove_listener("response", on_response)
    return captured


def fetch_chunk_files(context) -> list[dict]:
    """下载路由 chunk JS 文件，搜索 API 地址"""
    results = []
    for url in CHUNK_FILES:
        page = context.new_page()
        try:
            print(f"  -> 抓取 chunk: {url}")
            resp = page.goto(url, timeout=15000)
            if resp and resp.status == 200:
                text = resp.text()
                api_urls = list(set(re.findall(
                    r'''["']([^"']*(?:api|gateway|cms|service)[^"']*)["']''',
                    text, re.IGNORECASE
                )))
                base_urls = list(set(re.findall(
                    r'''(?:baseURL|BASE_URL|apiHost|apiUrl|serviceUrl|gateway|requestUrl)\s*[:=]\s*["']([^"']+)["']''',
                    text, re.IGNORECASE
                )))
                path_patterns = list(set(re.findall(
                    r'''(?:get|post|put|delete|fetch|request)\s*\(\s*["']([^"']+)["']''',
                    text, re.IGNORECASE
                )))

                results.append({
                    "chunk_url": url,
                    "api_urls": api_urls[:30],
                    "base_urls": base_urls[:10],
                    "request_paths": path_patterns[:30],
                })
            page.close()
        except Exception as e:
            print(f"    ⚠ chunk 加载出错: {e}")
    return results


def main():
    print("=" * 60)
    print("深蓝官网 (deepal.com.cn) API 接口探测")
    print(f"时间: {datetime.now().isoformat()}")
    print("=" * 60)

    all_results = {
        "scan_time": datetime.now().isoformat(),
        "target": "deepal.com.cn",
        "pages": {},
        "chunks": [],
        "summary": {"total_api_requests": 0, "unique_api_urls": [], "by_domain": {}},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # ---- 阶段 1: 各页面捕获 API ----
        print("\n[阶段 1] 访问页面并捕获 API 请求\n")
        for pi in PAGES_TO_VISIT:
            print(f"--- {pi['name']} ---")
            captured = capture_page_apis(page, pi["url"], pi["name"])
            all_results["pages"][pi["name"]] = {
                "url": pi["url"],
                "api_requests": list(captured.values()),
                "count": len(captured),
            }
            print(f"    捕获到 {len(captured)} 个 API 响应\n")

        # ---- 阶段 2: chunk 文件分析 ----
        print("[阶段 2] 下载路由 chunk 文件搜索 API 地址\n")
        chunk_results = fetch_chunk_files(context)
        all_results["chunks"] = chunk_results

        browser.close()

    # ---- 汇总 ----
    print("\n[汇总] 分析结果\n")

    unique_urls = set()
    domain_map = {}

    for page_name, page_data in all_results["pages"].items():
        for req in page_data.get("api_requests", []):
            url = req.get("url", "")
            if not url:
                continue
            unique_urls.add(url)
            parsed = urlparse(url)
            domain_map.setdefault(parsed.netloc, [])
            if url not in domain_map[parsed.netloc]:
                domain_map[parsed.netloc].append(url)

    all_results["summary"]["total_api_requests"] = sum(
        d["count"] for d in all_results["pages"].values()
    )
    all_results["summary"]["unique_api_urls"] = sorted(unique_urls)
    all_results["summary"]["by_domain"] = {k: sorted(v) for k, v in domain_map.items()}

    print(f"  总共捕获: {all_results['summary']['total_api_requests']} 个 API 请求")
    print(f"  唯一 URL : {len(unique_urls)} 个")
    print(f"  涉及域名 : {list(domain_map.keys())}")
    print(f"  Chunk 分析: {len(chunk_results)} 个文件")

    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n完整结果: {OUTPUT_FILE}")

    # 打印接口列表
    print("\n" + "=" * 60)
    print("发现的接口列表:")
    print("=" * 60)
    for domain, urls in domain_map.items():
        print(f"\n  域名: {domain}")
        for url in urls:
            print(f"    {url}")

    # 打印样本
    print("\n" + "=" * 60)
    print("重要接口响应结构 (前3个有 JSON 响应的):")
    print("=" * 60)
    shown = 0
    for page_name, page_data in all_results["pages"].items():
        for req in page_data.get("api_requests", []):
            if req.get("response_is_json") and shown < 3:
                shown += 1
                print(f"\n  [{page_name}] {req['url']}")
                print(f"    方法: {req['method']}  状态: {req['status']}")
                print(f"    关键字段: {req.get('response_keys', [])[:15]}")
                print(f"    响应样本: {json.dumps(req.get('response_sample', {}), ensure_ascii=False, indent=6)[:500]}")
                print()

    # 打印 chunk 线索
    if chunk_results:
        print("\n" + "=" * 60)
        print("Chunk 文件中的接口线索:")
        print("=" * 60)
        for chunk in chunk_results:
            print(f"\n  {chunk['chunk_url']}")
            if chunk.get("base_urls"):
                print(f"    疑似 base_urls: {chunk['base_urls']}")
            if chunk.get("api_urls"):
                print(f"    疑似 api_urls (前10): {chunk['api_urls'][:10]}")
            rel_paths = [p for p in chunk.get("request_paths", [])
                         if any(kw in p.lower() for kw in API_KEYWORDS)]
            if rel_paths:
                print(f"    相关请求路径: {rel_paths[:20]}")

    print("\n✅ 探测完成!")


if __name__ == "__main__":
    main()
