"""
Celery 定时任务：自动轮换 SECRET_KEY

使用此任务前需要配置 Celery beat
"""
import os
from loguru import logger

try:
    from celery import shared_task
except ImportError:
    logger.warning("Celery 未安装，任务不可用")
    # 创建一个装饰器兼容 mock
    def shared_task(func):
        return func


@shared_task(name='key_management.auto_rotate_secret_key')
def auto_rotate_secret_key(days=30):
    """
    自动轮换 SECRET_KEY 的 Celery 任务
    
    Args:
        days: 密钥轮换周期（默认30天）
    """
    logger.info(f"开始执行自动密钥轮换任务（周期：{days}天）")
    
    try:
        # 导入放在这里避免 Django 初始化问题
        from framework.key_management import get_key_manager
        
        manager = get_key_manager()
        
        # 检查是否需要轮换
        if not should_rotate(manager, days):
            logger.info("当前密钥还不需要轮换")
            return {"status": "skipped", "message": "不需要轮换"}
        
        # 执行轮换
        logger.info("开始轮换密钥...")
        new_key = manager.rotate_key(keep_old_days=days)
        
        logger.success(f"密钥自动轮换成功！")
        logger.info(f"新密钥前缀: {new_key[:15]}...")
        
        return {
            "status": "success",
            "new_key_prefix": new_key[:15],
            "old_key_kept_days": days
        }
        
    except Exception as e:
        logger.error(f"自动密钥轮换失败: {e}")
        return {"status": "error", "message": str(e)}


def should_rotate(manager, days):
    """判断是否应该轮换密钥"""
    from datetime import datetime
    
    keys_info = manager.get_key_info()
    
    # 找到主密钥
    primary_key = None
    for key in keys_info:
        if key['is_primary']:
            primary_key = key
            break
    
    if not primary_key:
        logger.warning("没有找到主密钥，执行轮换")
        return True
    
    try:
        created_at = datetime.fromisoformat(primary_key['created_at'])
        days_old = (datetime.now() - created_at).days
        
        logger.info(f"当前主密钥已使用 {days_old} 天")
        
        if days_old >= days:
            logger.info(f"达到轮换阈值（{days}天）")
            return True
        else:
            logger.info(f"还未到轮换时间（还剩 {days - days_old} 天）")
            return False
            
    except Exception as e:
        logger.error(f"检查密钥时间失败: {e}")
        return False


# ===============================================================
# 安全扫描类定时任务（证书到期 / 密钥泄漏 / 密钥年龄）
# ===============================================================

@shared_task(name='key_management.scan_tls_certificates')
def scan_tls_certificates():
    """
    扫描配置的 TLS 证书到期情况，临近过期经 alert_system 告警。

    证书路径来自 settings.TLS_CERT_PATHS（文件或目录列表）。
    """
    from django.conf import settings
    from framework.key_management.scan import scan_certificates
    from business.alert_system.services.alert_engine import AlertEngine

    paths = list(getattr(settings, "TLS_CERT_PATHS", []) or [])
    warn_days = int(getattr(settings, "TLS_CERT_WARN_DAYS", 30))

    if not paths:
        logger.info("[TLS] 未配置 TLS_CERT_PATHS，跳过证书扫描")
        return {"scanned": 0, "risks": 0}

    results = scan_certificates(paths, warn_days=warn_days)
    risks = [r for r in results if r.get("risk")]
    expired = [r for r in results if (r.get("days_remaining") is not None and r["days_remaining"] <= 0)]

    if risks:
        lines = []
        for r in risks:
            days = r.get("days_remaining")
            status = "已过期" if (days is not None and days <= 0) else f"剩余 {days} 天"
            lines.append(f"- {r['path']}: {status} (到期 {r.get('not_after')})")
        content = "TLS 证书即将到期/已过期:\n" + "\n".join(lines)
        AlertEngine.trigger(
            title=f"TLS 证书风险: {len(risks)} 张",
            content=content,
            level="critical" if expired else "warning",
            channels=list(getattr(settings, "ALERT_SECURITY_CHANNELS", []) or []),
            context={"scan": "tls_cert", "risks": len(risks)},
        )

    logger.info(f"[TLS] 扫描 {len(results)} 张证书，风险 {len(risks)} 张")
    return {"scanned": len(results), "risks": len(risks)}


@shared_task(name='key_management.scan_secret_leaks')
def scan_secret_leaks():
    """
    启发式扫描源码中的硬编码密钥/密码/令牌，发现经 alert_system 告警。
    """
    from django.conf import settings
    from framework.key_management.scan import scan_secret_leaks as _scan
    from business.alert_system.services.alert_engine import AlertEngine

    scan_paths = list(getattr(settings, "SECRET_LEAK_SCAN_PATHS", []) or [])
    if not scan_paths:
        # 默认扫描项目业务与框架代码（排除依赖与产物）
        base = str(_project_root())
        scan_paths = [
            os.path.join(base, "apps"),
            os.path.join(base, "framework"),
            os.path.join(base, "extensions"),
        ]

    findings = _scan(scan_paths)
    if findings:
        # 最多展示前 20 条，避免消息过长
        preview = findings[:20]
        lines = [f"- {f['path']}:{f['line']} [{f['rule']}] {f['masked']}" for f in preview]
        more = len(findings) - len(preview)
        if more > 0:
            lines.append(f"... 另有 {more} 条")
        content = "检测到疑似硬编码密钥/令牌:\n" + "\n".join(lines)
        AlertEngine.trigger(
            title=f"密钥泄漏扫描: {len(findings)} 处疑似",
            content=content,
            level="warning",
            channels=list(getattr(settings, "ALERT_SECURITY_CHANNELS", []) or []),
            context={"scan": "secret_leak", "count": len(findings)},
        )

    logger.info(f"[SecretLeak] 扫描发现 {len(findings)} 处疑似硬编码")
    return {"findings": len(findings)}


@shared_task(name='key_management.security_audit')
def security_audit():
    """
    聚合安全检查：密钥年龄 + TLS 证书 + 密钥泄漏，统一触发告警。
    每日运行一次即可。
    """
    summary = {}
    try:
        summary["key_age"] = _audit_key_age()
    except Exception as e:
        logger.error(f"[SecurityAudit] 密钥年龄检查失败: {e}")
    try:
        summary["tls"] = scan_tls_certificates()
    except Exception as e:
        logger.error(f"[SecurityAudit] 证书扫描失败: {e}")
    try:
        summary["secret_leak"] = scan_secret_leaks()
    except Exception as e:
        logger.error(f"[SecurityAudit] 密钥泄漏扫描失败: {e}")
    return summary


def _audit_key_age():
    """检查主密钥年龄（依赖 KeyRotationManager）。"""
    from django.conf import settings
    from framework.key_management import get_key_manager
    from framework.key_management.scan import check_key_age
    from business.alert_system.services.alert_engine import AlertEngine

    max_age = int(getattr(settings, "KEY_MAX_AGE_DAYS", 90))
    manager = get_key_manager()
    info = check_key_age(manager, max_age_days=max_age)
    if info.get("risk"):
        age = info.get("age_days")
        AlertEngine.trigger(
            title="主密钥年龄过旧",
            content=f"Django SECRET_KEY 已使用 {age} 天（阈值 {max_age} 天），建议尽快轮换。",
            level="warning",
            channels=list(getattr(settings, "ALERT_SECURITY_CHANNELS", []) or []),
            context={"scan": "key_age", "age_days": age},
        )
    return info


def _project_root() -> "Path":
    from pathlib import Path
    # framework/key_management/scan.py -> 项目根
    return Path(__file__).resolve().parent.parent.parent
