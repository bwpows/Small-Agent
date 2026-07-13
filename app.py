import streamlit as st
import traceback
import json
import concurrent.futures

from ui_components import render_sidebar, render_chat_history
from chat_manager import ChatManager
from core.planner import generate_plan       
from core.llm_engine import generate_answer  

st.set_page_config(page_title="Agent OS - 企业级风控并发版", page_icon="🛡️", layout="wide")

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
    st.session_state.pending_plan = None    # 待人类审批的图纸
if "approved_plan" not in st.session_state:
    st.session_state.approved_plan = None   # 已获批，准备并发执行的图纸

# ==========================================
# 2. 渲染 UI (侧边栏和历史记录)
# ==========================================
enable_web_search = render_sidebar()
render_chat_history()

# ==========================================
# 3. 三段式核心状态机流转 (语义风控升级版)
# ==========================================

# 🛡️ 状态 1：【透明化安全拦截期】大脑判断有风险，展示明细等待审批
if st.session_state.pending_plan:
    with st.chat_message("assistant", avatar="🛡️"):
        st.warning("🚨 **安全风控拦截**：系统检测到该计划包含高危/敏感操作！请仔细审阅以下操作明细：")
        
        # 🌟 极其清晰的明细渲染，不看 JSON，只看大白话！
        for task in st.session_state.pending_plan:
            risk = task.get("risk_level", "low")
            task_id = task.get("task_id", "?")
            action = task.get("action", "未知操作")
            details = task.get("risk_details", "无详细说明")
            
            if risk == "high":
                st.error(f"🔴 **【高危操作】任务 {task_id}：{action}** \n\n**具体动作**：{details}")
            elif risk == "medium":
                st.warning(f"🟡 **【中危操作】任务 {task_id}：{action}** \n\n**具体动作**：{details}")
            else:
                st.info(f"🟢 **【安全操作】任务 {task_id}：{action}** \n\n**具体动作**：{details}")
        
        st.write("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 我已知晓风险，授权执行", use_container_width=True):
                # 审批通过，移交执行队列
                st.session_state.approved_plan = st.session_state.pending_plan
                st.session_state.pending_plan = None
                st.rerun() 
                
        with col2:
            if st.button("❌ 危险过高，直接驳回", use_container_width=True, type="primary"):
                st.session_state.pending_plan = None
                rejection_msg = "🚫 **人类长官已驳回该计划，保护了系统安全。**"
                st.session_state.all_chats[st.session_state.current_chat_id].append({"role": "assistant", "content": rejection_msg})
                ChatManager.save_chats(st.session_state.all_chats)
                st.rerun()
                
    st.stop() # ⚠️ 致命防御：只要审批没过，下面的输入和执行代码绝对不允许跑！


