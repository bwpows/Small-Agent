import math
import logging

from agent_engine.llm_client import get_embedding_client
from agent_engine.agents.registry import AGENT_ROSTER

logger = logging.getLogger("retriever")

_AGENT_VECTOR_CACHE = {} 

def get_embedding(text: str) -> list:
    """调用嵌入服务获取文本的向量表示（自动适配 本地 Ollama / 云端 OpenAI）

    失败则抛出异常（不再静默返回空列表），便于上层 upsert 感知并重试/跳过。
    """
    client, model_name = get_embedding_client()
    response = client.embeddings.create(model=model_name, input=text)
    return response.data[0].embedding
    
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
        logger.info("[RAG] 正在初始化专家向量库缓存...")
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
    
    logger.info(f"[RAG] 智能检索完毕，命中 Top{top_k}：{', '.join(sorted_roles)}")
    for r in sorted_roles:
        logger.debug(f"   - {r}: {scores[r]:.4f}")
        
    return matched_agents