# # config.py

# ── .env 文件加载（安全注入 API key，不写死到代码里）──
from dotenv import load_dotenv
load_dotenv()

# ── HuggingFace 加速（国内环境） ──
# fastembed / mem0 底层需要从 HF 下载模型，设置镜像避免卡死
import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# ===== LLM 后端开关（三选一）=====
LLM_PROVIDER = "deepseek"          # "ollama" | "cloud" | "deepseek"

# 本地 Ollama（走 OpenAI 兼容端点 /v1）
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "qwen3-coder:30b"

# 通用云端（OpenAI / Kimi / 硅基流动 / 任何 OpenAI 兼容 API）
CLOUD_BASE_URL = "https://api.openai.com/v1"
CLOUD_API_KEY  = os.getenv("LLM_API_KEY", "")     # 从环境变量注入，不要写死 key
CLOUD_MODEL    = "gpt-4o-mini"

# DeepSeek（独立配置，base_url 固定，只需设 API key）
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL    = "deepseek-v4-flash"   # "deepseek-v4-flash"(快) 或 "deepseek-v4-pro"(强)、旧名 deepseek-chat 将于 2026-07-24 停用

# 同步到环境变量，供 mem0 等第三方库透明读取
if CLOUD_API_KEY:
    os.environ.setdefault("OPENAI_API_KEY", CLOUD_API_KEY)

# 向后兼容别名（按 LLM_PROVIDER 动态指向当前生效的模型名）
_MODEL_MAP = {
    "ollama": OLLAMA_MODEL,
    "cloud": CLOUD_MODEL,
    "deepseek": DEEPSEEK_MODEL,
}
LLM_MODEL = _MODEL_MAP.get(LLM_PROVIDER, OLLAMA_MODEL)

# ===== 嵌入后端（独立于推理）=====
EMBED_PROVIDER = "siliconflow"   # "ollama" | "openai" | "siliconflow"

# 本地 Ollama 嵌入
EMBEDDING_MODEL = "nomic-embed-text"

# OpenAI 嵌入（当 EMBED_PROVIDER="openai" 时生效，需设置 OPENAI_API_KEY）
OPENAI_EMBED_MODEL = "text-embedding-3-small"
OPENAI_EMBED_API_KEY = os.getenv("OPENAI_API_KEY", os.getenv("LLM_API_KEY", ""))

# 硅基流动嵌入（永久免费 BGE 模型，国内直连，OpenAI 兼容协议）
SILICONFLOW_EMBED_BASE_URL = "https://api.siliconflow.cn/v1"
SILICONFLOW_EMBED_API_KEY  = os.getenv("SILICONFLOW_API_KEY", "")  # 注册 siliconflow.cn 获取
SILICONFLOW_EMBED_MODEL    = "BAAI/bge-large-zh-v1.5"             # 1024 维中文向量，免费

# 向量维度：根据 EMBED_PROVIDER 自适应（⚠️ 切换嵌入源后需重建向量库）
_VECTOR_DIM_MAP = {"ollama": 768, "openai": 1536, "siliconflow": 1024}
VECTOR_DIM = _VECTOR_DIM_MAP.get(EMBED_PROVIDER, 768)
COLLECTION_NAME = "my_new_memory"
USER_ID = "local_master"

# ================= 沙箱安全配置 =================
# 沙箱级别: "strict" | "moderate" | "relaxed"
#   strict:   仅安全模块 + 严格资源限制 + 禁止网络/文件系统越权
#   moderate: 允许常用模块 + 中等资源限制 (默认推荐)
#   relaxed:  仅超时保护 (开发调试用)
SANDBOX_LEVEL = "moderate"

# 沙箱审计日志开关 (建议生产环境开启)
SANDBOX_AUDIT_ENABLED = True

# 网络域名黑名单 (搜索结果自动过滤)
NETWORK_BANNED_DOMAINS = []

# 文件扩展名白名单 (仅允许这些类型写入磁盘)
ALLOWED_FILE_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".html", ".xml",
    ".py", ".log", ".yaml", ".yml", ".toml", ".cfg", ".ini",
}

# ================= 调用链追踪配置 =================
# 是否启用 Tracing（关闭后零开销）
TRACE_ENABLED = True

# 追踪数据存储目录（JSONL 文件，按天分片）
TRACE_STORAGE_DIR = "agent_workspace/.traces"

# 内存环形缓冲最大条数（供 UI 实时查看）
TRACE_MAX_IN_MEMORY = 50