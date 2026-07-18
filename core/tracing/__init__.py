"""
Tracing 包 —— 调用链追踪引擎 + Agent 执行追踪器

子模块:
  engine  - 核心引擎（Trace / Span / Tracer / trace_span / contextvars 传播 / 存储）
  agent   - Agent 级别的追踪封装（AgentTracer：审计日志 + step 记录 + guard span）
"""

# ── 核心引擎（engine.py）──
from core.tracing.engine import (
    # 枚举
    SpanKind,
    SpanStatus,
    TraceStatus,
    # 数据模型
    Span,
    Trace,
    # 存储
    TraceStorage,
    # 引擎
    Tracer,
    get_tracer,
    reset_tracer,
    # 上下文管理器 & 装饰器
    trace_span,
    # 便捷函数
    trace_request,
    finish_trace,
    current_trace,
    # 子线程安全的 Agent 独立 Trace
    start_agent_trace,
    finish_agent_trace,
    trace_span_on_trace,
)

# ── Agent 追踪器（agent.py）──
from core.tracing.agent import AgentTracer
