#!/usr/bin/env python3
"""分析深蓝官网 JS 中的加密/解密逻辑"""
import re
from playwright.sync_api import sync_playwright

FILES = [
    "https://deepal.com.cn/20260715149/umi.1ae910b2.js",
    "https://deepal.com.cn/20260715149/layouts__index.7edd6b4c.async.js",
]

KEYWORDS = [
    "encStr", "encrypt", "decrypt", "AES", "aes",
    "crypto.subtle", "createDecipheriv", "createCipheriv",
    "importKey", "decryptData", "encryptData", "decryptResponse",
    "encryptRequest", "atob(", "btoa(", "Base64",
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    # 先加载 deepal 页面（同源才能 fetch）
    page.goto("https://deepal.com.cn/", wait_until="domcontentloaded", timeout=20000)

    for url in FILES:
        name = url.split("/")[-1]
        print(f"\n{'='*60}")
        print(f"文件: {name}")
        print(f"{'='*60}")

        try:
            text = page.evaluate(
                "async (u) => { const r = await fetch(u); return await r.text(); }",
                url,
            )
            print(f"大小: {len(text):,} 字符")

            for kw in KEYWORDS:
                positions = []
                idx = 0
                ltext = text.lower()
                while True:
                    idx = ltext.find(kw.lower(), idx)
                    if idx == -1:
                        break
                    positions.append(idx)
                    idx += len(kw)

                if positions:
                    print(f"\n  [{kw}]: {len(positions)} 处")
                    for pos in positions[:3]:
                        start = max(0, pos - 60)
                        end = min(len(text), pos + 300)
                        snippet = text[start:end]
                        print(f"    [{pos}]: {snippet[:380]}")

        except Exception as e:
            print(f"  ERROR: {e}")

    browser.close()
    print("\n\n分析完成!")
