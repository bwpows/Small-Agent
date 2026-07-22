"""
依赖注入 — FastAPI Depends() 函数，从请求中解析 TenantContext。
"""
from dataclasses import dataclass, field
from typing import Optional, Callable, List

from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session

from server.db import get_session, ApiKey, Conversation, User, UserIdentity, utcnow
from server.auth import resolve_api_key


@dataclass
class TenantContext:
    """贯穿整个请求生命周期的多租户上下文"""
    user_id: int
    api_key_id: Optional[int] = None          # IM 用户可无 API Key
    username: str = ""
    channel: Optional[str] = None             # feishu / telegram / qq（web 端为 None）
    platform_user_id: Optional[str] = None    # 平台 open_id
    conversation_id: Optional[int] = None

    # 隔离命名空间
    @property
    def memory_namespace(self) -> str:
        return f"mem_{self.user_id}"

    @property
    def workspace_root(self) -> str:
        from server.config import WORKSPACE_DIR
        import os
        return os.path.join(WORKSPACE_DIR, "users", str(self.user_id))

    # 工具白名单（P0: None 表示全部可用；后续可限制）
    allowed_tools: Optional[List[str]] = None

    # Drive token 解析器（延迟加载）
    drive_token_resolver: Optional[Callable] = None


def get_db() -> Session:
    """每个请求获取独立数据库会话，请求结束后自动关闭"""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_tenant_context(
    authorization: str = Header(..., description="Bearer sk-xxx"),
    session: Session = Depends(get_db),
) -> TenantContext:
    """从 Authorization: Bearer <api_key> 头解析 TenantContext"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization 头格式错误，应为 'Bearer sk-xxx'")

    raw_key = authorization.removeprefix("Bearer ").strip()
    if not raw_key:
        raise HTTPException(status_code=401, detail="缺少 API Key")

    api_key = resolve_api_key(session, raw_key)
    if api_key is None:
        raise HTTPException(status_code=401, detail="无效或已吊销的 API Key")

    user = session.get(User, api_key.user_id)
    username = user.username if user else "unknown"

    return TenantContext(
        user_id=api_key.user_id,
        api_key_id=api_key.id,
        username=username,
    )


def resolve_channel_user(
    channel: str,
    platform_user_id: str,
    session: Session,
    platform_union_id: Optional[str] = None,
    display_name: Optional[str] = None,
    avatar_url: Optional[str] = None,
) -> TenantContext:
    """
    根据渠道身份查找或懒注册内部用户，返回 TenantContext。
    首次来访自动建号（User + UserIdentity），无需密码/API Key。
    """
    # 查已有绑定
    identity = (
        session.query(UserIdentity)
        .filter(
            UserIdentity.channel == channel,
            UserIdentity.platform_user_id == platform_user_id,
        )
        .first()
    )

    if identity:
        user = session.get(User, identity.user_id)
        if user and user.is_active:
            return TenantContext(
                user_id=user.id,
                username=user.username,
                channel=channel,
                platform_user_id=platform_user_id,
            )

    # 懒注册：创建内部 User + 绑定 UserIdentity
    username = f"{channel}_{platform_user_id}"[:64]
    user = User(
        username=username,
        source=channel,
        display_name=display_name,
        avatar_url=avatar_url,
        union_id=platform_union_id,
        is_active=True,
    )
    session.add(user)
    session.flush()  # 获取 user.id

    identity = UserIdentity(
        user_id=user.id,
        channel=channel,
        platform_user_id=platform_user_id,
        platform_union_id=platform_union_id,
    )
    session.add(identity)
    session.commit()

    return TenantContext(
        user_id=user.id,
        username=user.username,
        channel=channel,
        platform_user_id=platform_user_id,
    )


def get_or_create_channel_conversation(
    ctx: TenantContext,
    session: Session,
    platform_chat_id: str,
    title: str = "飞书对话",
) -> Conversation:
    """
    根据渠道 + 平台会话 ID 查找或创建 Conversation。
    确保同一用户在同一平台的同一 chat 只有一条会话记录。
    """
    conv = (
        session.query(Conversation)
        .filter(
            Conversation.user_id == ctx.user_id,
            Conversation.channel == ctx.channel,
            Conversation.platform_chat_id == platform_chat_id,
        )
        .first()
    )
    if conv is None:
        conv = Conversation(
            user_id=ctx.user_id,
            channel=ctx.channel,
            platform_chat_id=platform_chat_id,
            title=title,
        )
        session.add(conv)
        session.commit()
        session.refresh(conv)
    return conv


def get_optional_conversation_id(
    conversation_id: Optional[int] = None,
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_db),
) -> TenantContext:
    """将 conversation_id（如果传入）绑定到上下文中，并校验归属"""
    if conversation_id is not None:
        conv = session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != ctx.user_id:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        ctx.conversation_id = conversation_id
    return ctx
