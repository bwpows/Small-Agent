#!/usr/bin/env python3
"""
深蓝业务验证脚本：抓取 → 建库 → 检索
一键验证 T1-T3 链路是否通。
"""

import sys
import os

# 将 src 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_engine.business.business_layer import get_business_layer, BusinessNotFoundError
from agent_engine.business.asset_registry import get_registry, BusinessAsset


def main():
    print("=" * 60)
    print("深蓝业务验证：T1(模型) → T2(爬虫) → T3(向量库)")
    print("=" * 60)

    # ── T1: 注册深蓝业务 ──
    print("\n[1] T1: 注册 '深蓝' 业务资产...")
    registry = get_registry()
    layer = get_business_layer()

    # 如果已存在先删除
    existing = registry.get("深蓝")
    if existing:
        registry.remove("深蓝")
        print("  已删除旧的 '深蓝' 业务")

    asset = BusinessAsset(
        alias="深蓝",
        type="web_corpus",
        description="深蓝汽车官网新闻资讯与车型信息（deepal.com.cn）",
        crawler_config={
            "start_urls": ["https://deepal.com.cn/news", "https://deepal.com.cn/car-series"],
            "article_pattern": "/policy?id=",
        },
        vector_ns="深蓝",
        allowed_ops=["read", "crawl", "retrieve"],
    )
    registry.register(asset)
    print(f"  ✅ 已注册: alias={asset.alias}, type={asset.type}, vector_ns={asset.vector_ns}")

    # ── T2: 抓取内容 ──
    print("\n[2] T2: 抓取深蓝官网内容...")
    try:
        result = layer.crawl("深蓝")
        print(f"  ✅ {result}")
    except Exception as e:
        print(f"  ❌ 抓取失败: {e}")
        return 1

    # ── T3: 向量检索 ──
    print("\n[3] T3: 向量检索测试...")
    from agent_engine.business import business_vector_store

    # 检查库状态
    ns = asset.vector_ns
    count = business_vector_store.count(ns)
    print(f"  向量库 '{ns}' 已有 {count} 条数据")

    if count == 0:
        print("  ⚠️ 向量库为空，无法检索")
        return 1

    test_queries = [
        "深蓝S07最新消息",
        "L3自动驾驶",
        "深蓝L06预售价格",
        "深蓝汽车销量",
    ]

    for q in test_queries:
        print(f"\n  查询: '{q}'")
        hits = layer.retrieve("深蓝", q, top_k=3)
        if hits:
            for i, h in enumerate(hits, 1):
                preview = h["chunk"].replace("\n", " ")[:120]
                print(f"    [{i}] score={h['score']:.4f} | {h['title'][:30]}")
                print(f"        {preview}...")
        else:
            print("    (无命中)")

    print("\n" + "=" * 60)
    print("✅ 验证完成！深蓝业务链路已通")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
