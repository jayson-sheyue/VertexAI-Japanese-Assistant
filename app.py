import streamlit as st
import psycopg2
from datetime import datetime
import json
from gtts import gTTS
import io
import os
from streamlit_oauth import OAuth2Component
import base64
import threading
import time

# ==========================================
# 0. UI 增强优化
# ==========================================
st.set_page_config(page_title="日语学习助手 v10.1 (SaaS 容灾版)", page_icon="🎌", layout="wide")
st.markdown(
    """
    <style>
        .main .block-container, div[data-testid="stVerticalBlock"], div[data-testid="stTabs"] { overflow: visible !important; }
        div[data-baseweb="tab-list"], div[role="tablist"] {
            position: -webkit-sticky !important; position: sticky !important;
            top: 2.875rem !important; z-index: 99999 !important;
            background-color: var(--background-color) !important;
            padding-top: 15px !important; padding-bottom: 5px !important;
            border-bottom: 1px solid rgba(128, 128, 128, 0.2) !important;
            margin-bottom: 20px !important;
        }
    </style>
    """, unsafe_allow_html=True
)

@st.cache_resource
def get_global_tasks(): return {}
APP_GLOBAL_TASKS = get_global_tasks()

if 'toast_msg' in st.session_state:
    st.toast(st.session_state.toast_msg[0], icon=st.session_state.toast_msg[1])
    del st.session_state.toast_msg

# ==========================================
# 1. AI 智能路由中心 (双通道引擎)
# ==========================================
def call_ai_model(auth_config, sys_instruction, prompt_content, audio_bytes=None):
    model_id = auth_config.get('model_id', 'gemini-1.5-pro')
    if auth_config['channel'] == 'aistudio':
        import google.generativeai as genai
        genai.configure(api_key=auth_config['api_key'])
        model = genai.GenerativeModel(model_name=model_id, system_instruction=sys_instruction)
        contents = []
        if audio_bytes: contents.append({'mime_type': 'audio/wav', 'data': audio_bytes})
        contents.append(prompt_content)
        return model.generate_content(contents).text
    elif auth_config['channel'] == 'vertex':
        import vertexai
        from vertexai.generative_models import GenerativeModel, Part
        vertexai.init(project=auth_config['project_id'], location=auth_config['location'])
        model = GenerativeModel(model_id, system_instruction=[sys_instruction])
        contents = []
        if audio_bytes: contents.append(Part.from_data(data=audio_bytes, mime_type="audio/wav"))
        contents.append(prompt_content)
        return model.generate_content(contents).text
    else:
        raise ValueError("未知的 AI 通道配置！")

# ==========================================
# 2. 数据库引擎重构：直连 Google Cloud SQL
# ==========================================
def get_db_connection():
    db_user = os.environ.get("DB_USER", "postgres")
    db_pass = os.environ.get("DB_PASS", "") 
    db_name = os.environ.get("DB_NAME", "jp_app_db")
    instance_name = os.environ.get("INSTANCE_CONNECTION_NAME", "webeye-internal-test:us-central1:jp-learning-db")
    if os.environ.get("K_SERVICE"):
        host = f"/cloudsql/{instance_name}"
        return psycopg2.connect(user=db_user, password=db_pass, dbname=db_name, host=host)
    else:
        st.error("🚨 警告：应用已升级为云原生架构。本地直接运行无法连接 Cloud SQL。请将代码部署至 Cloud Run。")
        st.stop()

