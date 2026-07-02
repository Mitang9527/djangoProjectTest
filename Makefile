# ================================================================
# Makefile —— Docker 常用命令封装
# 用法: make <目标>
# ================================================================

COMPOSE     = docker compose
COMPOSE_DEV = docker compose -f docker-compose.yml
COMPOSE_PROD= docker compose -f docker-compose.prod.yml
IMAGE_NAME  = djangosaas
IMAGE_TAG   ?= latest

.PHONY: help build up down restart logs shell migrate init-perms \
        prod-build prod-up prod-down prod-logs clean

# ----------------------------------------------------------------
help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ================================================================
# 开发环境
# ================================================================
build: ## 构建开发镜像
	$(COMPOSE_DEV) build

up: ## 启动开发环境（前台，带日志）
	$(COMPOSE_DEV) up

up-d: ## 启动开发环境（后台）
	$(COMPOSE_DEV) up -d

down: ## 停止并移除容器（保留数据卷）
	$(COMPOSE_DEV) down

restart: ## 重启所有服务
	$(COMPOSE_DEV) restart

logs: ## 查看所有服务日志
	$(COMPOSE_DEV) logs -f

logs-web: ## 查看 web 服务日志
	$(COMPOSE_DEV) logs -f web

logs-worker: ## 查看 Celery Worker 日志
	$(COMPOSE_DEV) logs -f celery-worker

shell: ## 进入 web 容器 bash
	$(COMPOSE_DEV) exec web bash

django-shell: ## 进入 Django shell
	$(COMPOSE_DEV) exec web python manage.py shell

migrate: ## 执行数据库迁移
	$(COMPOSE_DEV) exec web python manage.py migrate

makemigrations: ## 生成迁移文件
	$(COMPOSE_DEV) exec web python manage.py makemigrations

init-perms: ## 初始化权限和角色
	$(COMPOSE_DEV) exec web python manage.py init_permissions

collectstatic: ## 收集静态文件
	$(COMPOSE_DEV) exec web python manage.py collectstatic --noinput

# ================================================================
# 生产环境
# ================================================================
prod-build: ## 构建生产镜像
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

prod-up: ## 启动生产环境
	$(COMPOSE_PROD) up -d

prod-down: ## 停止生产环境
	$(COMPOSE_PROD) down

prod-logs: ## 查看生产日志
	$(COMPOSE_PROD) logs -f

prod-restart-web: ## 零停机重启 web 服务
	$(COMPOSE_PROD) up -d --no-deps --build web

# ================================================================
# 数据管理
# ================================================================
backup-db: ## 备份数据库
	$(COMPOSE_DEV) exec postgres pg_dump -U $${DB_USER:-saas_user} $${DB_NAME:-saas_db} \
		> backups/backup_$(shell date +%Y%m%d_%H%M%S).sql
	@echo "备份完成"

restore-db: ## 恢复数据库（用法: make restore-db FILE=backups/backup_xxx.sql）
	$(COMPOSE_DEV) exec -T postgres psql -U $${DB_USER:-saas_user} $${DB_NAME:-saas_db} < $(FILE)

# ================================================================
# 清理
# ================================================================
clean: ## 清理停止的容器和悬挂镜像
	docker system prune -f

clean-all: ## 清理所有（包含数据卷！危险操作）
	@echo "警告：此操作将删除所有数据！按 Ctrl+C 取消，或等待 5 秒继续..."
	@sleep 5
	$(COMPOSE_DEV) down -v
	docker system prune -af
