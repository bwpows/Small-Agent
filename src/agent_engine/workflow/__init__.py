"""
Workflow DAG Runtime — 任务规划 → DAG 调度 → 并发执行引擎。

核心组件:
    - WorkflowPlan   : Planner 产出的任务图容器
    - WorkflowRuntime: 总编排器（持有 GlobalContext，驱动 RiskGate → DAGScheduler）
    - DAGScheduler   : Kahn 拓扑排序 + ThreadPoolExecutor 并发执行
    - GlobalContext  : 单一全局上下文（artifacts 可写，其余只读）
    - TaskContext    : 轻量 View，零拷贝引用全局状态
    - TaskState      : 任务状态机（PENDING → RUNNING → SUCCEEDED/FAILED/SKIPPED）
    - ArtifactStore  : 线程安全的任务产物存储
    - RiskGate       : HITL 风控闸门
"""

from agent_engine.workflow.artifact import Artifact, ArtifactStore
from agent_engine.workflow.state import TaskStatus, TaskState
from agent_engine.workflow.plan import Task, WorkflowPlan
from agent_engine.workflow.context import GlobalContext, TaskContext
from agent_engine.workflow.risk_gate import RiskGate
from agent_engine.workflow.scheduler import DAGScheduler
from agent_engine.workflow.runtime import WorkflowRuntime

__all__ = [
    "Artifact",
    "ArtifactStore",
    "TaskStatus",
    "TaskState",
    "Task",
    "WorkflowPlan",
    "GlobalContext",
    "TaskContext",
    "RiskGate",
    "DAGScheduler",
    "WorkflowRuntime",
]
