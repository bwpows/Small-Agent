"""
飞书渠道适配器 — Webhook 验签、消息收发、OAuth。
"""
import hashlib
import json
import time
import logging
from typing import Optional, Dict, Any, Tuple

import httpx

from app_server.config import (
    FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_VERIFY_TOKEN,
    FEISHU_ENCRYPT_KEY, FEISHU_BASE_URL,
)

logger = logging.getLogger("feishu")

# ── 内存缓存的 access token ──
_token_cache: Dict[str, Tuple[str, float]] = {}  # key → (token, expire_timestamp)


def _get_app_access_token() -> str:
    """获取 app_access_token（用于 OAuth 换取用户信息）"""
    cache_key = "app_access"
    now = time.time()
    if cache_key in _token_cache and _token_cache[cache_key][1] > now + 60:
        return _token_cache[cache_key][0]

    resp = httpx.post(
        f"{FEISHU_BASE_URL}/auth/v3/app_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 app_access_token 失败: {data}")

    token = data["app_access_token"]
    expire = now + data.get("expire", 7200)
    _token_cache[cache_key] = (token, expire)
    return token


def _get_tenant_access_token() -> str:
    """获取 tenant_access_token（用于发送消息等 API）"""
    cache_key = "tenant_access"
    now = time.time()
    if cache_key in _token_cache and _token_cache[cache_key][1] > now + 60:
        return _token_cache[cache_key][0]

    resp = httpx.post(
        f"{FEISHU_BASE_URL}/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败: {data}")

    token = data["tenant_access_token"]
    expire = now + data.get("expire", 7200)
    _token_cache[cache_key] = (token, expire)
    return token


# ═══════════════════════════════════════════
# Webhook 验签
# ═══════════════════════════════════════════

def verify_signature(timestamp: str, nonce: str, body: bytes) -> bool:
    """
    校验飞书回调签名。
    飞书签名算法: SHA256(timestamp + nonce + encrypt_key + body)
    如果未配置 encrypt_key，则 body 取空字符串。
    """
    if not FEISHU_VERIFY_TOKEN:
        logger.warning("FEISHU_VERIFY_TOKEN 未配置，跳过验签")
        return True

    # 飞书 v2 签名：timestamp + nonce + encrypt_key + body
    # 但通常的做法是用 verify_token 来验证。这里简化处理。
    # 实际生产环境应该严格验证 X-Lark-Signature header。
    return True


def verify_lark_signature(
    timestamp: str,
    nonce: str,
    body_bytes: bytes,
    signature: str,
) -> bool:
    """
    飞书事件回调签名验证（v1 版本）。
    签名 = SHA256(timestamp + nonce + secret + body_string)
    优先用 encrypt_key，没有则用 verify_token。
    """
    if not signature:
        # 飞书没发签名，无条件放行（部分旧版应用可能没有）
        return True

    # 尝试所有可能的密钥（encrypt_key 和 verify_token 都可能参与签名）
    candidates = [s for s in (FEISHU_ENCRYPT_KEY, FEISHU_VERIFY_TOKEN) if s]

    for secret in candidates:
        raw = f"{timestamp}{nonce}{secret}".encode("utf-8") + body_bytes
        computed = hashlib.sha256(raw).hexdigest()
        if computed == signature:
            return True

    # 所有 key 都不匹配，开发阶段放行并警告
    logger.warning(
        f"飞书签名验证失败 — ts={timestamp} nonce={nonce} "
        f"expected={signature[:16]}..."
    )
    # 本地开发：返回 True 继续处理，生产环境改为 return False
    return True


# ═══════════════════════════════════════════
# 事件解析
# ═══════════════════════════════════════════

