"""
DAG 调度器（DAG Scheduler）
===========================
Kahn 拓扑排序 → 按层级分层 → ThreadPoolExecutor 并发执行同一层任务。

核心流程:
    1. topological_layers()  — 将 DAG 按依赖深度分层
    2. execute_layer()       — 并发执行同一层的所有任务
    3. run()                 — 逐层推进，直到所有任务完成
"""

from __future__ import annotations

import logging
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError, as_completed
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING

from agent_engine.workflow.state import TaskState, TaskStatus

if TYPE_CHECKING:
    from agent_engine.workflow.context import TaskContext
    from agent_engine.workflow.risk_gate import RiskGate

logger = logging.getLogger(__name__)


class DAGScheduler:
    """
    DAG 拓扑调度器。

    使用 Kahn 算法进行拓扑排序，将任务分层，
    同一层的任务可以并发执行。

    使用方式:
        scheduler = DAGScheduler(max_workers=4)
        scheduler.run(
            task_states=[ts1, ts2, ts3],
            executor_fn=my_executor,
        )
    """

    def __init__(
        self,
        max_workers: int = 4,
        task_timeout: float = 300.0,
        deadline: Optional[float] = None,
    ):
        """
        :param max_workers: 线程池最大并发数
        :param task_timeout: 单个任务超时（秒），默认 300
        :param deadline: 全局超时（秒），超时后终止调度
        """
        self.max_workers = max_workers
        self.task_timeout = task_timeout
        self.deadline = deadline
        self._executor: Optional[ThreadPoolExecutor] = None
        self._start_time: Optional[float] = None

    # ── 拓扑排序 ──────────────────────────────────────────

    @staticmethod
    def topological_layers(
        task_states: List["TaskState"],
    ) -> List[List["TaskState"]]:
        """
        Kahn 算法：将 DAG 按依赖深度分层。

        输入: 所有任务的 TaskState 列表
        输出: [[层级1任务], [层级2任务], ...]

        算法原理:
            1. 计算每个任务的入度（未完成依赖数）
            2. 入度为 0 的任务加入当前层
            3. 执行当前层后，减少后续任务的入度
            4. 重复直到所有任务分配完毕

        时间复杂度: O(V + E)，其中 V=任务数，E=依赖边数
        """
        if not task_states:
            return []

        # 构建 task_id → TaskState 的快速索引
        task_map: Dict[int, "TaskState"] = {ts.task_id: ts for ts in task_states}

        # 计算每个 task 的入度（只统计有效的依赖）
        in_degree: Dict[int, int] = {}
        dependents: Dict[int, List[int]] = {}  # task_id → [被它依赖的任务列表]

        for ts in task_states:
            in_degree[ts.task_id] = 0
            dependents[ts.task_id] = []

        # 构建反向依赖图
        for ts in task_states:
            for dep_id in ts.depends_on:
                if dep_id in task_map:
                    in_degree[ts.task_id] += 1
                    dependents.setdefault(dep_id, []).append(ts.task_id)

        # Kahn BFS 分层
        layers: List[List["TaskState"]] = []
        queue = deque()

        # 第一层：入度为 0 的节点
        current_layer: List["TaskState"] = []
        for ts in task_states:
            if in_degree[ts.task_id] == 0:
                current_layer.append(ts)

        if not current_layer:
            # 所有节点都有依赖 → 存在循环依赖
            logger.error("DAG 调度失败：存在循环依赖或无入口节点")
            return []

        while current_layer:
            layers.append(current_layer)
            next_layer: List["TaskState"] = []

            for completed in current_layer:
                for dependent_id in dependents.get(completed.task_id, []):
                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0:
                        next_layer.append(task_map[dependent_id])

            current_layer = next_layer

        # 检查是否有未分配的节点（循环依赖）
        assigned = sum(len(layer) for layer in layers)
        if assigned != len(task_states):
            logger.error(
                f"DAG 存在循环依赖：{assigned}/{len(task_states)} 个节点已分配，"
                f"剩余节点被循环阻塞"
            )

        return layers

    # ── 逐层执行 ──────────────────────────────────────────

    def execute_layer(
        self,
        layer: List["TaskState"],
        executor_fn: Callable[["TaskState"], None],
    ) -> Dict[int, str]:
        """
        并发执行同一层的所有任务。

        :param layer: 当前层任务列表
        :param executor_fn: 任务执行函数，签名为 fn(TaskState) -> None
        :return: {task_id: status} 每个任务的执行状态
        """
        results: Dict[int, str] = {}

        if not layer:
            return results

        if len(layer) == 1:
            # 单任务直接同步执行，避免线程开销
            ts = layer[0]
            try:
                executor_fn(ts)
            except Exception as e:
                logger.exception(f"任务 #{ts.task_id} 执行异常: {e}")
            results[ts.task_id] = ts.status.value
            return results

        # 多任务并发执行
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)

        futures: Dict[Future, "TaskState"] = {}

        for ts in layer:
            future = self._executor.submit(executor_fn, ts)
            futures[future] = ts

        for future in as_completed(futures):
            ts = futures[future]
            try:
                # 计算剩余 time_budget
                remaining = None
                if self.deadline and self._start_time:
                    elapsed = time.time() - self._start_time
                    remaining = max(0, self.deadline - elapsed)
                timeout = self.task_timeout if remaining is None else min(self.task_timeout, remaining)
                future.result(timeout=timeout)
            except TimeoutError:
                logger.error(f"任务 #{ts.task_id} 超时（{self.task_timeout}s），标记为失败")
                if ts.status != TaskStatus.FAILED:
                    ts.status = TaskStatus.FAILED
                    ts.error = f"任务执行超时（{self.task_timeout}s）"
            except Exception as e:
                logger.exception(f"任务 #{ts.task_id} 并发执行异常: {e}")
            results[ts.task_id] = ts.status.value

        return results

    # ── 全流程 ────────────────────────────────────────────

    def run(
        self,
        task_states: List["TaskState"],
        executor_fn: Callable[["TaskState"], None],
        on_layer_start: Optional[Callable[[int, List["TaskState"]], None]] = None,
        on_layer_done: Optional[Callable[[int, Dict[int, str]], None]] = None,
    ) -> bool:
        """
        全流程 DAG 调度。

        :param task_states: 所有任务的状态机列表
        :param executor_fn: 单个任务的执行函数，签名为 fn(TaskState) -> None
        :param on_layer_start: 层级开始回调（用于上报进度）
        :param on_layer_done: 层级完成回调
        :return: True 表示全部成功，False 表示有任务失败
        """
        self._start_time = time.time()

        layers = self.topological_layers(task_states)

        if not layers:
            logger.warning("DAG 分层为空，跳过执行")
            return False

        logger.info(f"DAG 共 {len(layers)} 层，{len(task_states)} 个任务")
        if self.deadline:
            logger.info(f"全局超时: {self.deadline}s，单任务超时: {self.task_timeout}s")

        for level_idx, layer in enumerate(layers):
            # 检查全局超时
            if self.deadline and (time.time() - self._start_time) > self.deadline:
                logger.warning(f"全局超时（{self.deadline}s），终止调度")
                for ts in task_states:
                    if ts.status == TaskStatus.PENDING:
                        ts.block(reason="全局超时")
                break

            # 过滤掉已终止的任务（BLOCKED/SKIPPED）
            runnable = [
                ts for ts in layer
                if ts.status == TaskStatus.PENDING
            ]
            blocked = [
                ts for ts in layer
                if ts.status in (TaskStatus.BLOCKED, TaskStatus.SKIPPED)
            ]

            if blocked:
                logger.info(
                    f"第 {level_idx + 1} 层: {len(runnable)} 个就绪, "
                    f"{len(blocked)} 个已跳过"
                )

            if on_layer_start:
                on_layer_start(level_idx, runnable)

            if runnable:
                results = self.execute_layer(runnable, executor_fn)
                if on_layer_done:
                    on_layer_done(level_idx, results)

            # 检查当前层完成后，哪些后续任务需要被 block
            self._propagate_failures(task_states)

        # 清理线程池
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None

        # 检查最终结果
        all_success = all(
            ts.status in (TaskStatus.SUCCEEDED, TaskStatus.SKIPPED)
            and ts.status != TaskStatus.FAILED
            for ts in task_states
        )
        return all_success

    def _propagate_failures(self, task_states: List["TaskState"]) -> None:
        """
        失败传染：FAILED/BLOCKED → 下游 BLOCKED，SKIPPED → 下游 SKIPPED。
        """
        task_map = {ts.task_id: ts for ts in task_states}
        failed_ids: Set[int] = {
            ts.task_id for ts in task_states
            if ts.status == TaskStatus.FAILED
        }
        blocked_ids: Set[int] = {
            ts.task_id for ts in task_states
            if ts.status == TaskStatus.BLOCKED
        }
        skipped_ids: Set[int] = {
            ts.task_id for ts in task_states
            if ts.status == TaskStatus.SKIPPED
        }

        for ts in task_states:
            if ts.status != TaskStatus.PENDING:
                continue
            for dep_id in ts.depends_on:
                if dep_id in failed_ids:
                    ts.block(reason=f"前置任务 #{dep_id} 执行失败")
                    break
                elif dep_id in blocked_ids:
                    ts.block(reason=f"前置任务 #{dep_id} 被阻塞")
                    break
                elif dep_id in skipped_ids:
                    ts.skip(reason=f"前置任务 #{dep_id} 已被跳过")
                    break

    def shutdown(self) -> None:
        """关闭线程池"""
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
