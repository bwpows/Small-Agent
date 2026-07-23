"""
app_server 层配置 — 独立于 agent_engine/config.py，只管理服务相关参数。
"""
import os
from dotenv import load_dotenv

# 加载 .env 文件（从仓库根目录）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(_REPO_ROOT, ".env"))


# ── 数据库 ──
DB_PATH = os.path.join(_REPO_ROOT, "data", "app.db")

# ── JWT / Session ──
JWT_SECRET       = os.getenv("JWT_SECRET", "change-me-in-production-please")
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_HOURS = 24

# ── API Key ──
API_KEY_PREFIX = "sk-"
API_KEY_BYTES  = 32  # 生成 Key 时的随机字节数

# ── Token 加密（用于 user_drive_tokens 等敏感字段） ──
TOKEN_ENCRYPTION_KEY = os.getenv(
    "TOKEN_ENCRYPTION_KEY",
    "change-me-to-a-random-32-byte-string!!"
)

# ── 沙箱工作目录 ──
WORKSPACE_DIR = os.path.join(_REPO_ROOT, "data", "workspace")

# ── 限流 ──
RATE_LIMIT_PER_KEY  = 10   # 每 Key 每分钟最大请求数
RATE_LIMIT_WINDOW   = 60   # 窗口秒数

# ── 飞书 ──
FEISHU_APP_ID       = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET   = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_VERIFY_TOKEN = os.getenv("FEISHU_VERIFY_TOKEN", "")
FEISHU_ENCRYPT_KEY  = os.getenv("FEISHU_ENCRYPT_KEY", "")   # 可选，飞书「事件订阅」加密 key
FEISHU_BASE_URL     = "https://open.feishu.cn/open-apis"

# ── 服务基础地址（用于 OAuth 回调） ──
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000")

# ── Google OAuth（Drive 授权，已废弃，保留兼容） ──
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

# ── Google OAuth 登录（OpenID Connect，Web application 类型） ──
GOOGLE_LOGIN_CLIENT_ID     = os.getenv("GOOGLE_LOGIN_CLIENT_ID", "")
GOOGLE_LOGIN_CLIENT_SECRET = os.getenv("GOOGLE_LOGIN_CLIENT_SECRET", "")

# ── Google Service Account（Drive 公共访问，推荐） ──
# 可通过环境变量 GOOGLE_SERVICE_ACCOUNT_JSON 直接传入 JSON 字符串
# 或 GOOGLE_SERVICE_ACCOUNT_FILE 指定 Service Account JSON 文件路径
# 也支持默认路径 data/workspace/service_account.json
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")

# 前端地址（OAuth 回调后跳转用，默认开发端口 3000）
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
