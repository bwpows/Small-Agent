"""
风险控制闸门（Risk Gate）
=========================
HITL（Human-in-the-Loop）风控机制：
- 高风险任务（risk_level == "high"）需要人工确认后才执行
- 中低风险任务自动放行
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_engine.workflow.state import TaskState


class RiskGate:
    """
    风控闸门 — 决定任务是否可以直接执行或需要人工审批。

    使用方式:
        gate = RiskGate()
        decision = gate.evaluate(task_state)
        if decision["blocked"]:
            # 等待人工确认
    """

    # 需要拦截的风险等级
    _BLOCKED_LEVELS = {"high", "critical"}

    def __init__(self):
        pass

    def evaluate(self, task_state: "TaskState") -> Dict[str, Any]:
        """
        评估一个任务是否需要人工审批。

        :param task_state: 当前任务的状态机
        :return: {
            "blocked": bool,        # 是否需要拦截
            "risk_level": str,      # 风险等级
            "risk_details": str,    # 风险详情
            "reason": str,          # 拦截原因
        }
        """
        risk_level = task_state.risk_level.lower()
        blocked = risk_level in self._BLOCKED_LEVELS

        if blocked:
            reason = (
                f"任务 #{task_state.task_id} [{task_state.agent_role}] "
                f"风险等级为「{risk_level}」，需要人工确认。\n"
                f"详情: {task_state.risk_details or '（未提供）'}"
            )
        else:
            reason = ""

        return {
            "blocked": blocked,
            "risk_level": risk_level,
            "risk_details": task_state.risk_details,
            "reason": reason,
        }

    def preview_consequences(self, task_state: "TaskState") -> str:
        """
        生成风险预览文本，用于展示给人工审批者。

        :return: 人类可读的风险说明
        """
        return (
            f"⚠️ 高风险任务 #{task_state.task_id}\n"
            f"  角色: {task_state.agent_role}\n"
            f"  操作: {task_state.action}\n"
            f"  说明: {task_state.instruction[:300]}\n"
            f"  风险: {task_state.risk_details}\n"
            f"  期望产出: {task_state.expected_output[:200]}"
        )
