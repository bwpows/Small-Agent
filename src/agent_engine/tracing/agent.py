"""
Agent 执行追踪器 (AgentTracer)
================================

把 trace span 创建、审计日志(audit_log)、guard span 等横切关注点
从 base_agent.py 中完全抽离，让 agent 代码只关注 ReAct 循环的业务逻辑。

设计原则:
  - Agent 只管「做什么」，AgentTracer 管「怎么记录」
  - 所有 span 命名和结构保持不变，仅迁移归属
  - audit_log 由 AgentTracer 内部管理，finish() 时自动汇总到 agent_span

用法:
    # 在 execute() 中
    self._tracer = AgentTracer(agent_name, instruction, prior_context)
    try:
        result = self._execute_impl(...)
        self._tracer.finish(result)
        return result
    except Exception as e:
        self._tracer.finish(error=e)
        return f"❌ ..."

    # 在 _execute_impl() 的每一步中
    self._tracer.step_start(step)
    with self._tracer.llm_span(step, model_name, msg_count) as llm_span:
        response = client.chat.completions.create(...)
        llm_span.set_output({...})
    ...
    self._tracer.log_tool_call(func_name, args)
    ...
    with self._tracer.tool_span(step, func_name, args) as tool_span:
        result = execute_tool(func_name, args)
        tool_span.set_output({...})
    self._tracer.step_end("continue", tool_result=result, nudge_type="general")
"""

import time
import datetime
from typing import Any, Optional

from agent_engine.tracing.engine import (
    SpanKind,
    trace_span,
    get_tracer,
    start_agent_trace,
    finish_agent_trace,
)


