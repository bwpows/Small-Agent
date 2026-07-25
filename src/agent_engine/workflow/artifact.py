"""
任务产物存储（Artifact Store）
=============================
线程安全的键值存储，支持按 task_id 存取任务执行结果，
并提供 build_prior_context() 为下游任务组装前置上下文。
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Artifact:
    """单个任务的执行产物"""
    task_id: int
    agent_role: str
    output: str
    status: str = "SUCCEEDED"        # SUCCEEDED / FAILED / SKIPPED
    metadata: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        """生成一句话摘要，用于传递给下游任务"""
        return f"[任务#{self.task_id} · {self.agent_role}]:\n{self.output[:2000]}"


class ArtifactStore:
    """
    线程安全的任务产物存储。

    内部使用 threading.Lock 保护写操作，支持多线程并发写入。
    每个任务的产物以 task_id 为 key 存储。

    使用方式:
        store = ArtifactStore()
        store.put(1, Artifact(task_id=1, agent_role="researcher", output="..."))
        ctx = store.build_prior_context([1, 2])  # 组装前置任务上下文
    """

    def __init__(self):
        self._artifacts: Dict[int, Artifact] = {}
        self._lock = threading.Lock()

    def put(self, task_id: int, artifact: Artifact) -> None:
        """存储一个任务的产物（线程安全）"""
        with self._lock:
            self._artifacts[task_id] = artifact

    def get(self, task_id: int) -> Optional[Artifact]:
        """获取指定任务的产物"""
        with self._lock:
            return self._artifacts.get(task_id)

    def get_all(self) -> Dict[int, Artifact]:
        """获取所有产物（返回浅拷贝，避免外部修改）"""
        with self._lock:
            return dict(self._artifacts)

    def build_prior_context(self, depends_on: List[int]) -> str:
        """
        为下游任务组装前置上下文。

        将 depends_on 列表中的 task_id 对应产物的 summary 拼接，
        形成一段完整的「前置情报」，供下游 Agent 使用。

        :param depends_on: 前置任务 ID 列表（如 [1, 2]）
        :return: 格式化后的前置上下文字符串
        """
        if not depends_on:
            return ""

        parts = []
        with self._lock:
            for tid in depends_on:
                artifact = self._artifacts.get(tid)
                if artifact is None:
                    parts.append(f"[任务#{tid}]: （前置任务未产出结果或已跳过）")
                else:
                    parts.append(artifact.summary())

        if not parts:
            return ""

        header = "【📋 前置任务情报汇总】\n" + "─" * 40 + "\n"
        body = "\n\n".join(parts)
        footer = "\n" + "─" * 40 + "\n"
        return header + body + footer

    def __len__(self) -> int:
        with self._lock:
            return len(self._artifacts)

    def __contains__(self, task_id: int) -> bool:
        with self._lock:
            return task_id in self._artifacts
