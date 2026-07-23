"""
鉴权系统 — 注册 / 登录 / API Key 管理 / Bearer 校验 / Google Drive OAuth。
密码用 bcrypt 哈希；API Key 只存 sha256 哈希；JWT 做会话管理。
Drive Token 用 AES-256-CBC 加密存储。
"""
import hashlib
import secrets
import base64
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import bcrypt
import jwt
from sqlalchemy.orm import Session
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from app_server.config import (
    JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS,
    API_KEY_PREFIX, API_KEY_BYTES,
    TOKEN_ENCRYPTION_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
)
from app_server.db import User, ApiKey, UserIdentity, utcnow


# ═══════════════════════════════════════════
# 密码工具
# ═══════════════════════════════════════════
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ═══════════════════════════════════════════
# JWT
# ═══════════════════════════════════════════
def create_jwt(user_id: int, username: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ═══════════════════════════════════════════
# API Key 工具
# ═══════════════════════════════════════════
def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    """生成 sk- 前缀的随机 Key"""
    raw = secrets.token_hex(API_KEY_BYTES)
    return f"{API_KEY_PREFIX}{raw}"


def create_api_key(session: Session, user_id: int, name: str = "default") -> Tuple[ApiKey, str]:
    """在数据库创建一条 ApiKey 记录，返回 (db_obj, 明文key)。
    明文 key 只在此处返回，调用方必须转交给用户。"""
    raw_key = generate_api_key()
    key_hash = _hash_key(raw_key)
    api_key = ApiKey(
        user_id=user_id,
        key_hash=key_hash,
        name=name,
    )
    session.add(api_key)
    session.commit()
    session.refresh(api_key)
    return api_key, raw_key


def resolve_api_key(session: Session, raw_key: str) -> Optional[ApiKey]:
    """Bearer token → ApiKey 对象（未吊销且用户激活才返回）"""
    key_hash = _hash_key(raw_key)
    key = (
        session.query(ApiKey)
        .filter(ApiKey.key_hash == key_hash, ApiKey.revoked == False)
        .first()
    )
    if key is None:
        return None
    # 检查关联用户是否活跃
    user = session.get(User, key.user_id)
    if user is None or not user.is_active:
        return None
    # 更新最后使用时间
    key.last_used_at = utcnow()
    session.commit()
    return key


# ═══════════════════════════════════════════
# 注册 / 登录
# ═══════════════════════════════════════════
def register_user(session: Session, username: str, password: str) -> User:
    existing = session.query(User).filter(User.username == username).first()
    if existing:
        raise ValueError(f"用户名 '{username}' 已存在")
    user = User(
        username=username,
        password_hash=hash_password(password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def authenticate_user(session: Session, username: str, password: str) -> Optional[User]:
    user = session.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        return None
    # IM 用户无密码，不允许密码登录
    if user.password_hash is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


# ═══════════════════════════════════════════
# 渠道身份管理
# ═══════════════════════════════════════════
def bind_channel_identity(
    session: Session,
    user_id: int,
    channel: str,
    platform_user_id: str,
    platform_union_id: Optional[str] = None,
) -> UserIdentity:
    """
    将渠道身份绑定到已有 Web 账号。
    如果 (channel, platform_user_id) 已绑定到其他 user_id，抛出异常。
    """
    from app_server.db import UserIdentity, utcnow

    # 检查该渠道身份是否已绑定
    existing = (
        session.query(UserIdentity)
        .filter(
            UserIdentity.channel == channel,
            UserIdentity.platform_user_id == platform_user_id,
        )
        .first()
    )
    if existing:
        if existing.user_id == user_id:
            return existing  # 已绑到当前用户，幂等
        raise ValueError(f"该 {channel} 身份已绑定到其他账号")

    identity = UserIdentity(
        user_id=user_id,
        channel=channel,
        platform_user_id=platform_user_id,
        platform_union_id=platform_union_id,
    )
    session.add(identity)
    session.commit()
    session.refresh(identity)
    return identity


def resolve_user_by_channel(
    session: Session,
    channel: str,
    platform_user_id: str,
) -> Optional[User]:
    """根据渠道身份查找内部用户"""
    identity = (
        session.query(UserIdentity)
        .filter(
            UserIdentity.channel == channel,
            UserIdentity.platform_user_id == platform_user_id,
        )
        .first()
    )
    if identity is None:
        return None
    return session.get(User, identity.user_id)


# ═══════════════════════════════════════════
# Drive Token 加密/解密
# ═══════════════════════════════════════════

def _derive_aes_key() -> bytes:
    """从 TOKEN_ENCRYPTION_KEY 派生 32 字节 AES-256 密钥"""
    raw = TOKEN_ENCRYPTION_KEY.encode("utf-8")
    return hashlib.sha256(raw).digest()


def encrypt_drive_token(plaintext: str) -> Tuple[str, str]:
    """AES-256-CBC 加密，返回 (ciphertext_base64, iv_base64)"""
    key = _derive_aes_key()
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    # PKCS7 padding
    data = plaintext.encode("utf-8")
    pad_len = 16 - (len(data) % 16)
    padded = data + bytes([pad_len] * pad_len)
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode(), base64.b64encode(iv).decode()


def decrypt_drive_token(encrypted_b64: str, iv_b64: str) -> str:
    """AES-256-CBC 解密，返回原始 token JSON 字符串"""
    key = _derive_aes_key()
    iv = base64.b64decode(iv_b64)
    encrypted = base64.b64decode(encrypted_b64)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(encrypted) + decryptor.finalize()
    # Remove PKCS7 padding
    pad_len = padded[-1]
    return padded[:-pad_len].decode("utf-8")


# ═══════════════════════════════════════════
# Google OAuth (Drive 授权)
# ═══════════════════════════════════════════

def google_oauth_url(redirect_uri: str) -> str:
    """生成 Google OAuth 授权 URL"""
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/spreadsheets",
        "access_type": "offline",
        "prompt": "consent",          # 每次授权都获取 refresh_token
    }
    import urllib.parse
    qs = urllib.parse.urlencode(params)
    return f"https://accounts.google.com/o/oauth2/v2/auth?{qs}"


def exchange_google_code(code: str, redirect_uri: str) -> Optional[dict]:
    """
    用 OAuth 授权码换取 token，返回 Google OAuth token dict:
    {
        "access_token": "...",
        "refresh_token": "...",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "...",
        "client_secret": "...",
        "scopes": [...],
        "expiry": "ISO8601",
    }
    """
    import requests
    try:
        payload = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        resp = requests.post("https://oauth2.googleapis.com/token", data=payload, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        # 转为 Google Credentials JSON 格式，兼容 tool_drive.py
        expiry = (
            datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))
        ).isoformat()
        return {
            "token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "scopes": [
                "https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/spreadsheets",
            ],
            "expiry": expiry,
        }
    except Exception:
        return None


