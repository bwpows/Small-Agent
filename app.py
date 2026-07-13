import streamlit as st
import traceback
import json
from ui_components import render_sidebar, render_chat_history
from chat_manager import ChatManager
from core.planner import generate_plan       # 👈 引入大脑
from core.llm_engine import generate_answer  # 👈 引入小脑

st.set_page_config(page_title="Agent OS - 双脑驱动版", page_icon="🧠", layout="wide")

# ==========================================
# 1. 核心初始化 (保留你原有的多会话逻辑)
# ==========================================
if "all_chats" not in st.session_state:
    st.session_state.all_chats = ChatManager.load_chats()

if "current_chat_id" not in st.session_state:
    if st.session_state.all_chats:
        st.session_state.current_chat_id = list(st.session_state.all_chats.keys())[-1]
    else:
        st.session_state.current_chat_id = ChatManager.add_new_chat(st.session_state.all_chats)

# 假设这里有从 Mem0 加载长期记忆的逻辑（目前先写死模拟）
if "long_term_memories" not in st.session_state:
    st.session_state.long_term_memories = [{"text": "用户的默认语言是中文。"}, {"text": "在处理数据时，优先使用网盘表格。"}]

# ==========================================
# 2. 渲染 UI (保留侧边栏和历史记录)
# ==========================================
enable_web_search = render_sidebar()
render_chat_history()

# ==========================================
# 3. 处理用户输入与智能命名
# ==========================================
user_input = st.chat_input("输入你极其复杂的宏大目标...")

if user_input:
    # 1. 界面上立即显示用户的消息
    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(user_input)
    
    # 2. 如果是新对话，先执行重命名
    current_chat = st.session_state.all_chats[st.session_state.current_chat_id]
    if len(current_chat) == 0 and "新对话" in st.session_state.current_chat_id:
        new_title = ChatManager.generate_chat_title(user_input)
        old_id = st.session_state.current_chat_id
        st.session_state.all_chats[new_title] = st.session_state.all_chats.pop(old_id)
        st.session_state.current_chat_id = new_title
        ChatManager.save_chats(st.session_state.all_chats)

    # 3. 把用户的输入存入当前频道
    st.session_state.all_chats[st.session_state.current_chat_id].append({"role": "user", "content": user_input})
    ChatManager.save_chats(st.session_state.all_chats)
    
    # 获取当前的短期聊天历史传给大脑
    current_history = st.session_state.all_chats[st.session_state.current_chat_id][:-1] 
    
    # ==========================================
    # 4. 🚀 启动双脑工作流
    # ==========================================
    with st.chat_message("assistant", avatar="🤖"):
        
        # 【阶段一：大脑 Planner 拆解任务】
        with st.status("🧠 大脑 (Planner) 正在结合记忆拆解全局任务...", expanded=True) as plan_status:
            try:
                task_list = generate_plan(
                    user_goal=user_input,
                    recent_history=current_history,
                    parsed_memories=st.session_state.long_term_memories
                )
                
                if not task_list:
                    plan_status.update(label="❌ 任务规划失败，请重试。", state="error")
                    st.stop()
                    
                st.write("✅ 任务图纸已生成：")
                st.json(task_list)
                plan_status.update(label=f"🎯 宏观规划完成，共拆解为 {len(task_list)} 个子任务", state="complete", expanded=False)
                
            except Exception as e:
                error_trace = traceback.format_exc()
                plan_status.update(label="❌ 大脑规划发生底层崩溃！", state="error")
                st.error(f"报错日志：\n```python\n{error_trace}\n```")
                st.stop()

        # 【阶段二：小脑 Worker 逐个击破】
        final_results = []
        
        for task in task_list:
            task_id = task.get("task_id")
            action = task.get("action", "执行任务")
            instruction = task.get("instruction", "")
            
            with st.status(f"🦾 小脑正在处理任务 {task_id}: {action}...", expanded=True) as worker_status:
                st.write(f"**任务指引**: {instruction}")
                
                try:
                    # 💡 注意：Worker 只需要专心处理当前的子 instruction，不需要了解宏观上下文
                    worker_result = generate_answer(
                        user_input=instruction, 
                        recent_history=[], 
                        parsed_memories=[], 
                        web_info=enable_web_search, 
                        ui_status=worker_status
                    )
                    
                    final_results.append(f"**【任务 {task_id} ({action})】**\n{worker_result}")
                    worker_status.update(label=f"✅ 任务 {task_id} 搞定！", state="complete", expanded=False)
                    
                except Exception as e:
                    error_trace = traceback.format_exc()
                    worker_status.update(label=f"❌ 任务 {task_id} 执行崩溃！", state="error")
                    st.error(f"底层异常日志:\n```python\n{error_trace}\n```")
                    
                    # 🌟 核心修改：把报错堆栈塞进 final_results，这样它就会被存入聊天历史！
                    final_results.append(f"**【任务 {task_id}】惨烈崩溃。**\n\n**崩溃原因：**\n```python\n{error_trace}\n```")
                    break

        # 【阶段三：最终总结上屏与存档】
        summary_text = "🎉 **执行总结报告：**\n\n" + "\n\n---\n".join(final_results)
        st.markdown(summary_text)
    
    # 5. 把包含了所有任务结果的最终回复存入频道，保证刷新页面后依然可见
    st.session_state.all_chats[st.session_state.current_chat_id].append({"role": "assistant", "content": summary_text})
    ChatManager.save_chats(st.session_state.all_chats)
    
    # 6. 轻量刷新 UI
    st.rerun()