# ⚡ 状态 2：【执行期】图纸已安全/已获批，小脑开始 DAG 并发狂飙
elif st.session_state.approved_plan:
    with st.chat_message("assistant", avatar="🤖"):
        task_list = st.session_state.approved_plan
        
        # 1. DAG 拓扑排序解析
        batches = []
        pending = {t.get('task_id'): t for t in task_list if 'task_id' in t}
        completed_ids = set()

        loop_breaker = 0
        while pending and loop_breaker < 100:
            loop_breaker += 1
            current_batch = []
            for tid, t in list(pending.items()):
                # 前置任务已全部完成，入列当前批次
                if all(d in completed_ids for d in t.get("depends_on", [])):
                    current_batch.append(t)
            
            if not current_batch:
                st.error("🚨 致命异常：检测到死锁，DAG 调度中断！")
                break
                
            for t in current_batch:
                del pending[t['task_id']]
                completed_ids.add(t['task_id'])
            batches.append(current_batch)

        # 2. 小脑线程函数 (支持接收前置任务的上下文)
        def worker_task_runner(instruction, prior_context=""):
            # 将前置情报拼接到指令中
            if prior_context:
                instruction += f"\n\n【系统提供的极其重要的前置情报】：\n{prior_context}\n请严格基于上述情报执行当前任务！"
                
            return generate_answer(
                user_input=instruction, 
                recent_history=[], 
                parsed_memories=[], 
                web_info=enable_web_search, 
                ui_status=None 
            )

        # 3. 开启线程池狂飙 (带有 XComs 数据流转)
        final_results = []
        batch_index = 1
        
        # 🌟 新增：全局情报箱，专门记录每个 task_id 执行完毕后的真实结果
        task_results_store = {} 
        
        for batch in batches:
            task_ids = [str(t.get('task_id')) for t in batch]
            with st.status(f"⚡ [并发批次 {batch_index}] 正在同时处理任务: {', '.join(task_ids)}...", expanded=True) as batch_status:
                for t in batch:
                    st.write(f"- 🚀 启动子线程: **{t.get('action', '执行任务')}**")
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch) if batch else 1) as executor:
                    
                    # 🌟 核心组装：在派发任务前，把当前任务依赖的前置结果提取出来
                    future_to_task = {}
                    for t in batch:
                        deps = t.get("depends_on", [])
                        # 把依赖项在情报箱里的结果拼接起来
                        deps_context = "\n".join([f"[前置任务 {d} 的结果]: {task_results_store[d]}" for d in deps if d in task_results_store])
                        
                        # 提交任务，并传入前置情报
                        future = executor.submit(worker_task_runner, t.get("instruction", ""), deps_context)
                        future_to_task[future] = t

                    # 等待并收集当前批次的结果
                    for future in concurrent.futures.as_completed(future_to_task):
                        task = future_to_task[future]
                        task_id = task.get("task_id")
                        action_name = task.get("action", "执行任务")
                        
                        try:
                            result = future.result()
                            final_results.append(f"**【任务 {task_id} ({action_name})】**\n{result}")
                            st.write(f"✅ 任务 {task_id} ({action_name}) 已极速完成！")
                            
                            # 🌟 核心存入：任务成功后，把结果塞进情报箱，供下一批次使用！
                            task_results_store[task_id] = result
                            
                        except Exception as e:
                            error_trace = traceback.format_exc()
                            st.error(f"❌ 任务 {task_id} ({action_name}) 并发执行崩溃！")
                            final_results.append(f"**【任务 {task_id}】惨烈崩溃。**\n\n```python\n{error_trace}\n```")
                            task_results_store[task_id] = "执行失败，无有效数据。" # 防止后续任务死等
                            
                batch_status.update(label=f"✅ [并发批次 {batch_index}] 全部队列执行完毕！", state="complete", expanded=False)
            batch_index += 1

        # 4. 汇总、清空并存档
        summary_text = "🎉 **全自动并发执行报告：**\n\n" + "\n\n---\n".join(final_results)
        st.markdown(summary_text)
        
        st.session_state.all_chats[st.session_state.current_chat_id].append({"role": "assistant", "content": summary_text})
        ChatManager.save_chats(st.session_state.all_chats)
        
        # ⚠️ 核心操作：任务跑完，必须清空执行队列，让系统回到普通的对话状态
        st.session_state.approved_plan = None
        st.rerun()


# 🧠 状态 3：【规划期】普通待机状态，接收新指令开始画图纸并执行语义风控
else:
    user_input = st.chat_input("输入你极其复杂的宏大目标...")
    
    if user_input:
        # 上屏显示并存储
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
        
        # 召唤大脑开始排期
        current_history = st.session_state.all_chats[st.session_state.current_chat_id][:-1]
        
        with st.chat_message("assistant", avatar="🤖"):
            with st.status("🧠 大脑 (Planner) 正在拆解任务并进行风控审计...", expanded=True) as plan_status:
                try:
                    task_list = generate_plan(
                        user_goal=user_input,
                        recent_history=current_history,
                        parsed_memories=st.session_state.long_term_memories
                    )
                    
                    if not task_list:
                        plan_status.update(label="❌ 任务规划失败，请重试。", state="error")
                        st.stop()
                        
                    plan_status.update(label="🔍 正在审查任务风险级别...", state="running")
                    
                    # ==========================================
                    # 🚨 智能语义风控路由 (基于 Planner 的大模型定级)
                    # ==========================================
                    # 只要有一个任务被大模型判定为 "high"，就触发拦截
                    needs_approval = any(t.get("risk_level") == "high" for t in task_list)
                    
                    if needs_approval:
                        plan_status.update(label="🚨 发现高危操作，已挂起等待人类授权！", state="error")
                        st.session_state.pending_plan = task_list
                    else:
                        plan_status.update(label="🟢 全部为低危/中危操作，免密放行，极速启动！", state="complete")
                        st.session_state.approved_plan = task_list
                        
                    # 刷新 UI，根据风险状态进入对应逻辑
                    st.rerun()
                    
                except Exception as e:
                    error_trace = traceback.format_exc()
                    plan_status.update(label="❌ 大脑规划发生底层崩溃！", state="error")
                    st.error(f"报错日志：\n```python\n{error_trace}\n```")
                    st.stop()