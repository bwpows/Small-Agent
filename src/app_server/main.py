"""
app_server/main.py — 无头 API 服务入口。
启动: uvicorn app_server.main:app --reload --host 0.0.0.0 --port 8000
"""
import os
import time
import uuid
import json
import logging
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Request, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse

from app_server.db import init_db, get_session, ApiKey, Conversation, User, UserIdentity
from app_server.auth import (
    register_user, authenticate_user, create_jwt, decode_jwt,
    create_api_key, resolve_api_key, bind_channel_identity,
)
from app_server.deps import (
    get_db, get_tenant_context, TenantContext,
    resolve_channel_user, get_or_create_channel_conversation,
)
from app_server.limiter import get_limiter
from app_server.chat_service import (
    chat_completion, chat_completion_channel, chat_completion_stream,
    list_conversations as svc_list_conversations,
    list_messages as svc_list_messages,
)
from app_server import schemas
from app_server.config import SERVER_BASE_URL, FRONTEND_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# 初始化数据库
init_db()

app = FastAPI(
    title="Small-Agent API",
    description="多租户 Agent 接口服务 — OpenAI 兼容 /v1/chat/completions + 多渠道 IM 适配",
    version="0.2.0",
)

# CORS（允许所有来源，生产环境应限定）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 全局限流中间件 ──
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """对所有 /v1/ 和 /channels/ 路径做限流"""
    path = request.url.path
    if path.startswith("/v1/") or path.startswith("/channels/"):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            raw_key = auth_header.removeprefix("Bearer ").strip()
            session = get_session()
            try:
                api_key = resolve_api_key(session, raw_key)
                if api_key:
                    allowed, wait = get_limiter().is_allowed(api_key.id)
                    if not allowed:
                        return JSONResponse(
                            status_code=429,
                            content={
                                "error": {
                                    "message": f"请求过于频繁，请 {wait} 秒后重试",
                                    "type": "rate_limit_exceeded",
                                }
                            },
                        )
            finally:
                session.close()
    return await call_next(request)


# ═══════════════════════════════════════════
# JWT 用户解析（用于 Key 管理 / Web 后台）
# ═══════════════════════════════════════════

def jwt_user_id(
    authorization: str = Header(..., alias="Authorization"),
) -> int:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要 Bearer Token")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_jwt(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="无效或过期的 Token")
    return int(payload["sub"])


# ═══════════════════════════════════════════
# Auth 路由（JWT 会话，用于管理后台）
# ═══════════════════════════════════════════

@app.post("/auth/register", response_model=schemas.AuthResponse, tags=["Auth"])
def api_register(body: schemas.RegisterRequest, session=Depends(get_db)):
    """注册新用户，返回 JWT"""
    try:
        user = register_user(session, body.username, body.password)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    token = create_jwt(user.id, user.username)
    return schemas.AuthResponse(
        access_token=token, user_id=user.id, username=user.username,
        role=user.role,
    )


