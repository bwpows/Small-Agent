import streamlit as st
import traceback  # 🚨 引入追踪报错的库
from ui_components import render_sidebar, render_chat_history
from chat_manager import ChatManager
from core.llm_engine import generate_answer 

st.set_page_config(page_title="Agent OS", layout="wide")

# ==========================================
# 1. 核心初始化
# ==========================================
if "all_chats" not in st.session_state:
    st.session_state.all_chats = ChatManager.load_chats()

if "current_chat_id" not in st.session_state:
    if st.session_state.all_chats:
        st.session_state.current_chat_id = list(st.session_state.all_chats.keys())[-1]
    else:
        st.session_state.current_chat_id = ChatManager.add_new_chat(st.session_state.all_chats)

# ==========================================
# 2. 渲染 UI
# ==========================================
enable_web_search = render_sidebar()
render_chat_history()

# ==========================================
# 3. 处理用户输入与智能命名
# ==========================================
user_input = st.chat_input("输入你的问题或指令...")

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
    
    # 4. 调用大模型大脑处理 (🛡️ 关键修复：加入防崩溃装甲)
    current_history = st.session_state.all_chats[st.session_state.current_chat_id][:-1] 
    
    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("Agent 正在深度思考与执行..."):
            try:
                # 尝试正常调用大模型引擎
                response = generate_answer(user_input, current_history, parsed_memories=[], web_info=enable_web_search)
                st.markdown(response)
            except Exception as e:
                # 💥 拦截死机！如果报错，抓取报错详情
                error_trace = traceback.format_exc()
                response = f"🚨 **系统执行异常**\n\nAgent 在调用工具或处理任务时发生了崩溃，请检查日志：\n\n```python\n{error_trace}\n```"
                st.error("执行时遇到底层逻辑错误！")
                st.markdown(response)
                print("=== Agent 崩溃日志 ===")
                print(error_trace)
    
    # 5. 把正常的回复（或红色的报错信息）也存入当前频道，保证逻辑闭环不断裂
    st.session_state.all_chats[st.session_state.current_chat_id].append({"role": "assistant", "content": response})
    ChatManager.save_chats(st.session_state.all_chats)
    
    # 6. 轻量刷新
    st.rerun()