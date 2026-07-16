"""
追踪查看器 Streamlit UI 组件
===============================
在侧边栏展示最近的调用链追踪记录，支持：
  - 时间轴视图（显示每个 Span 的耗时和状态）
  - 层级树展开（Trace → Span → 子 Span）
  - 错误详情查看（异常类型 + traceback）
  - 输入/输出快照
  - 历史 JSONL 文件加载
"""

import streamlit as st
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from core.tracing import get_tracer


# ── 常量和样式 ──────────────────────────────

KIND_COLORS = {
    "ENTRY":    "#6366F1",   # Indigo
    "PLANNER":  "#8B5CF6",   # Violet
    "AGENT":    "#F59E0B",   # Amber
    "LLM":      "#3B82F6",   # Blue
    "TOOL":     "#10B981",   # Emerald
    "SANDBOX":  "#EF4444",   # Red
    "DAG":      "#F97316",   # Orange
    "INTERNAL": "#6B7280",   # Gray
}

STATUS_ICONS = {
    "OK":    "✅",
    "ERROR": "❌",
    "UNSET": "⚪",
    "RUNNING": "⏳",
}


def render_trace_viewer():
    """
    在 Streamlit 中渲染完整的追踪查看器。
    放在 sidebar 中调用。
    """
    tracer = get_tracer()

    st.subheader("🔍 调用链追踪 (Tracing)")

    # Tracer 开关
    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption(f"状态: {'🟢 已启用' if tracer.enabled else '🔴 已禁用'}")
    with col2:
        if st.button("刷新", key="refresh_traces", use_container_width=True):
            st.rerun()

    # ── Tab: 实时 / 历史 ──────────────────
    tab1, tab2 = st.tabs(["📊 最新记录", "📁 历史文件"])

    with tab1:
        _render_latest_traces(tracer)

    with tab2:
        _render_history_tab(tracer)


def _render_latest_traces(tracer):
    """渲染内存中的最新 Trace 列表"""
    traces = tracer.latest_traces(20)

    if not traces:
        st.info("暂无追踪记录。执行一次请求后会自动出现。")
        return

    st.caption(f"最近 {len(traces)} 条记录")

    for i, trace in enumerate(traces):
        _render_trace_card(trace, idx=i)


def _render_trace_card(trace: dict, idx: int):
    """渲染单条 Trace 卡片"""
    trace_id = trace.get("trace_id", "?")
    status = trace.get("status", "UNSET")
    duration = trace.get("duration_ms", 0)
    user_input = trace.get("user_input", "")[:80]
    span_count = trace.get("span_count", 0)
    error_count = trace.get("error_count", 0)
    start_ts = trace.get("start_time", 0)
    start_str = datetime.fromtimestamp(start_ts).strftime("%H:%M:%S") if start_ts else "?"

    status_icon = STATUS_ICONS.get(status, "⚪")
    error_badge = f" {error_count}个错误" if error_count else ""

    # 根据状态着色
    if status == "ERROR":
        header_color = "#FEE2E2"
        emoji = "🔴"
    elif error_count:
        header_color = "#FEF3C7"
        emoji = "🟡"
    else:
        header_color = "#D1FAE5"
        emoji = "🟢"

    expander_title = f"{emoji} [{start_str}] {duration:.0f}ms | {span_count} spans {error_badge}「{user_input}」"

    with st.expander(expander_title, expanded=False):
        # 摘要行
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("耗时", f"{duration:.0f}ms")
        col_b.metric("Span 数", span_count)
        col_c.metric("错误数", error_count)
        col_d.metric("会话", trace.get("session_id", "-")[:12] or "-")

        st.divider()

        # ── 时间轴 ──────────────────────────
        spans_flat: List[dict] = trace.get("spans_flat", [])
        if not spans_flat:
            st.caption("无 Span 数据")
            return

        _render_waterfall(spans_flat, duration)

        # ── Span 详情列表 ──────────────────
        st.markdown("**📋 Span 详情:**")
        for span in spans_flat:
            _render_span_detail(span)


