# env_config.py
import os

# 阻击代理冲突，确保直连本地 Ollama
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

# 关闭 Mem0 隐私埋点
os.environ["MEM0_TELEMETRY"] = "False"

# 强制使用 Hugging Face 国内镜像源下载模型
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"


# ================= 2. 邮箱自动推送机密配置 =================
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SENDER_EMAIL = "250447552@qq.com"       # 替换为你的真实 QQ 邮箱
AUTH_CODE = "myfpxnqceniedibb"  # 粘贴那串字母，注意不要有空格