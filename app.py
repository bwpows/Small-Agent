import streamlit as st
import traceback
import concurrent.futures

from ui_components import render_sidebar, render_chat_history
from chat_manager import ChatManager
from core.planner import generate_plan       
from core.tracing import trace_request, finish_trace, trace_span, SpanKind

# 🌟 引入 Multi-Agent Swarm 集群专家
# from agents.base_agent import BaseAgent
# from agents.researcher import ResearcherAgent
# from agents.coder import CoderAgent
# from agents.google_drive import GoogleDriveAgent

st.set_page_config(page_title="Agent OS - Swarm 专家集群版", page_icon="🛡️", layout="wide")

# ==========================================
# 1. 核心与状态机初始化
# ==========================================
if "all_chats" not in st.session_state:
    st.session_state.all_chats = ChatManager.load_chats()

if "current_chat_id" not in st.session_state:
    if st.session_state.all_chats:
        st.session_state.current_chat_id = list(st.session_state.all_chats.keys())[-1]
    else:
        st.session_state.current_chat_id = ChatManager.add_new_chat(st.session_state.all_chats)

if "long_term_memories" not in st.session_state:
    st.session_state.long_term_memories = [{"text": "用户的默认语言是中文。"}, {"text": "在处理数据时，优先使用网盘表格。"}]

# 🌟 HITL 安全审批状态机变量
if "pending_plan" not in st.session_state:
    st.session_state.pending_plan = None    
if "approved_plan" not in st.session_state:
    st.session_state.approved_plan = None   

# ==========================================
# 2. 渲染 UI
# ==========================================
enable_web_search = render_sidebar()
render_chat_history()

# ==========================================
# 3. 三段式核心状态机流转 (语义风控 + Swarm路由)
# ==========================================

# 🛡️ 状态 1：【透明化安全拦截期】
if st.session_state.pending_plan:
    with st.chat_message("assistant", avatar="🛡️"):
        st.warning("🚨 **安全风控拦截**：系统检测到该计划包含高危/敏感操作！请仔细审阅以下操作明细：")
        
        for task in st.session_state.pending_plan:
            risk = task.get("risk_level", "low")
            task_id = task.get("task_id", "?")
            action = task.get("action", "未知操作")
            details = task.get("risk_details", "无详细说明")
            assigned_agent = task.get("agent_role", "general").upper()
            
            if risk == "high":
                st.error(f"🔴 **【高危 | 由 {assigned_agent} 执行】任务 {task_id}：{action}** \n\n**具体动作**：{details}")
            elif risk == "medium":
                st.warning(f"🟡 **【中危 | 由 {assigned_agent} 执行】任务 {task_id}：{action}** \n\n**具体动作**：{details}")
            else:
                st.info(f"🟢 **【安全 | 由 {assigned_agent} 执行】任务 {task_id}：{action}** \n\n**具体动作**：{details}")
        
        st.write("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 我已知晓风险，授权执行", use_container_width=True):
                st.session_state.approved_plan = st.session_state.pending_plan
                st.session_state.pending_plan = None
                st.rerun() 
                
        with col2:
            if st.button("❌ 危险过高，直接驳回", use_container_width=True, type="primary"):
                st.session_state.pending_plan = None
                st.session_state.all_chats[st.session_state.current_chat_id].append({"role": "assistant", "content": "🚫 **人类长官已驳回该计划，保护了系统安全。**"})
                ChatManager.save_chats(st.session_state.all_chats)
                st.rerun()
                
    st.stop()


