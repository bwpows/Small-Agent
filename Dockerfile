FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用缓存）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再装项目本身
COPY pyproject.toml ./
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# 数据目录
RUN mkdir -p /app/data/workspace

# 非 root 用户
RUN useradd -m -u 1000 agent && chown -R agent:agent /app
USER agent

EXPOSE 8000

# 1G 内存只用 1 个 worker
CMD ["uvicorn", "app_server.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
