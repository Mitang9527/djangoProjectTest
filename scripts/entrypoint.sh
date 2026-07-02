#!/bin/bash
# ================================================================
# Docker 容器入口脚本
# 负责：等待数据库就绪 → 执行迁移 → 初始化权限 → 启动服务
# ================================================================
set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ----------------------------------------------------------------
# 等待 PostgreSQL 就绪
# ----------------------------------------------------------------
wait_for_db() {
    local host="${DB_HOST:-postgres}"
    local port="${DB_PORT:-5432}"
    local retries=30
    local interval=2

    log_info "等待数据库 ${host}:${port} 就绪..."
    for i in $(seq 1 $retries); do
        if python -c "
import socket, sys
try:
    s = socket.create_connection(('${host}', ${port}), timeout=2)
    s.close()
    sys.exit(0)
except:
    sys.exit(1)
" 2>/dev/null; then
            log_info "数据库已就绪 (${i}/${retries})"
            return 0
        fi
        log_warn "数据库未就绪，${interval}s 后重试... (${i}/${retries})"
        sleep $interval
    done
    log_error "数据库连接超时，请检查配置"
    exit 1
}

# ----------------------------------------------------------------
# 等待 Redis 就绪（可选）
# ----------------------------------------------------------------
wait_for_redis() {
    if [ "${REDIS_ENABLED:-False}" != "True" ]; then
        return 0
    fi
    local host="${REDIS_HOST:-redis}"
    local port="${REDIS_PORT:-6379}"
    local retries=15

    log_info "等待 Redis ${host}:${port} 就绪..."
    for i in $(seq 1 $retries); do
        if python -c "
import socket, sys
try:
    s = socket.create_connection(('${host}', ${port}), timeout=2)
    s.close()
    sys.exit(0)
except:
    sys.exit(1)
" 2>/dev/null; then
            log_info "Redis 已就绪"
            return 0
        fi
        sleep 2
    done
    log_warn "Redis 连接超时，继续启动（部分功能可能受影响）"
}

# ----------------------------------------------------------------
# 执行数据库迁移
# ----------------------------------------------------------------
run_migrations() {
    log_info "执行数据库迁移..."
    python manage.py migrate --noinput
    log_info "迁移完成"
}

# ----------------------------------------------------------------
# 初始化权限和角色
# ----------------------------------------------------------------
init_permissions() {
    log_info "初始化内置权限和角色..."
    python manage.py init_permissions
    log_info "权限初始化完成"
}

# ----------------------------------------------------------------
# 收集静态文件（如果 static_root 为空）
# ----------------------------------------------------------------
collect_static() {
    if [ ! -f static_root/.manifest_strict ]; then
        log_info "收集静态文件..."
        python manage.py collectstatic --noinput
        log_info "静态文件收集完成"
    fi
}

# ----------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------
main() {
    log_info "===== Django SaaS 容器启动 ====="
    log_info "DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-djangoProjectTest.settings.prod}"

    # 确保 DJANGO_SETTINGS_MODULE 设置正确
    export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-djangoProjectTest.settings.prod}"

    wait_for_db
    wait_for_redis
    run_migrations
    init_permissions
    collect_static

    # 根据传入的命令决定启动方式
    case "${1:-gunicorn}" in
        gunicorn)
            log_info "启动 Gunicorn WSGI 服务器..."
            exec gunicorn djangoProjectTest.wsgi:application \
                --bind 0.0.0.0:8000 \
                --workers ${GUNICORN_WORKERS:-4} \
                --worker-class sync \
                --timeout ${GUNICORN_TIMEOUT:-120} \
                --max-requests ${GUNICORN_MAX_REQUESTS:-1000} \
                --max-requests-jitter 100 \
                --access-logfile - \
                --error-logfile - \
                --log-level ${GUNICORN_LOG_LEVEL:-info}
            ;;
        daphne)
            log_info "启动 Daphne ASGI 服务器（支持 WebSocket）..."
            exec daphne \
                -b 0.0.0.0 \
                -p 8000 \
                --access-log - \
                djangoProjectTest.asgi:application
            ;;
        celery-worker)
            log_info "启动 Celery Worker..."
            exec celery -A djangoProjectTest worker \
                --loglevel=${CELERY_LOG_LEVEL:-info} \
                --concurrency=${CELERY_WORKERS:-4} \
                -Q celery,exports
            ;;
        celery-beat)
            log_info "启动 Celery Beat 定时任务..."
            exec celery -A djangoProjectTest beat \
                --loglevel=${CELERY_LOG_LEVEL:-info} \
                --scheduler django_celery_beat.schedulers:DatabaseScheduler
            ;;
        shell)
            exec python manage.py shell
            ;;
        manage)
            shift
            exec python manage.py "$@"
            ;;
        *)
            exec "$@"
            ;;
    esac
}

main "$@"
