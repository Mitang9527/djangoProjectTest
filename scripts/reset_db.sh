#!/bin/bash
# ============================================================
# Django 数据库重置脚本
# WARNING: 此操作会删除所有数据！
# ============================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 项目根目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=============================================="
echo "Django 数据库重置"
echo "=============================================="
echo ""
echo -e "${RED}警告：此操作将删除所有数据库数据！${NC}"
read -p "确认要继续吗？(输入 'yes' 确认): " confirm

if [ "$confirm" != "yes" ]; then
    echo "操作已取消"
    exit 0
fi

# 先备份
echo -e "${YELLOW}[1/4] 先备份当前数据库...${NC}"
bash scripts/backup_db.sh

# 步骤 1: 查找并删除所有 migrations 文件（除了 __init__.py）
echo -e "${YELLOW}[2/4] 清理旧的 migration 文件...${NC}"
find apps/ -path "*/migrations/*.py" -not -name "__init__.py" -delete
find apps/ -path "*/migrations/*.pyc" 2>/dev/null -delete

echo -e "${GREEN}✓ 已清理 migration 文件${NC}"

# 步骤 2: 删除数据库
if [ -f "db.sqlite3" ]; then
    echo -e "${YELLOW}删除 SQLite 数据库文件...${NC}"
    rm -f db.sqlite3
fi

# 步骤 3: 重新创建
echo -e "${YELLOW}[3/4] 重新创建数据库...${NC}"
python manage.py makemigrations
python manage.py migrate

# 步骤 4: 初始化数据
echo -e "${YELLOW}[4/4] 初始化基础数据...${NC}"
python scripts/init_data.py

# 创建管理员
python scripts/create_admin.py

echo ""
echo -e "${GREEN}=============================================="
echo "数据库重置完成！"
echo "==============================================${NC}"
echo ""
echo "注意：开发数据已重置，"
echo "如需要导入旧数据请使用 backups/ 目录下的备份"
