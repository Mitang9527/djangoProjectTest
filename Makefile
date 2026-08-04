# ================================================================
# Makefile —— Django 企业级架构项目模板
# 用法: make <目标>    查看全部命令: make help
# ================================================================

COMPOSE     = docker compose
COMPOSE_DEV = docker compose -f docker-compose.yml
COMPOSE_PROD= docker compose -f docker-compose.prod.yml
IMAGE_NAME  = djangosaas
IMAGE_TAG   ?= latest

.PHONY: help \
        install install-dev migrate-local makemigrations-local runserver run-daphne \
        createsuperuser shell-local collectstatic-local \
        test test-cov test-fast \
        lint lint-fix format typecheck security pre-commit-run \
        db-shell \
        celery-worker celery-beat celery-flower \
        build up up-d down restart logs logs-web logs-worker shell django-shell \
        migrate makemigrations init-perms collectstatic \
        prod-build prod-up prod-down prod-logs prod-restart-web \
        backup-db restore-db \
        clean clean-all

# ----------------------------------------------------------------
help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ================================================================
# 本地开发（不依赖 Docker）
# ================================================================
install: ## 安装 Python 依赖
	pip install -r requirements.txt

install-dev: ## 安装开发依赖 (pre-commit/pytest 等)
	pip install -r requirements.txt && pip install pytest pytest-django pytest-cov factory-boy pre-commit

migrate-local: ## 本地执行数据库迁移
	python manage.py migrate

makemigrations-local: ## 本地生成迁移文件
	python manage.py makemigrations

runserver: ## 启动开发服务器 (端口 8000)
	python manage.py runserver 0.0.0.0:8000

run-daphne: ## 启动 ASGI 服务器 (支持 WebSocket)
	daphne -b 0.0.0.0 -p 8000 djangoProjectTest.asgi:application

createsuperuser: ## 创建超级用户
	python manage.py createsuperuser

shell-local: ## 本地 Django shell
	python manage.py shell

collectstatic-local: ## 本地收集静态文件
	python manage.py collectstatic --noinput

# ================================================================
# 测试
# ================================================================
test: ## 运行测试
	python -m pytest tests/ -v

test-cov: ## 运行测试并生成覆盖率报告
	python -m pytest tests/ --cov=apps --cov=framework --cov-report=term-missing --cov-report=html

test-fast: ## 运行测试 (无覆盖率，最快)
	python -m pytest tests/ -q --no-cov

# ================================================================
# 代码质量
# ================================================================
lint: ## ruff 代码检查
	ruff check apps/ framework/ djangoProjectTest/

lint-fix: ## ruff 检查并自动修复
	ruff check --fix apps/ framework/ djangoProjectTest/

format: ## ruff 格式化代码
	ruff format apps/ framework/ djangoProjectTest/

typecheck: ## mypy 类型检查
	mypy apps/ framework/ --ignore-missing-imports

security: ## bandit 安全扫描
	bandit -r apps/ framework/ -ll

pre-commit-run: ## 对全部文件运行 pre-commit
	pre-commit run --all-files

# ================================================================
# 数据库（本地）
# ================================================================
db-shell: ## PostgreSQL 交互式 shell (本地，需 pgsql 在 PATH 中)
	psql -U $${DB_USER:-saas_user} -d $${DB_NAME:-saas_db}

# ================================================================
# Celery
# ================================================================
celery-worker: ## 启动 Celery Worker
	celery -A djangoProjectTest worker -l info

celery-beat: ## 启动 Celery Beat 调度器
	celery -A djangoProjectTest beat -l info

celery-flower: ## 启动 Flower 监控面板
	celery -A djangoProjectTest flower --port=5555

# ================================================================
# 开发环境（Docker）
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

django-shell: ## 进入 Django shell（容器内）
	$(COMPOSE_DEV) exec web python manage.py shell

migrate: ## 执行数据库迁移（容器内）
	$(COMPOSE_DEV) exec web python manage.py migrate

makemigrations: ## 生成迁移文件（容器内）
	$(COMPOSE_DEV) exec web python manage.py makemigrations

init-perms: ## 初始化权限和角色（容器内）
	$(COMPOSE_DEV) exec web python manage.py init_permissions

collectstatic: ## 收集静态文件（容器内）
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
