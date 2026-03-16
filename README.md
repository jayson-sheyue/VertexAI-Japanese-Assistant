# 🎌 Vertex AI 日语学习助手 (Dual-Track SaaS Edition)

🚀 **基于 Google Cloud Run 与 Gemini API 打造的云原生 AI 语言外教系统**

本项目是一个完整的、商业级（SaaS）的日语学习 Web 应用。它不仅仅是一个简单的 API 调用脚本，而是一个拥有**异步任务队列、双通道 AI 路由、企业级数据库挂载与容灾冷备份**的现代化 Web 平台。

## ✨ 核心亮点架构 (Core Architecture)

* **🚄 智能双通道路由 (Dual-Track AI Engine)**：支持普通用户输入免费的 Google AI Studio API Key 自带干粮调用，同时支持企业级通过 Google Cloud ADC 验证无缝接入 Vertex AI 专线。
* **⏳ 全局异步任务队列 (Asynchronous Workers)**：采用多线程与 Streamlit Session State 结合，所有耗时的 AI 生成任务（如生成试卷、听力）全部后台静默运行，配合全局“消息通知盒子”丝滑切换，彻底告别页面卡顿。
* **☁️ 云原生架构 (Cloud-Native)**：基于 Docker 容器化，完美适配 **Google Cloud Run**（无服务器运行）并挂载持久化的 **Cloud SQL (PostgreSQL)**，实现极致的扩缩容与数据隔离。
* **💽 容灾备份引擎 (Disaster Recovery)**：内置原子级的 JSON 数据全量导出与事务级（Transaction Rollback）覆盖式恢复功能，保障用户数据资产的绝对安全。

## 🎯 核心功能模块 (Features)

1. **📝 笔记智能归纳**：将零散的日语笔记一键萃取为结构化 Markdown（核心语法、高频词汇、易错点）。
2. **📚 历史笔记管理**：支持笔记正文编辑，AI 将自动根据编辑后的正文**重新重构**归纳点评。
3. **🧠 智能测验卡片**：从指定的多篇笔记中混合抽取图文/语音并茂的测试题，并由 AI 考官严格批改点评。
4. **📇 知识闪卡 (Flashcards)**：自动提取笔记核心考点，生成正反面抽认卡并带原生发音。
5. **💬 语音实景对练**：语音输入（STT） -> 大模型语境理解 -> 语音回复（TTS），全链路口语陪练。
6. **🎧 专属听力素材库**：根据用户选定的零散语法点，AI 自动编写 300 字情景短文并提供原生朗读与全量翻译。

## 🛠️ 技术栈 (Tech Stack)

* **前端/框架**: Streamlit (Python)
* **大模型**: Gemini 2.5 Pro ( DIY via `vertexai` & `google-generativeai`)
* **数据库**: PostgreSQL (Google Cloud SQL) / SQLite (本地降级方案)
* **鉴权**: Google OAuth 2.0 (OpenID)
* **部署**: Docker, Google Cloud Run

## 🚀 快速部署指南

### 1. 环境变量要求
在 Cloud Run 部署时，需注入以下环境变量：
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `REDIRECT_URI`, `DB_USER`, `DB_PASS`, `DB_NAME`, `INSTANCE_CONNECTION_NAME`

### 2. 部署指令
```bash
gcloud run deploy jp-learning-app \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080