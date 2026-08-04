# Django SECRET_KEY 无缝轮换指南

## 概述

本系统支持双密钥无缝轮换，允许在不中断服务的情况下更新 SECRET_KEY。同时支持手动和自动两种轮换方式。

## 工作原理

1. **主密钥**：用于签名新数据
2. **副密钥**：用于验证旧数据
3. **过渡期**：两个密钥同时生效
4. **轮换完成**：旧密钥自动失效

## 快速开始

### 方式一：使用 Django 管理命令（推荐）

```bash
# 查看当前密钥状态
python manage.py rotate_secret_key --check-only

# 轮换密钥（默认保留30天）
python manage.py rotate_secret_key

# 自定义保留天数
python manage.py rotate_secret_key --days 14

# 强制执行（忽略时间检查）
python manage.py rotate_secret_key --force
```

### 方式二：使用 Python 脚本

```bash
# 查看当前密钥状态
python framework/key_management/key_rotation.py status

# 轮换密钥
python framework/key_management/key_rotation.py rotate 7

# 查看密钥详情
python framework/key_management/key_rotation.py list
```

---

## 自动轮换配置

### 使用 Celery Beat（推荐）

如果项目已配置 Celery，可以设置定时自动轮换：

1. **配置 Celery Beat**

在你的 Django settings 中添加：

```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'auto-rotate-secret-key': {
        'task': 'key_management.auto_rotate_secret_key',
        'schedule': crontab(day_of_month=1, hour=3),  # 每月1号凌晨3点
        'kwargs': {'days': 30},  # 每30天轮换一次
    },
}
```

2. **启动 Celery Beat**

```bash
celery -A your_project beat -l INFO
```

### 使用系统 Cron Job

如果不使用 Celery，可以用系统 cron：

```bash
# 编辑 crontab
crontab -e

# 添加任务（每月1号凌晨3点执行）
0 3 1 * * cd /path/to/your/project && /path/to/python manage.py rotate_secret_key >> /var/log/key_rotation.log 2>&1
```

---

## 集成到 Django 项目

### 方式 1：基本集成（不修改现有代码）

密钥会自动从环境变量初始化，不需要修改代码。

### 方式 2：使用多密钥签名（高级）

在需要签名数据的地方，使用我们提供的工具：

```python
from framework.key_management import multi_key_sign, multi_key_unsign

# 签名
signed = multi_key_sign("my-data", salt="my-salt")

# 验证（会自动尝试所有有效密钥）
original = multi_key_unsign(signed, salt="my-salt")
```

### 方式 3：自定义 Signer

```python
from framework.key_management import get_signer, get_timestamp_signer

# 普通签名
signer = get_signer(salt="custom-salt")
signed = signer.sign("data")
original = signer.unsign(signed)

# 时间戳签名（带过期时间）
ts_signer = get_timestamp_signer()
signed = ts_signer.sign("data")
original = ts_signer.unsign(signed, max_age=3600)  # 1小时过期
```

## 完整的轮换流程

### 步骤 1：生成新密钥

```bash
python framework/key_management/key_rotation.py rotate 7
```

这会：
- 保留旧密钥 7 天
- 新数据使用新密钥签名
- 旧数据仍然可以用旧密钥验证

### 步骤 2：更新 .env（可选但推荐）

虽然系统可以自动管理，但建议同时更新 `.env` 文件：

```env
SECRET_KEY=新生成的密钥
```

### 步骤 3：等待过渡期结束

7 天后，旧密钥自动失效。

### 步骤 4：确认并清理

```bash
python framework/key_management/key_rotation.py status
```

## 密钥存储位置

密钥数据默认存储在：
```
data/secret_keys.json
```

**重要**：请确保此文件：
- ❌ 不要提交到 Git
- ✅ 加入 .gitignore
- ✅ 做好备份
- ✅ 设置正确的文件权限

## .gitignore 更新建议

添加以下内容：

```
# 密钥轮换数据
data/secret_keys.json
data/
```

## 生产环境最佳实践

### 1. 定期轮换
- 建议每 6-12 个月轮换一次
- 设置日历提醒

### 2. 监控
- 轮换前通知用户可能需要重新登录
- 监控登录率是否异常

### 3. 备份
- 轮换前备份当前密钥
- 保留密钥历史（在安全的地方）

### 4. 回滚方案
如果出现问题，可以恢复旧密钥：

```python
from framework.key_management import get_key_manager

manager = get_key_manager()
# 手动编辑 data/secret_keys.json 恢复旧密钥
```

## API 参考

### KeyRotationManager

```python
from framework.key_management import KeyRotationManager

manager = KeyRotationManager()

# 获取主密钥
primary_key = manager.get_primary_key()

# 获取所有有效密钥
all_keys = manager.get_all_active_keys()

# 轮换密钥
new_key = manager.rotate_key(keep_old_days=7)

# 获取密钥信息（安全）
info = manager.get_key_info()
```

### 快捷函数

```python
from framework.key_management import (
    get_key_manager,
    get_rotatable_secret_key,
    get_all_secret_keys
)

manager = get_key_manager()
primary = get_rotatable_secret_key()
all_keys = get_all_secret_keys()
```

## 注意事项

⚠️ **重要**：
- 轮换密钥后，所有用户会话会失效
- Password reset tokens 会失效
- 但不影响已加密的密码（密码使用单独的哈希）
- 确保 data/ 目录有写权限

## 故障排查

### 密钥文件丢失
如果 `secret_keys.json` 丢失，系统会自动从 `.env` 重新初始化。

### 权限问题
确保 Django 进程有权限读写 `data/` 目录。

### 需要立即撤销密钥
```python
manager = get_key_manager()
manager.deactivate_key("旧密钥")
```

## 与 Django Session 的集成

目前 Django 的 session 系统仍然使用 settings.SECRET_KEY。
要完全支持 session 的无缝轮换，需要自定义 session backend，
这是一个高级功能，如需实现请参考 Django 文档自定义 SessionStore。
