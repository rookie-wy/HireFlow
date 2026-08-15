import streamlit as st
import requests
import json
import time
from datetime import datetime

# ---------- 配置 ----------
BACKEND_URL = "http://localhost:8000/api/v1"


def login(username: str, password: str, tenant_id: str):
    """调用后端登录接口获取 JWT，失败返回 None。"""
    try:
        resp = requests.post(f"{BACKEND_URL}/auth/login", json={
            "username": username, "password": password, "tenant_id": tenant_id
        }, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("access_token")
    except Exception:
        pass
    return None


def register(username: str, password: str, tenant_id: str):
    """调用后端注册接口，返回 (是否成功, 提示信息)。"""
    try:
        resp = requests.post(f"{BACKEND_URL}/auth/register", json={
            "username": username, "password": password, "tenant_id": tenant_id
        }, timeout=10)
        if resp.status_code == 200:
            return True, "注册成功"
        return False, resp.text[:200]
    except Exception as e:
        return False, str(e)

# ---------- 页面设置 ----------
st.set_page_config(page_title="AI 招聘助手", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 1rem;
    }
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


# ---------- 数据加载函数 ----------
def load_candidates_from_backend():
    try:
        headers = {"Authorization": f"Bearer {st.session_state.auth_token}"}
        resp = requests.get(f"{BACKEND_URL}/candidates", headers=headers)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            formatted = []
            for item in data:
                formatted.append({
                    "candidate_id": item["candidate_id"],
                    "profile": {
                        "name": item["name"],
                        "email": item["email"],
                        "phone": item.get("phone", ""),
                        "skills": item.get("skills", []),
                    }
                })
            st.session_state.candidates = formatted
    except Exception:
        pass

def load_jobs_from_backend():
    try:
        headers = {"Authorization": f"Bearer {st.session_state.auth_token}"}
        resp = requests.get(f"{BACKEND_URL}/jobs", headers=headers)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            formatted = []
            for item in data:
                formatted.append({
                    "id": item["job_id"],
                    "title": item["title"],
                    "parsed": {
                        "title": item["title"],
                        "hard_requirements": item.get("hard_requirements", []),
                        "soft_requirements": item.get("soft_requirements", []),
                        "job_category": item.get("category", "general")
                    },
                    "jd_text": ""
                })
            st.session_state.jobs = formatted
    except Exception:
        pass

def load_screening_results(job_id: str):
    try:
        headers = {"Authorization": f"Bearer {st.session_state.auth_token}"}
        resp = requests.get(f"{BACKEND_URL}/match_results?job_id={job_id}", headers=headers)
        if resp.status_code == 200:
            st.session_state.screening_results = resp.json().get("data", [])
        else:
            st.session_state.screening_results = []
    except Exception:
        st.session_state.screening_results = []
# ---------- 初始化会话状态 ----------
def init_session():
    defaults = {
        "auth_token": None,
        "session_id": None,
        "job_id": None,
        "jobs": [],
        "candidates": [],
        "screening_results": [],
        "uploading": False,
        "upload_count": 0,
        "last_job_id": None
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if not st.session_state.jobs:
        load_jobs_from_backend()
    if st.session_state.job_id and not st.session_state.screening_results:
        load_screening_results(st.session_state.job_id)
    if not st.session_state.candidates:
        load_candidates_from_backend()

init_session()

# ---------- 登录门禁 ----------
if not st.session_state.auth_token:
    st.title("🔐 登录 AI 招聘助手")
    tab_login, tab_register = st.tabs(["登录", "注册"])
    with tab_login:
        with st.form("login_form"):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            tenant_id = st.text_input("租户 ID")
            if st.form_submit_button("登录", use_container_width=True):
                token = login(username, password, tenant_id)
                if token:
                    st.session_state.auth_token = token
                    st.rerun()
                else:
                    st.error("登录失败，请检查用户名 / 密码 / 租户 ID")
    with tab_register:
        with st.form("register_form"):
            r_username = st.text_input("用户名", key="reg_user")
            r_password = st.text_input("密码（至少8位）", type="password", key="reg_pass")
            r_tenant = st.text_input("租户 ID", key="reg_tenant")
            if st.form_submit_button("注册", use_container_width=True):
                ok, msg = register(r_username, r_password, r_tenant)
                if ok:
                    st.success("注册成功，请切换到「登录」标签登录")
                else:
                    st.error(f"注册失败：{msg}")
    st.stop()

# ---------- 工具函数 ----------
def call_backend(endpoint, data=None, files=None, method="POST"):
    headers = {"Authorization": f"Bearer {st.session_state.auth_token}"}
    url = f"{BACKEND_URL}{endpoint}"
    try:
        if method == "POST":
            if files:
                resp = requests.post(url, files=files, headers=headers)
            else:
                resp = requests.post(url, json=data, headers=headers)
        else:
            resp = requests.get(url, headers=headers, params=data)
        if resp.status_code != 200:
            st.error(f"请求失败 ({resp.status_code}): {resp.text[:200]}")
            return None
        return resp.json().get("data")
    except Exception as e:
        st.error(f"连接后端失败: {e}")
        return None

def _send_feedback(candidate_id: str, job_id: str, feedback: str):
    data = {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "feedback": feedback,
        "session_id": st.session_state.session_id or ""
    }
    resp = requests.post(
        f"{BACKEND_URL}/feedback",
        json=data,
        headers={"Authorization": f"Bearer {st.session_state.auth_token}"}
    )
    if resp.status_code == 200:
        st.toast(f"反馈成功：{feedback}")
    else:
        st.error(f"反馈提交失败: {resp.status_code}")

# ---------- 侧边栏 ----------
with st.sidebar:
    st.markdown("## ⚙️ 导航")
    tab = st.radio(
        "选择功能",
        ["📤 简历上传", "📋 职位管理", "🔍 智能筛选", "📅 面试调度"],
        index=0,
        key="nav_radio"
    )

    st.divider()
    st.markdown("### 📊 快速统计")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("已上传简历", len(st.session_state.candidates))
    with col2:
        st.metric("已解析岗位", len(st.session_state.jobs))

# ---------- 主界面标题 ----------
st.markdown('<div class="main-header">🤖 AI 招聘助手</div>', unsafe_allow_html=True)

# ==================== 1. 简历上传 ====================
if tab == "📤 简历上传":
    st.markdown("### 📤 上传候选人简历")
    st.caption("支持 PDF、Word、图片格式，系统将自动解析并提取关键信息")

    uploader_key = f"main_uploader_{st.session_state.upload_count}"
    uploaded_file = st.file_uploader(
        "拖拽文件到此处或点击浏览",
        type=["pdf", "png", "jpg", "jpeg"],
        key=uploader_key,
        disabled=st.session_state.uploading
    )

    if uploaded_file is not None and not st.session_state.uploading:
        st.session_state.uploading = True
        with st.spinner("正在解析简历..."):
            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
            result = call_backend("/candidates/upload", files=files)
            if result and "profile" in result:
                st.success(f"✅ 解析成功！已添加/更新 {result['profile'].get('name', '未知')}")
                load_candidates_from_backend()
                st.session_state.upload_count += 1
                st.session_state.uploading = False
                st.rerun()
            else:
                st.error("解析失败，请检查文件格式或后端服务")
                st.session_state.uploading = False
    elif st.session_state.uploading:
        st.info("正在处理中，请稍候...")

    if st.session_state.candidates:
        st.divider()
        st.markdown("### 📋 已上传候选人")
        for cand in st.session_state.candidates:
            p = cand["profile"]
            cid = cand["candidate_id"]
            with st.expander(f"👤 {p.get('name', '未知姓名')} - {p.get('email', '')}", expanded=False):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**电话**: {p.get('phone', '未提供')}")
                    st.markdown("**工作经历**:")
                    for exp in p.get("work_experience", [])[:3]:
                        st.markdown(f"- {exp.get('title')} @ {exp.get('company')}")
                    st.markdown("**技能**: " + ", ".join(p.get("skills", [])))
                with col2:
                    if st.button("🗑️ 删除", key=f"del_{cid}"):
                        resp = requests.delete(
                            f"{BACKEND_URL}/candidates/{cid}",
                            headers={"Authorization": f"Bearer {st.session_state.auth_token}"}
                        )
                        if resp.status_code == 200:
                            load_candidates_from_backend()
                            st.rerun()

# ==================== 2. 职位管理 ====================
elif tab == "📋 职位管理":
    st.markdown("### 📋 新建职位解析")
    with st.form("jd_form"):
        jd_text = st.text_area("粘贴职位描述（JD）", height=200, placeholder="例如：我们正在寻找一位拥有3年以上Python开发经验的工程师...")
        submitted = st.form_submit_button("🔍 解析职位", use_container_width=True)
        if submitted and jd_text:
            with st.spinner("AI 正在解析职位要求..."):
                result = call_backend("/jobs", {"jd_text": jd_text, "language": "zh"})
                if result and "parsed" in result:
                    parsed = result["parsed"]
                    job_data = {
                        "id": result["job_id"],
                        "title": parsed["title"],
                        "parsed": parsed,
                        "jd_text": jd_text
                    }
                    st.session_state.jobs.append(job_data)
                    st.session_state.job_id = result["job_id"]
                    load_jobs_from_backend()
                    st.success(f"职位解析成功！已创建：{parsed['title']}")
                    st.rerun()

    if st.session_state.jobs:
        st.divider()
        st.markdown("### 📚 已解析岗位列表")
        for job in st.session_state.jobs:
            with st.expander(f"🏢 {job['title']} ({job['parsed']['job_category']})", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**硬性要求**")
                    for req in job['parsed']['hard_requirements']:
                        st.markdown(f"- {req}")
                with col2:
                    st.markdown("**软性要求**")
                    for req in job['parsed']['soft_requirements']:
                        st.markdown(f"- {req}")
                if st.button("🔍 使用此岗位进行筛选", key=f"screen_{job['id']}"):
                    st.session_state.job_id = job['id']
                    load_screening_results(job['id'])
                    st.rerun()

# ==================== 3. 智能筛选 ====================
elif tab == "🔍 智能筛选":
    st.markdown("### 🔍 候选人筛选")

    if not st.session_state.jobs:
        st.warning("请先在「职位管理」中解析一个岗位")
    else:
        job_names = [j['title'] for j in st.session_state.jobs]
        selected_job = st.selectbox("选择招聘岗位", options=job_names, key="job_selector")
        selected_idx = job_names.index(selected_job)
        current_job_id = st.session_state.jobs[selected_idx]['id']
        st.session_state.job_id = current_job_id

        if st.session_state.get("last_job_id") != current_job_id:
            load_screening_results(current_job_id)
            st.session_state.last_job_id = current_job_id

        query = st.text_input("筛选查询（可选）", placeholder="例如：3年SaaS销售经验")
        max_candidates = st.slider("返回人数", 3, 10, 5)

        if st.button("🚀 开始智能筛选", use_container_width=True):
            with st.spinner("正在执行筛选流程..."):
                data = {
                    "job_id": st.session_state.job_id,
                    "query": query if query else "",
                    "max_candidates": max_candidates,
                    "session_id": st.session_state.session_id or None
                }
                result = call_backend("/screen", data=data)
                if result:
                    st.session_state.session_id = result.get("session_id")
                    st.session_state.screening_results = result.get("results", [])
                    st.session_state.last_job_id = current_job_id
                    st.rerun()

        if st.session_state.screening_results:
            st.divider()
            st.markdown("### 🏆 推荐候选人")
            cols = st.columns(len(st.session_state.screening_results))
            for idx, r in enumerate(st.session_state.screening_results):
                cid = r.get('candidate_id', '?')
                with cols[idx]:
                    with st.container(border=True):
                        st.metric(label=f"#{idx+1}", value=f"{r.get('overall_score', r.get('score', 0)):.1f}分")
                        st.caption(f"候选人ID: {cid}")
                        dim_scores = r.get("dimension_scores", {})
                        if dim_scores:
                            dim_df = {"维度": list(dim_scores.keys()), "分数": list(dim_scores.values())}
                            st.bar_chart(dim_df, x="维度", y="分数", use_container_width=True)
                        with st.expander("查看证据"):
                            for ev in r.get("evidence", [])[:2]:
                                st.markdown(f"- {ev}")

                        # 反馈按钮
                        fb_key = f"fb_{cid}_{current_job_id}"
                        if fb_key not in st.session_state:
                            st.session_state[fb_key] = None
                        current_fb = st.session_state[fb_key]
                        if current_fb is None:
                            f1, f2, f3 = st.columns(3)
                            with f1:
                                if st.button("👍", key=f"good_{fb_key}"):
                                    _send_feedback(cid, current_job_id, "suitable")
                                    st.session_state[fb_key] = "suitable"
                                    st.rerun()
                            with f2:
                                if st.button("👎", key=f"bad_{fb_key}"):
                                    _send_feedback(cid, current_job_id, "not_suitable")
                                    st.session_state[fb_key] = "not_suitable"
                                    st.rerun()
                            with f3:
                                if st.button("⏸️", key=f"pend_{fb_key}"):
                                    _send_feedback(cid, current_job_id, "pending")
                                    st.session_state[fb_key] = "pending"
                                    st.rerun()
                        else:
                            st.info(f"已标记：{current_fb}")

# ==================== 4. 面试调度 ====================
elif tab == "📅 面试调度":
    st.markdown("### 📅 面试邀请")
    if not st.session_state.screening_results:
        st.warning("请先在「智能筛选」中完成一次筛选")
    else:
        candidates_str = [f"#{i+1} {r.get('candidate_id','?')} ({r.get('overall_score',r.get('score',0)):.1f}分)" for i,r in enumerate(st.session_state.screening_results)]
        sel = st.selectbox("选择候选人", candidates_str)
        idx = candidates_str.index(sel)
        cand = st.session_state.screening_results[idx]
        col1, col2 = st.columns(2)
        with col1:
            date = st.date_input("日期", value=datetime.now().date())
        with col2:
            time_slot = st.selectbox("时间段", ["10:00-11:00", "14:00-15:00", "16:00-17:00"])
        proposed_time = f"{date.strftime('%Y-%m-%d')}T{time_slot.split('-')[0]}:00Z"
        if st.button("✉️ 发送邀请", use_container_width=True):
            with st.spinner("发送中..."):
                res = call_backend("/interview/send", {
                    "session_id": st.session_state.session_id,
                    "candidate_id": cand["candidate_id"],
                    "proposed_times": [proposed_time]
                })
                if res:
                    st.success(f"邀请已发送至 {cand['candidate_id']}")
                    st.balloons()

st.divider()
st.caption("AI招聘助手 v3.0")