@app.post("/auth/login", response_model=schemas.AuthResponse, tags=["Auth"])
def api_login(body: schemas.LoginRequest, session=Depends(get_db)):
    """登录，返回 JWT"""
    user = authenticate_user(session, body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_jwt(user.id, user.username)
    return schemas.AuthResponse(
        access_token=token, user_id=user.id, username=user.username,
        role=user.role,
    )


@app.get("/auth/me", response_model=schemas.UserInfo, tags=["Auth"])
def get_me(user_id: int = Depends(jwt_user_id), session=Depends(get_db)):
    """获取当前登录用户信息（含角色）"""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return schemas.UserInfo(
        id=user.id, username=user.username, display_name=user.display_name,
        avatar_url=user.avatar_url, source=user.source, role=user.role,
        is_active=user.is_active, created_at=user.created_at,
    )


@app.get("/auth/keys", response_model=list[schemas.ApiKeyListItem], tags=["Auth"])
def list_keys(user_id: int = Depends(jwt_user_id), session=Depends(get_db)):
    """列出当前用户的所有 API Key（不含明文）"""
    keys = session.query(ApiKey).filter(ApiKey.user_id == user_id).all()
    return [
        schemas.ApiKeyListItem(
            id=k.id, name=k.name, revoked=k.revoked,
            last_used_at=k.last_used_at, created_at=k.created_at,
        )
        for k in keys
    ]


@app.post("/auth/keys", response_model=schemas.ApiKeyResponse, tags=["Auth"])
def create_key(
    body: schemas.ApiKeyCreateRequest,
    user_id: int = Depends(jwt_user_id),
    session=Depends(get_db),
):
    """生成一个新的 API Key（明文仅返回一次！）"""
    api_key_obj, raw_key = create_api_key(session, user_id, body.name)
    return schemas.ApiKeyResponse(
        id=api_key_obj.id, name=api_key_obj.name, key=raw_key,
        revoked=api_key_obj.revoked, last_used_at=api_key_obj.last_used_at,
        created_at=api_key_obj.created_at,
    )


@app.post("/auth/keys/{key_id}/revoke", tags=["Auth"])
def revoke_key(
    key_id: int,
    user_id: int = Depends(jwt_user_id),
    session=Depends(get_db),
):
    """吊销一个 API Key"""
    key = session.query(ApiKey).filter(
        ApiKey.id == key_id, ApiKey.user_id == user_id
    ).first()
    if key is None:
        raise HTTPException(status_code=404, detail="Key 不存在")
    key.revoked = True
    session.commit()
    return {"detail": "Key 已吊销"}


# ═══════════════════════════════════════════
# OpenAI 兼容 /v1 路由（API Key 鉴权）
# ═══════════════════════════════════════════

@app.get("/v1/models", response_model=schemas.ModelsResponse, tags=["OpenAI Compatible"])
def list_models(ctx: TenantContext = Depends(get_tenant_context)):
    """列出可用模型"""
    from agent_engine.config import LLM_MODEL
    return schemas.ModelsResponse(
        data=[schemas.ModelItem(id=LLM_MODEL, owned_by="small-agent")]
    )


@app.post("/v1/chat/completions", tags=["OpenAI Compatible"])
async def chat_completions(
    body: schemas.ChatCompletionRequest,
    conversation_id: Optional[int] = Query(None, description="会话 ID（可选，同一会话会复用历史）"),
    ctx: TenantContext = Depends(get_tenant_context),
    session=Depends(get_db),
):
    """
    OpenAI 兼容聊天接口。
    鉴权：Authorization: Bearer sk-xxx
    请求体符合 OpenAI /v1/chat/completions 格式。
    支持 stream=true 使用 SSE 流式输出。
    """
    # 绑定会话（校验归属）
    if conversation_id is not None:
        conv = session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != ctx.user_id:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        ctx.conversation_id = conversation_id

    # 取最后一条 user 消息
    user_messages = [m for m in body.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="至少需要一条 user 消息")
    user_input = user_messages[-1].content

    try:
        # ── SSE 流式分支 ──
        if body.stream:
            return StreamingResponse(
                chat_completion_stream(ctx, user_input),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # ── 非流式分支 ──
        result = chat_completion(ctx, user_input, stream=False)

        request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        from agent_engine.config import LLM_MODEL
        usage_data = result.get("usage", {})
        return schemas.ChatCompletionResponse(
            id=request_id,
            created=int(time.time()),
            model=LLM_MODEL,
            choices=[
                schemas.ChatChoice(
                    message=schemas.ChatMessage(role="assistant", content=result["content"]),
                    finish_reason="stop",
                )
            ],
            usage=schemas.ChatUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            ),
            conversation_id=ctx.conversation_id,
            reasoning_content=result.get("reasoning", "") or None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"引擎错误: {str(e)}")


@app.get("/v1/tools", response_model=schemas.ToolsResponse, tags=["OpenAI Compatible"])
def list_tools(ctx: TenantContext = Depends(get_tenant_context)):
    """列出可用工具（MCP 格式）"""
    from agent_engine.llm_engine import get_tools_as_mcp
    return schemas.ToolsResponse(tools=get_tools_as_mcp())


# ═══════════════════════════════════════════
# 会话管理路由
# ═══════════════════════════════════════════

@app.get("/v1/conversations", response_model=list[schemas.ConversationResponse], tags=["Conversations"])
def list_conversations(ctx: TenantContext = Depends(get_tenant_context)):
    """列出当前用户的所有会话"""
    return [
        schemas.ConversationResponse(
            id=c["id"], title=c["title"],
            created_at=c["created_at"], updated_at=c["updated_at"],
        )
        for c in svc_list_conversations(ctx)
    ]


@app.post("/v1/conversations", response_model=schemas.ConversationResponse, tags=["Conversations"])
def create_conversation(
    body: schemas.ConversationCreateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    session=Depends(get_db),
):
    """创建新会话"""
    conv = Conversation(user_id=ctx.user_id, title=body.title or "新会话")
    session.add(conv)
    session.commit()
    session.refresh(conv)
    ctx.conversation_id = conv.id
    return schemas.ConversationResponse(
        id=conv.id, title=conv.title,
        created_at=conv.created_at, updated_at=conv.updated_at,
    )


@app.patch("/v1/conversations/{conv_id}", response_model=schemas.ConversationResponse, tags=["Conversations"])
def update_conversation(
    conv_id: int,
    body: schemas.ConversationUpdateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    session=Depends(get_db),
):
    """更新会话标题"""
    conv = session.get(Conversation, conv_id)
    if conv is None or conv.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    conv.title = body.title
    session.commit()
    session.refresh(conv)
    return schemas.ConversationResponse(
        id=conv.id, title=conv.title,
        created_at=conv.created_at, updated_at=conv.updated_at,
    )


@app.post("/v1/conversations/generate-title", response_model=schemas.ConversationResponse, tags=["Conversations"])
def generate_conversation_title(
    body: schemas.GenerateTitleRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """根据消息内容，调用 LLM 自动生成会话标题（4-8 字）"""
    from agent_engine.llm_engine import generate_answer
    prompt = f"请根据这句话，给这段对话起一个 4-8 个字的简短标题，直接返回标题内容，不要带引号、不要标点：{body.text}"
    result = generate_answer(prompt, recent_history=[], parsed_memories=[], web_info=False)
    # result 可能是 str（旧版）或 dict（新版）
    if isinstance(result, dict):
        raw_title = result.get("content", body.text[:20])
    else:
        raw_title = str(result)
    clean_title = raw_title.strip().replace('"', '').replace("'", "").replace("。", "").replace("，", "")
    title = clean_title if clean_title else body.text[:20]
    # 限制长度
    if len(title) > 20:
        title = title[:20]
    return schemas.ConversationResponse(
        id=0, title=title,
        created_at=None, updated_at=None,
    )


@app.get("/v1/conversations/{conv_id}/messages",
         response_model=list[schemas.MessageResponse], tags=["Conversations"])
def get_messages(
    conv_id: int,
    ctx: TenantContext = Depends(get_tenant_context),
    session=Depends(get_db),
):
    """获取指定会话的消息列表"""
    conv = session.get(Conversation, conv_id)
    if conv is None or conv.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    ctx.conversation_id = conv_id
    return [
        schemas.MessageResponse(
            id=m["id"], role=m["role"],
            content=m["content"], created_at=m["created_at"],
            usage=schemas.UsageInfo(**m["usage"]) if m.get("usage") else None,
            duration_ms=m.get("duration_ms"),
            thinking_count=m.get("thinking_count"),
            reasoning=m.get("reasoning"),
        )
        for m in svc_list_messages(ctx)
    ]


# ═══════════════════════════════════════════
# 飞书 Webhook 路由
# ═══════════════════════════════════════════

@app.post("/channels/feishu/webhook", tags=["Channels"])
async def feishu_webhook(request: Request, session=Depends(get_db)):
    """
    飞书事件回调入口。
    处理 URL 验证（返回 challenge）和消息事件。
    """
    from app_server.channels.feishu import (
        parse_message_event, verify_lark_signature, send_text_message,
    )

    body_bytes = await request.body()
    body: dict = {}

    try:
        body = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="无效的 JSON body")

    # ── 1. URL 验证 ──
    challenge = body.get("challenge")
    if challenge:
        logger.info("飞书 URL 验证请求")
        return {"challenge": challenge}

    # ── 2. 验签 ──
    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")
    if not verify_lark_signature(timestamp, nonce, body_bytes, signature):
        logger.warning("飞书签名验证失败")
        raise HTTPException(status_code=403, detail="签名验证失败")

    # ── 3. 解析事件 ──
    event_data = parse_message_event(body)
    if event_data is None:
        # 非 im.message.receive_v1 事件，返回 200 避免飞书重试
        return {"code": 0}

    open_id = event_data["open_id"]
    chat_id = event_data["chat_id"]
    message_id = event_data["message_id"]
    text = event_data["text"]
    chat_type = event_data["chat_type"]

    # ── 4. 限流（按 user_id 维度，因为飞书用户无 API Key） ──
    # 先解析用户拿到 user_id
    identity = (
        session.query(UserIdentity)
        .filter(
            UserIdentity.channel == "feishu",
            UserIdentity.platform_user_id == open_id,
        )
        .first()
    )
    if identity:
        allowed, wait = get_limiter().is_allowed_by_user(identity.user_id)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": {"message": f"请求过于频繁，请 {wait} 秒后重试"}},
            )

    # ── 5. 解析用户 & 会话 ──
    ctx = resolve_channel_user(
        channel="feishu",
        platform_user_id=open_id,
        session=session,
    )

    conversation_title = f"飞书{'群聊' if chat_type == 'group' else '私聊'} {chat_id[:8]}"
    conv = session.query(Conversation).filter(
        Conversation.user_id == ctx.user_id,
        Conversation.channel == "feishu",
        Conversation.platform_chat_id == chat_id,
    ).first()
    if conv is None:
        conv = Conversation(
            user_id=ctx.user_id,
            channel="feishu",
            platform_chat_id=chat_id,
            title=conversation_title,
        )
        session.add(conv)
        session.commit()
        session.refresh(conv)

    ctx.conversation_id = conv.id

    # ── 6. 调用引擎 ──
    is_group = chat_type == "group"
    # 群聊用 chat_id 回复，私聊用 open_id 回复
    reply_target = chat_id if is_group else open_id

    try:
        reply = chat_completion_channel(
            ctx=ctx,
            user_input=text,
            platform_chat_id=chat_id,
            platform_message_id=message_id,
        )
    except Exception as e:
        logger.error(f"引擎错误: {e}", exc_info=True)
        reply = "抱歉，处理你的消息时出错了。请稍后再试。"
        send_text_message(reply_target, reply, is_group=is_group)
        return {"code": 0}

    # ── 7. 回写飞书 ──
    if reply:
        # 飞书消息有长度限制，超长分段发送
        max_len = 4000
        if len(reply) > max_len:
            chunks = [reply[i:i+max_len] for i in range(0, len(reply), max_len)]
            for chunk in chunks:
                send_text_message(reply_target, chunk, is_group=is_group)
        else:
            send_text_message(reply_target, reply, is_group=is_group)

    return {"code": 0}


