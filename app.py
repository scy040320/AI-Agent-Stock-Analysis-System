import sqlite3
import uuid
import streamlit as st
from pipeline import get_user_app, tracker
from langchain_core.messages import HumanMessage
from langchain_community.callbacks.manager import get_openai_callback

st.set_page_config(page_title="多用户 A股AI投研平台", page_icon="📊", layout="wide")

# ================= 数据库初始化 (用户认证) =================
def init_user_db():
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_user_db()

def register_user(username, password):
    try:
        conn = sqlite3.connect("users.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False

def verify_user(username, password):
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
    user = cursor.fetchone()
    conn.close()
    return user is not None

# ================= 登录 / 注册界面 =================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""

if not st.session_state.logged_in:
    st.title("🔐 欢迎使用 A股多智能体投研平台 (SaaS版)")
    tab1, tab2 = st.tabs(["用户登录", "新用户注册"])
    
    with tab1:
        l_user = st.text_input("用户名", key="l_user")
        l_pass = st.text_input("密码", type="password", key="l_pass")
        if st.button("登录系统", type="primary"):
            if verify_user(l_user, l_pass):
                st.session_state.logged_in = True
                st.session_state.username = l_user
                st.rerun()
            else:
                st.error("用户名或密码错误！")
                
    with tab2:
        r_user = st.text_input("设置用户名", key="r_user")
        r_pass = st.text_input("设置密码", type="password", key="r_pass")
        if st.button("注册账号"):
            if r_user and r_pass:
                if register_user(r_user, r_pass):
                    st.success("注册成功！请切换到登录页面进行登录。")
                else:
                    st.error("该用户名已被注册！")
            else:
                st.warning("输入不能为空！")
    st.stop()

# ================= 登录后的主界面 =================
with st.sidebar:
    st.title(f"👋 {st.session_state.username}")
    user_api_key = st.text_input("输入 DeepSeek API Key", type="password", help="系统不保存您的密钥，仅在本地会话中生效")
    
    if st.button("🚪 退出登录"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.rerun()
        
    st.markdown("---")
    
    # 多会话列表管理
    if "sessions" not in st.session_state:
        init_id = f"{st.session_state.username}_{str(uuid.uuid4())[:6]}"
        st.session_state.sessions = {init_id: "默认投研会话"}
        st.session_state.current_thread_id = init_id
        st.session_state.total_tokens = 0
        st.session_state.total_cost = 0.0

    if st.button("➕ 新建对话", type="primary", use_container_width=True):
        new_id = f"{st.session_state.username}_{str(uuid.uuid4())[:6]}"
        st.session_state.sessions[new_id] = f"投研会话 {len(st.session_state.sessions) + 1}"
        st.session_state.current_thread_id = new_id
        st.rerun()

    st.markdown("### 💬 历史会话列表")
    for s_id, s_title in list(st.session_state.sessions.items()):
        if s_id.startswith(st.session_state.username):
            if s_id == st.session_state.current_thread_id:
                st.markdown(f"👉 **{s_title}**")
            else:
                if st.button(f"📁 {s_title}", key=f"switch_{s_id}", use_container_width=True):
                    st.session_state.current_thread_id = s_id
                    st.rerun()

    st.markdown("---")
    st.metric(label="消耗总 Tokens", value=f"{st.session_state.total_tokens:,}")
    st.metric(label="预估 API 成本", value=f"${st.session_state.total_cost:.5f}")

active_thread_id = st.session_state.current_thread_id
config = {"configurable": {"thread_id": active_thread_id}}

st.title("📈 A股多智能体量化投研平台")
st.caption("支持意图路由（个股分析 vs 宏观研报） | 多用户会话持久化 | 人机协同审批")

if not user_api_key:
    st.warning("⚠️ 请先在左侧边栏输入您的 **DeepSeek API Key** 才能开始投研！")
    st.stop()

# 加载图应用
user_app = get_user_app(user_api_key)
current_state = user_app.get_state(config)
is_paused = len(current_state.next) > 0 and current_state.next[0] == "Investment_Manager"

# 渲染正常的对话历史
if "messages" in current_state.values:
    for msg in current_state.values["messages"]:
        if msg.type == "human":
            with st.chat_message("user"):
                st.markdown(msg.content)
        elif msg.type == "ai" and len(msg.content) > 80:
            with st.chat_message("assistant"):
                st.markdown(msg.content)

# ================= HITL 审批面板 =================
if is_paused:
    st.warning("⚠️ **系统中断 (HITL)：个股数据已准备就绪，等待人工审核！**")
        
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ 数据无误，授权投资经理撰写个股研报", type="primary", use_container_width=True):
            with st.spinner("投资经理 Chen 正在深度撰写个股研报..."):
                with get_openai_callback() as cb:
                    user_app.invoke(None, config=config)
                    st.session_state.total_tokens += cb.total_tokens
                    st.session_state.total_cost += cb.total_cost
            st.rerun()
    with col2:
        if st.button("❌ 数据有误，驳回", use_container_width=True):
            st.error("已驳回。请在下方重新提问。")
            user_app.update_state(config, {"messages": []}, as_node="Investment_Manager")
            st.rerun()

# ================= 正常用户输入流 =================
elif not is_paused:
    if user_input := st.chat_input("请输入需求（例如：'分析贵州茅台 600519' 或 '当前宏观经济大盘走势如何'）"):
        if len(current_state.values.get("messages", [])) == 0:
            st.session_state.sessions[active_thread_id] = user_input[:12] + "..."
            
        with st.chat_message("user"):
            st.markdown(user_input)
            
        with st.spinner("🤖 智能路由正在识别意图并调度对应的分析师支路..."):
            with get_openai_callback() as cb:
                user_app.invoke({"messages": [HumanMessage(content=user_input)]}, config=config)
                st.session_state.total_tokens += cb.total_tokens
                st.session_state.total_cost += cb.total_cost
        st.rerun()