class AgentTracer:
    """管理单个 Agent 执行的完整追踪：Trace、Agent Span、审计日志"""

    def __init__(self, agent_name: str, instruction: str, prior_context: str = ""):
        self.agent_name = agent_name

        # ── 创建独立的 Agent Trace（子线程安全）──
        self._trace = start_agent_trace(agent_name, instruction, prior_context)

        # ── 创建 agent span ──
        self._tracer = get_tracer()
        self._agent_span = self._tracer.start_span(
            name=f"agent::{agent_name}",
            kind=SpanKind.AGENT,
            inputs={
                "instruction": instruction[:300],
                "prior_context": (prior_context or "")[:200],
            },
            metadata={
                "agent_name": agent_name,
                "trace_id": self._trace.trace_id,
            },
        )

        # ── 审计日志 ──
        self.audit_log: list = []

        # ── 当前步骤的临时状态 ──
        self._step_start: float = 0.0
        self._step_entry: Optional[dict] = None

    # ═══════════════════════════════════════════════
    # 步骤生命周期
    # ═══════════════════════════════════════════════

    def step_start(self, step: int):
        """开始新一步 ReAct 循环"""
        self._step_start = time.time()
        self._step_entry = {
            "step": step + 1,
            "timestamp": datetime.datetime.now().isoformat(),
            "tool_name": None,
            "tool_args": None,
            "tool_result_preview": None,
            "guard": None,            # "repeat_fuse" / "hallucination_block" / "force_break"
            "nudge_type": None,       # "confirm" / "read" / "general"
            "llm_tool_call": False,
            "result_action": None,    # "return" / "continue" / "fuse" / "error"
        }

    def step_end(self, result_action: str, *,
                 tool_result: Any = None,
                 nudge_type: str = None,
                 guard: str = None):
        """结束当前步骤，将 step_entry 写入 audit_log"""
        if self._step_entry is None:
            return
        self._step_entry["result_action"] = result_action
        self._step_entry["duration_ms"] = round((time.time() - self._step_start) * 1000, 1)
        if nudge_type:
            self._step_entry["nudge_type"] = nudge_type
        if guard:
            self._step_entry["guard"] = guard
        if tool_result is not None:
            self._step_entry["tool_result_preview"] = str(tool_result)[:300]
        self.audit_log.append(self._step_entry)
        self._step_entry = None

    def step_error(self, error: Exception):
        """记录步骤异常"""
        if self._step_entry is None:
            return
        self._step_entry["guard"] = "exception"
        self._step_entry["result_action"] = "error"
        self._step_entry["error"] = str(error)[:300]
        self._step_entry["duration_ms"] = round((time.time() - self._step_start) * 1000, 1)
        self.audit_log.append(self._step_entry)
        self._step_entry = None

    # ═══════════════════════════════════════════════
    # 工具调用信息
    # ═══════════════════════════════════════════════

    def log_tool_call(self, func_name: str, args: dict):
        """记录 LLM 本轮决定调用的工具（写入 step_entry）"""
        if self._step_entry is not None:
            self._step_entry["tool_name"] = func_name
            self._step_entry["tool_args"] = args
            self._step_entry["llm_tool_call"] = True

    # ═══════════════════════════════════════════════
    # Span 上下文管理器（供 agent 用 with 语句包裹）
    # ═══════════════════════════════════════════════

    def llm_span(self, step: int, model_name: str = "", msg_count: int = 0):
        """返回 LLM 调用的 trace span 上下文管理器"""
        return trace_span(
            f"step{step + 1}_llm::{self.agent_name}",
            kind=SpanKind.LLM,
            inputs={"step": step + 1, "msg_count": msg_count, "model": model_name},
            metadata={"agent": self.agent_name},
        )

    def tool_span(self, step: int, func_name: str, args: dict = None):
        """返回工具执行的 trace span 上下文管理器"""
        return trace_span(
            f"step{step + 1}_tool::{func_name}",
            kind=SpanKind.TOOL,
            inputs={"step": step + 1, "tool": func_name, "args": args},
            metadata={"agent": self.agent_name},
        )

    def guard_span(self, step: int, guard_name: str, **inputs):
        """
        守卫触发的瞬时 span（立即进入并退出）。
        用于标记 repeat_fuse / hallucination 等安全拦截事件。
        """
        span_ctx = trace_span(
            f"step{step + 1}_guard_{guard_name}",
            kind=SpanKind.INTERNAL,
            inputs={"step": step + 1, **inputs},
            metadata={"agent": self.agent_name},
        )
        span_ctx.__enter__()
        span_ctx.__exit__(None, None, None)

    # ═══════════════════════════════════════════════
    # 熔断记录
    # ═══════════════════════════════════════════════

    def log_fuse(self, max_loops: int, called_tools: dict):
        """记录 ReAct 循环达到上限被强制熔断"""
        fuse_step = {
            "step": max_loops + 1,
            "timestamp": datetime.datetime.now().isoformat(),
            "guard": "force_break",
            "result_action": "fuse",
            "detail": f"ReAct 循环达到最大次数 {max_loops}，强制熔断",
            "called_tools_summary": {k: v for k, v in called_tools.items()},
            "total_steps": max_loops,
        }
        self.audit_log.append(fuse_step)

    # ═══════════════════════════════════════════════
    # 完成 & 落盘
    # ═══════════════════════════════════════════════

    def finish(self, result: str = "", error: Exception = None):
        """
        结束 Agent 追踪：
        1. 从 audit_log 汇总 agent_span 的输出
        2. 结束 agent_span
        3. 落盘独立 Trace
        """
        if error:
            self._tracer.end_span(self._agent_span, error=error)
        else:
            self._agent_span.set_output({
                "result_preview": (result or "")[:500],
                "audit_steps": len(self.audit_log),
                "tools_called": [
                    s.get("tool_name") for s in self.audit_log if s.get("tool_name")
                ],
                "guards_triggered": [
                    s.get("guard") for s in self.audit_log if s.get("guard")
                ],
                "total_duration_ms": self._agent_span.duration_ms(),
                "trace_id": self._trace.trace_id,
            })
            self._tracer.end_span(self._agent_span, output=(result or "")[:500])

        # 落盘独立 Trace
        finish_agent_trace(self._trace)