# ═══════════════════════════════════════════
# 飞书 OAuth 登录 / 绑定
# ═══════════════════════════════════════════

@app.get("/auth/feishu/login", tags=["Auth"])
async def feishu_login(redirect: Optional[str] = None):
    """
    飞书 OAuth 登录入口。
    前端跳转到飞书授权页，用户授权后回调 redirect 指定的地址（默认后端回调）。
    前端传 redirect=/feishu-callback 则飞书授权后回到前端页面，由前端 AJAX 调用回调接口。
    """
    from app_server.config import FEISHU_APP_ID
    from urllib.parse import quote
    if redirect:
        # 让飞书先回调后端，后端登录成功后再 302 跳回前端页面
        redirect_uri = (
            f"{SERVER_BASE_URL.rstrip('/')}/auth/feishu/callback"
            f"?redirect={quote(redirect.lstrip('/'))}"
        )
    else:
        redirect_uri = f"{SERVER_BASE_URL}/auth/feishu/callback"
    auth_url = (
        f"https://open.feishu.cn/open-apis/authen/v1/authorize"
        f"?app_id={FEISHU_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=contact:user.email:readonly"
    )
    return {"auth_url": auth_url}


@app.get("/auth/feishu/callback", tags=["Auth"])
async def feishu_callback(
    code: str,
    redirect: Optional[str] = None,
    state: Optional[str] = None,
    session=Depends(get_db),
):
    """
    飞书 OAuth 回调。
    用授权码换取用户身份，自动建号或登录，返回 JWT。
    若携带 redirect 参数（前端页面路径，如 /feishu-callback），
    则登录成功后 302 跳转回该页面并附带 token，由前端读取并落库。
    """
    from app_server.channels.feishu import exchange_oauth_code, get_user_info
    from urllib.parse import urlencode

    user_info = exchange_oauth_code(code)
    if user_info is None:
        raise HTTPException(status_code=400, detail="飞书 OAuth 授权失败")

    open_id = user_info["open_id"]
    union_id = user_info.get("union_id", "")
    name = user_info.get("name", "")
    avatar_url = user_info.get("avatar_url", "")

    # 尝试通过通讯录 API 获取邮箱（需要 contact:user.email:readonly 权限）
    email = None
    detail_info = get_user_info(open_id)
    if detail_info:
        email = detail_info.get("email", None)

    # 查找或创建用户
    ctx = resolve_channel_user(
        channel="feishu",
        platform_user_id=open_id,
        session=session,
        platform_union_id=union_id,
        display_name=name,
        avatar_url=avatar_url,
    )

    # 如果用 OAuth 拿到了用户名/邮箱，更新用户信息
    if name:
        user = session.get(User, ctx.user_id)
        if user:
            if not user.display_name:
                user.display_name = name
            if avatar_url:
                user.avatar_url = avatar_url
            if email and not user.email:
                user.email = email
            session.commit()

    token = create_jwt(ctx.user_id, ctx.username)

    if redirect:
        # 只允许相对路径，跳回前端页面（由 FRONTEND_URL 决定主机）。
        # 这样本地（前端在 localhost:3000、后端走 ngrok）和线上（同域名）都能正确跳转。
        path = redirect.lstrip("/")
        if "://" in path or path.startswith("//"):
            raise HTTPException(status_code=400, detail="非法的跳转路径")
        target = f"{FRONTEND_URL.rstrip('/')}/{path}"
        sep = "&" if "?" in target else "?"
        query = urlencode({
            "access_token": token,
            "user_id": ctx.user_id,
            "username": ctx.username,
        })
        return RedirectResponse(url=f"{target}{sep}{query}")

    return schemas.AuthResponse(
        access_token=token,
        user_id=ctx.user_id,
        username=ctx.username,
    )


