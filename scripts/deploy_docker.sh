#!/bin/bash
# ============================================================
# 一键部署脚本（Linux + Docker）
# 在 Linux 服务器上拉起完整生产环境：
#   Nginx(托管 Vue dist + 反代 /api) + Django(Gunicorn)
#   + PostgreSQL + Redis + Celery(worker/beat)
#
# 用法：
#   ./scripts/deploy_docker.sh              # 生产环境 (docker-compose.prod.yml)
#   ./scripts/deploy_docker.sh --dev        # 开发环境 (docker-compose.yml)
#   ./scripts/deploy_docker.sh --no-build   # 跳过镜像构建
#   ./scripts/deploy_docker.sh --port=8080  # 自定义健康检查端口
#   ./scripts/deploy_docker.sh --help
#
# 可选环境变量：
#   CREATE_ADMIN=true                       # 自动创建管理员（需同时设置下方变量）
#   DJANGO_SUPERUSER_USERNAME / _EMAIL / _PASSWORD
# ============================================================
set -euo pipefail

# ---------- 颜色 ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "${CYAN}==>${NC} $*"; }

# ---------- 路径 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# ---------- 参数 ----------
PROFILE=prod
NO_BUILD=0
HEALTH_PORT=""
for arg in "$@"; do
  case "$arg" in
    --dev)      PROFILE=dev ;;
    --no-build) NO_BUILD=1 ;;
    --port=*)   HEALTH_PORT="${arg#*=}" ;;
    --help|-h)  sed -n '2,18p' "$0"; exit 0 ;;
    *)          log_warn "未知参数，已忽略: $arg" ;;
  esac
done

if [ "$PROFILE" = "prod" ]; then
  COMPOSE_FILE="docker-compose.prod.yml"
  HEALTH_PORT="${HEALTH_PORT:-80}"
else
  COMPOSE_FILE="docker-compose.yml"
  HEALTH_PORT="${HEALTH_PORT:-8000}"
fi

# ---------- docker compose 命令探测 ----------
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  log_error "未检测到 docker compose，请先安装 Docker Engine 与 compose 插件"
  exit 1
fi

# ---------- 运行环境检查 ----------
log_step "检查运行环境"
command -v docker >/dev/null 2>&1 || { log_error "未安装 docker，请先安装"; exit 1; }
docker info >/dev/null 2>&1 || { log_error "docker 守护进程未运行，请执行: sudo systemctl start docker"; exit 1; }
command -v curl  >/dev/null 2>&1 || log_warn "缺少 curl，将跳过健康检查"
command -v openssl >/dev/null 2>&1 || log_warn "缺少 openssl，将改用 /dev/urandom 生成密钥"

# ---------- 环境变量引导 ----------
ENV_FILE=".env.docker"
[ "$PROFILE" = "dev" ] && ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
  if [ -f ".env.template" ]; then
    cp .env.template "$ENV_FILE"
    log_info "已从 .env.template 生成 $ENV_FILE"
  else
    log_error "缺少 $ENV_FILE 且没有 .env.template，请手动创建环境配置"; exit 1
  fi
fi

gen_secret() {
  local len="${1:-64}"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex $((len / 2))
  else
    tr -dc 'a-zA-Z0-9' < /dev/urandom | head -c "$len"
  fi
}

# 当配置仍为占位符/空/过短时，自动填充随机值（幂等：已有真实值则不动）
gen_and_set() {
  local key="$1" len="$2" minlen="$3"
  local cur
  cur="$(grep -E "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
  if [[ -z "$cur" || "$cur" == your-* || "$cur" == *change-this* || "${#cur}" -lt "$minlen" ]]; then
    local val; val="$(gen_secret "$len")"
    sed -i -E "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    echo "$val"   # 返回新生成的值（供摘要展示）
  else
    echo ""
  fi
}

log_step "校验并补全 $ENV_FILE 中的密钥"
SECRET_VAL="$(gen_and_set SECRET_KEY 64 50)"
DB_PW="$(gen_and_set DB_PASSWORD 24 12)"
REDIS_PW="$(gen_and_set REDIS_PASSWORD 24 12)"
log_warn "请确认 $ENV_FILE 中的 ALLOWED_HOSTS / CORS_ALLOWED_ORIGINS 已指向你的域名"

# ---------- 构建镜像 ----------
if [ "$NO_BUILD" -eq 0 ]; then
  log_step "构建镜像 ($COMPOSE_FILE)"
  $DC -f "$COMPOSE_FILE" build
else
  log_info "跳过镜像构建"
fi

# ---------- 启动服务 ----------
log_step "启动服务: $DC -f $COMPOSE_FILE up -d"
$DC -f "$COMPOSE_FILE" up -d

# ---------- 等待健康检查 ----------
if command -v curl >/dev/null 2>&1; then
  log_step "等待服务就绪 (http://127.0.0.1:${HEALTH_PORT}/api/v1/health/)"
  HEALTHY=0
  for i in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${HEALTH_PORT}/api/v1/health/" >/dev/null 2>&1; then
      log_info "服务已就绪 ✓ (第 ${i} 次探测)"
      HEALTHY=1
      break
    fi
    sleep 3
  done
  if [ "$HEALTHY" -eq 0 ]; then
    log_error "健康检查超时，请查看日志: $DC -f $COMPOSE_FILE logs --tail=50 web"
  fi
else
  log_warn "跳过健康检查（无 curl），请手动访问 /api/v1/health/"
fi

# ---------- 可选：创建管理员 ----------
if [ "${CREATE_ADMIN:-false}" = "true" ]; then
  log_step "创建管理员账号"
  $DC -f "$COMPOSE_FILE" exec -T web python scripts/create_admin.py \
    || log_warn "管理员创建失败，请进入容器手动执行: $DC -f $COMPOSE_FILE exec web python manage.py createsuperuser"
fi

# ---------- 部署摘要 ----------
echo
log_info "============ 部署完成 ============"
echo -e "  前端入口   : ${CYAN}http://<你的服务器IP>/${NC}"
echo -e "  管理后台   : ${CYAN}/admin/${NC}   (Django 模板，已保留)"
echo -e "  API 文档   : ${CYAN}/api/schema/swagger-ui/${NC}   (需管理员登录)"
echo -e "  健康检查   : ${CYAN}/api/v1/health/${NC}"
echo -e "  查看日志   : ${CYAN}$DC -f $COMPOSE_FILE logs -f${NC}"
echo
if [ -n "$DB_PW" ];   then echo -e "  ${YELLOW}自动生成 DB_PASSWORD   : $DB_PW${NC}"; fi
if [ -n "$REDIS_PW" ]; then echo -e "  ${YELLOW}自动生成 REDIS_PASSWORD: $REDIS_PW${NC}"; fi
if [ -n "$DB_PW" ] || [ -n "$REDIS_PW" ]; then
  echo -e "  ${YELLOW}以上为随机密码，已写入 $ENV_FILE，请妥善保存${NC}"
fi
echo
log_warn "若使用域名 / HTTPS，请将证书放入 deploy/nginx/ssl/ 并在 conf.d/django.conf 取消 HTTPS 注释"
