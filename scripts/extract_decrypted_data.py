#!/usr/bin/env python3
"""
深蓝官网 API 解密数据提取
方案：利用 Playwright 在浏览器运行时注入钩子，
拦截已解密的前端数据（绕过加密问题）。
同时尝试提取前端加密/解密相关代码。
"""

import json
import re
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "src" / "agent_engine" / "assets"
OUTPUT_FILE = OUTPUT_DIR / "deepal_decrypted_data.json"

PAGES_TO_VISIT = [
    {"name": "首页", "url": "https://deepal.com.cn/"},
    {"name": "新闻资讯", "url": "https://deepal.com.cn/news"},
    {"name": "车型系列", "url": "https://deepal.com.cn/car-series"},
]


def main():
    print("=" * 60)
    print("深蓝官网 - 解密数据提取")
    print("=" * 60)

    results = {
        "scan_time": datetime.now().isoformat(),
        "decrypted_apis": {},
        "page_text": {},
        "encryption_clues": {},
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

        # === 方法1: 拦截已解密的数据 ===
        decrypted_responses = []

        def on_response(response):
            """尝试从 response 中获取已解密的数据"""
            url = response.url
            if "app-api.deepal.com.cn" not in url:
                return
            req = response.request
            if req.resource_type not in ("xhr", "fetch"):
                return

            try:
                # 先在浏览器里执行：检查是否有全局存储的解密后数据
                pass
            except:
                pass

            # 记录请求信息
            info = {
                "url": url,
                "method": req.method,
                "status": response.status,
                "response_headers": dict(response.headers),
            }
            try:
                raw = response.text()
                info["raw_body_preview"] = raw[:300]
                # 检查是否仍然是加密的
                if raw.startswith('{"encStr":'):
                    info["is_encrypted"] = True
                else:
                    info["is_encrypted"] = False
                    info["raw_body_preview"] = raw[:1000]
            except Exception as e:
                info["body_error"] = str(e)

            decrypted_responses.append(info)

        page.on("response", on_response)

        # 收集页面渲染后的文本和加密逻辑
        for pi in PAGES_TO_VISIT:
            name = pi["name"]
            url = pi["url"]
            print(f"\n--- {name}: {url} ---")

            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(4000)

                # 滚动触发更多加载
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(1000)

                # 方法A: 提取页面可见文本
                visible_text = page.evaluate("""() => {
                    // 获取 body 中的所有文本内容
                    function getVisibleText(el) {
                        let text = '';
                        for (let child of el.childNodes) {
                            if (child.nodeType === 3) { // Text node
                                text += child.textContent.trim() + ' ';
                            } else if (child.nodeType === 1) { // Element node
                                const style = window.getComputedStyle(child);
                                if (style.display !== 'none' && style.visibility !== 'hidden') {
                                    text += getVisibleText(child);
                                }
                            }
                        }
                        return text;
                    }
                    return getVisibleText(document.body).substring(0, 5000);
                }""")
                results["page_text"][name] = visible_text[:5000]
                print(f"  -> 可见文本长度: {len(visible_text)} 字符")
                print(f"  -> 文本预览: {visible_text[:300]}...")

                # 方法B: 尝试提取 Vue/React 组件数据
                component_data = page.evaluate("""() => {
                    try {
                        // 尝试从 Vue 实例获取数据
                        const app = document.querySelector('#root');
                        if (app && app.__vue_app__) {
                            return {type: 'vue', data: 'found vue app'};
                        }
                        // 尝试从 React fiber 获取数据
                        const rootEl = document.getElementById('root');
                        if (rootEl) {
                            const fiberKey = Object.keys(rootEl).find(k => k.startsWith('__reactFiber'));
                            if (fiberKey) {
                                return {type: 'react', found: true};
                            }
                        }
                    } catch(e) {}
                    return {type: 'unknown'};
                }""")
                results["encryption_clues"][name] = {"component_data": component_data}

                # 方法C: 搜索 window 上的解密函数或全局数据
                window_data = page.evaluate("""() => {
                    const keys = Object.keys(window).filter(k => {
                        return k.includes('enc') || k.includes('decrypt') ||
                               k.includes('crypto') || k.includes('aes') ||
                               k.includes('api') || k.includes('config') ||
                               k.includes('store') || k.includes('state');
                    });
                    const result = {};
                    for (let k of keys.slice(0, 30)) {
                        try {
                            const v = window[k];
                            if (typeof v === 'string') result[k] = v.substring(0, 200);
                            else if (typeof v === 'object') result[k] = '[object]';
                            else result[k] = typeof v;
                        } catch(e) {}
                    }
                    return result;
                }""")
                results["encryption_clues"][name]["window_keys"] = window_data
                print(f"  -> window 关键 key: {list(window_data.keys())}")

            except Exception as e:
                print(f"  ⚠ 页面错误: {e}")

        page.remove_listener("response", on_response)

        # 记录所有加密响应
        results["decrypted_apis"]["all_responses"] = decrypted_responses

        # === 方法2: 搜索 JS 源代码中的加密函数 ===
        print("\n[搜索] 在所有 JS 资源中搜索加密/解密逻辑...")
        encryption_code = page.evaluate("""() => {
            const scripts = Array.from(document.querySelectorAll('script[src]'));
            return {
                total_scripts: scripts.length,
                script_srcs: scripts.map(s => s.src).slice(0, 20)
            };
        }""")
        results["encryption_clues"]["script_info"] = encryption_code

        # 方法3: 尝试在浏览器中拦截 fetch/XHR 并捕获解密后数据
        print("\n[注入] 注入 XHR/fetch 拦截器捕获解密后数据...")
        intercepted = page.evaluate("""() => {
            return new Promise((resolve) => {
                const captured = [];
                const done = {};
                
                // 劫持 Response.json()
                const origJson = Response.prototype.json;
                Response.prototype.json = function() {
                    const promise = origJson.call(this);
                    return promise.then(data => {
                        if (this.url && this.url.includes('app-api.deepal.com.cn')) {
                            captured.push({
                                url: this.url,
                                status: this.status,
                                data_preview: JSON.stringify(data).substring(0, 1000)
                            });
                        }
                        return data;
                    });
                };
                
                // 劫持 XMLHttpRequest
                const origOpen = XMLHttpRequest.prototype.open;
                const origSend = XMLHttpRequest.prototype.send;
                XMLHttpRequest.prototype.open = function(method, url) {
                    this._url = url;
                    this._method = method;
                    return origOpen.apply(this, arguments);
                };
                XMLHttpRequest.prototype.send = function() {
                    this.addEventListener('load', function() {
                        if (this._url && this._url.includes('app-api.deepal.com.cn')) {
                            try {
                                const data = JSON.parse(this.responseText);
                                captured.push({
                                    url: this._url,
                                    status: this.status,
                                    data_preview: JSON.stringify(data).substring(0, 1000)
                                });
                            } catch(e) {}
                        }
                    });
                    return origSend.apply(this, arguments);
                };
                
                // 等待一会收集数据
                setTimeout(() => {
                    Response.prototype.json = origJson;
                    resolve(captured);
                }, 5000);
            });
        }""")
        results["decrypted_apis"]["intercepted"] = intercepted
        print(f"  -> 拦截到 {len(intercepted)} 条数据")

        # 分析拦截结果
        for item in intercepted:
            print(f"  -> URL: {item.get('url', '')}")
            preview = item.get('data_preview', '')
            if '"encStr"' in preview:
                print(f"     ⚠ 仍加密: {preview[:150]}...")
            else:
                print(f"     ✅ 已解密: {preview[:300]}...")

        browser.close()

    # 保存结果
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n完整结果: {OUTPUT_FILE}")

    # 总结
    print("\n" + "=" * 60)
    print("总结")
    print("=" * 60)
    for name, text in results["page_text"].items():
        print(f"\n{name}: 提取到 {len(text)} 字符可见文本")

    has_decrypted = any(
        '"encStr"' not in item.get('data_preview', '{}')
        for item in intercepted
    )
    if has_decrypted:
        print("\n✅ 成功获取解密后数据！")
    else:
        print("\n⚠ 所有数据仍加密，需要深入分析 JS 解密逻辑")


if __name__ == "__main__":
    main()
