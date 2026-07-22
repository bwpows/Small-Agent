"""
调用链追踪引擎 (Tracing Engine)
================================
参考 OpenTelemetry 语义化设计，单文件零依赖的轻量级追踪框架。

核心概念:
  Trace  - 一次完整的用户请求（包含多个 Span）
  Span   - 一个执行单元（可嵌套，自动计时 + 错误捕获 + 输入/输出快照）
  Tracer - 全局单例，负责 Span 生命周期管理、上下文传播、持久化

上下文传播:
  使用 Python contextvars 实现线程安全 + asyncio 安全的上下文传递，
  ThreadPoolExecutor 子线程可自动继承父线程的 Trace 上下文。

存储:
  - JSONL 文件: data/workspace/.traces/trace_YYYY-MM-DD.jsonl
  - 内存环形缓冲: 最近 N 条 Trace（供 UI 实时展示）

使用方式:
  方案 A - 装饰器:
      @trace_span("llm_chat")
      def call_llm(messages): ...

  方案 B - 上下文管理器:
      with trace_span("tool_exec", kind="TOOL", inputs={"name": fn}):
          result = do_work()

  方案 C - 手动 API:
      tracer = get_tracer()
      span = tracer.start_span("my_op")
      try:
          ...
          span.set_output(result)
      except Exception as e:
          span.record_error(e)
          raise
      finally:
          tracer.end_span(span)
"""

from __future__ import annotations

import contextvars
import time
import uuid
import json
import os
import sys
import threading
import traceback
import functools
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Optional, Dict, List
from collections import deque


# ═══════════════════════════════════════════════
# 枚举定义
# ═══════════════════════════════════════════════

class SpanKind(str, Enum):
    """Span 类型（对齐 OpenTelemetry 语义）"""
    ENTRY     = "ENTRY"       # 请求入口（用户输入 → 系统响应）
    PLANNER   = "PLANNER"     # 任务规划
    AGENT     = "AGENT"       # Agent 执行
    LLM       = "LLM"         # LLM API 调用
    TOOL      = "TOOL"        # 工具调用
    SANDBOX   = "SANDBOX"     # 沙箱执行
    DAG       = "DAG"         # DAG 调度
    INTERNAL  = "INTERNAL"    # 内部逻辑


class SpanStatus(str, Enum):
    UNSET = "UNSET"
    OK    = "OK"
    ERROR = "ERROR"


class TraceStatus(str, Enum):
    RUNNING  = "RUNNING"
    OK       = "OK"
    ERROR    = "ERROR"


# ═══════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════

@dataclass
class Span:
    """一个执行单元"""
    span_id:          str
    trace_id:         str
    parent_span_id:   Optional[str]
    name:             str
    kind:             SpanKind          = SpanKind.INTERNAL
    start_time:       float             = 0.0
    end_time:         Optional[float]   = None
    status:           SpanStatus        = SpanStatus.UNSET
    inputs:           Optional[Any]     = None      # 序列化后的输入快照
    outputs:          Optional[Any]     = None      # 序列化后的输出快照
    error:            Optional[str]     = None      # 错误摘要
    error_traceback:  Optional[str]     = None
    attributes:       Dict[str, Any]    = field(default_factory=dict)
    metadata:         Dict[str, Any]    = field(default_factory=dict)
    sub_spans:        List[Span]        = field(default_factory=list)  # 子 Span（仅根 Span 持有）

    def duration_ms(self) -> float:
        if self.end_time is None:
            return round((time.time() - self.start_time) * 1000, 2)
        return round((self.end_time - self.start_time) * 1000, 2)

    def set_output(self, data: Any, max_chars: int = 2000):
        self.outputs = _safe_truncate(data, max_chars)
        if self.end_time is None:
            self.end_time = time.time()
        if self.status == SpanStatus.UNSET:
            self.status = SpanStatus.OK

    def record_error(self, exc: Exception):
        self.status = SpanStatus.ERROR
        self.error = f"{type(exc).__name__}: {exc}"
        self.error_traceback = traceback.format_exc()
        if self.end_time is None:
            self.end_time = time.time()

    def flatten(self) -> List[dict]:
        """递归展平 Span 树为列表，便于展示"""
        result = [self._to_dict()]
        for child in self.sub_spans:
            result.extend(child.flatten())
        return result

    def _to_dict(self) -> dict:
        return {
            "span_id":         self.span_id,
            "trace_id":        self.trace_id,
            "parent_span_id":  self.parent_span_id,
            "name":            self.name,
            "kind":            self.kind.value if isinstance(self.kind, SpanKind) else self.kind,
            "start_time":      self.start_time,
            "end_time":        self.end_time,
            "duration_ms":     self.duration_ms(),
            "status":          self.status.value if isinstance(self.status, SpanStatus) else self.status,
            "inputs":          self.inputs,
            "outputs":         self.outputs,
            "error":           self.error,
            "error_traceback": self.error_traceback,
            "attributes":      self.attributes,
            "metadata":        self.metadata,
        }


