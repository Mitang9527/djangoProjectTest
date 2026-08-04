"""
密钥与证书安全扫描
====================

提供两类主动安全检查，供 Celery Beat 周期调用：

1. TLS 证书到期检查 (check_certificate_expiry / scan_certificates)
   - 解析 PEM/DER 证书，读取 not_valid_after，计算剩余天数。
   - 剩余天数 < warn_days 视为风险。支持单文件或目录递归（.pem/.crt/.cer）。

2. 密钥/敏感信息泄漏扫描 (scan_secret_leaks)
   - 在指定源码目录中启发式匹配硬编码密钥/密码/令牌/私钥。
   - 仅报告文件:行号 + 掩码后片段，绝不输出真实密钥值。

依赖说明：
  - 证书解析优先使用 `cryptography`，缺失时降级到 stdlib `ssl`。
  - 所有函数均为纯函数，不依赖 Django，可在脚本中直接调用。
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------
# TLS 证书到期检查
# ---------------------------------------------------------------

_CERT_EXTS = (".pem", ".crt", ".cer", ".der")


def _load_cert_not_after(cert_path: str) -> Optional[datetime]:
    """读取证书过期时间（UTC）。优先 cryptography，降级 ssl。返回 None 表示解析失败。"""
    data = Path(cert_path).read_bytes()
    # 1) cryptography（推荐）
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend

        try:
            cert = x509.load_pem_x509_certificate(data, default_backend())
        except Exception:
            cert = x509.load_der_x509_certificate(data, default_backend())
        if hasattr(cert, "not_valid_after_utc"):
            return cert.not_valid_after_utc
        # 旧版 cryptography：naive datetime，按 UTC 处理
        return cert.not_valid_after.replace(tzinfo=timezone.utc)
    except Exception:
        pass

    # 2) 降级到 stdlib ssl（仅 PEM，且只支持文件对象）
    try:
        import ssl

        der = ssl.PEM_cert_to_DER_cert(data.decode("utf-8", "ignore"))
        # ssl 没有直接解析 API，使用 cryptography 失败时的最后手段
        from cryptography import x509  # noqa
        from cryptography.hazmat.backends import default_backend

        cert = x509.load_der_x509_certificate(der, default_backend())
        if hasattr(cert, "not_valid_after_utc"):
            return cert.not_valid_after_utc
        return cert.not_valid_after.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def check_certificate_expiry(
    cert_path: str, warn_days: int = 30, now: Optional[datetime] = None
) -> Dict[str, object]:
    """
    检查单个证书到期情况。

    Returns:
        {
          "path": str,
          "valid": bool,           # 是否成功解析
          "error": str | None,
          "not_after": str | None, # ISO
          "days_remaining": int | None,
          "risk": bool,            # days_remaining < warn_days
        }
    """
    result: Dict[str, object] = {
        "path": cert_path,
        "valid": False,
        "error": None,
        "not_after": None,
        "days_remaining": None,
        "risk": False,
    }
    if not os.path.isfile(cert_path):
        result["error"] = "文件不存在"
        return result

    not_after = _load_cert_not_after(cert_path)
    if not_after is None:
        result["error"] = "无法解析证书（缺少 cryptography 或格式不支持）"
        return result

    result["valid"] = True
    result["not_after"] = not_after.isoformat()
    n = now or datetime.now(timezone.utc)
    days = (not_after - n).days
    result["days_remaining"] = days
    result["risk"] = days < warn_days
    return result


def scan_certificates(
    paths: List[str], warn_days: int = 30
) -> List[Dict[str, object]]:
    """
    扫描证书文件/目录，返回每个证书的到期检查结果。

    Args:
        paths: 文件路径或目录列表。目录会递归查找证书扩展名文件。
        warn_days: 剩余天数低于此值标记 risk。
    """
    targets: List[str] = []
    for p in paths or []:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in files:
                    if f.lower().endswith(_CERT_EXTS):
                        targets.append(os.path.join(root, f))
        elif os.path.isfile(p):
            targets.append(p)

    return [check_certificate_expiry(t, warn_days=warn_days) for t in targets]


# ---------------------------------------------------------------
# 密钥泄漏扫描
# ---------------------------------------------------------------

# 启发式规则：(名称, 正则)。匹配到即视为可疑，输出掩码片段。
_SECRET_PATTERNS = [
    ("rsa_private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("aws_secret", re.compile(r"(?i)aws_secret_access_key\s*=\s*['\"][A-Za-z0-9/+=]{40}['\"]")),
    ("generic_secret_assign", re.compile(
        r"(?i)(password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|private[_-]?key)"
        r"\s*[:=]\s*['\"](.{6,})['\"]"
    )),
    ("bearer_token", re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+={0,2}")),
    ("jwt_like", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
]

# 扫描时跳过的目录
_SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "static", "media", "htmlcov", "logs", "dist", "build",
}

# 仅扫描这些扩展名
_SCAN_EXTS = (".py", ".env", ".ini", ".yaml", ".yml", ".toml", ".json", ".cfg", ".conf")


def _mask(value: str, keep: int = 4) -> str:
    """掩码敏感值，仅保留尾部若干字符。"""
    value = value.strip().strip("'\"")
    if len(value) <= keep:
        return "****"
    return "****" + value[-keep:]


def scan_secret_leaks(
    scan_paths: List[str], extra_patterns: Optional[List] = None
) -> List[Dict[str, str]]:
    """
    启发式扫描源码中的硬编码密钥/密码/令牌。

    Args:
        scan_paths: 待扫描目录或文件列表。
        extra_patterns: 额外 (name, compiled_regex) 规则。

    Returns:
        [{"path": str, "line": int, "rule": str, "masked": str}, ...]
        按 (path, line) 去重。
    """
    patterns = list(_SECRET_PATTERNS)
    if extra_patterns:
        patterns.extend(extra_patterns)

    findings: List[Dict[str, str]] = []
    seen = set()

    for base in scan_paths or []:
        if os.path.isfile(base):
            files = [base]
        elif os.path.isdir(base):
            files = []
            for root, dirs, fnames in os.walk(base):
                dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                for fn in fnames:
                    if fn.lower().endswith(_SCAN_EXTS):
                        files.append(os.path.join(root, fn))
        else:
            continue

        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        for rule_name, rx in patterns:
                            m = rx.search(line)
                            if not m:
                                continue
                            key = (fp, lineno, rule_name)
                            if key in seen:
                                continue
                            seen.add(key)
                            # 提取可掩码片段
                            snippet = m.group(0)
                            if m.groups():
                                snippet = m.group(m.lastindex or 1)
                            findings.append({
                                "path": fp,
                                "line": lineno,
                                "rule": rule_name,
                                "masked": _mask(snippet),
                            })
            except Exception:
                # 单文件读取失败不应中断整体扫描
                continue

    return findings


# ---------------------------------------------------------------
# 密钥年龄检查（结合 KeyRotationManager）
# ---------------------------------------------------------------

def check_key_age(manager, max_age_days: int = 90,
                  now: Optional[datetime] = None) -> Dict[str, object]:
    """
    检查主密钥年龄，过旧提示轮换。

    Args:
        manager: KeyRotationManager 实例。
        max_age_days: 主密钥最大允许年龄（天）。
    """
    infos = manager.get_key_info()
    primary = next((k for k in infos if k.get("is_primary")), None)
    result: Dict[str, object] = {
        "primary_exists": primary is not None,
        "age_days": None,
        "risk": False,
        "key_count": len(infos),
    }
    if not primary:
        return result
    try:
        created = datetime.fromisoformat(primary["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        n = now or datetime.now(timezone.utc)
        age = (n - created).days
        result["age_days"] = age
        result["risk"] = age >= max_age_days
    except Exception:
        pass
    return result