def store_drive_token(session: Session, user_id: int, token_json: str) -> 'UserDriveToken':
    """加密并存储 Drive Token 到数据库"""
    from app_server.db import UserDriveToken
    encrypted, iv = encrypt_drive_token(token_json)
    existing = session.query(UserDriveToken).filter(UserDriveToken.user_id == user_id).first()
    now = utcnow()
    if existing:
        existing.encrypted_token = encrypted
        existing.iv = iv
        existing.status = "active"
        existing.refreshed_at = now
        session.commit()
        return existing
    else:
        record = UserDriveToken(
            user_id=user_id,
            encrypted_token=encrypted,
            iv=iv,
            status="active",
            created_at=now,
            refreshed_at=now,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def get_drive_token(session: Session, user_id: int) -> Optional[str]:
    """从数据库解密并返回 Drive Token JSON 字符串"""
    from app_server.db import UserDriveToken
    record = (
        session.query(UserDriveToken)
        .filter(UserDriveToken.user_id == user_id, UserDriveToken.status == "active")
        .first()
    )
    if record is None:
        return None
    try:
        return decrypt_drive_token(record.encrypted_token, record.iv)
    except Exception:
        return None


def revoke_drive_token(session: Session, user_id: int):
    """标记 Drive Token 为已吊销"""
    from app_server.db import UserDriveToken
    record = (
        session.query(UserDriveToken)
        .filter(UserDriveToken.user_id == user_id, UserDriveToken.status == "active")
        .first()
    )
    if record:
        record.status = "revoked"
        session.commit()


# ═══════════════════════════════════════════
# Service Account（公共 Drive）管理
# ═══════════════════════════════════════════

def get_drive_service_account_email() -> str | None:
    """获取当前 Service Account 的 email（用于分享 Drive 权限）"""
    from agent_engine.tools.tool_drive import _load_service_account_creds
    creds = _load_service_account_creds()
    if creds is not None and hasattr(creds, 'service_account_email'):
        return creds.service_account_email
    return None


def drive_connection_status(session: Session, user_id: int) -> dict:
    """
    返回当前用户的 Drive 连接状态（综合判断）：
    - service_account: 全局 Service Account 是否已配置
    - user_oauth: 用户是否有个人 OAuth 授权
    - ready: 是否可以正常使用 Drive 功能
    """
    from agent_engine.tools.tool_drive import has_service_account
    oauth_token = get_drive_token(session, user_id)
    sa_ready = has_service_account()
    return {
        "ready": sa_ready or (oauth_token is not None),
        "service_account": sa_ready,
        "user_oauth": oauth_token is not None,
        "sa_email": get_drive_service_account_email() if sa_ready else None,
    }
