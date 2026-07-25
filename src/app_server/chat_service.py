"""
Chat 服务编排 — 包装 agent_engine/ 引擎，注入 TenantContext 做多租户隔离。
P0：所有用户共享全局 LLM 配置；后续 P2 接入 user_llm_config 每用户自选引擎。
"""
import os
import time
import json
import uuid
import datetime
import logging
from typing import List, Optional, Generator, AsyncGenerator

from app_server.deps import TenantContext
from app_server.db import get_session, Conversation, Message, utcnow

logger = logging.getLogger("chat_service")

def _ensure_workspace(ctx: TenantContext):
    """确保用户的隔离工作目录存在"""
    os.makedirs(ctx.workspace_root, exist_ok=True)


def get_or_create_conversation(ctx: TenantContext, title: str = "新会话") -> Conversation:
    """获取或创建会话"""
    session = get_session()
    try:
        if ctx.conversation_id:
            conv = session.get(Conversation, ctx.conversation_id)
            if conv:
                return conv
        conv = Conversation(user_id=ctx.user_id, title=title)
        session.add(conv)
        session.commit()
        session.refresh(conv)
        ctx.conversation_id = conv.id
        return conv
    finally:
        session.close()


def load_conversation_history(ctx: TenantContext) -> List[dict]:
    """加载当前会话的历史消息（用于传给 LLM）"""
    if not ctx.conversation_id:
        return []
    session = get_session()
    try:
        messages = (
            session.query(Message)
            .filter(Message.conversation_id == ctx.conversation_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        return [{"role": m.role, "content": m.content} for m in messages]
    finally:
        session.close()


def save_message(
    ctx: TenantContext,
    role: str,
    content: str,
    platform_message_id: Optional[str] = None,
    usage: Optional[dict] = None,
    duration_ms: Optional[int] = None,
    thinking_count: Optional[int] = None,
    reasoning_text: Optional[str] = None,
) -> bool:
    """
    保存一条消息到数据库（含用量指标）。
    如果 platform_message_id 已存在则跳过（幂等去重），返回 False。
    返回 True 表示成功保存。
    """
    if not ctx.conversation_id:
        return False
    session = get_session()
    try:
        # Webhook 幂等去重
        if platform_message_id:
            existing = (
                session.query(Message)
                .filter(Message.platform_message_id == platform_message_id)
                .first()
            )
            if existing:
                logger.info(f"消息已存在（幂等跳过）: {platform_message_id}")
                return False

        kwargs = dict(
            conversation_id=ctx.conversation_id,
            role=role,
            content=content,
            platform_message_id=platform_message_id,
        )
        # assistant 消息才存储指标
        if role == "assistant":
            if usage:
                kwargs["prompt_tokens"] = usage.get("prompt_tokens")
                kwargs["completion_tokens"] = usage.get("completion_tokens")
                kwargs["total_tokens"] = usage.get("total_tokens")
            kwargs["duration_ms"] = duration_ms
            kwargs["thinking_count"] = thinking_count
            kwargs["reasoning_text"] = reasoning_text

        msg = Message(**kwargs)
        session.add(msg)
        # 更新时间戳
        conv = session.get(Conversation, ctx.conversation_id)
        if conv:
            conv.updated_at = utcnow()
        session.commit()
        return True
    except Exception as e:
        logger.error(f"保存消息失败: {e}")
        session.rollback()
        return False
    finally:
        session.close()


def chat_completion(
    ctx: TenantContext,
    user_input: str,
    stream: bool = False,
) -> dict:
    """
    核心聊天方法 — 非流式。
    1. 确保隔离工作目录
    2. 获取/创建会话
    3. 加载历史
    4. 调用 core.llm_engine.generate_answer
    5. 保存消息
    6. 返回 {"content": str, "usage": dict, "reasoning": str}
    """
    _ensure_workspace(ctx)
    get_or_create_conversation(ctx)

    # 保存用户消息
    save_message(ctx, "user", user_input)

    # 加载历史
    history = load_conversation_history(ctx)
    # 去掉刚存的最后一条 user 消息，避免重复（generate_answer 内部会再加一次）
    recent_history = history[:-1] if len(history) > 1 else []

    # 暂时不放长期记忆和搜索（P0 跑通基础链路）
    parsed_memories = []
    web_info = ""

    # 注入 Drive 凭证（多租户）
    _inject_drive_creds(ctx)

    # ── 尝试 DAG 多任务工作流 ──────────────────────────────
    t0 = time.perf_counter()
    dag_result = _try_dag_workflow(
        user_input=user_input,
        recent_history=recent_history,
        parsed_memories=parsed_memories,
    )
    if dag_result is not None:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        save_message(ctx, "assistant", dag_result["content"],
                     usage=dag_result.get("usage", {}),
                     duration_ms=elapsed_ms,
                     thinking_count=dag_result.get("thinking_count", 0),
                     reasoning_text=dag_result.get("reasoning", ""))
        return dag_result

    # ── 降级：单 Agent ReAct ───────────────────────────────
    logger.info("DAG 工作流不可用，降级到单 Agent ReAct 模式")
    from agent_engine.llm_engine import generate_answer
    t0 = time.perf_counter()
    result = generate_answer(
        user_input=user_input,
        recent_history=recent_history,
        parsed_memories=parsed_memories,
        web_info=web_info,
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # 兼容旧版 str 返回（异常场景）
    if isinstance(result, str):
        result = {"content": result, "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, "reasoning": "", "thinking_count": 0}

    # 保存助手回复（含指标）
    save_message(ctx, "assistant", result["content"],
                 usage=result.get("usage"),
                 duration_ms=elapsed_ms,
                 thinking_count=result.get("thinking_count", 0),
                 reasoning_text=result.get("reasoning"))

    return result


async def chat_completion_stream(
    ctx: TenantContext,
    user_input: str,
) -> AsyncGenerator[str, None]:
    """
    核心聊天方法 — SSE 流式版。
    yield 格式为标准 SSE（text/event-stream）：
      event: text_delta
      data: {"content":"..."}

      event: tool_call
      data: {"name":"...","args":{...}}

      event: done
      data: {"content":"...","usage":{...},"reasoning":"...","thinking_count":N,"duration_ms":N,"trace_id":"xxxx"}
    """
    _ensure_workspace(ctx)
    get_or_create_conversation(ctx)

    # 保存用户消息
    save_message(ctx, "user", user_input)

    # 加载历史
    history = load_conversation_history(ctx)
    recent_history = history[:-1] if len(history) > 1 else []

    parsed_memories = []
    web_info = ""
    _inject_drive_creds(ctx)

    t0 = time.perf_counter()
    trace_id = uuid.uuid4().hex[:16]  # 16 位短 ID，每次请求唯一

    # ── 尝试 DAG 多任务工作流 ──────────────────────────────
    dag_result = _try_dag_workflow(
        user_input=user_input,
        recent_history=recent_history,
        parsed_memories=parsed_memories,
    )
    if dag_result is not None:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        # DAG 结果以 SSE done 事件返回
        final_event = {
            "type": "done",
            "content": dag_result["content"],
            "usage": dag_result.get("usage", {}),
            "reasoning": dag_result.get("reasoning", ""),
            "thinking_count": dag_result.get("thinking_count", 0),
            "duration_ms": elapsed_ms,
            "trace_id": trace_id,
        }
        yield f"event: done\ndata: {json.dumps(final_event, ensure_ascii=False)}\n\n"
        save_message(ctx, "assistant", dag_result["content"],
                     usage=dag_result.get("usage"),
                     duration_ms=elapsed_ms,
                     thinking_count=dag_result.get("thinking_count", 0),
                     reasoning_text=dag_result.get("reasoning", ""))
        return

    # ── 降级：单 Agent 流式 ReAct ──────────────────────────
    from agent_engine.llm_engine import generate_answer_stream

    # 收集指标
    final_content = ""
    final_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    final_reasoning = ""
    final_thinking_count = 0

    try:
        async for event in generate_answer_stream(
            user_input=user_input,
            recent_history=recent_history,
            parsed_memories=parsed_memories,
            web_info=web_info,
        ):
            if event["type"] == "done":
                final_content = event.get("content", "")
                final_usage = event.get("usage", {})
                final_reasoning = event.get("reasoning", "")
                final_thinking_count = event.get("thinking_count", 0)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                event["duration_ms"] = elapsed_ms
                event["trace_id"] = trace_id
            yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.error(f"流式引擎错误: {e}", exc_info=True)
        yield f"event: error\ndata: {json.dumps({'content': str(e)}, ensure_ascii=False)}\n\n"

    # 流式完成后保存助手消息（含指标）
    if final_content:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        save_message(ctx, "assistant", final_content,
                     usage=final_usage,
                     duration_ms=elapsed_ms,
                     thinking_count=final_thinking_count,
                     reasoning_text=final_reasoning)


def _inject_drive_creds(ctx: TenantContext):
    """在调用 LLM 引擎前，从 DB 读取用户 Drive Token 并注入工具层"""
    try:
        from agent_engine.tools.tool_drive import set_thread_drive_creds, clear_thread_drive_creds
        from app_server.auth import get_drive_token
        session = get_session()
        try:
            token = get_drive_token(session, ctx.user_id)
            if token:
                set_thread_drive_creds(token)
            else:
                clear_thread_drive_creds()
        finally:
            session.close()
    except Exception:
        pass


def chat_completion_channel(
    ctx: TenantContext,
    user_input: str,
    platform_chat_id: str,
    platform_message_id: str,
) -> str:
    """
    渠道版聊天方法 — 用于 IM webhook。
    比 chat_completion 多了：
    - 按 (user_id, channel, platform_chat_id) 定位会话
    - 按 platform_message_id 幂等去重
    - 返回回复文本（仅 content 字符串，IM 不需 token 数据）
    """
    _ensure_workspace(ctx)

    session = get_session()
    try:
        # 查找或创建渠道会话
        conv = (
            session.query(Conversation)
            .filter(
                Conversation.user_id == ctx.user_id,
                Conversation.channel == ctx.channel,
                Conversation.platform_chat_id == platform_chat_id,
            )
            .first()
        )
        if conv is None:
            conv = Conversation(
                user_id=ctx.user_id,
                channel=ctx.channel,
                platform_chat_id=platform_chat_id,
                title=f"{ctx.channel or 'IM'} 对话",
            )
            session.add(conv)
            session.commit()
            session.refresh(conv)

        ctx.conversation_id = conv.id

        # 幂等检查：该平台消息是否已处理
        existing = (
            session.query(Message)
            .filter(Message.platform_message_id == platform_message_id)
            .first()
        )
        if existing:
            logger.info(f"平台消息已处理（幂等跳过）: {platform_message_id}")
            # 返回已有的助手回复（查找该 user 消息之后的 assistant 消息）
            next_msg = (
                session.query(Message)
                .filter(
                    Message.conversation_id == conv.id,
                    Message.id > existing.id,
                    Message.role == "assistant",
                )
                .order_by(Message.id.asc())
                .first()
            )
            if next_msg:
                return next_msg.content
            return "（消息已处理）"

        # 保存用户消息
        msg = Message(
            conversation_id=conv.id,
            role="user",
            content=user_input,
            platform_message_id=platform_message_id,
        )
        session.add(msg)
        session.commit()
    finally:
        session.close()

    # 加载历史
    history = load_conversation_history(ctx)
    recent_history = history[:-1] if len(history) > 1 else []

    parsed_memories = []
    web_info = ""

    # 注入 Drive 凭证（多租户）
    _inject_drive_creds(ctx)

    # ── 尝试 DAG 多任务工作流 ──────────────────────────────
    dag_result = _try_dag_workflow(
        user_input=user_input,
        recent_history=recent_history,
        parsed_memories=parsed_memories,
    )
    if dag_result is not None:
        reply = dag_result["content"]
        save_message(ctx, "assistant", reply)
        return reply

    # ── 降级：单 Agent ReAct ───────────────────────────────
    logger.info("DAG 工作流不可用，降级到单 Agent ReAct 模式")
    from agent_engine.llm_engine import generate_answer
    result = generate_answer(
        user_input=user_input,
        recent_history=recent_history,
        parsed_memories=parsed_memories,
        web_info=web_info,
    )

    # 兼容旧版 str 返回
    reply = result["content"] if isinstance(result, dict) else result

    # 保存助手回复
    save_message(ctx, "assistant", reply)

    return reply


def list_conversations(ctx: TenantContext) -> list:
    """列出当前用户的所有会话"""
    session = get_session()
    try:
        convs = (
            session.query(Conversation)
            .filter(Conversation.user_id == ctx.user_id)
            .order_by(Conversation.updated_at.desc())
            .all()
        )
        return [
            {
                "id": c.id,
                "title": c.title,
                "channel": c.channel,
                "platform_chat_id": c.platform_chat_id,
                "created_at": c.created_at.isoformat() + "Z" if c.created_at else None,
                "updated_at": c.updated_at.isoformat() + "Z" if c.updated_at else None,
            }
            for c in convs
        ]
    finally:
        session.close()


def delete_conversation(user_id: int, conv_id: int) -> bool:
    """删除用户的一个会话及其所有消息。返回是否成功。"""
    session = get_session()
    try:
        conv = (
            session.query(Conversation)
            .filter(Conversation.id == conv_id, Conversation.user_id == user_id)
            .first()
        )
        if not conv:
            return False
        # 删除关联消息
        session.query(Message).filter(Message.conversation_id == conv_id).delete()
        session.delete(conv)
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def list_messages(ctx: TenantContext) -> list:
    """列出当前会话的所有消息"""
    if not ctx.conversation_id:
        return []
    session = get_session()
    try:
        msgs = (
            session.query(Message)
            .filter(Message.conversation_id == ctx.conversation_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "platform_message_id": m.platform_message_id,
                "created_at": m.created_at.isoformat() + "Z" if m.created_at else None,
                "usage": {
                    "prompt_tokens": m.prompt_tokens or 0,
                    "completion_tokens": m.completion_tokens or 0,
                    "total_tokens": m.total_tokens or 0,
                } if m.prompt_tokens is not None and m.total_tokens is not None else None,
                "duration_ms": m.duration_ms,
                "thinking_count": m.thinking_count,
                "reasoning": m.reasoning_text,
            }
            for m in msgs
        ]
    finally:
        session.close()


# ══════════════════════════════════════════════════════════
# DAG 多任务工作流
# ══════════════════════════════════════════════════════════

def _try_dag_workflow(
    user_input: str,
    recent_history: list,
    parsed_memories: list,
) -> "Optional[dict]":
    """
    尝试使用 DAG 多任务工作流执行用户请求。

    流程:
    1. 调用 Planner 生成任务计划
    2. 检查是否为 DAG 计划（多任务且有依赖）
    3. 是 → 创建 WorkflowPlan → WorkflowRuntime 执行
    4. 否 → 返回 None（调用方降级到单 Agent 模式）

    :return: 成功时返回 {"content": str, ...}，失败时返回 None
    """
    try:
        # Step 1: Planner 生成任务计划
        from agent_engine.planner import generate_plan
        tasks_raw = generate_plan(
            user_goal=user_input,
            recent_history=recent_history,
            parsed_memories=parsed_memories,
        )

        if not tasks_raw:
            logger.info("Planner 未生成有效计划，跳过 DAG")
            return None

        # Step 2: 构建 WorkflowPlan
        from agent_engine.workflow.plan import WorkflowPlan
        plan = WorkflowPlan.from_planner_output(
            {"plan_type": "dag", "tasks": tasks_raw}
        )

        if plan is None or not plan.is_dag:
            logger.info(
                f"计划不是 DAG 类型（任务数={len(tasks_raw)}），"
                f"降级到单 Agent 模式"
            )
            return None

        logger.info(f"DAG 计划生成成功: {plan.summary}")

        # Step 3: 创建 AgentRegistry 和 WorkflowRuntime
        from agent_engine.agents.registry import AgentRegistry
        from agent_engine.workflow.runtime import WorkflowRuntime

        registry = AgentRegistry(use_cache=True)

        # 提取记忆文本
        memories_text = ""
        if parsed_memories:
            memories_text = "\n".join(
                f"- {m.get('text', m)}" if isinstance(m, dict) else f"- {m}"
                for m in parsed_memories
            )

        # 提取历史对话文本
        history_text = ""
        if recent_history:
            history_text = "\n".join(
                f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
                for msg in recent_history[-10:]
            )

        runtime = WorkflowRuntime(
            plan=plan,
            registry=registry,
            user_query=user_input,
            memories=memories_text,
            history=history_text,
            max_workers=4,
            task_timeout=300.0,
            max_retries=1,
        )

        # Step 4: 执行工作流
        result = runtime.execute()

        if not result.get("success"):
            logger.warning("DAG 工作流部分任务失败，返回已有结果")
        else:
            logger.info("DAG 工作流全部成功")

        content = result.get("summary", "")
        if not content:
            tasks_output = [
                tr for tr in result.get("task_results", [])
                if tr.get("status") == "SUCCEEDED"
            ]
            content = "\n\n".join(
                t.get("output_preview", "") for t in tasks_output
            )

        return {
            "content": content,
            "usage": result.get("total_usage", {
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            }),
            "reasoning": "",
            "thinking_count": len(result.get("task_results", [])),
        }

    except Exception as e:
        logger.error(f"DAG 工作流执行异常，降级: {e}", exc_info=True)
        return None
