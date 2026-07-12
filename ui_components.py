import json
import os

# ui_components.py
import streamlit as st
from chat_manager import ChatManager

def inject_custom_css():
    """注入卡片式 CSS"""
    custom_css = """
    <style>
    /* 隐藏原生折叠后的顽固元素 */
    #MainMenu, footer, header {visibility: hidden;}

    /* 放宽主内容区域，减少中间区域过窄的问题 */
    .block-container {
        max-width: 100% !important;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    
    /* 侧边栏按钮统一伪装成卡片 */
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button {
        width: 100%;
        border-radius: 10px;
        border: 1px solid rgba(128, 128, 128, 0.16);
        background-color: var(--background-color);
        padding: 10px 12px;
        display: flex;
        justify-content: flex-start;
        align-items: flex-start;
        text-align: left;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        transition: all 0.2s ease;
        line-height: 1.35;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button > div,
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button > span {
        width: 100%;
        justify-content: flex-start;
        text-align: left;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button p {
        margin: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
        background-color: rgba(128, 128, 128, 0.08);
        border-color: #10a37f;
        text-align: left;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"] {
        background: linear-gradient(135deg, rgba(16, 163, 127, 0.22), rgba(16, 163, 127, 0.10));
        border-color: #10a37f;
        box-shadow: 0 0 0 1px rgba(16, 163, 127, 0.14), 0 6px 18px rgba(16, 163, 127, 0.10);
        font-weight: 600;
        color: inherit;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:hover {
        background: linear-gradient(135deg, rgba(16, 163, 127, 0.28), rgba(16, 163, 127, 0.14));
        border-color: #10a37f;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button:focus {
        border-color: #10a37f;
        box-shadow: 0 0 0 1px #10a37f;
    }
    </style>
    """
    st.markdown(custom_css, unsafe_allow_html=True)

def render_sidebar():
    inject_custom_css()
    
    with st.sidebar:
        st.markdown("### 🌌 Agent OS")
        enable_web_search = st.toggle("🌐 开启实时联网", value=False)
        # st.divider()
        
        if st.button("✨ 新建对话", use_container_width=True):
            new_id = ChatManager.add_new_chat(st.session_state.all_chats)
            st.session_state.current_chat_id = new_id
            st.rerun()
            
        # st.markdown("<p style='font-size:0.85em; color: gray; margin-top: 15px;'>💬 会话列表</p>", unsafe_allow_html=True)
        
        # 仅做整体倒序，不引入额外排序规则
        chat_ids = list(reversed(list(st.session_state.all_chats.keys())))
        
        # 使用容器遍历渲染“卡片”
        for chat_id in chat_ids:
            is_active = (chat_id == st.session_state.current_chat_id)
            chat_col, del_col = st.columns([0.82, 0.18], gap="small")

            with chat_col:
                card_text = f"{chat_id}"
                if st.button(
                    card_text,
                    key=f"btn_{chat_id}",
                    use_container_width=True,
                    type="primary" if is_active else "secondary",
                ):
                    st.session_state.current_chat_id = chat_id
                    st.rerun()

            with del_col:
                if st.button("🗑️", key=f"del_{chat_id}", help="删除该对话", use_container_width=True):
                    st.session_state.all_chats.pop(chat_id, None)

                    if not st.session_state.all_chats:
                        new_id = ChatManager.add_new_chat(st.session_state.all_chats)
                        st.session_state.current_chat_id = new_id
                    elif st.session_state.current_chat_id == chat_id:
                        st.session_state.current_chat_id = list(st.session_state.all_chats.keys())[-1]

                    ChatManager.save_chats(st.session_state.all_chats)
                    st.rerun()
                
    return enable_web_search

def render_chat_history():
    st.markdown("<h2 style='text-align: center; margin-bottom: 0;'>🧠 模块化双引擎 Agent</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center; color: gray; font-size: 0.9em; margin-bottom: 2rem;'>当前频道：<span style='background-color: rgba(128,128,128,0.1); padding: 4px 8px; border-radius: 6px; font-family: monospace;'>{st.session_state.current_chat_id}</span></p>", unsafe_allow_html=True)

    current_messages = []
    if os.path.exists(ChatManager.DB_FILE):
        try:
            with open(ChatManager.DB_FILE, "r", encoding="utf-8") as f:
                all_chats = json.load(f) or {}
                current_messages = all_chats.get(st.session_state.current_chat_id, [])
        except (json.JSONDecodeError, OSError):
            current_messages = st.session_state.all_chats.get(st.session_state.current_chat_id, [])
    else:
        current_messages = st.session_state.all_chats.get(st.session_state.current_chat_id, [])

    for msg in current_messages:
        avatar = "🧑‍💻" if msg["role"] == "user" else "🤖"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])