@app.post("/auth/bind/feishu", tags=["Auth"])
async def bind_feishu(
    body: schemas.FeishuBindRequest,
    user_id: int = Depends(jwt_user_id),
    session=Depends(get_db),
):
    """
    已登录 Web 用户绑定飞书身份。
    用飞书 OAuth 授权码换取 open_id，绑定到当前账号。
    之后飞书消息和 Web 消息共享同一 user_id。
    """
    from app_server.channels.feishu import exchange_oauth_code

    user_info = exchange_oauth_code(body.code)
    if user_info is None:
        raise HTTPException(status_code=400, detail="飞书 OAuth 授权失败")

    try:
        bind_channel_identity(
            session=session,
            user_id=user_id,
            channel="feishu",
            platform_user_id=user_info["open_id"],
            platform_union_id=user_info.get("union_id"),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # 更新用户来源标记
    user = session.get(User, user_id)
    if user:
        user.source = "web"  # 保持 web 为主来源
        if not user.display_name:
            user.display_name = user_info.get("name", "")
        session.commit()

    return {
        "detail": "飞书身份绑定成功",
        "feishu_name": user_info.get("name", ""),
    }


# ═══════════════════════════════════════════
# Google Drive 授权（Service Account + OAuth 兼容）
# ═══════════════════════════════════════════

# ── Service Account（公共 Drive 授权，推荐） ──

@app.post("/auth/drive/service-account", tags=["Auth"])
def upload_service_account(
    body: dict,
    session=Depends(get_db),
):
    """
    上传/设置 Service Account JSON 密钥。
    接收 { "service_account_json": "{...}" }，写入全局凭证。
    仅管理员可用（后续可加入角色校验）。
    """
    sa_json = body.get("service_account_json", "")
    if not sa_json:
        raise HTTPException(status_code=400, detail="缺少 service_account_json 字段")

    # 校验 JSON 格式
    try:
        info = json.loads(sa_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="service_account_json 不是有效的 JSON")

    required_fields = ["type", "project_id", "private_key_id", "private_key", "client_email"]
    missing = [f for f in required_fields if f not in info]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Service Account JSON 缺少必要字段: {', '.join(missing)}"
        )

    from agent_engine.tools.tool_drive import set_service_account_from_json
    set_service_account_from_json(sa_json)

    return {
        "detail": "Service Account 已设置",
        "client_email": info.get("client_email", ""),
        "project_id": info.get("project_id", ""),
    }


