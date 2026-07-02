-- ================================================================
-- PostgreSQL 初始化脚本
-- 在 PostgreSQL 容器首次启动时自动执行
-- ================================================================

-- 设置时区
SET timezone = 'Asia/Shanghai';

-- 启用必要扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";    -- UUID 生成
CREATE EXTENSION IF NOT EXISTS "pg_trgm";      -- 模糊搜索加速
CREATE EXTENSION IF NOT EXISTS "unaccent";     -- 去音调搜索

-- 提示
SELECT 'PostgreSQL 初始化完成，扩展已启用' AS info;
