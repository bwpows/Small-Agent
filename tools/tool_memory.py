# tools/tool_memory.py
from mem0 import Memory

# ✅ 1. 明确地从 config/config.py 中把所有需要的变量一次性全部拔出来
from config.config import (
    LLM_MODEL, 
    EMBEDDING_MODEL, 
    COLLECTION_NAME, 
    VECTOR_DIM, 
    USER_ID
)

class MemoryManager:
    def __init__(self):
        """初始化连接本地数据库"""
        mem0_config = {
            # ✅ 2. 彻底去掉所有 config. 前缀，直接使用上面导入的纯变量名
            "llm": {"provider": "ollama", "config": {"model": LLM_MODEL}},
            "embedder": {"provider": "ollama", "config": {"model": EMBEDDING_MODEL}},
            "vector_store": {
                "provider": "qdrant", 
                "config": {
                    "collection_name": COLLECTION_NAME, 
                    "embedding_model_dims": VECTOR_DIM
                }
            }
        }
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