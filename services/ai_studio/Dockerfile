FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

# 系统依赖（psycopg2 编译需要 gcc/libpq）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY services/ai_studio/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY services/ai_studio /app/
# 注入共享框架包，使独立服务可直接 `import framework`（替代整份拷贝）
COPY framework /app/framework

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