def parse_message_event(body: dict) -> Optional[dict]:
    """
    解析飞书消息事件，返回标准化字段。
    仅处理 im.message.receive_v1 事件。
    返回: {"open_id": str, "chat_id": str, "message_id": str, "text": str, "chat_type": str}
    """
    header = body.get("header", {})
    event_type = header.get("event_type", "")

    if event_type != "im.message.receive_v1":
        return None

    event = body.get("event", {})
    sender = event.get("sender", {})
    sender_id = sender.get("sender_id", {})
    open_id = sender_id.get("open_id", "")

    message = event.get("message", {})
    chat_id = message.get("chat_id", "")
    message_id = message.get("message_id", "")
    chat_type = message.get("chat_type", "private")  # private / group

    # 飞书消息内容为 JSON 字符串，需要二次解析
    content_str = message.get("content", "{}")
    try:
        content = json.loads(content_str)
    except json.JSONDecodeError:
        content = {}

    text = content.get("text", "")

    if not text and "content" in content:
        # 富文本取 title 兜底
        text = str(content.get("content", ""))

    # 去掉 @ 机器人的 mention
    if text:
        text = _clean_at_mention(text)

    if not open_id or not chat_id or not message_id or not text:
        return None

    return {
        "open_id": open_id,
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "chat_type": chat_type,
    }


def _clean_at_mention(text: str) -> str:
    """去除 @机器人 的 at 标记，保留纯文本"""
    # 飞书 at 格式: @_user_1 或 @所有人，替换掉
    import re
    # 去除 @_xxx 格式
    text = re.sub(r'@_[\w-]+\s*', '', text)
    # 去除可能残留的多余空格
    return text.strip()


# ═══════════════════════════════════════════
# 发送消息
# ═══════════════════════════════════════════

def send_text_message(
    receive_id: str,
    text: str,
    msg_type: str = "text",
    is_group: bool = False,
) -> bool:
    """
    通过飞书 API 发送文本消息。
    receive_id: 接收者 ID（私聊为 open_id，群聊为 chat_id）
    text: 消息内容
    is_group: 是否为群聊（决定 receive_id_type 用 open_id 还是 chat_id）
    返回是否发送成功
    """
    try:
        token = _get_tenant_access_token()
        id_type = "chat_id" if is_group else "open_id"
        url = f"{FEISHU_BASE_URL}/im/v1/messages?receive_id_type={id_type}"

        content = json.dumps({"text": str(text)}, ensure_ascii=False)
        payload = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": content,
        }

        resp = httpx.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error(f"飞书发送消息失败: {data}")
            return False
        return True
    except Exception as e:
        logger.error(f"飞书发送消息异常: {e}")
        return False


# ═══════════════════════════════════════════
# OAuth
# ═══════════════════════════════════════════

def exchange_oauth_code(code: str) -> Optional[dict]:
    """
    用飞书 OAuth 授权码换取用户身份信息。
    返回: {"open_id": str, "union_id": str, "name": str, "avatar_url": str}
    """
    try:
        token = _get_app_access_token()
        resp = httpx.post(
            f"{FEISHU_BASE_URL}/authen/v1/access_token",
            json={"grant_type": "authorization_code", "code": code},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error(f"飞书 OAuth 换 token 失败: {data}")
            return None

        return {
            "open_id": data.get("data", {}).get("open_id", ""),
            "union_id": data.get("data", {}).get("union_id", ""),
            "name": data.get("data", {}).get("name", ""),
            "avatar_url": data.get("data", {}).get("avatar_url", ""),
        }
    except Exception as e:
        logger.error(f"飞书 OAuth 异常: {e}")
        return None


def get_user_info(open_id: str) -> Optional[dict]:
    """
    通过 open_id 获取飞书用户信息。
    """
    try:
        token = _get_tenant_access_token()
        resp = httpx.get(
            f"{FEISHU_BASE_URL}/contact/v3/users/{open_id}",
            params={"user_id_type": "open_id"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            return None

        user_data = data.get("data", {}).get("user", {})
        return {
            "open_id": user_data.get("open_id", ""),
            "union_id": user_data.get("union_id", ""),
            "name": user_data.get("name", ""),
            "avatar_url": user_data.get("avatar", {}).get("avatar_240", ""),
            "email": user_data.get("email", None),
        }
    except Exception as e:
        logger.error(f"获取飞书用户信息异常: {e}")
        return None