@dataclass
class Trace:
    """一次完整的用户请求"""
    trace_id:      str
    user_input:    str                         = ""
    start_time:    float                       = 0.0
    end_time:      Optional[float]             = None
    status:        TraceStatus                 = TraceStatus.RUNNING
    root_spans:    List[Span]                  = field(default_factory=list)  # 顶层 Span 列表
    metadata:      Dict[str, Any]              = field(default_factory=dict)
    session_id:    str                         = ""

    def total_duration_ms(self) -> float:
        if self.end_time is None:
            return round((time.time() - self.start_time) * 1000, 2)
        return round((self.end_time - self.start_time) * 1000, 2)

    def span_count(self) -> int:
        return sum(len(s.flatten()) for s in self.root_spans)

    def error_count(self) -> int:
        return sum(
            1 for s in self.flatten_all_spans()
            if s.get("status") == "ERROR"
        )

    def flatten_all_spans(self) -> List[dict]:
        """展平所有 root span 及其子树"""
        result = []
        for rs in self.root_spans:
            result.extend(rs.flatten())
        return result

    def to_dict(self) -> dict:
        return {
            "trace_id":      self.trace_id,
            "session_id":    self.session_id,
            "user_input":    self.user_input[:500],
            "start_time":    self.start_time,
            "end_time":      self.end_time,
            "duration_ms":   self.total_duration_ms(),
            "status":        self.status.value,
            "span_count":    self.span_count(),
            "error_count":   self.error_count(),
            "metadata":      self.metadata,
            "root_spans":    [rs._to_dict() for rs in self.root_spans],
            "spans_flat":    self.flatten_all_spans(),
        }


# ═══════════════════════════════════════════════
# 上下文传播 (contextvars)
# ═══════════════════════════════════════════════

# 当前活跃的 Trace（每个线程/协程独立）
_current_trace:   contextvars.ContextVar[Optional[Trace]]  = contextvars.ContextVar("_current_trace", default=None)
# 当前活跃的 Span 栈（支持嵌套）
_active_span:     contextvars.ContextVar[Optional[Span]]    = contextvars.ContextVar("_active_span", default=None)


# ═══════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════

def _safe_truncate(data: Any, max_chars: int) -> Any:
    """安全截断过大的输出，防止 JSONL 膨胀"""
    if data is None:
        return None
    if isinstance(data, str):
        return data[:max_chars] + ("...[截断]" if len(data) > max_chars else "")
    try:
        s = json.dumps(data, ensure_ascii=False, default=str)
        if len(s) <= max_chars:
            return data
        return {"_raw_len": len(s), "_preview": s[:max_chars] + "...[截断]"}
    except Exception:
        return str(data)[:max_chars] + "...[截断]"


def _redact_sensitive(data: Any, keys: set = None) -> Any:
    """脱敏敏感字段（API key, token 等）"""
    if keys is None:
        keys = {"api_key", "token", "password", "secret", "authorization", "key"}
    if isinstance(data, dict):
        return {k: "[REDACTED]" if k.lower() in keys else _redact_sensitive(v, keys) for k, v in data.items()}
    if isinstance(data, list):
        return [_redact_sensitive(v, keys) for v in data]
    return data


def _short_id() -> str:
    """16 字符短 ID，便于在日志中阅读"""
    return uuid.uuid4().hex[:16]


# ═══════════════════════════════════════════════
# 存储引擎
# ═══════════════════════════════════════════════