# ⚡ 状态 2：【执行期】图纸已获批，Swarm 专家组并发狂飙
elif st.session_state.approved_plan:
    with st.chat_message("assistant", avatar="🤖"):
        task_list = st.session_state.approved_plan

        # ── 开始执行期追踪 ──
        trace = trace_request(
            user_input="[已审批的计划]",
            session_id=st.session_state.current_chat_id,
            metadata={"phase": "execution", "task_count": len(task_list)},
        )

        # 1. DAG 拓扑排序解析
        with trace_span("dag_toposort", kind=SpanKind.DAG):
            batches = []
            pending = {t.get('task_id'): t for t in task_list if 'task_id' in t}
            completed_ids = set()

            loop_breaker = 0
            while pending and loop_breaker < 100:
                loop_breaker += 1
                current_batch = []
                for tid, t in list(pending.items()):
                    if all(d in completed_ids for d in t.get("depends_on", [])):
                        current_batch.append(t)
                
                if not current_batch:
                    st.error("🚨 致命异常：检测到死锁，DAG 调度中断！")
                    break
                    
                for t in current_batch:
                    del pending[t['task_id']]
                    completed_ids.add(t['task_id'])
                batches.append(current_batch)

        # 🌟 2. 核心模块：基于反射的动态专家工厂
        def get_agent_instance(role_name):
            from agents.registry import AGENT_ROSTER
            from agents.base_agent import BaseAgent
            
            if role_name not in AGENT_ROSTER:
                return BaseAgent(agent_name="General Worker", role_prompt="你是一个全能助理，尽力满足要求。", allowed_tool_names=None)
                
            agent_info = AGENT_ROSTER[role_name]
            class_name = agent_info["class_name"]
            
            try:
                module = __import__(f"agents.{role_name}", fromlist=[class_name])
                agent_class = getattr(module, class_name)
                return agent_class()
            except Exception as e:
                print(f"🚨 动态加载专家 [{role_name}] 失败: {e}")
                return BaseAgent(agent_name=f"Fallback_{role_name}", role_prompt="尽力完成任务。", allowed_tool_names=None)

        # 🌟 修复核心：在主线程提取 memories 作为参数传入，防止子线程崩溃
        def worker_task_runner(task_dict, prior_context="", memories=None):
            instruction = task_dict.get("instruction", "")
            role = task_dict.get("agent_role", "general")
            
            agent = get_agent_instance(role)
            
            return agent.execute(
                instruction=instruction, 
                prior_context=prior_context, 
                parsed_memories=memories,  # 👈 接收外部传入的安全变量
                ui_status=None 
            )

        # 3. 开启线程池狂飙 (带有 XComs 数据流转)
        with trace_span("dag_execute_all", kind=SpanKind.DAG):
            final_results = []
            batch_index = 1
            task_results_store = {} 
            
            # 👈 核心提取：在主线程中提前把 session_state 拿出来
            current_memories = st.session_state.long_term_memories 
            
            for batch in batches:
                task_ids = [str(t.get('task_id')) for t in batch]
                with st.status(f"⚡ [批次 {batch_index}] 正在分派专家组处理任务: {', '.join(task_ids)}...", expanded=True) as batch_status:
                    for t in batch:
                        role_display = t.get('agent_role', 'general').upper()
                        st.write(f"- 🚀 [{role_display}] 启动独立节点: **{t.get('action', '执行任务')}**")
                    
                    with trace_span(f"dag_batch_{batch_index}", kind=SpanKind.DAG, metadata={"tasks": task_ids}):
                        with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch) if batch else 1) as executor:
                            
                            future_to_task = {}
                            for t in batch:
                                deps = t.get("depends_on", [])
                                deps_context = "\n".join([f"[前置任务 {d} 的结果]: {task_results_store[d]}" for d in deps if d in task_results_store])
                                
                                # 👈 把 current_memories 当做普通变量传给子线程
                                future = executor.submit(worker_task_runner, t, deps_context, current_memories) 
                                future_to_task[future] = t

                            for future in concurrent.futures.as_completed(future_to_task):
                                task = future_to_task[future]
                                task_id = task.get("task_id")
                                action_name = task.get("action", "执行任务")
                                assigned_role = task.get("agent_role", "general").upper()
                                
                                try:
                                    result = future.result()
                                    final_results.append(f"**【[{assigned_role}] 任务 {task_id} ({action_name})】**\n{result}")
                                    st.write(f"✅ [{assigned_role}] 任务 {task_id} 已极速完成！")
                                    task_results_store[task_id] = result
                                    
                                except Exception as e:
                                    error_trace = traceback.format_exc()
                                    st.error(f"❌ [{assigned_role}] 任务 {task_id} 执行崩溃！")
                                    final_results.append(f"**【[{assigned_role}] 任务 {task_id}】惨烈崩溃。**\n\n```python\n{error_trace}\n```")
                                    task_results_store[task_id] = "执行失败，无有效数据。" 
                                    
                    batch_status.update(label=f"✅ [批次 {batch_index}] 专家组执行完毕！", state="complete", expanded=False)
                batch_index += 1

        summary_text = "🎉 **Swarm 专家集群执行报告：**\n\n" + "\n\n---\n".join(final_results)
        st.markdown(summary_text)

        # ── 捕获当前 trace 摘要信息，随消息一起存入历史 ──
        from core.tracing import get_tracer
        trace_info = None
        current_trace = get_tracer().current_trace()
        if current_trace:
            trace_info = {
                "duration_ms": round(current_trace.total_duration_ms(), 0),
                "spans": current_trace.span_count(),
                "errors": current_trace.error_count(),
                "trace_id": current_trace.trace_id[:8],
            }
        
        st.session_state.all_chats[st.session_state.current_chat_id].append({
            "role": "assistant",
            "content": summary_text,
            "trace": trace_info,   # 👈 存入元数据，供对话历史渲染
        })
        ChatManager.save_chats(st.session_state.all_chats)
        
        # ── 结束执行期追踪 ──
        finish_trace(trace)
        st.session_state.approved_plan = None
        st.rerun()