def init_db():
    conn = get_db_connection(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS notes (id SERIAL PRIMARY KEY, user_email TEXT, created_at TEXT, title TEXT DEFAULT '未命名笔记', custom_prompt TEXT, original_note TEXT, summary TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS listening_materials (id SERIAL PRIMARY KEY, user_email TEXT, created_at TEXT, title TEXT DEFAULT '未命名听力素材', source_notes_keys TEXT, transcript TEXT, translation TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS custom_prompts (id SERIAL PRIMARY KEY, user_email TEXT, feature_key TEXT, prompt_name TEXT, prompt_content TEXT)''')
    conn.commit(); c.close(); conn.close()

# --- 查重与常规增删改查 ---
def check_note_title_exists(user_email, title):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('SELECT id FROM notes WHERE user_email = %s AND title = %s', (user_email, title))
    exists = c.fetchone() is not None; c.close(); conn.close(); return exists

def check_listening_title_exists(user_email, title):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('SELECT id FROM listening_materials WHERE user_email = %s AND title = %s', (user_email, title))
    exists = c.fetchone() is not None; c.close(); conn.close(); return exists

def check_prompt_name_exists(user_email, feature_key, name):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('SELECT id FROM custom_prompts WHERE user_email = %s AND feature_key = %s AND prompt_name = %s', (user_email, feature_key, name))
    exists = c.fetchone() is not None; c.close(); conn.close(); return exists

def save_note(user_email, title, prompt, original, summary):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('INSERT INTO notes (user_email, created_at, title, custom_prompt, original_note, summary) VALUES (%s, %s, %s, %s, %s, %s)', (user_email, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), title, prompt, original, summary))
    conn.commit(); c.close(); conn.close()

def get_all_notes(user_email):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('SELECT id, created_at, title, original_note, summary, custom_prompt FROM notes WHERE user_email = %s ORDER BY id DESC', (user_email,))
    data = c.fetchall(); c.close(); conn.close(); return data

def update_note(note_id, user_email, new_title, new_original, new_summary):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('UPDATE notes SET title = %s, original_note = %s, summary = %s WHERE id = %s AND user_email = %s', (new_title, new_original, new_summary, note_id, user_email))
    conn.commit(); c.close(); conn.close()

def delete_note(note_id, user_email):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('DELETE FROM notes WHERE id = %s AND user_email = %s', (note_id, user_email))
    conn.commit(); c.close(); conn.close()

def clear_all_notes(user_email):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('DELETE FROM notes WHERE user_email = %s', (user_email,))
    conn.commit(); c.close(); conn.close()

def add_custom_prompt(user_email, feature_key, name, content):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('INSERT INTO custom_prompts (user_email, feature_key, prompt_name, prompt_content) VALUES (%s, %s, %s, %s)', (user_email, feature_key, name, content))
    conn.commit(); c.close(); conn.close()

def update_custom_prompt(prompt_id, user_email, new_name, new_content):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('UPDATE custom_prompts SET prompt_name = %s, prompt_content = %s WHERE id = %s AND user_email = %s', (new_name, new_content, prompt_id, user_email))
    conn.commit(); c.close(); conn.close()

def delete_custom_prompt(prompt_id, user_email):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('DELETE FROM custom_prompts WHERE id = %s AND user_email = %s', (prompt_id, user_email))
    conn.commit(); c.close(); conn.close()

def clear_all_prompts(user_email):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('DELETE FROM custom_prompts WHERE user_email = %s', (user_email,))
    conn.commit(); c.close(); conn.close()

def save_listening_material(user_email, title, keys, transcript, translation):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('INSERT INTO listening_materials (user_email, created_at, title, source_notes_keys, transcript, translation) VALUES (%s, %s, %s, %s, %s, %s)', (user_email, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), title, keys, transcript, translation))
    conn.commit(); c.close(); conn.close()

def get_all_listening_materials(user_email):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('SELECT id, created_at, title, source_notes_keys, transcript, translation FROM listening_materials WHERE user_email = %s ORDER BY id DESC', (user_email,))
    data = c.fetchall(); c.close(); conn.close(); return data

def update_listening_material_title(lm_id, user_email, new_title):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('UPDATE listening_materials SET title = %s WHERE id = %s AND user_email = %s', (new_title, lm_id, user_email))
    conn.commit(); c.close(); conn.close()

def delete_listening_material(lm_id, user_email):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('DELETE FROM listening_materials WHERE id = %s AND user_email = %s', (lm_id, user_email))
    conn.commit(); c.close(); conn.close()

def clear_all_listening(user_email):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('DELETE FROM listening_materials WHERE user_email = %s', (user_email,))
    conn.commit(); c.close(); conn.close()

# ==========================================
# 2.5 V10.1 核心：数据冷备份与恢复引擎
# ==========================================
def export_user_data_to_dict(user_email):
    """提取该用户所有表数据并打包成字典"""
    conn = get_db_connection(); c = conn.cursor()
    
    c.execute('SELECT title, custom_prompt, original_note, summary, created_at FROM notes WHERE user_email = %s', (user_email,))
    notes = [{"title": r[0], "custom_prompt": r[1], "original_note": r[2], "summary": r[3], "created_at": r[4]} for r in c.fetchall()]
    
    c.execute('SELECT title, source_notes_keys, transcript, translation, created_at FROM listening_materials WHERE user_email = %s', (user_email,))
    listening = [{"title": r[0], "source_notes_keys": r[1], "transcript": r[2], "translation": r[3], "created_at": r[4]} for r in c.fetchall()]
    
    c.execute('SELECT feature_key, prompt_name, prompt_content FROM custom_prompts WHERE user_email = %s', (user_email,))
    prompts = [{"feature_key": r[0], "prompt_name": r[1], "prompt_content": r[2]} for r in c.fetchall()]
    
    c.close(); conn.close()
    return {"notes": notes, "listening_materials": listening, "custom_prompts": prompts}

def restore_user_data_from_dict(user_email, data):
    """安全覆盖式恢复数据（带防灾回滚机制）"""
    conn = get_db_connection(); c = conn.cursor()
    try:
        # 1. 物理抹除该用户当前所有数据
        c.execute('DELETE FROM notes WHERE user_email = %s', (user_email,))
        c.execute('DELETE FROM listening_materials WHERE user_email = %s', (user_email,))
        c.execute('DELETE FROM custom_prompts WHERE user_email = %s', (user_email,))
        
        # 2. 逐条写入备份数据
        for n in data.get("notes", []):
            c.execute('INSERT INTO notes (user_email, created_at, title, custom_prompt, original_note, summary) VALUES (%s, %s, %s, %s, %s, %s)',
                      (user_email, n.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")), n.get("title", "恢复的笔记"), n.get("custom_prompt", ""), n.get("original_note", ""), n.get("summary", "")))
                      
        for l in data.get("listening_materials", []):
            c.execute('INSERT INTO listening_materials (user_email, created_at, title, source_notes_keys, transcript, translation) VALUES (%s, %s, %s, %s, %s, %s)',
                      (user_email, l.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")), l.get("title", "恢复的听力"), l.get("source_notes_keys", ""), l.get("transcript", ""), l.get("translation", "")))
                      
        for p in data.get("custom_prompts", []):
            c.execute('INSERT INTO custom_prompts (user_email, feature_key, prompt_name, prompt_content) VALUES (%s, %s, %s, %s)',
                      (user_email, p.get("feature_key", "chat"), p.get("prompt_name", "恢复的提示词"), p.get("prompt_content", "")))
                      
        # 3. 只有全部成功，才提交事务
        conn.commit()
    except Exception as e:
        conn.rollback() # 发生任何解析错误，立刻回滚，保护用户原数据不丢失
        raise e
    finally:
        c.close(); conn.close()

# ==========================================
# 3. 辅助功能组件与 UI 渲染
# ==========================================
def generate_japanese_audio(text):
    try:
        tts = gTTS(text=text, lang='ja')
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        return fp.getvalue()
    except Exception as e:
        st.error(f"语音生成失败: {e}")
        return None

def render_note_selector(note_options_dict, prefix):
    selected_keys = []
    st.markdown("👉 **请勾选历史笔记作为素材源：**")
    with st.container(height=150):
        for key in note_options_dict.keys():
            if st.checkbox(key, key=f"checkbox_{prefix}_{key}"):
                selected_keys.append(key)
    return selected_keys

def prompt_manager_ui(user_email, feature_key, default_prompt_text):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('SELECT id, prompt_name, prompt_content FROM custom_prompts WHERE feature_key = %s AND user_email = %s', (feature_key, user_email))
    custom_prompts = c.fetchall(); c.close(); conn.close()

    options = {"[默认] 系统出厂提示词": default_prompt_text}
    prompt_lookup = {}
    for p in custom_prompts:
        opt_key = f"[自定义] {p[1]} (ID:{p[0]})"
        options[opt_key] = p[2]
        prompt_lookup[opt_key] = {"id": p[0], "name": p[1], "content": p[2]}

    selected_option = st.selectbox("🎭 选择 AI 人设与系统提示词：", list(options.keys()), key=f"select_prompt_{feature_key}")
    current_prompt = options[selected_option]
    st.caption("👇 当前生效的提示词内容：")
    st.info(current_prompt)

    hide_edit_key = f"hide_edit_{feature_key}"
    last_sel_key = f"last_sel_{feature_key}"
    
    if st.session_state.get(last_sel_key) != selected_option:
        st.session_state[hide_edit_key] = False
        st.session_state[last_sel_key] = selected_option

    with st.expander("⚙️ 管理自定义提示词 (编辑 / 新增 / 删除)"):
        if "[自定义]" in selected_option:
            p_data = prompt_lookup[selected_option]
            p_id = p_data["id"]
            
            if not st.session_state.get(hide_edit_key, False):
                st.markdown("✏️ **编辑当前选中的提示词**")
                edit_name = st.text_input("名称", value=p_data["name"], key=f"edit_name_{feature_key}_{p_id}")
                edit_content = st.text_area("内容", value=p_data["content"], key=f"edit_content_{feature_key}_{p_id}")
                col_e1, col_e2 = st.columns([1, 1])
                with col_e1:
                    if st.button("💾 保存修改", key=f"save_edit_{feature_key}_{p_id}", type="primary"):
                        edit_name_clean = edit_name.strip()
                        if edit_name_clean != p_data["name"] and check_prompt_name_exists(user_email, feature_key, edit_name_clean):
                            st.error(f"❌ 名称 '{edit_name_clean}' 已存在，请换一个！")
                        else:
                            update_custom_prompt(p_id, user_email, edit_name_clean, edit_content)
                            st.session_state.toast_msg = ("提示词修改成功！", "✅")
                            st.session_state[hide_edit_key] = True 
                            st.rerun()
                with col_e2:
                    if st.button("🗑️ 删除此提示词", key=f"del_{feature_key}_{p_id}"):
                        delete_custom_prompt(p_id, user_email)
                        st.session_state.toast_msg = ("提示词已删除！", "🗑️")
                        st.rerun()
            else:
                st.success("✅ 操作成功！编辑面板已收起。如需再次修改，请切换一下上方的选项。")
            st.write("---")
            
        st.markdown("➕ **新增自定义提示词**")
        with st.form(key=f"new_prompt_form_{feature_key}", clear_on_submit=True):
            new_name = st.text_input("新提示词名称 (如: 关西腔毒舌外教)")
            new_content = st.text_area("新提示词内容")
            submitted = st.form_submit_button("💾 新建并保存", type="primary")
            if submitted:
                new_name_clean = new_name.strip()
                if new_name_clean and new_content.strip():
                    if check_prompt_name_exists(user_email, feature_key, new_name_clean):
                        st.error(f"❌ 提示词名称 '{new_name_clean}' 已存在！")
                    else:
                        add_custom_prompt(user_email, feature_key, new_name_clean, new_content)
                        st.session_state.toast_msg = (f"已成功创建提示词：{new_name_clean}", "🎉")
                        st.rerun()
                else:
                    st.warning("名称和内容不能为空！")

    return current_prompt

# ==========================================
# 4. 真后台异步任务引擎 
# ==========================================
def bg_ai_task(task_id, auth_config, sys_instruction, prompt, context_data):
    try:
        response_text = call_ai_model(auth_config, sys_instruction, prompt)
        APP_GLOBAL_TASKS[task_id] = {'status': 'success', 'data': response_text, 'context': context_data}
    except Exception as e:
        APP_GLOBAL_TASKS[task_id] = {'status': 'error', 'data': str(e), 'context': context_data}

def start_bg_task(task_id, task_type, auth_config, sys_instruction, prompt, context_data=None):
    if context_data is None: context_data = {}
    context_data['task_type'] = task_type
    user_email = context_data.get('user_email')
    for t in APP_GLOBAL_TASKS.values():
        if t['status'] == 'running' and t['context'].get('user_email') == user_email and t['context'].get('task_type') == task_type:
            return 
            
    APP_GLOBAL_TASKS[task_id] = {'status': 'running', 'context': context_data}
    type_names = {"quiz": "智能测验卡片", "flashcard": "知识闪卡", "listening": "长篇听力素材"}
    t_name = type_names.get(task_type, "任务")
    st.session_state.inbox_messages.insert(0, {"id": task_id, "text": f"⏳ 正在后台为您生成 {t_name}...", "tab": None, "type": "running"})
    t = threading.Thread(target=bg_ai_task, args=(task_id, auth_config, sys_instruction, prompt, context_data))
    t.start()

def handle_msg_click(msg_id, target_tab):
    st.session_state.inbox_messages = [m for m in st.session_state.inbox_messages if m['id'] != msg_id]
    if target_tab: st.session_state.nav_menu = target_tab

def dismiss_msg(msg_id):
    st.session_state.inbox_messages = [m for m in st.session_state.inbox_messages if m['id'] != msg_id]

# ==========================================
# 5. Session State & 登录拦截
# ==========================================
@st.cache_data
def load_google_credentials():
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if client_id and client_secret: return client_id, client_secret

    cred_file = "client_secret.json"
    if os.path.exists(cred_file):
        try:
            with open(cred_file, "r") as f:
                creds_data = json.load(f)
                web_creds = creds_data.get("web", {})
                return web_creds.get("client_id"), web_creds.get("client_secret")
        except: pass
    return None, None

CLIENT_ID, CLIENT_SECRET = load_google_credentials()
REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://localhost:8501/")

if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if 'user_email' not in st.session_state: st.session_state.user_email = None
if 'user_name' not in st.session_state: st.session_state.user_name = None
if 'ai_auth_config' not in st.session_state: st.session_state.ai_auth_config = None 

if 'inbox_messages' not in st.session_state: st.session_state.inbox_messages = []
if 'quiz_data' not in st.session_state: st.session_state.quiz_data = None
if 'current_q_index' not in st.session_state: st.session_state.current_q_index = 0
if 'feedback' not in st.session_state: st.session_state.feedback = None
if 'flashcards_data' not in st.session_state: st.session_state.flashcards_data = None
if 'current_card_index' not in st.session_state: st.session_state.current_card_index = 0
if 'card_flipped' not in st.session_state: st.session_state.card_flipped = False
if 'chat_history' not in st.session_state: st.session_state.chat_history = []

def next_question():
    if st.session_state.current_q_index < len(st.session_state.quiz_data) - 1: st.session_state.current_q_index += 1; st.session_state.feedback = None 
def prev_question():
    if st.session_state.current_q_index > 0: st.session_state.current_q_index -= 1; st.session_state.feedback = None
def next_card():
    if st.session_state.current_card_index < len(st.session_state.flashcards_data) - 1: st.session_state.current_card_index += 1; st.session_state.card_flipped = False
def prev_card():
    if st.session_state.current_card_index > 0: st.session_state.current_card_index -= 1; st.session_state.card_flipped = False
def flip_card(): st.session_state.card_flipped = not st.session_state.card_flipped

# ==========================================
# 6. 全局后台任务检查器
# ==========================================
if st.session_state.user_email:
    my_completed_tasks = [tid for tid, t in APP_GLOBAL_TASKS.items() if t['context'].get('user_email') == st.session_state.user_email and t['status'] in ['success', 'error']]
    for tid in my_completed_tasks:
        t = APP_GLOBAL_TASKS.pop(tid)
        if t['status'] == 'success':
            try:
                raw_json = t['data'].replace("```json", "").replace("```", "").strip()
                data = json.loads(raw_json)
                task_type = t['context'].get('task_type')
                
                success_text = ""; target_tab = ""
                if task_type == 'quiz':
                    st.session_state.quiz_data = data; st.session_state.current_q_index = 0
                    success_text = "✅ 智能测验卡片已生成完毕！"; target_tab = "🧠 卡片测试"
                elif task_type == 'flashcard':
                    st.session_state.flashcards_data = data; st.session_state.current_card_index = 0
                    success_text = "✅ 知识闪卡已生成完毕！"; target_tab = "📇 知识闪卡"
                elif task_type == 'listening':
                    ctx = t['context']
                    save_listening_material(ctx['user_email'], ctx['title'], ctx['keys_str'], data['transcript'], data['translation'])
                    success_text = f"✅ 听力素材《{ctx['title']}》已生成完毕！"; target_tab = "🎧 专属听力库"
                
                found = False
                for msg in st.session_state.inbox_messages:
                    if msg['id'] == tid:
                        msg['text'] = success_text; msg['tab'] = target_tab; msg['type'] = "success"
                        found = True; break
                if not found: st.session_state.inbox_messages.insert(0, {"id": tid, "text": success_text, "tab": target_tab, "type": "success"})
                st.toast(success_text, icon="🎉")
            except Exception as e:
                for msg in st.session_state.inbox_messages:
                    if msg['id'] == tid:
                        msg['text'] = f"❌ 解析失败，请重试: {e}"; msg['type'] = "error"
                st.toast("解析生成内容时出错", icon="❌")
                
        elif t['status'] == 'error':
            for msg in st.session_state.inbox_messages:
                if msg['id'] == tid:
                    msg['text'] = f"❌ 任务失败: {t['data'][:50]}..."; msg['type'] = "error"
            st.toast("后台任务执行失败", icon="❌")

try: init_db()
except Exception as db_e:
    st.error(f"🚨 数据库初始化失败，请检查 Cloud SQL 配置：{db_e}"); st.stop()

if not st.session_state.user_email:
    st.title("🎌 Vertex AI 日语学习助手 v10.1 (SaaS容灾版)")
    st.markdown("### 欢迎使用专属你的 AI 语言外教系统")
    st.write("请使用您的 Google 账号安全登录以访问和隔离您的个人学习数据。")
    st.write("---")
    if not CLIENT_ID or not CLIENT_SECRET: st.error("🚨 找不到 Google OAuth 凭据配置。")
    else:
        oauth2 = OAuth2Component(client_id=CLIENT_ID, client_secret=CLIENT_SECRET, authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth", token_endpoint="https://oauth2.googleapis.com/token", refresh_token_endpoint="https://oauth2.googleapis.com/token", revoke_token_endpoint="https://oauth2.googleapis.com/revoke")
        result = oauth2.authorize_button("使用 Google 账号安全登录", redirect_uri=REDIRECT_URI, scope="openid email profile", icon="https://www.google.com.tw/favicon.ico", key="google_login_btn", use_container_width=False)
        if result and 'token' in result:
            id_token = result['token']['id_token']; payload = id_token.split('.')[1]; payload += '=' * (-len(payload) % 4)
            user_info = json.loads(base64.b64decode(payload).decode('utf-8'))
            st.session_state.user_email = user_info.get("email"); st.session_state.user_name = user_info.get("name")
            st.rerun()
    st.stop()

# ==========================================
# 7. 侧边栏导航与配置
# ==========================================
current_user = st.session_state.user_email

with st.sidebar:
    st.markdown("## 🎌 日语学习助手")
    st.caption("Dual-Track AI Powered Engine")
    st.write("---")
    
    if st.session_state.inbox_messages:
        with st.expander(f"📬 消息通知盒子 ({len(st.session_state.inbox_messages)})", expanded=True):
            for msg in st.session_state.inbox_messages:
                if msg['type'] == 'running': st.info(msg['text'])
                elif msg['type'] == 'success':
                    st.success(msg['text'])
                    st.button(f"前往 {msg['tab']}", key=f"go_{msg['id']}", on_click=handle_msg_click, args=(msg['id'], msg['tab']), type="primary")
                else:
                    st.error(msg['text'])
                    st.button("清除消息", key=f"clr_{msg['id']}", on_click=dismiss_msg, args=(msg['id'],))
            st.write("---")

    if 'nav_menu' not in st.session_state: st.session_state.nav_menu = "📝 笔记归纳"
    st.radio("📌 功能导航", ["📝 笔记归纳", "📚 历史笔记", "🧠 卡片测试", "📇 知识闪卡", "💬 语音对练", "🎧 专属听力库"], key="nav_menu", label_visibility="collapsed")
    st.write("---")
    
    with st.expander("🗣️ 随手查：临时语音朗读", expanded=False):
        tts_text = st.text_area("把想要听的日语粘贴在这里：", height=80, label_visibility="collapsed", placeholder="输入日语...")
        if st.button("🔊 朗读", use_container_width=True):
            if tts_text.strip():
                audio_bytes = generate_japanese_audio(tts_text)
                if audio_bytes: st.audio(audio_bytes, format='audio/mp3')

    st.write("---")
    st.success(f"👋 {st.session_state.user_name}\n\n📧 {current_user}")
    if st.button("退出登录", use_container_width=True):
        st.session_state.user_email = None; st.session_state.user_name = None; st.session_state.authenticated = False; st.session_state.ai_auth_config = None; st.rerun()

    st.write("---")
    with st.expander("⚙️ AI 模型服务通道配置", expanded=not bool(st.session_state.authenticated)):
        st.write("请选择用于处理您私人数据的 AI 模型通道：")
        auth_channel = st.radio("认证方式", ["🟢 Google AI Studio (API Key / 免费)", "🔵 Vertex AI (GCP / 企业级)"], label_visibility="collapsed")
        
        if "API Key" in auth_channel:
            api_key = st.text_input("Gemini API Key", type="password", placeholder="AIzaSy...")
            model_id = st.text_input("模型版本", value="gemini-1.5-pro")
            if st.button("🔌 测试并保存配置 (AI Studio)", use_container_width=True):
                if not api_key: st.warning("请输入 API Key")
                else:
                    st.session_state.ai_auth_config = {'channel': 'aistudio', 'api_key': api_key, 'model_id': model_id}
                    try:
                        with st.spinner("连接 Google AI Studio..."):
                            call_ai_model(st.session_state.ai_auth_config, "You are a tester.", "Say OK")
                            st.session_state.authenticated = True
                            st.session_state.toast_msg = ("AI Studio 连接并验证成功！", "✅"); st.rerun()
                    except Exception as e: st.error(f"❌ 验证失败：{e}")
        else:
            project_id = st.text_input("GCP Project ID", placeholder="my-gcp-project")
            location = st.text_input("Location", value="us-central1")
            model_id = st.text_input("模型版本", value="gemini-1.5-pro") 
            if st.button("🔌 测试并保存配置 (Vertex AI)", use_container_width=True):
                if not project_id or not location: st.warning("请填写完整的云项目信息")
                else:
                    st.session_state.ai_auth_config = {'channel': 'vertex', 'project_id': project_id, 'location': location, 'model_id': model_id}
                    try:
                        with st.spinner("连接 Vertex AI 企业网关..."):
                            call_ai_model(st.session_state.ai_auth_config, "You are a tester.", "Say OK")
                            st.session_state.authenticated = True
                            st.session_state.toast_msg = ("Vertex AI 连接并验证成功！", "✅"); st.rerun()
                    except Exception as e: st.error(f"❌ 验证失败：{e}")

    # V10.1 新增：数据冷备份与恢复模块
    st.write("---")
    with st.expander("💽 数据冷备份与恢复", expanded=False):
        st.markdown("将您的所有**笔记**、**听力素材**和**自定义提示词**导出为安全的 JSON 文件，或者通过备份文件一键恢复您的数据库。")
        
        # 导出功能
        try:
            user_data_dict = export_user_data_to_dict(current_user)
            json_str = json.dumps(user_data_dict, ensure_ascii=False, indent=2)
            st.download_button(
                label="⬇️ 一键打包并导出全部数据",
                data=json_str,
                file_name=f"jp_learning_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                mime="application/json",
                use_container_width=True
            )
        except Exception as e:
            st.error(f"打包备份数据时出错: {e}")
            
        st.write("---")
        
        # 导入功能
        uploaded_file = st.file_uploader("⬆️ 上传备份文件进行恢复", type=["json"])
        if uploaded_file is not None:
            if st.button("⚠️ 确认覆盖当前数据并恢复", type="primary", use_container_width=True):
                try:
                    with st.spinner("📦 正在安全擦除并覆盖写入数据..."):
                        backup_data = json.load(uploaded_file)
                        restore_user_data_from_dict(current_user, backup_data)
                        st.session_state.toast_msg = ("数据恢复成功！欢迎回来。", "🎉")
                        st.rerun()
                except Exception as e:
                    st.error(f"恢复失败，请确保文件未损坏: {e}")

    st.write("---")
    with st.expander("🚨 危险区域 (清空数据)", expanded=False):
        pwd = st.text_input("请输入管理密码解锁", type="password")
        if pwd == "123456":
            st.success("🔓 操作已解锁")
            if st.button("🗑️ 清空所有笔记", type="primary", use_container_width=True):
                clear_all_notes(current_user); st.session_state.toast_msg=("所有笔记已清空", "🗑️"); st.rerun()
            if st.button("🗑️ 清空所有听力素材", type="primary", use_container_width=True):
                clear_all_listening(current_user); st.session_state.toast_msg=("所有听力素材已清空", "🗑️"); st.rerun()
            if st.button("🗑️ 清空自定义提示词", type="primary", use_container_width=True):
                clear_all_prompts(current_user); st.session_state.toast_msg=("自定义提示词已清空", "🗑️"); st.rerun()
            if st.button("💥 一键清空所有数据", type="primary", use_container_width=True):
                clear_all_notes(current_user); clear_all_listening(current_user); clear_all_prompts(current_user)
                st.session_state.toast_msg=("所有数据已彻底清空", "💥"); st.rerun()

# ==========================================
# 8. 核心业务逻辑
# ==========================================
if st.session_state.authenticated and st.session_state.ai_auth_config:
    auth_cfg = st.session_state.ai_auth_config
    history_notes = get_all_notes(current_user)
    note_options_dict = {f"[{note[1][:10]}] {note[2]} (ID:{note[0]})": note for note in history_notes} if history_notes else {}

    # ----- 1：笔记归纳 -----
    if st.session_state.nav_menu == "📝 笔记归纳":
        st.header("📝 笔记归纳与处理")
        active_summary_prompt = prompt_manager_ui(current_user, "summary", "你是一个专业的日语教师。请帮我整理以下日语学习笔记，提取核心语法、高频词汇，并指出需要注意的易错点。请用Markdown结构化的方式输出。")
        note_title = st.text_input("给这篇笔记起个标题吧 🏷️", placeholder="例如：第12课 动词Te形变化规则")
        user_note = st.text_area("输入日语学习笔记正文", height=150)
        
        if st.button("✨ 开始归纳整理", type="primary"):
            note_title_clean = note_title.strip()
            if not note_title_clean: st.warning("请输入笔记标题哦！")
            elif check_note_title_exists(current_user, note_title_clean): st.error(f"❌ 笔记标题 '{note_title_clean}' 已存在！")
            elif user_note.strip():
                with st.spinner("努力思考中..."):
                    try:
                        summary = call_ai_model(auth_cfg, active_summary_prompt, f"请归纳以下笔记内容：\n{user_note}")
                        st.markdown(summary)
                        save_note(current_user, note_title_clean, active_summary_prompt, user_note, summary)
                        st.toast("笔记已成功归纳并保存至历史记录！", icon="💾")
                        st.success("🎉 笔记归纳完成！已自动为您保存至历史记录。")
                        st.markdown("### 💡 AI 点评与归纳"); st.info(summary)
                    except Exception as e: st.error(f"生成失败：{e}")

    # ----- 2：历史笔记 -----
    elif st.session_state.nav_menu == "📚 历史笔记":
        st.header("📚 查看与管理历史笔记")
        if history_notes:
            selected_note_key = st.selectbox("📝 选择历史笔记（用于预览和编辑）：", options=list(note_options_dict.keys()), key="tab2_select")
            st.write("---")
            view_tab, edit_tab, bulk_del_tab = st.tabs(["👁️ 预览与朗读", "✏️ 编辑此笔记", "🗑️ 批量检索与删除"])
            if selected_note_key:
                note = note_options_dict[selected_note_key]; note_id = note[0]
                with view_tab:
                    st.subheader(note[2]); st.info(note[3])
                    if st.button("🔊 生成笔记语音", key=f"audio_btn_{note_id}"):
                        audio_b = generate_japanese_audio(note[3])
                        if audio_b: st.audio(audio_b, format='audio/mp3')
                    st.success(note[4])
                with edit_tab:
                    st.markdown("保存时，AI将根据新的笔记正文自动重新生成归纳结果。")
                    edit_title = st.text_input("修改笔记标题", value=note[2], key=f"edit_title_{note_id}")
                    edit_original = st.text_area("修改原始笔记正文", value=note[3], height=150, key=f"edit_orig_{note_id}")
                    if st.button("💾 保存修改并同步更新 AI 归纳", type="primary", key=f"save_btn_{note_id}"):
                        edit_title_clean = edit_title.strip()
                        if edit_title_clean != note[2] and check_note_title_exists(current_user, edit_title_clean):
                            st.error(f"❌ 标题 '{edit_title_clean}' 已存在！")
                        else:
                            with st.spinner("AI 正在根据修改后的内容重新归纳，请稍候..."):
                                try:
                                    new_summary = call_ai_model(auth_cfg, note[5], f"请归纳以下修改后的笔记内容：\n{edit_original}")
                                    update_note(note_id, current_user, edit_title_clean, edit_original, new_summary)
                                    st.session_state.toast_msg = ("修改已保存，AI归纳已同步更新！", "✅"); st.rerun()
                                except Exception as e: st.error(f"生成失败：{e}")
            with bulk_del_tab:
                st.markdown("### 🔍 筛选与批量删除")
                search_kw = st.text_input("搜索笔记标题或正文 (留空显示全部)", key="search_note_kw")
                filtered_notes = [n for n in history_notes if search_kw.lower() in n[2].lower() or search_kw.lower() in n[3].lower()]
                if filtered_notes:
                    del_options = {f"[{n[1][:10]}] {n[2]} (ID:{n[0]})": n[0] for n in filtered_notes}
                    selected_del_keys = st.multiselect("请勾选要永久删除的笔记：", list(del_options.keys()), key="ms_del_notes")
                    if st.button("🚨 确认删除选中的笔记", type="primary", key="btn_del_notes"):
                        if selected_del_keys:
                            for k in selected_del_keys: delete_note(del_options[k], current_user)
                            st.session_state.toast_msg = (f"成功删除了 {len(selected_del_keys)} 条笔记！", "✅"); st.rerun()
                        else: st.warning("请先勾选需要删除的笔记。")
                else: st.info("没有找到符合条件的笔记。")
        else: st.info("您还没有保存过任何笔记。")

    # ----- 3：卡片测试 -----
    elif st.session_state.nav_menu == "🧠 卡片测试":
        st.header("🧠 智能测验卡片")
        if history_notes:
            active_quiz_prompt = prompt_manager_ui(current_user, "quiz", "你是一个严格的日语考官。请考察我的掌握程度。")
            st.write("---")
            is_running = any(t['context'].get('user_email') == current_user and t.get('task_type') == 'quiz' for t in APP_GLOBAL_TASKS.values())
            
            if is_running:
                st.info("⏳ **正在后台为您定制考题...**\n\n您可以无缝切换到左侧的其他功能模块。\n生成完毕后，左侧的【📬 消息通知盒子】会主动提醒您！")
                if st.button("🔄 手动刷新状态", key="refresh_quiz"): st.rerun()
            elif not st.session_state.quiz_data:
                with st.form("quiz_generate_form"):
                    col1, col2 = st.columns([2, 1])
                    with col1: selected_quiz_keys = render_note_selector(note_options_dict, "quiz")
                    with col2: num_questions = st.number_input("生成题目数量", min_value=1, value=5, key="quiz_num")
                    submitted = st.form_submit_button("🚀 组合素材后台生成混合测试", type="primary")
                    if submitted:
                        if not selected_quiz_keys: st.warning("请至少勾选一个素材！")
                        else:
                            with st.spinner("🚀 正在将您的请求送往大模型通道..."):
                                combined_material = "\n\n".join([note_options_dict[k][3] for k in selected_quiz_keys])
                                sys_instruction = f"{active_quiz_prompt}\n\n【强制系统约束(勿修改)】：请生成{num_questions}道题。题目形式必须是随机混合的：部分是纯文字题（不带语音），部分是听力语音题。请严格按照以下 JSON 格式输出数组，不要输出任何解释文字：\n[{{'question':'中文提问或情境说明','has_audio': true或false, 'japanese_text':'如果has_audio为true则填入需要发音的日文原句，否则留空','standard_answer':'答案','hint':'提示'}}]"
                                task_id = "quiz_" + str(datetime.now().timestamp())
                                ctx = {'user_email': current_user}
                                start_bg_task(task_id, "quiz", auth_cfg, sys_instruction, f"学习素材：\n{combined_material}", context_data=ctx)
                                time.sleep(0.6); st.rerun() 

            if st.session_state.quiz_data:
                if st.button("🗑️ 放弃当前试卷，重新生成测试", type="secondary"): st.session_state.quiz_data = None; st.rerun()
                q_list = st.session_state.quiz_data; i = st.session_state.current_q_index; q = q_list[i]
                st.markdown("---")
                st.markdown(f"**[{i+1}/{len(q_list)}] 问题：** {q['question']}")
                if bool(q.get('has_audio', False)) and q.get('japanese_text'):
                    st.write("🔈 **请听音频完成作答：**"); st.audio(generate_japanese_audio(q['japanese_text']), format='audio/mp3')

                user_answer = st.text_input("✍️ 答案：", key=f"ans_{i}")
                if st.button("✅ 批改", key=f"grade_btn_{i}", type="primary"):
                    if not user_answer.strip(): st.warning("请输入答案才能批改哦！")
                    else:
                        with st.spinner("AI 老师批改中..."):
                            try:
                                feedback = call_ai_model(auth_cfg, active_quiz_prompt, f"请批改学生的回答。\n题目:{q['question']}\n标准答案:{q['standard_answer']}\n学生的回答:{user_answer}\n请给出简短点评。")
                                st.session_state.feedback = feedback
                            except Exception as e: st.session_state.feedback = f"❌ 批改失败：{e}"
                
                if st.session_state.feedback: st.info(st.session_state.feedback)
                c1, c2, c3 = st.columns([1, 8, 1])
                with c1: st.button("⬅️ 上一题", on_click=prev_question, disabled=(i==0))
                with c3: st.button("下一题 ➡️", on_click=next_question, disabled=(i==len(q_list)-1))
        else: st.info("需要先保存笔记哦。")

    # ----- 4：知识闪卡 -----
    elif st.session_state.nav_menu == "📇 知识闪卡":
        st.header("📇 快速知识闪卡复习")
        if history_notes:
            active_flashcard_prompt = prompt_manager_ui(current_user, "flashcard", "你是一个专业的日语助教。请提取词汇或语法点并提供例句。")
            st.write("---")
            is_running = any(t['context'].get('user_email') == current_user and t.get('task_type') == 'flashcard' for t in APP_GLOBAL_TASKS.values())
            
            if is_running:
                st.info("⏳ **正在后台为您萃取知识卡片...**\n\n您可以无缝切换到左侧的其他功能模块。\n生成完毕后，左侧的【📬 消息通知盒子】会主动提醒您！")
                if st.button("🔄 手动刷新状态", key="refresh_flash"): st.rerun()
            elif not st.session_state.flashcards_data:
                with st.form("flashcard_form"):
                    col1, col2 = st.columns([2, 1])
                    with col1: selected_flash_keys = render_note_selector(note_options_dict, "flashcard")
                    with col2: num_cards = st.number_input("生成闪卡数量", min_value=1, max_value=50, value=10)
                    submitted = st.form_submit_button("🃏 后台抽取记忆闪卡", type="primary")
                    if submitted:
                        if not selected_flash_keys: st.warning("请至少勾选一个素材！")
                        else:
                            with st.spinner("🚀 正在唤醒后台 AI 助教..."):
                                combined_material = "\n\n".join([note_options_dict[k][3] for k in selected_flash_keys])
                                sys_instruction = f"{active_flashcard_prompt}\n\n【强制系统约束(勿修改)】：请抽取 {num_cards} 个核心点。严格按照 JSON 格式输出数组，绝不输出其他说明文本：\n[{{'front': '日文','back': '中文意思','example': '日文例句','type': '词汇/语法'}}]"
                                task_id = "flash_" + str(datetime.now().timestamp())
                                ctx = {'user_email': current_user}
                                start_bg_task(task_id, "flashcard", auth_cfg, sys_instruction, f"学习素材：\n{combined_material}", context_data=ctx)
                                time.sleep(0.6); st.rerun()

            if st.session_state.flashcards_data:
                if st.button("🗑️ 放弃当前闪卡，重新抽取", type="secondary"): st.session_state.flashcards_data = None; st.rerun()
                cards = st.session_state.flashcards_data; c_idx = st.session_state.current_card_index; card = cards[c_idx]
                st.write("---")
                st.markdown(f"<h4 style='text-align: center;'>进度: {c_idx + 1} / {len(cards)}</h4>", unsafe_allow_html=True)
                card_style = "<div style='padding: 40px; border-radius: 15px; border: 2px solid #4CAF50; text-align: center; background-color: #f9f9f9; min-height: 200px; display: flex; flex-direction: column; justify-content: center;'><h2 style='color: #333;'>{content}</h2><p style='color: #666; font-size: 14px; margin-top: 20px;'>{sub_content}</p></div>"
                if not st.session_state.card_flipped: st.markdown(card_style.format(content=card['front'], sub_content=f"类型: {card.get('type', '知识点')}"), unsafe_allow_html=True)
                else:
                    st.markdown(card_style.format(content=card['back'], sub_content=f"例句: {card.get('example', '')}"), unsafe_allow_html=True)
                    audio_text = f"{card['front']}。 {card.get('example', '')}"
                    st.write("🔈 **知识点发音：**"); st.audio(generate_japanese_audio(audio_text), format='audio/mp3')
                st.write("") 
                ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1, 1, 1])
                with ctrl_col1: st.button("⬅️ 上一张", use_container_width=True, on_click=prev_card, disabled=(c_idx==0))
                with ctrl_col2: st.button("查看背面" if not st.session_state.card_flipped else "翻回正面", use_container_width=True, on_click=flip_card, type="primary")
                with ctrl_col3: st.button("下一张 ➡️", use_container_width=True, on_click=next_card, disabled=(c_idx==len(cards)-1))
        else: st.info("需要先保存笔记哦。")

    # ----- 5：语音对练 -----
    elif st.session_state.nav_menu == "💬 语音对练":
        st.header("💬 AI 日语口语对练")
        active_chat_prompt = prompt_manager_ui(current_user, "chat", "你是一个亲切的日语老师。用自然口语化的日语回复，并加上中文翻译。")
        st.write("---")
        audio_value = st.audio_input("🎤 按下此处开始录音...")
        if audio_value:
            if st.button("发送给 AI 老师 📤", type="primary"):
                with st.spinner("AI 正在听你的录音并准备回复..."):
                    try:
                        reply_text = call_ai_model(auth_cfg, active_chat_prompt, "（这是我的语音留言，请直接用语音里提到的语境回复我）", audio_bytes=audio_value.getvalue())
                        st.session_state.chat_history.append({"role": "user", "audio": audio_value.getvalue()})
                        st.session_state.chat_history.append({"role": "ai", "text": reply_text})
                    except Exception as e: st.error(f"对话失败：{e}")

        st.write("---")
        for chat in st.session_state.chat_history:
            if chat["role"] == "user":
                with st.chat_message("user"): st.audio(chat["audio"], format="audio/wav")
            else:
                with st.chat_message("assistant"):
                    st.markdown(chat["text"])
                    ai_audio = generate_japanese_audio(chat["text"])
                    if ai_audio: st.audio(ai_audio, format='audio/mp3')

    # ----- 6：专属听力库 -----
    elif st.session_state.nav_menu == "🎧 专属听力库":
        st.header("🎧 长篇听力生成与素材库")
        active_listening_prompt = prompt_manager_ui(current_user, "listening", "你是一个专业的日语听力教材编写专家。把笔记中的词汇自然融入短文中。")
        st.write("---")
        st.subheader("1. 创作专属听力素材")
        if history_notes:
            is_running = any(t['context'].get('user_email') == current_user and t.get('task_type') == 'listening' for t in APP_GLOBAL_TASKS.values())
            if is_running:
                st.info("⏳ **AI 正在后台奋笔疾书为您编写听力短文...**\n\n您可以无缝切换到左侧的其他功能模块。\n生成完毕后，左侧的【📬 消息通知盒子】会主动提醒您！")
                if st.button("🔄 手动刷新状态", key="refresh_listen"): st.rerun()
            else:
                with st.form("listening_form"):
                    listen_title = st.text_input("给听力素材起个标题 🏷️", placeholder="例如：商务敬语情景会话")
                    listen_selected_keys = render_note_selector(note_options_dict, "listen")
                    submitted = st.form_submit_button("🎙️ 后台一键生成长篇听力", type="primary")
                    if submitted:
                        listen_title_clean = listen_title.strip()
                        if not listen_title_clean: st.warning("请给听力素材起个标题哦！")
                        elif check_listening_title_exists(current_user, listen_title_clean): st.error(f"❌ 听力标题 '{listen_title_clean}' 已存在！")
                        elif not listen_selected_keys: st.warning("请勾选至少一个笔记素材！")
                        else:
                            with st.spinner("🚀 正在为您分配大模型计算资源..."):
                                combined_material = "\n\n".join([note_options_dict[k][3] for k in listen_selected_keys])
                                sys_instruction = f"{active_listening_prompt}\n\n【强制系统约束(勿修改)】：请编写150-300字的日语短文。严格按照 JSON 格式输出，杜绝任何其他说明：\n{{\"transcript\": \"纯日文原文\", \"translation\": \"详细的中文翻译\"}}"
                                ctx = {'user_email': current_user, 'title': listen_title_clean, 'keys_str': ", ".join(listen_selected_keys)}
                                task_id = "listen_" + str(datetime.now().timestamp())
                                start_bg_task(task_id, "listening", auth_cfg, sys_instruction, f"请使用以下笔记素材进行创作：\n{combined_material}", context_data=ctx)
                                time.sleep(0.6); st.rerun()
        else: st.info("需要先保存笔记哦。")
            
        st.write("---")
        st.subheader("2. 个人听力素材库")
        listen_materials = get_all_listening_materials(current_user)
        if listen_materials:
            listen_options = {f"[{lm[1][:10]}] {lm[2]} (ID:{lm[0]})": lm for lm in listen_materials}
            selected_listen_key = st.selectbox("📝 选择要操作的听力素材：", options=list(listen_options.keys()))
            st.write("---")
            v_tab, e_tab, bd_tab = st.tabs(["👁️ 收听与查看", "✏️ 重命名此素材", "🗑️ 批量检索与删除"])
            if selected_listen_key:
                lm_record = listen_options[selected_listen_key]; lm_id = lm_record[0]
                with v_tab:
                    st.caption(f"语料来源: {lm_record[3]}")
                    st.write("🎧 **点击收听全文：**")
                    audio_b = generate_japanese_audio(lm_record[4])
                    if audio_b: st.audio(audio_b, format='audio/mp3')
                    with st.expander("📝 查看日语原文"): st.write(lm_record[4])
                    with st.expander("🌐 查看中文翻译"): st.write(lm_record[5])
                with e_tab:
                    edit_listen_title = st.text_input("修改标题", value=lm_record[2], key=f"edit_lm_{lm_id}")
                    if st.button("💾 保存新标题", key=f"save_lm_{lm_id}", type="primary"):
                        edit_lm_title_clean = edit_listen_title.strip()
                        if edit_lm_title_clean != lm_record[2] and check_listening_title_exists(current_user, edit_lm_title_clean):
                            st.error(f"❌ 标题 '{edit_lm_title_clean}' 已存在！")
                        else:
                            update_listening_material_title(lm_id, current_user, edit_lm_title_clean)
                            st.session_state.toast_msg = ("听力素材已重命名！", "✅"); st.rerun()
            with bd_tab:
                st.markdown("### 🔍 筛选与批量删除")
                search_kw_lm = st.text_input("搜索听力标题或原文内容 (留空显示全部)", key="search_lm_kw")
                filtered_lms = [lm for lm in listen_materials if search_kw_lm.lower() in lm[2].lower() or search_kw_lm.lower() in lm[4].lower()]
                if filtered_lms:
                    del_lm_options = {f"[{lm[1][:10]}] {lm[2]} (ID:{lm[0]})": lm[0] for lm in filtered_lms}
                    selected_del_lms = st.multiselect("请勾选要永久删除的听力素材：", list(del_lm_options.keys()), key="ms_del_lms")
                    if st.button("🚨 确认删除选中的听力", type="primary", key="btn_del_lms"):
                        if selected_del_lms:
                            for k in selected_del_lms: delete_listening_material(del_lm_options[k], current_user)
                            st.session_state.toast_msg = (f"成功删除了 {len(selected_del_lms)} 条听力素材！", "✅"); st.rerun()
                        else: st.warning("请先勾选需要删除的听力。")
                else: st.info("没有找到符合条件的听力素材。")
elif st.session_state.authenticated and not st.session_state.ai_auth_config:
    st.info("👈 欢迎登入！请在左侧边栏展开【⚙️ AI 模型服务通道配置】，并选择认证方式即可激活所有功能！")