@app.delete("/auth/drive/service-account", tags=["Auth"])
def remove_service_account():
    """移除 Service Account 凭证"""
    from agent_engine.tools.tool_drive import clear_service_account
    clear_service_account()
    return {"detail": "Service Account 已移除"}


# ── Drive 连接状态 ──

@app.get("/auth/drive/status", tags=["Auth"])
def drive_status(
    user_id: int = Depends(jwt_user_id),
    session=Depends(get_db),
):
    """查询 Drive 连接状态（Service Account + 用户 OAuth）"""
    from app_server.auth import drive_connection_status
    return drive_connection_status(session, user_id)


# ── OAuth 个人授权（保留兼容，但已不推荐） ──

@app.get("/auth/google/login", tags=["Auth"])
def google_login(user_id: int = Depends(jwt_user_id)):
    """
    [已废弃] Google Drive OAuth 登录入口。
    推荐使用 Service Account（POST /auth/drive/service-account）。
    """
    from app_server.auth import google_oauth_url
    redirect_uri = f"{SERVER_BASE_URL}/auth/google/callback"
    auth_url = google_oauth_url(redirect_uri)
    if "?" in auth_url:
        auth_url += f"&state={user_id}"
    else:
        auth_url += f"?state={user_id}"
    return {"auth_url": auth_url, "deprecated": True}


