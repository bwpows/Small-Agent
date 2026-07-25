"""
工作流运行时（Workflow Runtime）
================================
总编排器：持有 GlobalContext，驱动 RiskGate → DAGScheduler，
实现完整的 DAG 任务计划执行生命周期。

核心流程:
    1. 接收 WorkflowPlan + AgentRegistry
    2. 创建 GlobalContext（ArtifactStore + 用户信息）
    3. 遍历每层任务：
       a. RiskGate 风控检查
       b. Agent 执行（通过 TaskContext）
       c. 产物存入 ArtifactStore
       d. 失败传染给后续依赖
    4. 返回最终结果
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from agent_engine.workflow.artifact import Artifact, ArtifactStore
from agent_engine.workflow.state import TaskStatus, TaskState
from agent_engine.workflow.context import GlobalContext, TaskContext
from agent_engine.workflow.plan import WorkflowPlan
from agent_engine.workflow.risk_gate import RiskGate
from agent_engine.workflow.scheduler import DAGScheduler

if TYPE_CHECKING:
    from agent_engine.agents.registry import AgentRegistry

logger = logging.getLogger(__name__)


# ── 默认执行回调（可替换） ────────────────────────────────


class WorkflowRuntime:
    """
    DAG 工作流总运行时。

    持有全局上下文，编排整个执行生命周期。

    使用方式:
        runtime = WorkflowRuntime(
            plan=workflow_plan,
            registry=agent_registry,
            user_query="...",
            memories="...",
            profile="...",
        )
        summary = runtime.execute()
    """

    def __init__(
        self,
        plan: WorkflowPlan,
        registry: "AgentRegistry",
        user_query: str = "",
        memories: str = "",
        profile: str = "",
        history: str = "",
        runtime_meta: Optional[Dict[str, Any]] = None,
        max_workers: int = 4,
        task_timeout: float = 300.0,
        deadline: Optional[float] = None,
        max_retries: int = 1,
        risk_gate: Optional[RiskGate] = None,
    ):
        """
        :param plan: Planner 产出的 WorkflowPlan
        :param registry: Agent 注册表（含工厂方法）
        :param user_query: 用户原始提问
        :param memories: 用户记忆/偏好
        :param profile: 用户画像
        :param history: 对话历史
        :param runtime_meta: 运行时元数据（如 session_id）
        :param max_workers: 最大并发数
        :param task_timeout: 单个任务超时（秒），默认 300
        :param deadline: 全局超时（秒），超时后终止调度
        :param max_retries: 任务失败后最大重试次数，默认 1
        :param risk_gate: 风控闸门（可选，默认创建新实例）
        """
        self.plan = plan
        self.registry = registry
        self.user_query = user_query
        self.max_workers = max_workers
        self.task_timeout = task_timeout
        self.deadline = deadline
        self.max_retries = max_retries
        self.risk_gate = risk_gate or RiskGate()

        # ── 构建全局上下文 ──────────────────────────────────
        self.artifact_store = ArtifactStore()

        self.global_ctx = GlobalContext(
            artifacts=self.artifact_store,
            memories=memories,
            profile=profile,
            runtime=runtime_meta or {},
            history=history,
        )

        # ── 构建 TaskState 列表 ─────────────────────────────
        self.task_states: Dict[int, TaskState] = {}
        self._build_task_states()

        # ── 调度器 ──────────────────────────────────────────
        self.scheduler = DAGScheduler(
            max_workers=max_workers,
            task_timeout=task_timeout,
            deadline=deadline,
        )

        # ── 结果收集 ────────────────────────────────────────
        self._blocked_tasks: List[TaskState] = []
        self._total_usage: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def _build_task_states(self) -> None:
        """将 WorkflowPlan 中的 Task 转换为 TaskState"""
        self.task_states.clear()
        for task in self.plan.tasks:
            self.task_states[task.task_id] = TaskState(task.to_dict())

    # ── 核心执行 ────────────────────────────────────────────

    def execute(self) -> Dict[str, Any]:
        """
        执行整个 DAG 工作流。

        :return: {
            "success": bool,
            "summary": str,               # 最终摘要
            "task_results": [...],        # 每个任务的结果
            "blocked_tasks": [...],       # 被风控拦截的任务
            "artifacts": {...},           # 所有产物
        }
        """
        # Step 1: 风控预检 — 标记高风险任务
        high_risk = []
        for ts in self.task_states.values():
            decision = self.risk_gate.evaluate(ts)
            if decision["blocked"]:
                ts.skip(reason=decision["reason"])
                high_risk.append(ts)

        if high_risk:
            self._blocked_tasks = high_risk
            logger.warning(
                f"风控拦截 {len(high_risk)} 个高风险任务: "
                f"{[ts.task_id for ts in high_risk]}"
            )

        # Step 2: DAG 调度执行
        all_states = list(self.task_states.values())
        all_success = self.scheduler.run(
            task_states=all_states,
            executor_fn=self._execute_single_task,
            on_layer_start=self._on_layer_start,
            on_layer_done=self._on_layer_done,
        )

        # Step 3: 组装结果
        task_results = [ts.to_dict() for ts in all_states]
        summary = self._build_summary()

        return {
            "success": all_success,
            "summary": summary,
            "task_results": task_results,
            "blocked_tasks": [ts.to_dict() for ts in self._blocked_tasks],
            "artifacts": {
                tid: a.summary()
                for tid, a in self.artifact_store.get_all().items()
            },
            "total_usage": self._total_usage,
        }

    def _execute_single_task(self, ts: TaskState) -> None:
        """
        执行单个任务（由 DAGScheduler 的线程池调用）。

        支持自动重试：retry_count <= max_retries 时失败后会重置重试。
        通过 monkey-patch 收集 token 用量。
        使用 create_new() 确保同一角色多实例并发安全。
        """
        while ts.retry_count <= self.max_retries:
            ts.transition(TaskStatus.RUNNING)

            # 构建 TaskContext
            task_ctx = TaskContext(
                global_ctx=self.global_ctx,
                task_state=ts,
            )

            logger.info(
                f"▶ 执行任务 #{ts.task_id} [{ts.agent_role}]: {ts.instruction[:100]}"
                + (f" (重试 {ts.retry_count}/{self.max_retries})" if ts.retry_count > 0 else "")
            )

            try:
                # 并发安全：同一角色多任务时创建新实例
                agent = self.registry.create_new(ts.agent_role)
                if agent is None:
                    raise RuntimeError(f"无法创建 Agent: {ts.agent_role}")

                # 调用 Agent 执行
                result = agent.execute_with_ctx(task_ctx)

                # 适配新旧返回格式
                if isinstance(result, dict):
                    output = result.get("output", "")
                    usage = result.get("usage", {})
                else:
                    output = str(result)
                    usage = {}

                # 累积 token 用量
                if usage:
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        if k in usage:
                            self._total_usage[k] += usage.get(k, 0)

                # 标记成功
                ts.transition(TaskStatus.SUCCEEDED, output=output)
                logger.info(f"✓ 任务 #{ts.task_id} 完成 ({len(output)} chars)")

                # 存入产物存储
                self.artifact_store.put(
                    ts.task_id,
                    Artifact(
                        task_id=ts.task_id,
                        agent_role=ts.agent_role,
                        output=output,
                        status="SUCCEEDED",
                        metadata={
                            "instruction": ts.instruction[:200],
                            "usage": usage,
                        },
                    ),
                )
                return  # 成功，跳出重试循环

            except Exception as e:
                logger.exception(f"✗ 任务 #{ts.task_id} 执行失败: {e}")
                ts.increment_retry()
                if ts.retry_count <= self.max_retries:
                    logger.info(f"任务 #{ts.task_id} 重试 {ts.retry_count}/{self.max_retries}")
                    ts.reset_for_retry()
                else:
                    ts.transition(TaskStatus.FAILED, error=str(e))
                    self.artifact_store.put(
                        ts.task_id,
                        Artifact(
                            task_id=ts.task_id,
                            agent_role=ts.agent_role,
                            output=f"执行失败（已重试{self.max_retries}次）: {str(e)}",
                            status="FAILED",
                            metadata={"error": str(e), "retries": ts.retry_count},
                        ),
                    )
                    return

    # ── 回调 ────────────────────────────────────────────────

    def _on_layer_start(self, level: int, tasks: List[TaskState]) -> None:
        names = [f"#{ts.task_id}" for ts in tasks]
        logger.info(f"── 第 {level + 1} 层开始: {', '.join(names)}")

    def _on_layer_done(self, level: int, results: Dict[int, str]) -> None:
        status_str = ", ".join(f"#{tid}={status}" for tid, status in results.items())
        logger.info(f"── 第 {level + 1} 层完成: {status_str}")

    # ── 结果 ────────────────────────────────────────────────

    def _build_summary(self) -> str:
        """构建最终执行摘要（避免重复内容）"""
        lines = ["📋 **任务执行摘要**\n"]

        for ts in sorted(self.task_states.values(), key=lambda x: x.task_id):
            status_icon = {
                TaskStatus.SUCCEEDED: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.SKIPPED: "⏭️",
                TaskStatus.BLOCKED: "🚫",
                TaskStatus.PENDING: "⏳",
                TaskStatus.RUNNING: "🔄",
            }.get(ts.status, "❓")

            preview = (ts.output or "")[:200]
            lines.append(
                f"{status_icon} **任务 #{ts.task_id}** [{ts.agent_role}] "
                f"— {ts.status.value}"
            )
            if preview and ts.status == TaskStatus.SUCCEEDED:
                lines.append(f"   > {preview}")

        # ── 仅拼接最终叶子任务的完整输出（避免与上方预览重复） ──
        leaf_tasks = [
            ts for ts in self.task_states.values()
            if ts.status == TaskStatus.SUCCEEDED
            and not any(
                ts.task_id in (other.depends_on or [])
                for other in self.task_states.values()
            )
        ]
        if leaf_tasks:
            lines.append("\n---")
            lines.append("**最终产出:**")
            for ts in sorted(leaf_tasks, key=lambda x: x.task_id):
                if ts.output:
                    lines.append(ts.output)

        return "\n".join(lines)

    # ── HITL 相关 ───────────────────────────────────────────

    @property
    def has_blocked_tasks(self) -> bool:
        return len(self._blocked_tasks) > 0

    def get_blocked_tasks(self) -> List[TaskState]:
        return list(self._blocked_tasks)

    def resume_blocked_task(self, task_id: int, approved: bool = True) -> bool:
        """
        恢复被风控拦截的任务（人工审批通过后调用），并立即执行。

        :param task_id: 任务 ID
        :param approved: False 表示拒绝，任务保持 SKIPPED
        :return: 是否恢复并执行成功
        """
        ts = self.task_states.get(task_id)
        if ts is None or ts.status != TaskStatus.SKIPPED:
            return False

        if not approved:
            return False  # 维持 SKIPPED

        # 重置为 PENDING
        ts.status = TaskStatus.PENDING
        ts.output = None
        ts.error = None
        self._blocked_tasks = [
            bt for bt in self._blocked_tasks if bt.task_id != task_id
        ]

        # 立即执行该任务
        logger.info(f"人工审批通过，恢复执行任务 #{task_id}")
        self._execute_single_task(ts)
        return ts.status == TaskStatus.SUCCEEDED