class TraceStorage:
    """双层存储：内存环形缓冲 + JSONL 文件持久化"""

    def __init__(self, storage_dir: str, max_in_memory: int = 50):
        self.storage_dir = storage_dir
        self.max_in_memory = max_in_memory
        self._buffer: deque[dict] = deque(maxlen=max_in_memory)
        self._lock = threading.Lock()
        os.makedirs(storage_dir, exist_ok=True)

    def _today_jsonl(self) -> str:
        from datetime import datetime
        return os.path.join(self.storage_dir, f"trace_{datetime.now().strftime('%Y-%m-%d')}.jsonl")

    def save(self, trace: Trace):
        """保存一条 Trace 到双层存储"""
        record = trace.to_dict()
        with self._lock:
            self._buffer.append(record)
        # JSONL 追加
        try:
            with open(self._today_jsonl(), "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass  # 落盘失败不影响主流程

    def latest(self, n: int = 20) -> List[dict]:
        """返回最近 n 条 Trace（倒序）"""
        with self._lock:
            return list(reversed(self._buffer))[:n]

    def load_from_file(self, filename: str) -> List[dict]:
        """从 JSONL 文件加载历史 Trace"""
        filepath = os.path.join(self.storage_dir, filename)
        if not os.path.exists(filepath):
            return []
        traces = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        traces.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return traces

    def list_files(self) -> List[str]:
        """列出所有 JSONL 文件"""
        if not os.path.exists(self.storage_dir):
            return []
        files = sorted(
            [f for f in os.listdir(self.storage_dir) if f.endswith(".jsonl")],
            reverse=True
        )
        return files


# ═══════════════════════════════════════════════
# Tracer - 核心引擎
# ═══════════════════════════════════════════════

class Tracer:
    """
    全局追踪器（单例）

    管理工作：
      - Trace 生命周期（创建 / 结束）
      - Span 生命周期（创建 / 压栈 / 出栈 / 结束）
      - contextvars 上下文传播
      - 持久化存储
    """

    def __init__(self, storage: TraceStorage):
        self.storage = storage
        self.enabled = True
        self._lock = threading.Lock()

    # ── Trace 管理 ──────────────────────────

    def start_trace(self, user_input: str = "", metadata: dict = None, session_id: str = "") -> Trace:
        """创建一条新 Trace 并设为当前活跃"""
        trace = Trace(
            trace_id=_short_id(),
            user_input=user_input,
            start_time=time.time(),
            metadata=metadata or {},
            session_id=session_id,
        )
        _current_trace.set(trace)
        return trace

    def end_trace(self, trace: Trace = None):
        """结束 Trace，标记状态并落盘"""
        if trace is None:
            trace = _current_trace.get()
        if trace is None:
            return
        trace.end_time = time.time()
        # 汇总状态
        if trace.error_count() > 0:
            trace.status = TraceStatus.ERROR
        else:
            trace.status = TraceStatus.OK
        # 持久化
        if self.enabled:
            self.storage.save(trace)
        # 清理上下文
        _current_trace.set(None)
        _active_span.set(None)

    # ── Span 管理 ──────────────────────────

    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        inputs: Any = None,
        attributes: dict = None,
        metadata: dict = None,
        parent_span: Span = None,
    ) -> Span:
        """创建并开启一个 Span，自动挂到当前 Span 下"""
        if not self.enabled:
            return _NOOP_SPAN

        trace = _current_trace.get()
        parent = parent_span or _active_span.get()

        if trace is None:
            # 没有 Trace 时自动创建（确保任何时候都能追踪）
            trace = self.start_trace()
            _current_trace.set(trace)

        span = Span(
            span_id=_short_id(),
            trace_id=trace.trace_id,
            parent_span_id=parent.span_id if parent else None,
            name=name,
            kind=kind,
            start_time=time.time(),
            inputs=_safe_truncate(inputs, 2000),
            attributes=attributes or {},
            metadata=metadata or {},
        )

        # 挂到父 Span 的子列表
        if parent:
            parent.sub_spans.append(span)
        else:
            # 没有父 Span → 这是顶层 Span，追加到 root_spans
            trace.root_spans.append(span)

        # 设为当前活跃 Span
        _active_span.set(span)
        return span

    def end_span(self, span: Span, output: Any = None, error: Exception = None):
        """结束一个 Span，恢复父 Span"""
        if span is _NOOP_SPAN:
            return

        span.end_time = time.time()

        if error:
            span.record_error(error)
        elif output is not None:
            span.set_output(_safe_truncate(output, 5000))

        if span.status == SpanStatus.UNSET:
            span.status = SpanStatus.OK

        # 恢复到父 Span
        current = _active_span.get()
        if current and current.span_id == span.span_id:
            # 找到父 Span 并恢复
            parent = self._find_parent(span)
            _active_span.set(parent)

    def _find_parent(self, span: Span) -> Optional[Span]:
        """在 Trace 树中查找 Span 的父节点"""
        trace = _current_trace.get()
        if trace is None or not trace.root_spans:
            return None
        return self._find_by_id(trace.root_spans, span.parent_span_id)

    def _find_by_id(self, spans: List[Span], target_id: str) -> Optional[Span]:
        for s in spans:
            if s.span_id == target_id:
                return s
            found = self._find_by_id(s.sub_spans, target_id)
            if found:
                return found
        return None

    # ── 获取当前状态 ──────────────────────

    def current_trace(self) -> Optional[Trace]:
        return _current_trace.get()

    def current_span(self) -> Optional[Span]:
        return _active_span.get()

    # ── 查询接口 ──────────────────────────

    def latest_traces(self, n: int = 20) -> List[dict]:
        return self.storage.latest(n)

    def load_history(self, filename: str) -> List[dict]:
        return self.storage.load_from_file(filename)

    def list_history_files(self) -> List[str]:
        return self.storage.list_files()


