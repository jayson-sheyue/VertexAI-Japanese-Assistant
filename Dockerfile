# 使用官方轻量级 Python 镜像
FROM python:3.11-slim

# 允许 Python 直接输出日志
ENV PYTHONUNBUFFERED True

# 设定工作目录
WORKDIR /app

# ⚠️ 核心修复：安装 PostgreSQL 的系统级底层依赖
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制所有代码到容器内
COPY . ./

# 暴露 Streamlit 默认端口
EXPOSE 8501

# 启动 Streamlit，动态绑定 Cloud Run 分配的端口
CMD streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0