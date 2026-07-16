# # config.py

# ── HuggingFace 加速（国内环境） ──
# fastembed / mem0 底层需要从 HF 下载模型，设置镜像避免卡死
import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# 大模型 API 设置
OLLAMA_BASE_URL = "http://localhost:11434"
# LLM_MODEL = "llama3.1:8b"  # 👈 暂且换成这个小模型测试
LLM_MODEL = "qwen3-coder:30b"  # 换成你实际在跑的模型名（如 qwen3-coder:30b）

# 记忆向量库设置
EMBEDDING_MODEL = "nomic-embed-text"
VECTOR_DIM = 768
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