# ═══════════════════════════════════════════════
# 空 Span（用于 enabled=False 时避免大量 if 判断）
# ═══════════════════════════════════════════════

class _NoopSpan:
    span_id = "noop"
    trace_id = "noop"
    parent_span_id = None
    name = "noop"
    kind = SpanKind.INTERNAL
    start_time = 0.0
    end_time = None
    status = SpanStatus.UNSET
    inputs = None
    outputs = None
    error = None
    error_traceback = None
    attributes = {}
    metadata = {}
    sub_spans = []

    def set_output(self, data: Any, **kw): pass
    def record_error(self, exc: Exception): pass
    def flatten(self): return []
    def _to_dict(self): return {}
    def duration_ms(self): return 0.0

_NOOP_SPAN = _NoopSpan()


# ═══════════════════════════════════════════════
# 装饰器 & 上下文管理器 API
# ═══════════════════════════════════════════════

class trace_span:
    """
    Span 上下文管理器 + 装饰器（二合一）

    用法 1 - 上下文管理器:
        with trace_span("tool_search", kind="TOOL", inputs={"query": q}) as span:
            result = search(q)
            span.set_output(result)

    用法 2 - 装饰器:
        @trace_span("generate_plan", kind="PLANNER")
        def generate_plan(user_goal):
            ...
    """

    def __init__(
        self,
        name: str,
        kind: SpanKind | str = SpanKind.INTERNAL,
        capture_input: bool = True,
        capture_output: bool = True,
        capture_error: bool = True,
        inputs: Any = None,
        attributes: dict = None,
        metadata: dict = None,
    ):
        if isinstance(kind, str):
            kind = SpanKind(kind)
        self.name = name
        self.kind = kind
        self._capture_input   = capture_input
        self._capture_output  = capture_output
        self._capture_error   = capture_error
        self._inputs          = inputs
        self._attributes      = attributes or {}
        self._metadata        = metadata or {}
        self._span: Span = None
        self._tracer: Tracer = None

    # ── 上下文管理器协议 ──────────────────

    def __enter__(self) -> Span:
        self._tracer = get_tracer()
        self._span = self._tracer.start_span(
            name=self.name,
            kind=self.kind,
            inputs=self._inputs,
            attributes=self._attributes,
            metadata=self._metadata,
        )
        return self._span

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._span is None:
            return
        if exc_type and self._capture_error:
            self._span.record_error(exc_val)
        if self._span.status == SpanStatus.UNSET:
            self._span.status = SpanStatus.OK if not exc_type else SpanStatus.ERROR
        self._tracer.end_span(self._span)
        # 不吞噬异常
        return False

    # ── 装饰器协议 ─────────────────────────

    def __call__(self, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer()
            # 捕获输入
            inputs = None
            if self._capture_input:
                try:
                    inputs_map = {}
                    if args:
                        inputs_map["args"] = _safe_truncate(str(args), 500)
                    if kwargs:
                        inputs_map["kwargs"] = _safe_truncate(kwargs, 2000)
                    if inputs_map:
                        inputs = inputs_map
                except Exception:
                    pass

            span = tracer.start_span(
                name=self.name,
                kind=self.kind,
                inputs=inputs,
                attributes=self._attributes,
                metadata=self._metadata,
            )
            try:
                result = func(*args, **kwargs)
                if self._capture_output:
                    span.set_output(_safe_truncate(result, 5000))
                return result
            except Exception as e:
                if self._capture_error:
                    span.record_error(e)
                raise
            finally:
                tracer.end_span(span)

        # 保留对原始函数的引用
        wrapper.__wrapped__ = func  # type: ignore
        return wrapper


# ═══════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════

_tracer_instance: Optional[Tracer] = None
_tracer_lock = threading.Lock()


def get_tracer() -> Tracer:
    """获取全局 Tracer 实例（懒加载）"""
    global _tracer_instance
    if _tracer_instance is not None:
        return _tracer_instance
    with _tracer_lock:
        if _tracer_instance is not None:
            return _tracer_instance
        # 确定存储目录
        try:
            from agent_engine.config import TRACE_STORAGE_DIR
            storage_dir = TRACE_STORAGE_DIR
        except ImportError:
            storage_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                "data", "workspace", ".traces"
            )
        storage = TraceStorage(storage_dir=storage_dir)
        _tracer_instance = Tracer(storage=storage)
        # 是否启用
        try:
            from agent_engine.config import TRACE_ENABLED
            _tracer_instance.enabled = TRACE_ENABLED
        except ImportError:
            _tracer_instance.enabled = True
        return _tracer_instance


