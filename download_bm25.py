#!/usr/bin/env python3
"""预下载 fastembed 所需的 Qdrant/bm25 模型（通过 HF 镜像加速）"""
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

print("🔄 正在从 hf-mirror.com 下载 Qdrant/bm25 模型...")
print("   (首次大约需要几秒到一分钟，取决于网速)\n")

try:
    from fastembed import SparseTextEmbedding
    model = SparseTextEmbedding(model_name="Qdrant/bm25")
    # 触发模型加载（真正下载）
    embeddings = list(model.embed(["测试"]))
    print(f"\n✅ 模型下载并加载成功！向量维度: {len(embeddings[0].values)}")
    print("   现在启动 Streamlit 不会再卡住了。")
except Exception as e:
    print(f"\n❌ 下载失败: {e}")
    print("   可能的原因：")
    print("   1. 网络不通 — 尝试改用 VPN 或代理")
    print("   2. 镜像挂了 — 换成 os.environ['HF_ENDPOINT'] = 'https://huggingface.co'")
