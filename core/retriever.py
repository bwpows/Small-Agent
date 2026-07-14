import requests
import math

# 🌟 核心修改：从配置文件中统一导入所有模型参数
from config.config import OLLAMA_BASE_URL, EMBEDDING_MODEL
from agents.registry import AGENT_ROSTER

_AGENT_VECTOR_CACHE = {} 

def get_embedding(text: str) -> list:
    """调用 Ollama 获取文本的向量表示"""
    url = f"{OLLAMA_BASE_URL}/api/embeddings"
    try:
        # 🌟 核心修改：使用配置文件中的 EMBEDDING_MODEL 变量
        res = requests.post(url, json={"model": EMBEDDING_MODEL, "prompt": text}, timeout=10)
        res.raise_for_status()
        return res.json().get("embedding", [])
    except Exception as e:
        print(f"⚠️ 向量化失败 (当前使用模型: {EMBEDDING_MODEL}): {e}")
        print("💡 提示：请确保你已在终端运行 `ollama pull {EMBEDDING_MODEL}`")
        return []
    
def cosine_similarity(v1: list, v2: list) -> float:
    """纯 Python 实现的余弦相似度计算 (零外部依赖)"""
    if not v1 or not v2: return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    return dot / (norm1 * norm2) if norm1 and norm2 else 0.0

def retrieve_top_agents(user_goal: str, top_k: int = 3) -> dict:
    """
    🔍 猎头机制：根据用户目标，通过向量检索捞出最合适的专家
    """
    global _AGENT_VECTOR_CACHE
    
    # 1. 启动时：初始化所有专家的向量缓存
    if not _AGENT_VECTOR_CACHE:
        print("🧠 [RAG] 正在初始化专家向量库缓存...")
        for role_id, info in AGENT_ROSTER.items():
            # 将“角色名 + 描述”组合起来生成向量，命中率更高
            text_to_embed = f"{role_id} {info['desc']}"
            _AGENT_VECTOR_CACHE[role_id] = get_embedding(text_to_embed)
            
    # 2. 将用户的目标向量化
    goal_vector = get_embedding(user_goal)
    if not goal_vector:
        # 如果模型崩了，兜底返回前几个
        return dict(list(AGENT_ROSTER.items())[:top_k])
        
    # 3. 计算相似度并排序
    scores = {}
    for role_id, vector in _AGENT_VECTOR_CACHE.items():
        scores[role_id] = cosine_similarity(goal_vector, vector)
        
    # 按得分从高到低排序，切片取 Top K
    sorted_roles = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)[:top_k]
    
    # 4. 组装中标名单
    matched_agents = {role: AGENT_ROSTER[role] for role in sorted_roles}
    
    print(f"🎯 [RAG] 智能检索完毕。匹配得分：")
    for r in sorted_roles:
        print(f"   - {r}: {scores[r]:.4f}")
        
    return matched_agents