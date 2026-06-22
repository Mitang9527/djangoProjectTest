#!/bin/bash
# ============================================================
# Django 项目部署脚本
# ============================================================

set -e

echo "=============================================="
echo "Django 项目部署脚本"
echo "=============================================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# 步骤 1: 检查虚拟环境或安装依赖
echo -e "${YELLOW}[1/7] 检查并安装依赖...${NC}"
if command -v uv &> /dev/null; then
    echo "使用 uv 安装依赖..."
    uv pip install -r requirements.txt
elif command -v pip &> /dev/null; then
    echo "使用 pip 安装依赖..."
    pip install -r requirements.txt
else
    echo -e "${RED}错误：未找到 pip 或 uv，请先安装${NC}"
    exit 1
fi

# 步骤 2: 检查并加载环境变量
echo -e "${YELLOW}[2/7] 检查环境变量配置...${NC}"
if [ ! -f ".env" ]; then
    echo -e "${RED}警告：.env 文件不存在，正在从模板复制...${NC}"
    cp .env.template .env
    echo -e "${YELLOW}请修改 .env 文件中的配置后重新运行${NC}"
    exit 1
fi
echo -e "${GREEN}✓ 环境变量已加载${NC}"

# 步骤 3: 数据库迁移
echo -e "${YELLOW}[3/7] 执行数据库迁移...${NC}"
python manage.py makemigrations
python manage.py migrate
echo -e "${GREEN}✓ 数据库迁移完成${NC}"

# 步骤 4: 收集静态文件
echo -e "${YELLOW}[4/7] 收集静态文件...${NC}"
python manage.py collectstatic --noinput
echo -e "${GREEN}✓ 静态文件收集完成${NC}"

# 步骤 5: 检查是否需要创建超级用户
echo -e "${YELLOW}[5/7] 检查管理用户...${NC}"
python scripts/create_admin.py

# 步骤 6: 运行测试（可选）
echo -e "${YELLOW}[6/7] 运行测试...${NC}"
python manage.py check

# 步骤 7: 启动服务
echo -e "${YELLOW}[7/7] 部署完成！${NC}"
echo ""
echo -e "${GREEN}=============================================="
echo "部署成功！"
echo "==============================================${NC}"
echo ""
echo "开发模式启动："
echo "  python manage.py runserver"
echo ""
echo "生产模式启动（Gunicorn + Uvicorn）："
echo "  gunicorn djangoProjectTest.asgi:application -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000"
echo ""
echo "WebSocket 服务（Daphne）："
echo "  daphne djangoProjectTest.asgi:application -b 0.0.0.0 -p 8000"
echo ""
