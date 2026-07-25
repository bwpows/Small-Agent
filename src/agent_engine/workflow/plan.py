"""
工作流计划（Workflow Plan）
==========================
Planner 产出的 DAG 任务图容器，负责解析和校验任务依赖关系。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Task:
    """Planner 产出的单个任务节点。

    每个 Task 包含执行所需的全部信息：
    - task_id: 任务序号（从 1 开始）
    - title: 简短标题
    - action: 任务动作名称
    - agent_role: 负责的 Agent 角色
    - depends_on: 依赖的前置 task_id 列表
    - instruction: 执行指令
    - risk_level: 风险等级 (low/medium/high)
    - risk_details: 风险详情说明
    - expected_output: 期望产出描述
    """
    task_id: int
    title: str
    action: str
    agent_role: str
    depends_on: List[int] = field(default_factory=list)
    instruction: str = ""
    risk_level: str = "low"
    risk_details: str = ""
    expected_output: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """从 Planner 输出的 dict 构造 Task 对象"""
        return cls(
            task_id=data.get("task_id", 0),
            title=data.get("title", ""),
            action=data.get("action", ""),
            agent_role=data.get("agent_role", ""),
            depends_on=data.get("depends_on", []) or [],
            instruction=data.get("instruction", ""),
            risk_level=data.get("risk_level", "low"),
            risk_details=data.get("risk_details", ""),
            expected_output=data.get("expected_output", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "action": self.action,
            "agent_role": self.agent_role,
            "depends_on": self.depends_on,
            "instruction": self.instruction,
            "risk_level": self.risk_level,
            "risk_details": self.risk_details,
            "expected_output": self.expected_output,
        }

    @property
    def has_dependencies(self) -> bool:
        return len(self.depends_on) > 0


class WorkflowPlan:
    """
    Planner 产出的 DAG 任务图容器。

    提供便捷的校验、查询方法。本身是纯数据对象，
    不包含任何执行逻辑。

    使用方式:
        plan = WorkflowPlan.from_planner_output(planner_result)
        if plan.is_dag:
            ... 进入 DAG Runtime
        ordered = plan.topological_order()  # 拓扑排序后的任务列表
    """

    def __init__(self, tasks: List[Task], raw_plan: Optional[Dict[str, Any]] = None):
        """
        :param tasks: 解析后的 Task 列表
        :param raw_plan: Planner 的原始输出（保留用于调试/tracing）
        """
        self.tasks: List[Task] = tasks
        self.raw_plan: Optional[Dict[str, Any]] = raw_plan

    # ── 工厂方法 ──────────────────────────────────────────

    @classmethod
    def from_planner_output(cls, planner_result: Dict[str, Any]) -> Optional["WorkflowPlan"]:
        """
        从 Planner 的 JSON 输出构造 WorkflowPlan。

        Planner 输出格式示例:
        {
            "plan_type": "dag",
            "tasks": [
                {"task_id": 1, "title": "...", "depends_on": [], ...},
                {"task_id": 2, "title": "...", "depends_on": [1], ...},
            ]
        }

        如果 plan_type 不是 "dag" 或解析失败，返回 None。
        """
        if not planner_result:
            return None

        plan_type = planner_result.get("plan_type", "single")
        if plan_type not in ("dag", "multi_step"):
            return None

        tasks_data = planner_result.get("tasks", [])
        if not tasks_data:
            return None

        tasks = [Task.from_dict(td) for td in tasks_data]
        plan = cls(tasks=tasks, raw_plan=planner_result)
        if not plan.validate():
            return None

        return plan

    # ── 校验 ──────────────────────────────────────────────

    def validate(self) -> bool:
        """
        校验计划的合法性:
        1. task_id 唯一
        2. depends_on 引用的 task_id 存在
        3. 无自依赖
        4. 至少有一个任务
        5. 无循环依赖（A→B, B→A）
        """
        if not self.tasks:
            return False

        task_ids = {t.task_id for t in self.tasks}

        for task in self.tasks:
            # 检查 depends_on 引用的 task_id 是否都存在
            for dep_id in task.depends_on:
                if dep_id not in task_ids:
                    return False
                if dep_id == task.task_id:
                    return False  # 自依赖

        # ── 循环依赖检测（DFS 三色标记法） ──
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in task_ids}

        def _has_cycle(tid: int) -> bool:
            color[tid] = GRAY
            task = self.get_task(tid)
            if task:
                for dep_id in task.depends_on:
                    if color[dep_id] == GRAY:
                        return True  # 发现回边 → 环
                    if color[dep_id] == WHITE:
                        if _has_cycle(dep_id):
                            return True
            color[tid] = BLACK
            return False

        for tid in task_ids:
            if color[tid] == WHITE:
                if _has_cycle(tid):
                    return False

        return True

    # ── 查询 ──────────────────────────────────────────────

    @property
    def is_dag(self) -> bool:
        """是否包含多任务依赖（非单任务线性）"""
        return len(self.tasks) > 1 and any(t.has_dependencies for t in self.tasks)

    @property
    def task_count(self) -> int:
        return len(self.tasks)

    def get_task(self, task_id: int) -> Optional[Task]:
        for t in self.tasks:
            if t.task_id == task_id:
                return t
        return None

    def get_root_tasks(self) -> List[Task]:
        """返回所有无依赖的根任务"""
        return [t for t in self.tasks if not t.has_dependencies]

    def get_leaf_tasks(self) -> List[Task]:
        """返回所有不被其他任务依赖的叶子任务"""
        all_ids = {t.task_id for t in self.tasks}
        referenced = set()
        for t in self.tasks:
            for dep_id in t.depends_on:
                referenced.add(dep_id)
        leaf_ids = all_ids - referenced
        return [t for t in self.tasks if t.task_id in leaf_ids]

    @property
    def summary(self) -> str:
        """生成计划摘要（用于日志/tracing）"""
        lines = [f"WorkflowPlan: {self.task_count} 个任务"]
        for t in self.tasks:
            dep_str = f" ← [{', '.join(f'#{d}' for d in t.depends_on)}]" if t.depends_on else ""
            lines.append(f"  #{t.task_id} [{t.agent_role}] {t.title}{dep_str}")
        return "\n".join(lines)