@app.get("/auth/google/callback", tags=["Auth"])
def google_callback(
    code: str,
    state: Optional[str] = None,
    session=Depends(get_db),
):
    """
    [已废弃] Google OAuth 回调。
    """
    from app_server.auth import exchange_google_code, store_drive_token
    from app_server.config import FRONTEND_URL
    from fastapi.responses import RedirectResponse

    user_id = None
    if state:
        try:
            user_id = int(state)
        except ValueError:
            pass
    if user_id is None:
        raise HTTPException(status_code=400, detail="缺少 state 参数（user_id）")

    token_info = exchange_google_code(code, redirect_uri=f"{SERVER_BASE_URL}/auth/google/callback")
    if token_info is None:
        raise HTTPException(status_code=400, detail="Google OAuth 授权失败，请重试")

    token_json = json.dumps(token_info)
    store_drive_token(session, user_id, token_json)

    return RedirectResponse(url=f"{FRONTEND_URL}/chat?drive_linked=1")


@app.delete("/auth/drive", tags=["Auth"])
def drive_revoke(
    user_id: int = Depends(jwt_user_id),
    session=Depends(get_db),
):
    """断开个人 Drive OAuth 授权"""
    from app_server.auth import revoke_drive_token
    revoke_drive_token(session, user_id)
    return {"detail": "Drive OAuth 授权已断开"}


# ═══════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════

@app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok", "service": "small-agent-api"}


# ═══════════════════════════════════════════
# 启动入口
# ═══════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app_server.main:app", host="0.0.0.0", port=8000, reload=True)
