"""
数据模型 — SQLAlchemy ORM，9 张必备表。
启动时自动调用 create_all() 建表（SQLite）。
"""
import os
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean, DateTime,
    ForeignKey, UniqueConstraint, JSON, Float, event,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship
from app_server.config import DB_PATH


# ── 引擎 & Base ──
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},  # FastAPI 多线程
    echo=False,
)

# SQLite 兼容：默认启用外键约束
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Base(DeclarativeBase):
    pass


def get_session() -> Session:
    """获取一个新的数据库会话（调用方负责关闭）"""
    return Session(engine)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ═══════════════════════════════════════════
# 表 1: users — 用户账号
# ═══════════════════════════════════════════
class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    username      = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)   # IM 用户无密码
    display_name  = Column(String(128), nullable=True)   # 对外展示名
    avatar_url    = Column(String(512), nullable=True)
    source        = Column(String(32), nullable=False, default="web")  # web / feishu / telegram / qq
    union_id      = Column(String(128), nullable=True, index=True)     # 跨应用统一 ID
    role          = Column(String(16), nullable=False, default="user")  # user / admin
    is_active     = Column(Boolean, default=True, nullable=False)
    created_at    = Column(DateTime, default=utcnow, nullable=False)

    # 关系
    api_keys        = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    conversations   = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    traces          = relationship("Trace", back_populates="user", cascade="all, delete-orphan")
    identities      = relationship("UserIdentity", back_populates="user", cascade="all, delete-orphan")


# ═══════════════════════════════════════════
# 表 2: api_keys — API Key
# ═══════════════════════════════════════════
class ApiKey(Base):
    __tablename__ = "api_keys"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key_hash     = Column(String(255), unique=True, nullable=False, index=True)  # sha256(sk-xxx)
    name         = Column(String(64), nullable=False, default="default")
    last_used_at = Column(DateTime, nullable=True)
    revoked      = Column(Boolean, default=False, nullable=False)
    created_at   = Column(DateTime, default=utcnow, nullable=False)

    user = relationship("User", back_populates="api_keys")


# ═══════════════════════════════════════════
# 表 3: user_identities — 多渠道身份绑定
# ═══════════════════════════════════════════
class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("user_id", "channel", "platform_user_id", name="uq_uid_channel"),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    user_id           = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel           = Column(String(32), nullable=False)    # feishu / telegram / qq
    platform_user_id  = Column(String(128), nullable=False)   # 平台 open_id
    platform_union_id = Column(String(128), nullable=True)    # 跨应用 union_id
    created_at        = Column(DateTime, default=utcnow, nullable=False)

    user = relationship("User", back_populates="identities")


# ═══════════════════════════════════════════
# 表 4: conversations — 会话
# ═══════════════════════════════════════════
class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("user_id", "channel", "platform_chat_id",
                         name="uq_user_channel_chat"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    user_id         = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel         = Column(String(32), nullable=True)           # feishu / telegram / qq (web 端为 NULL)
    platform_chat_id = Column(String(128), nullable=True)         # 平台会话 ID（群/私聊）
    title           = Column(String(128), nullable=False, default="新会话")
    created_at      = Column(DateTime, default=utcnow, nullable=False)
    updated_at      = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    user     = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


# ═══════════════════════════════════════════
# 表 5: messages — 消息
# ═══════════════════════════════════════════
class Message(Base):
    __tablename__ = "messages"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id     = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role                = Column(String(16), nullable=False)   # user / assistant / tool
    content             = Column(Text, nullable=False)
    platform_message_id = Column(String(128), nullable=True, unique=True)  # 平台消息 ID，用于 webhook 幂等去重
    # ── 用量指标（仅 assistant 消息有意义）──
    prompt_tokens       = Column(Integer, nullable=True)
    completion_tokens   = Column(Integer, nullable=True)
    total_tokens        = Column(Integer, nullable=True)
    duration_ms         = Column(Integer, nullable=True)        # 引擎耗时（毫秒）
    thinking_count      = Column(Integer, nullable=True)        # 思考文本段数
    reasoning_text      = Column(Text, nullable=True)           # 思考过程全文
    created_at          = Column(DateTime, default=utcnow, nullable=False)

    conversation = relationship("Conversation", back_populates="messages")


# ═══════════════════════════════════════════
# 表 6: traces — 调用链追踪
# ═══════════════════════════════════════════
class Trace(Base):
    __tablename__ = "traces"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    user_id         = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    trace_id        = Column(String(64), nullable=False, index=True)
    session_id      = Column(String(64), nullable=True)
    phase           = Column(String(32), nullable=True)   # planning / execution
    duration_ms     = Column(Integer, nullable=True)
    span_count      = Column(Integer, nullable=True)
    error_count     = Column(Integer, default=0)
    created_at      = Column(DateTime, default=utcnow, nullable=False)

    user = relationship("User", back_populates="traces")


# ═══════════════════════════════════════════
# 表 7: user_drive_tokens — Google Drive 凭证（加密）
# ═══════════════════════════════════════════
class UserDriveToken(Base):
    __tablename__ = "user_drive_tokens"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    user_id         = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    encrypted_token = Column(Text, nullable=False)        # creds.to_json() AES 加密后
    iv              = Column(String(64), nullable=False)  # 加密向量
    status          = Column(String(16), default="active", nullable=False)
    created_at      = Column(DateTime, default=utcnow, nullable=False)
    refreshed_at    = Column(DateTime, nullable=True)


# ═══════════════════════════════════════════
# 表 8: drive_files — Drive 文件缓存
# ═══════════════════════════════════════════
class DriveFile(Base):
    __tablename__ = "drive_files"
    __table_args__ = (
        UniqueConstraint("user_id", "drive_file_id", name="uq_user_drive_file"),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    drive_file_id = Column(String(64), nullable=False)
    name         = Column(String(255), nullable=False)
    mime_type    = Column(String(64), nullable=True)
    updated_at   = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


# ═══════════════════════════════════════════
# 表 9: business_assets — 业务资产注册表
# ═══════════════════════════════════════════
class BusinessAsset(Base):
    __tablename__ = "business_assets"
    __table_args__ = (
        UniqueConstraint("user_id", "alias", name="uq_user_alias"),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    alias         = Column(String(128), nullable=False)
    type          = Column(String(32), nullable=False, default="google_sheet")
    drive_file_id = Column(String(64), nullable=True)
    columns       = Column(JSON, default=list)
    allowed_ops   = Column(JSON, default=lambda: ["read", "append", "update"])
    description   = Column(Text, default="")
    confirmed     = Column(Boolean, default=True)


# ═══════════════════════════════════════════
# 自动建表 — 通过 Alembic 迁移
# ═══════════════════════════════════════════
def init_db():
    """
    应用所有待执行的数据库迁移，确保数据库结构与模型定义同步。
    开发阶段：改模型后运行 `alembic revision --autogenerate -m "..."`
    然后 `alembic upgrade head`（或直接启动服务，自动 apply）。
    """
    import os, sys
    from pathlib import Path

    # 仓库根目录 = src/app_server/ 向上三级
    _repo_root = Path(__file__).resolve().parent.parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))

    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config(str(_repo_root / "alembic.ini"))
    # env.py 中会覆盖 sqlalchemy.url，这里确保路径一致
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")

    command.upgrade(alembic_cfg, "head")
