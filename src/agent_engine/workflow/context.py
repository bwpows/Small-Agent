"""
全局上下文 & 任务视图（GlobalContext + TaskContext）
=================================================
Runtime 持有唯一的 GlobalContext（单一真相源），
每个 Task 通过 TaskContext（轻量 View）零拷贝引用全局状态。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_engine.workflow.artifact import ArtifactStore


class GlobalContext:
    """
    全局上下文 — 整个工作流的单一真相源。

    属性:
        artifacts : ArtifactStore   — 线程安全的任务产物存储（可写）
        memories   : str            — 用户记忆/偏好（只读）
        profile    : str            — 用户画像（只读）
        runtime    : Dict[str, Any]  — 运行时元数据（只读）
        history    : str            — 历史对话（只读）
    """

    def __init__(
        self,
        artifacts: "ArtifactStore",
        memories: str = "",
        profile: str = "",
        runtime: Optional[Dict[str, Any]] = None,
        history: str = "",
    ):
        self._artifacts = artifacts
        self._memories = memories
        self._profile = profile
        self._runtime = runtime or {}
        self._history = history

    # ── 属性访问（只读保护） ──────────────────────────────

    @property
    def artifacts(self) -> "ArtifactStore":
        return self._artifacts

    @property
    def memories(self) -> str:
        return self._memories

    @property
    def profile(self) -> str:
        return self._profile

    @property
    def runtime(self) -> Dict[str, Any]:
        return self._runtime

    @property
    def history(self) -> str:
        return self._history

    @property
    def summary(self) -> str:
        return (
            f"GlobalContext(artifacts={len(self._artifacts)}, "
            f"memories={len(self._memories)} chars, "
            f"profile={len(self._profile)} chars)"
        )


class TaskContext:
    """
    任务上下文 — GlobalContext 的轻量视图。

    每个 Agent 在执行时接收一个 TaskContext 实例，
    prior_context 通过 ArtifactStore.build_prior_context() 懒计算前置任务产物，
    所有字段都是对 GlobalContext 的零拷贝引用。

    使用方式:
        ctx = TaskContext(global_ctx=global_ctx, task_state=task_state)
        result = agent.execute(ctx)  # Agent 内部通过 ctx 获取一切所需信息
    """

    def __init__(
        self,
        global_ctx: GlobalContext,
        task_state: "agent_engine.workflow.state.TaskState",
    ):
        """
        :param global_ctx: 全局上下文引用（零拷贝）
        :param task_state: 当前任务的 TaskState 实例
        """
        self._global = global_ctx
        self._task_state = task_state
        self._cached_prior_context: Optional[str] = None

    # ── 委托属性（从 task_state） ─────────────────────────

    @property
    def task_id(self) -> int:
        return self._task_state.task_id

    @property
    def agent_role(self) -> str:
        return self._task_state.agent_role

    @property
    def instruction(self) -> str:
        return self._task_state.instruction

    @property
    def depends_on(self) -> list:
        return self._task_state.depends_on

    @property
    def risk_level(self) -> str:
        return self._task_state.risk_level

    @property
    def expected_output(self) -> str:
        return self._task_state.expected_output

    @property
    def action(self) -> str:
        return self._task_state.task.get("action", "")

    @property
    def title(self) -> str:
        return self._task_state.task.get("title", "")

    # ── 委托属性（从 global_ctx） ─────────────────────────

    @property
    def global_(self) -> GlobalContext:
        """获取底层 GlobalContext 引用（高级用法）"""
        return self._global

    @property
    def memories(self) -> str:
        return self._global.memories

    @property
    def profile(self) -> str:
        return self._global.profile

    @property
    def runtime(self) -> Dict[str, Any]:
        return self._global.runtime

    @property
    def history(self) -> str:
        return self._global.history

    @property
    def artifacts(self) -> "ArtifactStore":
        return self._global.artifacts

    # ── 核心方法 ─────────────────────────────────────────

    @property
    def prior_context(self) -> str:
        """
        组装前置任务产物上下文。

        从 ArtifactStore 中读取 depends_on 对应的任务产物，
        拼接成一段完整的「前置情报」。结果会被缓存，
        多次调用不会重复计算。
        """
        if self._cached_prior_context is None:
            self._cached_prior_context = (
                self._global.artifacts.build_prior_context(self.depends_on)
            )
        return self._cached_prior_context

    def get_prior_artifact(self, task_id: int) -> Optional[Any]:
        """按 task_id 获取指定前置任务的产物"""
        return self._global.artifacts.get(task_id)

    def build_full_prompt(self) -> str:
        """
        组装完整的执行提示词，包含:
        - 前置任务情报
        - 当前任务指令
        - 用户画像/记忆（如有）

        这是传递给 Agent 的最终 prompt。
        """
        parts = []

        # 对话历史
        if self.history:
            parts.append(f"【💬 历史对话】\n{self.history}")

        # 前置任务情报
        prior = self.prior_context
        if prior:
            parts.append(prior)

        # 用户信息
        if self.profile:
            parts.append(f"【👤 用户画像】{self.profile}")
        if self.memories:
            parts.append(f"【🧠 用户偏好】{self.memories}")

        # 当前任务
        parts.append(f"【📌 当前任务】\n{self.instruction}")

        if self.expected_output:
            parts.append(f"【🎯 期望产出】{self.expected_output}")

        return "\n\n".join(parts)