def reset_tracer():
    """测试/重启时重置 Tracer"""
    global _tracer_instance
    _tracer_instance = None


# ═══════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════

def trace_request(user_input: str = "", session_id: str = "", metadata: dict = None) -> Trace:
    """快捷入口：开始一次请求追踪"""
    tracer = get_tracer()
    return tracer.start_trace(user_input=user_input, session_id=session_id, metadata=metadata)


def finish_trace(trace: Trace = None):
    """快捷出口：结束当前请求追踪并落盘"""
    tracer = get_tracer()
    tracer.end_trace(trace)


def current_trace() -> Optional[Trace]:
    return get_tracer().current_trace()


# ═══════════════════════════════════════════════
# 子线程安全的 Agent 独立 Trace
# ═══════════════════════════════════════════════

def start_agent_trace(agent_name: str, instruction: str, prior_context: str = "") -> Trace:
    """
    为 Agent（可能在子线程中执行）创建一个独立的 Trace。
    
    解决子线程中 contextvars 可能未正确传播的问题：
    - 不依赖当前上下文中的 Trace
    - 显式创建新 Trace 并直接返回 Trace 对象
    - Agent 完成后调用 finish_agent_trace() 落盘
    
    使用方式:
        agent_trace = start_agent_trace("GoogleDrive", instruction)
        try:
            with trace_span_on_trace(agent_trace, "agent::GoogleDrive", ...) as span:
                result = do_work()
                span.set_output(result)
        finally:
            finish_agent_trace(agent_trace)
    """
    tracer = get_tracer()
    # 强制创建独立 Trace，不依赖 contextvars
    trace = Trace(
        trace_id=_short_id(),
        user_input=instruction[:500],
        start_time=time.time(),
        metadata={
            "agent_name": agent_name,
            "prior_context": (prior_context or "")[:200],
            "phase": "agent_execution",
        },
    )
    _current_trace.set(trace)
    _active_span.set(None)  # 清除可能残留的父 span，确保 agent span 是 root
    return trace


def finish_agent_trace(trace: Trace):
    """结束 Agent 独立 Trace 并落盘"""
    tracer = get_tracer()
    if trace.end_time is None:
        trace.end_time = time.time()
    # 汇总状态
    if trace.error_count() > 0:
        trace.status = TraceStatus.ERROR
    else:
        trace.status = TraceStatus.OK
    # 持久化（绕过 contextvars，直接保存）
    if tracer.enabled:
        tracer.storage.save(trace)
    # 清理当前线程的上下文（如果存在）
    try:
        _current_trace.set(None)
        _active_span.set(None)
    except Exception:
        pass


def trace_span_on_trace(trace: Trace, name: str, kind: SpanKind = SpanKind.INTERNAL,
                         inputs: Any = None, metadata: dict = None) -> trace_span:
    """
    在指定的 Trace 对象上创建 Span 的上下文管理器。
    不依赖 contextvars，直接操作传入的 trace。
    适用于子线程中 Agent 的独立 Trace。
    """
    # 将 trace 设为当前上下文
    _current_trace.set(trace)
    return trace_span(name=name, kind=kind, inputs=inputs, metadata=metadata, capture_input=inputs is None)
