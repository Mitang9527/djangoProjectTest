# ================================================================
# 多阶段构建 Dockerfile
# Stage 1: builder  —— 安装依赖
# Stage 2: runtime  —— 精简运行镜像
# ================================================================

# ---------- Stage 1: builder ----------
FROM python:3.12-slim AS builder

# 安装构建依赖（编译 C 扩展用，完成后不进入 runtime）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件（利用 Docker 层缓存）
COPY requirements.txt ./

# 安装到独立目录，方便复制到 runtime 镜像
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt \
    && pip install --prefix=/install --no-cache-dir psycopg2-binary openpyxl reportlab


# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

LABEL maintainer="django-project"
LABEL description="Django SaaS Enterprise Backend"

# 只安装运行时必需的系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    gettext \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制已安装的 Python 包
COPY --from=builder /install /usr/local

WORKDIR /app

# 创建非 root 用户运行应用（安全最佳实践）
RUN groupadd -r django && useradd -r -g django django

# 复制项目代码
COPY . .

# 创建必要目录，设置权限
RUN mkdir -p logs media static_root backups \
    && chown -R django:django /app

# 切换到非 root 用户
USER django

# 收集静态文件（构建时完成）
RUN python manage.py collectstatic --noinput --settings=djangoProjectTest.settings.prod

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/health/ || exit 1

EXPOSE 8000

# 入口脚本
ENTRYPOINT ["./scripts/entrypoint.sh"]
CMD ["gunicorn"]