def _render_waterfall(spans: List[dict], total_duration: float):
    """渲染瀑布图/时间轴"""
    if total_duration <= 0:
        total_duration = 1

    st.markdown("**⏱️ 时间轴 (瀑布图):**")

    # 构建 HTML 瀑布图
    rows = ["<div style='font-family:monospace;font-size:12px;line-height:1.8;'>"]
    rows.append(
        "<div style='display:flex;color:#888;border-bottom:1px solid #333;padding-bottom:4px;margin-bottom:4px;'>"
        "<span style='width:260px;'>Span Name</span>"
        "<span style='width:80px;text-align:right;'>耗时</span>"
        "<span style='flex:1;'>时间轴</span>"
        "</div>"
    )

    for span in spans:
        name = span.get("name", "?")
        kind = span.get("kind", "INTERNAL")
        color = KIND_COLORS.get(kind, "#666")
        status = span.get("status", "UNSET")
        s_icon = STATUS_ICONS.get(status, "⚪")
        dur = span.get("duration_ms", 0)
        dur_label = f"{dur:.0f}ms" if dur > 1 else f"<1ms"
        error = span.get("error", "")

        # 计算条形宽度
        bar_pct = min(dur / total_duration * 100, 100)
        bar_pct = max(bar_pct, 1)  # 至少 1% 可见

        if error:
            color = "#EF4444"

        rows.append(
            "<div style='display:flex;align-items:center;margin:1px 0;'>"
            f"<span style='width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>{s_icon} {name}</span>"
            f"<span style='width:80px;text-align:right;font-size:11px;'>{dur_label}</span>"
            "<span style='flex:1;background:#1a1a2e;border-radius:3px;height:12px;position:relative;'>"
            f"<span style='position:absolute;left:0;top:0;height:100%;width:{bar_pct}%;background:{color};border-radius:3px;opacity:0.8;min-width:3px;'></span>"
            "</span>"
            "</div>"
        )

    rows.append("</div>")
    st.markdown("".join(rows), unsafe_allow_html=True)


def _render_span_detail(span: dict):
    """渲染单个 Span 的详细信息"""
    span_id = span.get("span_id", "")[:8]
    name = span.get("name", "?")
    kind = span.get("kind", "INTERNAL")
    status = span.get("status", "UNSET")
    dur = span.get("duration_ms", 0)
    color = KIND_COLORS.get(kind, "#666")
    s_icon = STATUS_ICONS.get(status, "⚪")

    with st.container(border=True):
        # Header
        st.markdown(
            f"<span style='background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:11px;'>{kind}</span> "
            f"**{name}** "
            f"{s_icon} `{dur:.0f}ms` "
            f"<small style='color:#888;'>(id: {span_id})</small>",
            unsafe_allow_html=True
        )

        # 错误信息
        if span.get("error"):
            st.error(f"**{span['error']}**")
            if span.get("error_traceback"):
                with st.expander("📋 完整 Traceback", expanded=False):
                    st.code(span["error_traceback"], language="python")

        # 输入/输出
        cols = st.columns(2)
        with cols[0]:
            inp = span.get("inputs")
            if inp:
                with st.expander("📥 输入", expanded=False):
                    st.json(inp, expanded=False)

        with cols[1]:
            out = span.get("outputs")
            if out:
                with st.expander("📤 输出", expanded=False):
                    if isinstance(out, str) and len(out) < 500:
                        st.text(out)
                    elif isinstance(out, str):
                        st.text(out[:500] + "\n...(截断)")
                    else:
                        st.json(out, expanded=False)

        # 属性
        attrs = span.get("attributes") or span.get("metadata")
        if attrs:
            with st.expander("🏷️ 标签", expanded=False):
                st.json(attrs, expanded=False)


def _render_history_tab(tracer):
    """渲染历史文件 Tab"""
    files = tracer.list_history_files()

    if not files:
        st.info("暂无历史追踪文件。")
        return

    selected = st.selectbox("选择日期:", files, key="trace_file_selector")

    if selected and st.button("📂 加载", key="load_trace_file"):
        traces = tracer.load_history(selected)
        if not traces:
            st.warning("文件为空或格式错误。")
            return

        st.caption(f"共 {len(traces)} 条记录")

        for i, trace in enumerate(traces):
            _render_trace_card(trace, idx=1000 + i)


def render_trace_summary_in_chat():
    """
    在对话区域底部显示当前请求的追踪摘要（小徽章形式）。
    可在 st.chat_message 内部调用。
    """
    tracer = get_tracer()
    trace = tracer.current_trace()
    if trace is None:
        return

    dur = trace.total_duration_ms()
    spans = trace.span_count()
    errors = trace.error_count()

    parts = [f"⏱️ {dur:.0f}ms", f"📊 {spans} spans"]
    if errors:
        parts.append(f"❌ {errors} 错误")

    trace_id = trace.trace_id[:8]

    st.caption(
        " | ".join(parts) + f" | `trace:{trace_id}`",
    )
