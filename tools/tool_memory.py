# tools/tool_memory.py
from mem0 import Memory

from config.config import (
    LLM_PROVIDER, EMBED_PROVIDER,
    OLLAMA_MODEL, CLOUD_MODEL, CLOUD_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_API_KEY,
    EMBEDDING_MODEL, OPENAI_EMBED_MODEL, OPENAI_EMBED_API_KEY,
    COLLECTION_NAME, VECTOR_DIM, USER_ID,
)


def _build_mem0_config():
    """根据 LLM_PROVIDER + EMBED_PROVIDER 构建 mem0 配置。
    推理 LLM 和 Embeder 独立选择，例如：推理走 DeepSeek，嵌入走本地 Ollama。"""
    # ── LLM 配置 ──
    if LLM_PROVIDER == "ollama":
        llm_cfg = {"provider": "ollama", "config": {"model": OLLAMA_MODEL}}
    elif LLM_PROVIDER == "deepseek":
        llm_cfg = {"provider": "openai", "config": {"model": DEEPSEEK_MODEL, "api_key": DEEPSEEK_API_KEY, "api_base": "https://api.deepseek.com/v1"}}
    else:  # cloud
        llm_cfg = {"provider": "openai", "config": {"model": CLOUD_MODEL, "api_key": CLOUD_API_KEY}}

    # ── Embedder 配置 ──
    if EMBED_PROVIDER == "ollama":
        embed_cfg = {"provider": "ollama", "config": {"model": EMBEDDING_MODEL}}
    else:  # openai
        embed_cfg = {"provider": "openai", "config": {"model": OPENAI_EMBED_MODEL, "api_key": OPENAI_EMBED_API_KEY}}

    return {
        "llm": llm_cfg,
        "embedder": embed_cfg,
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": COLLECTION_NAME,
                "embedding_model_dims": VECTOR_DIM,
            },
        },
    }


class MemoryManager:
    def __init__(self):
        """初始化连接本地数据库"""
        mem0_config = _build_mem0_config()
        self.db = Memory.from_config(mem0_config)

    def add_memory(self, text):
        """写入记忆"""
        # ✅ 3. 擦除这里的 config. 前缀
        self.db.add(text, user_id=USER_ID)

    def search_memory(self, query):
        """检索并清洗记忆数据格式"""
        # ✅ 4. 擦除这里的 config. 前缀
        raw_memories = self.db.search(query, filters={"user_id": USER_ID})
        return self._safe_extract(raw_memories)

    def _safe_extract(self, raw_memories):
        """万能记忆解析器：处理各类异常数据结构"""
        extracted = []
        if not raw_memories: 
            return extracted
        
        if isinstance(raw_memories, dict):
            raw_memories = raw_memories.get('results', [raw_memories])
            
        if isinstance(raw_memories, list):
            for item in raw_memories:
                if isinstance(item, dict):
                    text = item.get('memory', item.get('text', str(item)))
                    extracted.append({'text': text, 'score': item.get('score', 'N/A')})
                elif isinstance(item, str):
                    extracted.append({'text': item, 'score': 'N/A'})
                elif hasattr(item, 'memory'):
                    extracted.append({'text': item.memory, 'score': getattr(item, 'score', 'N/A')})
        return extracted


# ========================================================
# 🌟 新增：包装函数 (作为大模型调用工具的"前台接待")
# ========================================================
def manage_memory(action, content):
    """供大模型调用的路由函数，内部实例化 MemoryManager 来干活"""
    try:
        manager = MemoryManager()
        
        if action == "save":
            manager.add_memory(content)
            return f"✅ 成功写入长期记忆: {content}"
            
        elif action == "query":
            results = manager.search_memory(content)
            if not results:
                return f"🔍 未找到关于『{content}』的相关记忆。"
                
            # 把提取出的结果格式化成好看的字符串
            result_str = "\n".join([f"- {r['text']} (匹配度: {r['score']})" for r in results])
            return f"🔍 找到以下记忆内容:\n{result_str}"
            
        else:
            return "❌ 未知的操作类型，仅支持 save 或 query。"
            
    except Exception as e:
        return f"❌ 记忆库操作异常: {str(e)}"


# ======= 动态路由注册声明 =======

REGISTER_NAME = "manage_memory"  # 👈 现在有了上面的函数，彻底对上了！

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "manage_memory",
        "description": "长期记忆管理工具。当用户要求你记住某件事，或者查询以前记录的特定偏好、信息时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["save", "query"], "description": "保存记忆或查询记忆"},
                "content": {"type": "string", "description": "要保存的具体记忆内容，或查询时的关键词"}
            },
            "required": ["action", "content"]
        }
    }
}