# ==========================================
# 🌟 专家注册表 (百人级架构底座)
# ==========================================
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Type, Any

logger = logging.getLogger(__name__)

# ─── 向后兼容的 AGENT_ROSTER（retriever.py 等引用） ────────
AGENT_ROSTER = {
    "researcher": {
        "class_name": "ResearcherAgent",
        "desc": "调研专家。专精：联网搜索新闻、查阅资料、搜集全网情报。无本地修改权限。"
    },
    "coder": {
        "class_name": "CoderAgent",
        "desc": "编程/执行专家。专精：读写本地文件、数据处理、操作云盘、发送邮件等落地执行操作。"
    },
    "googledrive": {
        "class_name": "GoogleDriveAgent",
        "desc": "Google Drive 管理专家。专精：管理和操作用户在 Google Drive 上的文件和数据。"
    }
}


# ─── AgentCard 数据类 ────────────────────────────────────

@dataclass
class AgentCard:
    """Agent 的角色名片（用于 Planner 规划和注册表查询）"""
    role_id: str
    display_name: str
    description: str
    agent_class: type
    risk_profile: str = "medium"       # low / medium / high
    max_concurrent: int = 1            # 最大并发数
    tags: List[str] = field(default_factory=list)


# ─── 惰性构建 AgentCard 注册表（避免循环导入） ────────────

def _build_default_cards() -> Dict[str, "AgentCard"]:
    """惰性构建 AgentCard 注册表"""
    from agent_engine.agents.researcher import ResearcherAgent
    from agent_engine.agents.coder import CoderAgent
    from agent_engine.agents.googledrive import GoogleDriveAgent

    return {
        "researcher": AgentCard(
            role_id="researcher",
            display_name="情报研究员",
            description="联网搜索、查阅外部资料并输出脱水情报",
            agent_class=ResearcherAgent,
            risk_profile="low",
            max_concurrent=2,
            tags=["search", "web", "research", "情报", "搜索"],
        ),
        "coder": AgentCard(
            role_id="coder",
            display_name="自动化工程师",
            description="读写本地文件、执行代码、发送邮件等落地操作",
            agent_class=CoderAgent,
            risk_profile="medium",
            max_concurrent=1,
            tags=["code", "file", "exec", "代码", "文件"],
        ),
        "googledrive": AgentCard(
            role_id="googledrive",
            display_name="Google Drive 管家",
            description="管理 Google Drive 文件，读写 Sheets 表格数据",
            agent_class=GoogleDriveAgent,
            risk_profile="medium",
            max_concurrent=1,
            tags=["drive", "sheets", "google", "表格", "云端"],
        ),
    }


# ─── AgentRegistry 工厂类 ─────────────────────────────────

class AgentRegistry:
    """
    Agent 注册表工厂类 — 管理 Agent 的注册、查找和实例化。

    用于 WorkflowRuntime 按 role 名称创建 Agent 实例。
    支持线程安全的单例缓存，也支持创建新实例（用于并发场景）。

    使用方式:
        registry = AgentRegistry()
        agent = registry.create("researcher")
    """

    def __init__(self, use_cache: bool = True):
        self._cards: Dict[str, AgentCard] = {}
        self._cache: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._use_cache = use_cache
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """惰性初始化：首次使用时加载 Agent 类"""
        if self._initialized:
            return
        self._initialized = True
        try:
            self._cards = _build_default_cards()
        except Exception as e:
            logger.error(f"AgentRegistry 初始化失败: {e}")

    # ── 注册管理 ──────────────────────────────────────────

    def register(self, card: AgentCard) -> None:
        """注册新的 Agent 角色"""
        self._ensure_initialized()
        self._cards[card.role_id] = card
        with self._lock:
            self._cache.pop(card.role_id, None)
        logger.info(f"已注册 Agent 角色: {card.role_id} ({card.display_name})")

    def get_card(self, role_id: str) -> Optional[AgentCard]:
        """获取 Agent 角色名片"""
        self._ensure_initialized()
        return self._cards.get(role_id)

    def list_roles(self) -> List[str]:
        """列出所有已注册的角色 ID"""
        self._ensure_initialized()
        return list(self._cards.keys())

    # ── 工厂方法（WorkflowRuntime 的核心入口） ─────────────

    def create(self, role_id: str, use_cache: Optional[bool] = None) -> Optional[Any]:
        """
        Agent 工厂方法 — 根据 role 名称创建 Agent 实例。

        :param role_id: Agent 角色名（如 "researcher", "coder", "googledrive"）
        :param use_cache: 是否使用缓存（覆盖实例级设置）
        :return: Agent 实例（None 表示无法创建）
        """
        self._ensure_initialized()

        should_cache = use_cache if use_cache is not None else self._use_cache
        card = self._cards.get(role_id)

        if card is None:
            # 不区分大小写近似匹配
            for rid, c in self._cards.items():
                if rid.lower() == role_id.lower():
                    card = c
                    role_id = rid
                    break

        if card is None:
            logger.warning(f"AgentRegistry: 未找到角色 '{role_id}'")
            return None

        # 缓存命中
        if should_cache:
            with self._lock:
                if role_id in self._cache:
                    return self._cache[role_id]

        # 新建实例
        try:
            instance = card.agent_class()
            logger.info(f"AgentRegistry: 创建 {role_id} → {type(instance).__name__}")
            if should_cache:
                with self._lock:
                    self._cache[role_id] = instance
            return instance
        except Exception as e:
            logger.error(f"AgentRegistry: 实例化 '{role_id}' 失败: {e}")
            return None

    def create_new(self, role_id: str) -> Optional[Any]:
        """强制创建新实例（不使用缓存），用于并发场景"""
        return self.create(role_id, use_cache=False)

    def clear_cache(self) -> None:
        """清除缓存"""
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        self._ensure_initialized()
        return len(self._cards)

    def __contains__(self, role_id: str) -> bool:
        self._ensure_initialized()
        return role_id in self._cards