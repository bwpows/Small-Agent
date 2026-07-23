"""
Pydantic 请求/响应 Schema — 全部用于 FastAPI 路由校验与文档自动生成。
"""
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field


# ── Auth ──
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, examples=["alice"])
    password: str = Field(..., min_length=6, max_length=128)

class LoginRequest(BaseModel):
    username: str
    password: str

class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    role: str = "user"

class UserInfo(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    source: str = "web"
    role: str = "user"
    is_active: bool = True
    created_at: datetime


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(default="default", max_length=64)

class ApiKeyResponse(BaseModel):
    id: int
    name: str
    key: str               # 明文 Key（仅创建时返回一次！）
    revoked: bool
    last_used_at: Optional[datetime]
    created_at: datetime

class ApiKeyListItem(BaseModel):
    id: int
    name: str
    revoked: bool
    last_used_at: Optional[datetime]
    created_at: datetime


# ── Chat (OpenAI 兼容) ──
class ChatMessage(BaseModel):
    role: str                           # user / assistant / system / tool
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = "default"
    messages: List[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = 0.2
    max_tokens: Optional[int] = None
    tools: Optional[List[dict]] = None

class ChatChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"

class ChatUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatChoice]
    usage: ChatUsage = Field(default_factory=ChatUsage)
    conversation_id: Optional[int] = None
    reasoning_content: Optional[str] = None


# ── Conversations ──
class ConversationResponse(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime

class ConversationCreateRequest(BaseModel):
    title: Optional[str] = "新会话"

class ConversationUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=128)

class GenerateTitleRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)

class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    usage: Optional[UsageInfo] = None
    duration_ms: Optional[int] = None
    thinking_count: Optional[int] = None
    reasoning: Optional[str] = None


# ── Models ──
class ModelItem(BaseModel):
    id: str
    object: str = "model"
    owned_by: str = "small-agent"

class ModelsResponse(BaseModel):
    object: str = "list"
    data: List[ModelItem]


# ── Tools ──
class ToolItem(BaseModel):
    name: str
    description: str
    inputSchema: dict

class ToolsResponse(BaseModel):
    tools: List[ToolItem]


# ── Channel OAuth ──
class FeishuBindRequest(BaseModel):
    """飞书身份绑定到已有 Web 账号（需 JWT 鉴权）"""
    code: str = Field(..., description="飞书 OAuth 授权码")


class ChannelUserInfo(BaseModel):
    """渠道用户信息"""
    channel: str
    platform_user_id: str
    platform_union_id: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


# ── Admin ──
class AdminStats(BaseModel):
    total_users: int
    total_conversations: int
    total_messages: int
    active_users_today: int
    total_tokens: int
    users_by_source: dict[str, int] = {}
    conversations_today: int = 0
    messages_today: int = 0


class AdminUserItem(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    source: str = "web"
    role: str = "user"
    is_active: bool = True
    created_at: datetime
    api_key_count: int = 0
    conversation_count: int = 0


class AdminUserListResponse(BaseModel):
    users: list[AdminUserItem]
    total: int
    page: int
    page_size: int


class AdminUpdateRoleRequest(BaseModel):
    role: str = Field(..., pattern="^(user|admin)$")


class AdminToggleActiveRequest(BaseModel):
    is_active: bool
