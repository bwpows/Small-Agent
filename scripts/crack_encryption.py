#!/usr/bin/env python3
"""
深蓝官网 - 尝试在浏览器运行时解密 API 数据
利用 Playwright 的 page.evaluate() 调用页面自身的解密函数
"""

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "src" / "agent_engine" / "assets"
OUTPUT_FILE = OUTPUT_DIR / "deepal_decrypted_final.json"


def main():
    print("=" * 60)
    print("深蓝官网 - 运行时解密尝试")
    print("=" * 60)

    results = {"success": False, "method": "", "data": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        # 先加载首页让所有 JS 加载
        page.goto("https://deepal.com.cn/", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # ==========================================
        # 方法1: 用 page.route 拦截 API 响应，
        # 用 eval 调用页面内部的解密函数
        # ==========================================
        print("\n[方法1] page.route 拦截 + 页面内部解密...")

        captured_raw = []
        captured_decrypted = []

        def handle_route(route):
            url = route.request.url
            if "app-api.deepal.com.cn" in url:
                # 让请求通过但不立即响应
                pass
            route.continue_()

        page.route("**/app-api.deepal.com.cn/**", handle_route)

        # 重新导航触发 API 请求
        page.goto("https://deepal.com.cn/news", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(5000)

        page.unroute("**/app-api.deepal.com.cn/**")

        # ==========================================
        # 方法2: 搜索页面的加密/解密模块
        # ==========================================
        print("\n[方法2] 搜索 Webpack 模块中的加密函数...")

        webpack_modules = page.evaluate("""() => {
            // 在 Umi/Webpack 中，所有模块通常在全局 webpackChunk/__webpack_modules__ 中
            const results = {webpackFound: false, cryptoModules: []};
            
            // 尝试常见模式
            const possibleGlobals = [
                '__webpack_modules__',
                'webpackJsonp',
                'webpackChunk',
                '__webpack_require__',
                'webpackHotUpdate',
            ];
            
            for (const name of possibleGlobals) {
                try {
                    const v = eval('window.' + name);
                    if (v !== undefined) {
                        results.webpackFound = true;
                        results[name + '_type'] = typeof v;
                        if (name === '__webpack_modules__' && typeof v === 'object') {
                            // 搜索加密相关的模块
                            const keys = Object.keys(v);
                            results.totalModules = keys.length;
                            for (const key of keys) {
                                const mod = v[key];
                                const modStr = typeof mod === 'function' ? mod.toString().substring(0, 500) : String(mod).substring(0, 500);
                                if (modStr.includes('encrypt') || modStr.includes('decrypt') || 
                                    modStr.includes('encStr') || modStr.includes('AES') ||
                                    modStr.includes('cipher') || modStr.includes('Cipher') ||
                                    modStr.includes('Fn(') && modStr.includes('encStr')) {
                                    results.cryptoModules.push({
                                        key: key,
                                        preview: modStr.substring(0, 400)
                                    });
                                }
                            }
                        }
                    }
                } catch(e) {}
            }
            
            return results;
        }""")

        results["webpack"] = webpack_modules
        print(f"  Webpack 发现: {webpack_modules.get('webpackFound')}")
        print(f"  加密模块: {len(webpack_modules.get('cryptoModules', []))}")

        # ==========================================
        # 方法3: 使用 page.route 完全拦截，
        # 修改响应头让解密跳过
        # ==========================================
        print("\n[方法3] 修改响应头绕过加密...")

        bypass_results = []

        def bypass_route(route):
            url = route.request.url
            if "app-api.deepal.com.cn" not in url:
                route.continue_()
                return

            # 拦截响应
            response = route.fetch()
            body = response.text()

            # 尝试去掉 x-sl-ag-sf-72a1f3c8 头（让解密跳过）
            headers = dict(response.headers)
            headers.pop("x-sl-ag-sf-72a1f3c8", None)
            headers.pop("x-sl-ag-gf-1e3d5c7b", None)

            # 尝试：如果响应是 {"encStr": "..."}，提取 encStr 传给 decrypt
            try:
                data = json.loads(body)
                if isinstance(data, dict) and "encStr" in data:
                    bypass_results.append({
                        "url": url,
                        "has_encStr": True,
                        "encStr_len": len(data["encStr"]),
                    })
            except:
                pass

            route.fulfill(
                status=response.status,
                headers=headers,
                body=body,
            )

        page.route("**/app-api.deepal.com.cn/**", bypass_route)

        # 导航到新闻页
        page.goto("https://deepal.com.cn/news", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(5000)

        results["bypass"] = bypass_results
        print(f"  拦截到 {len(bypass_results)} 个加密响应")

        # ==========================================
        # 方法4: 直接 export 加密函数到 window 调用
        # ==========================================
        print("\n[方法4] 尝试暴露内部解密函数...")

        # 搜索 se() 和 Fn() 函数的位置
        func_info = page.evaluate("""() => {
            // 在 Umi 中，模块通常在 __webpack_modules__ 
            // 或者通过 webpackChunk 加载
            const code = document.querySelector('script[src*="umi"]');
            
            // 尝试找 webpackJsonp callback
            let results = {};
            
            // 搜索 window 上所有可能是加密相关的
            for (const key of Object.getOwnPropertyNames(window)) {
                if (key.length < 3) continue;
                try {
                    const val = window[key];
                    if (typeof val === 'function') {
                        const src = val.toString().substring(0, 300);
                        if (src.includes('encStr') || src.includes('decrypt') || 
                            src.includes('encryptBlock') || src.includes('createDecipheriv')) {
                            results[key] = {
                                type: 'function',
                                name: val.name || 'anonymous',
                                preview: src
                            };
                        }
                    }
                } catch(e) {}
            }
            
            return results;
        }""")

        results["exposed_functions"] = func_info
        for name, info in func_info.items():
            print(f"  找到: window.{name} ({info.get('type', '?')})")

        browser.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n完整结果: {OUTPUT_FILE}")

    # 总结
    print("\n" + "=" * 60)
    print("总结")
    print("=" * 60)
    print(f"  页面内加密函数: {len(func_info)} 个")
    print(f"  Webpack 模块: {'是' if webpack_modules.get('webpackFound') else '否'}")

    # 现在给出最终建议
    print("\n" + "=" * 60)
    print("关键结论")
    print("=" * 60)
    print("""
从 umi.1ae910b2.js 中发现的加密机制:
1. 请求加密: se(JSON.stringify(data)) → {encStr: ...}  或  Fn(key, data) → {encStr: ...}
2. 响应解密: Zn(response, {appType, key, baseAPI})
3. 加密模式: AES (从 encryptBlock/encryptBlockRaw 确认)
4. 关键请求头: x-sl-ag-sf-72a1f3c8 (控制是否解密)
    """)


if __name__ == "__main__":
    main()
