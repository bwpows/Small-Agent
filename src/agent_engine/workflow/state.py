"""
任务状态机（Task State Machine）
===============================
定义任务从 PENDING → RUNNING → 终态的完整生命周期，
支持 FAILED 后的 BLOCKED 传染（依赖失败的任务自动跳过）。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class TaskStatus(str, Enum):
    """任务生命周期状态"""
    PENDING    = "PENDING"       # 等待依赖就绪
    RUNNING    = "RUNNING"       # 正在执行
    SUCCEEDED  = "SUCCEEDED"     # 执行成功
    FAILED     = "FAILED"        # 执行失败
    SKIPPED    = "SKIPPED"       # 被跳过（HITL 拦截 或 依赖失败传染）
    BLOCKED    = "BLOCKED"       # 被阻塞（依赖的任务失败了）

    @property
    def is_terminal(self) -> bool:
        """是否为终态"""
        return self in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.BLOCKED)

    @property
    def is_success(self) -> bool:
        return self == TaskStatus.SUCCEEDED


class TaskState:
    """
    单个任务的状态机。

    包装 Planner 产出的任务字典 + 运行时状态，
    提供 transition() 方法进行状态转换（含合法性校验）。

    使用方式:
        ts = TaskState(task_dict)
        ts.transition(TaskStatus.RUNNING)
        ts.transition(TaskStatus.SUCCEEDED, output="...")
    """

    # 合法的状态转换表
    _VALID_TRANSITIONS: Dict[TaskStatus, set] = {
        TaskStatus.PENDING:    {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.SKIPPED, TaskStatus.FAILED},
        TaskStatus.RUNNING:    {TaskStatus.SUCCEEDED, TaskStatus.FAILED},
        # 终态可回退用于重试
        TaskStatus.SUCCEEDED:  set(),
        TaskStatus.FAILED:     {TaskStatus.PENDING},    # 支持重试
        TaskStatus.SKIPPED:    {TaskStatus.PENDING},    # 支持 HITL 恢复
        TaskStatus.BLOCKED:    set(),
    }

    def __init__(self, task: Dict[str, Any]):
        """
        :param task: Planner 产出的任务字典，包含:
            task_id, action, agent_role, depends_on, instruction,
            risk_level, risk_details, expected_output
        """
        self.task: Dict[str, Any] = task
        self.task_id: int = task["task_id"]
        self.agent_role: str = task["agent_role"]
        self.instruction: str = task["instruction"]
        self.depends_on: list = task.get("depends_on", [])
        self.risk_level: str = task.get("risk_level", "low")
        self.risk_details: str = task.get("risk_details", "")
        self.expected_output: str = task.get("expected_output", "")
        self.status: TaskStatus = TaskStatus.PENDING
        self.output: Optional[str] = None        # 执行结果
        self.error: Optional[str] = None          # 错误信息
        self.retry_count: int = 0                 # 重试次数

    def transition(self, new_status: TaskStatus, output: str = None, error: str = None) -> bool:
        """
        状态转换。合法转换返回 True，非法返回 False。

        :param new_status: 目标状态
        :param output: 执行结果（SUCCEEDED 时填写）
        :param error: 错误信息（FAILED 时填写）
        """
        valid_targets = self._VALID_TRANSITIONS.get(self.status, set())
        if new_status not in valid_targets:
            return False

        self.status = new_status
        if output is not None:
            self.output = output
        if error is not None:
            self.error = error
        return True

    def block(self, reason: str = "") -> None:
        """标记为阻塞（前置任务失败导致）"""
        self.transition(TaskStatus.BLOCKED, error=f"前置任务失败: {reason}" if reason else "前置任务未完成")

    def skip(self, reason: str = "") -> None:
        """标记为跳过（HITL 拦截等）"""
        self.transition(TaskStatus.SKIPPED, error=reason or "任务被风控拦截")

    def increment_retry(self) -> int:
        """递增重试计数并返回当前值"""
        self.retry_count += 1
        return self.retry_count

    def reset_for_retry(self) -> None:
        """
        从 FAILED 状态重置为 PENDING，准备重试。
        注意：直接设置 status（绕过 transition 校验），
        因为 FAILED→PENDING 不是标准转换路径。
        """
        self.status = TaskStatus.PENDING
        self.output = None
        self.error = None
        # retry_count 由外部调用 increment_retry() 维护

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_role": self.agent_role,
            "instruction": self.instruction[:200],
            "depends_on": self.depends_on,
            "risk_level": self.risk_level,
            "status": self.status.value,
            "output_preview": (self.output or "")[:500],
            "error": self.error,
        }