# 🧠 状态 3：【规划期】接收新指令，画图纸并派单
else:
    user_input = st.chat_input("输入你极其复杂的宏大目标...")
    
    if user_input:
        # ── 开始一次完整的请求追踪 ──
        trace = trace_request(
            user_input=user_input,
            session_id=st.session_state.current_chat_id,
            metadata={"phase": "planning"},
        )

        with st.chat_message("user", avatar="🧑‍💻"):
            st.markdown(user_input)
        
        current_chat = st.session_state.all_chats[st.session_state.current_chat_id]
        if len(current_chat) == 0 and "新对话" in st.session_state.current_chat_id:
            new_title = ChatManager.generate_chat_title(user_input)
            old_id = st.session_state.current_chat_id
            st.session_state.all_chats[new_title] = st.session_state.all_chats.pop(old_id)
            st.session_state.current_chat_id = new_title

        st.session_state.all_chats[st.session_state.current_chat_id].append({"role": "user", "content": user_input})
        ChatManager.save_chats(st.session_state.all_chats)
        
        current_history = st.session_state.all_chats[st.session_state.current_chat_id][:-1]
        
        with st.chat_message("assistant", avatar="🤖"):
            with trace_span("request_entry", kind=SpanKind.ENTRY):
                with st.status("🧠 大脑 (Planner) 正在拆解任务并为专家派单...", expanded=True) as plan_status:
                    try:
                        task_list = generate_plan(
                            user_goal=user_input,
                            recent_history=current_history,
                            parsed_memories=st.session_state.long_term_memories
                        )
                        
                        if not task_list:
                            plan_status.update(label="❌ 任务规划失败，请重试。", state="error")
                            finish_trace(trace)
                            st.stop()
                            
                        plan_status.update(label="🔍 正在审查任务风险级别...", state="running")
                        
                        needs_approval = any(t.get("risk_level") == "high" for t in task_list)
                        
                        if needs_approval:
                            plan_status.update(label="🚨 发现高危操作，已挂起等待人类授权！", state="error")
                            st.session_state.pending_plan = task_list
                        else:
                            plan_status.update(label="🟢 全部为低/中危操作，免密放行，极速启动！", state="complete")
                            st.session_state.approved_plan = task_list

                        # 规划完成，结束当前入口 Span
                        finish_trace(trace)
                        st.rerun()
                        
                    except Exception as e:
                        error_trace = traceback.format_exc()
                        plan_status.update(label="❌ 大脑规划发生底层崩溃！", state="error")
                        st.error(f"报错日志：\n```python\n{error_trace}\n```")
                        finish_trace(trace)
                        st.stop()