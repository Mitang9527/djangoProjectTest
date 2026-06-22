#!/bin/bash
# ============================================================
# Django 数据库备份脚本
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

# 备份目录
BACKUP_DIR="$PROJECT_DIR/backups"
mkdir -p "$BACKUP_DIR"

# 日期时间格式
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

echo "=============================================="
echo "Django 数据库备份"
echo "=============================================="

# 检测数据库类型
DB_ENGINE=$(grep "^DB_ENGINE" .env 2>/dev/null | cut -d'=' -f2)
DB_NAME=$(grep "^DB_NAME" .env 2>/dev/null | cut -d'=' -f2)

if [ -f "db.sqlite3" ]; then
    echo -e "${YELLOW}检测到 SQLite 数据库${NC}"
    
    # SQLite 备份
    BACKUP_FILE="$BACKUP_DIR/db_backup_$TIMESTAMP.sqlite3"
    cp db.sqlite3 "$BACKUP_FILE"
    
    echo -e "${GREEN}✓ SQLite 备份成功: $BACKUP_FILE${NC}"
    
elif [ "$DB_ENGINE" == "django.db.backends.postgresql" ] || [ "$DB_ENGINE" == "django.db.backends.mysql" ]; then
    echo -e "${YELLOW}检测到生产数据库${NC}"
    
    # 使用 Django dumpdata 命令备份
    BACKUP_FILE="$BACKUP_DIR/db_backup_$TIMESTAMP.json"
    python manage.py dumpdata --natural-foreign --natural-primary -o "$BACKUP_FILE"
    
    echo -e "${GREEN}✓ 数据导出成功: $BACKUP_FILE${NC}"
    
else
    # 默认尝试使用 dumpdata
    echo -e "${YELLOW}使用 Django dumpdata 命令备份${NC}"
    BACKUP_FILE="$BACKUP_DIR/db_backup_$TIMESTAMP.json"
    python manage.py dumpdata --natural-foreign --natural-primary -o "$BACKUP_FILE"
    echo -e "${GREEN}✓ 数据导出成功: $BACKUP_FILE${NC}"
fi

# 压缩备份文件
if [ -f "$BACKUP_FILE" ]; then
    echo -e "${YELLOW}压缩备份文件...${NC}"
    gzip -f "$BACKUP_FILE"
    echo -e "${GREEN}✓ 压缩完成: ${BACKUP_FILE}.gz${NC}"
fi

# 清理旧备份（保留 7 天）
echo -e "${YELLOW}清理 7 天前的旧备份...${NC}"
find "$BACKUP_DIR" -name "db_backup_*.gz" -mtime +7 -delete
find "$BACKUP_DIR" -name "db_backup_*.sqlite3" -mtime +7 -delete
find "$BACKUP_DIR" -name "db_backup_*.json" -mtime +7 -delete

echo ""
echo -e "${GREEN}=============================================="
echo "备份完成！"
echo "备份目录: $BACKUP_DIR"
echo "==============================================${NC}"
