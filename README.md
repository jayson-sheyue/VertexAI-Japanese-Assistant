# 🎌 Vertex AI 日语学习助手 (Dual-Track SaaS Edition)

🚀 **基于 Google Cloud Run 与 Gemini 1.5 Pro 打造的云原生 AI 语言外教系统**

本项目是一个完整的、达到商业级 SaaS 标准的日语学习 Web 应用。它不仅实现了大模型多模态（文本/语音）的深度调用，还在底层架构上实现了**异步任务队列、双通道 AI 路由、企业级持久化数据库挂载与容灾冷备份**，彻底告别了传统 Python 脚本的单机局限。

---

## ✨ 核心架构亮点 (Core Architecture Highlights)

* **🚄 智能双通道路由 (Dual-Track AI Engine)**：
  支持用户在 UI 侧自由切换底层算力。既允许普通用户输入免费的 Google AI Studio API Key（自带干粮），也支持通过 Google Cloud ADC 验证无缝接入企业级 Vertex AI 专线。
* **⏳ 全局异步任务引擎 (Asynchronous Task Workers)**：
  采用 Python 多线程与 Streamlit Session State 结合，所有耗时的 AI 生成任务（如生成试卷、长篇听力）全部在后台静默运行。配合全局“消息通知盒子 (Inbox)”，用户可无缝切换页面，告别阻塞等待。
* **☁️ 云原生安全架构 (Cloud-Native & Secure)**：
  抛弃本地 SQLite，通过 GCP 内网 Unix Socket 安全直连 **Cloud SQL (PostgreSQL)**。同时，代码内置“云端环境锁”，强制隔离本地与云端运行环境。
* **💽 容灾备份与防并发机制 (Disaster Recovery & Mutex Locks)**：
  内置任务去重锁（防止前端疯狂连点），并支持将用户所有核心数据（笔记、听力、提示词）原子级打包导出为 JSON 冷备份，支持安全回滚的覆盖式导入恢复。

---

## 🎯 核心功能模块 (Features)

1. **📝 笔记智能归纳**：将零散的日语笔记一键萃取为结构化 Markdown（核心语法、高频词汇、易错点），带同名校验。
2. **📚 历史笔记管理**：支持笔记正文重新编辑，AI 将自动根据修改后的正文**重新重构**归纳点评，即时预览。
3. **🧠 智能测验卡片**：从多篇笔记中后台抽取图文与语音并茂的混合测试卷，并由 AI 考官严格批改。
4. **📇 知识闪卡 (Flashcards)**：自动提取考点，后台生成正反面抽认卡，内置原生发音。
5. **💬 语音实景对练**：语音输入 (STT) -> 大模型语境理解 -> 语音回复 (TTS)，全链路口语陪练。
6. **🎧 专属听力素材库**：AI 自动编写情景短文并提供原生朗读与全量中文翻译。

---

## 🛠️ 技术栈 (Tech Stack)

* **前端/交互**: Streamlit (Python)
* **大模型引擎**: Gemini 1.5 Pro (Dual-Track: `vertexai` & `google-generativeai`)
* **数据库**: PostgreSQL (Google Cloud SQL) / `psycopg2-binary`
* **身份鉴权**: Google OAuth 2.0 (OpenID)
* **部署/容器化**: Docker, Google Cloud Run

---

## 🚀 从零到一部署指南 (Deployment Guide)

本项目专为 **Google Cloud Run** 设计。若要复现本项目，请严格按照以下步骤准备云端资源。

### 第一步：准备 Google OAuth 2.0 登录凭证
1. 前往 [Google Cloud Console -> API 与服务 -> 凭据](https://console.cloud.google.com/apis/credentials)。
2. 创建凭据 -> **OAuth 客户端 ID**（应用类型选择“Web 应用”）。
3. 记录下生成的 `Client ID` 和 `Client Secret`（稍后作为环境变量注入）。
4. *注意：部署完成后，需回到此处将 Cloud Run 分配的网址填入“已获授权的重定向 URI”中。*

### 第二步：配置 Cloud SQL (PostgreSQL) 数据库
1. 在 GCP 控制台搜索 `SQL`，创建一个 **PostgreSQL** 实例。
2. 为节省成本，建议选择 **Enterprise (企业版)** -> **Shared Core (共享核心 db-f1-micro)**。
3. 设置好数据库密码（记下作为 `DB_PASS`）。
4. 实例创建完成后，在实例内新建一个数据库，命名为 `jp_app_db`（记下作为 `DB_NAME`）。
5. 在实例的“概览”页找到 **连接名称 (Connection name)**（格式如 `project-id:region:instance-name`），记下作为 `INSTANCE_CONNECTION_NAME`。

### 第三步：启用必需的 Google Cloud API
在 GCP 控制台中启用以下 API：
* **Cloud Run API**
* **Cloud SQL Admin API**
* **Vertex AI API**
* **Cloud Build API**

### 第四步：一键编译与部署 (Deploy to Cloud Run)
在项目根目录（包含 `Dockerfile` 和 `app.py`）打开终端，使用 `gcloud` 命令行工具执行部署。请替换以下命令中的中文占位符：

```bash
gcloud run deploy jp-learning-app \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --add-cloudsql-instances 【你的数据库连接名称INSTANCE_CONNECTION_NAME】 \
  --set-env-vars "GOOGLE_CLIENT_ID=【你的OAuth Client ID】" \
  --set-env-vars "GOOGLE_CLIENT_SECRET=【你的OAuth Client Secret】" \
  --set-env-vars "REDIRECT_URI=https://【你的Cloud Run服务网址】/" \
  --set-env-vars "DB_USER=postgres" \
  --set-env-vars "DB_PASS=【你的数据库密码】" \
  --set-env-vars "DB_NAME=jp_app_db" \
  --set-env-vars "INSTANCE_CONNECTION_NAME=【你的数据库连接名称】"

```

*(💡 提示：首次部署时若不知道 `REDIRECT_URI`，可先填一个临时网址，等 Cloud Run 生成真实网址后，通过 `gcloud run services update` 命令更新该环境变量即可。)*

### ⚠️ 关于本地运行的特别说明

本项目已升级为强云原生安全架构。为了防止本地开发环境意外覆盖线上数据库，`app.py` 中内置了云端环境锁：

```python
if os.environ.get("K_SERVICE"):
    # 连接 Cloud SQL 内网
else:
    st.error("🚨 警告：应用已升级为云原生架构...")

```

如需在本地强行调试，需安装并运行 [Cloud SQL Auth Proxy](https://cloud.google.com/sql/docs/postgres/sql-proxy)，并手动修改 `get_db_connection()` 函数跳过拦截。

---

## 🔒 数据安全与隐私

* 所有的数据库连接和 API 密钥均通过**云端环境变量 (Environment Variables)** 注入，代码库中不包含任何明文敏感信息。
* 用户登录系统完全基于 Google 官方 OAuth 授权，应用本身不接触、不存储用户的 Google 密码。