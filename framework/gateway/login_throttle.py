"""
登录/注册限流：防暴力破解 + 防刷注册（语义对齐 Fast-Vben-Admin login.py）。

登录维度（IP + 用户名双维度，Redis INCR + 窗口 TTL）：每次登录失败对 IP 与用户名
分别计数；任一维度失败次数 >= LOGIN_RATE_LIMIT_MAX_ATTEMPTS 即锁定该维度
LOGIN_RATE_LIMIT_BLOCK_SECONDS 秒（block key），期间对应登录直接 429；
登录成功后 clear_failed_login_attempts 清零两个维度（成功即信任）。

注册维度（IP，防批量刷注册）：每次注册请求（成功/失败均计）对 IP 计数，窗口内
>= REGISTER_RATE_LIMIT_MAX_ATTEMPTS 即锁定该 IP REGISTER_RATE_LIMIT_BLOCK_SECONDS
秒，期间注册直接 429；⚠️ 注册成功【不】清零（成功同样消耗窗口额度，否则防不住
批量开号），锁定随窗口/block TTL 自然过期；clear_register_attempts 仅手动解除用。

⚠️ 故障策略：Redis 不可用/异常时 fail-open 放行（可用性优先，避免基础设施故障
阻断全员登录/注册；_NullRedis 的 incr→1 / get→None 天然满足）。

配置（env → model.py global_config → settings，留空回退默认）：
LOGIN_RATE_LIMIT_ENABLED=True / MAX_ATTEMPTS=5 / WINDOW_SECONDS=300 /
BLOCK_SECONDS=900；REGISTER_RATE_LIMIT_ENABLED=True / MAX_ATTEMPTS=10 /
WINDOW_SECONDS=3600 / BLOCK_SECONDS=3600。

用法：LTS.is_login_rate_limited(request, username) 预检；
LTS.record_failed_login_attempt(request, username) 登录失败计数；
LTS.clear_failed_login_attempts(request, username) 登录成功清零；
LTS.is_register_rate_limited(request) 注册预检；
LTS.record_register_attempt(request) 注册请求（成败均计）。
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Redis 键前缀（与 gateway 限流体系同前缀，便于统一排查）
_LOGIN_PREFIX = "ratelimit:login:"
_REGISTER_PREFIX = "ratelimit:register:"
_PASSWORD_RESET_PREFIX = "ratelimit:reset:"


def _get_client_ip(request) -> str:
    """从请求中提取真实客户端 IP（与 framework.gateway.throttle 同规则）"""
    if request is None:
        return "unknown"
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("HTTP_X_REAL_IP", "") or request.META.get("REMOTE_ADDR", "unknown")


class LoginThrottleService:
    """登录限流服务：双维度失败计数 + 超限锁定，Redis 故障自动放行。"""

    @classmethod
    def is_enabled(cls) -> bool:
        try:
            return bool(getattr(settings, "LOGIN_RATE_LIMIT_ENABLED", True))
        except Exception:
            return True

    @classmethod
    def _settings(cls) -> tuple:
        """返回 (max_attempts, window_seconds, block_seconds)"""
        try:
            max_attempts = int(getattr(settings, "LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 0) or 5)
            window = int(getattr(settings, "LOGIN_RATE_LIMIT_WINDOW_SECONDS", 0) or 300)
            block = int(getattr(settings, "LOGIN_RATE_LIMIT_BLOCK_SECONDS", 0) or 900)
        except Exception:
            max_attempts, window, block = 5, 300, 900
        return max_attempts, window, block

    @classmethod
    def _client(cls):
        try:
            from framework.cache.redis_client import get_redis
            return get_redis()
        except Exception:
            return None

    @classmethod
    def _keys(cls, request, username: str) -> tuple:
        """返回 (ip_attempt, user_attempt, ip_block, user_block) 四个键"""
        ip = _get_client_ip(request)
        username = (username or "").strip().lower()
        return (
            f"{_LOGIN_PREFIX}attempts:ip:{ip}",
            f"{_LOGIN_PREFIX}attempts:user:{username}",
            f"{_LOGIN_PREFIX}block:ip:{ip}",
            f"{_LOGIN_PREFIX}block:user:{username}",
        )

    # 查询 / 记录

    @classmethod
    def is_login_rate_limited(cls, request, username: str) -> bool:
        """任一维度被锁定 → True（应拒绝本次登录，建议 429）"""
        if not cls.is_enabled():
            return False
        client = cls._client()
        if client is None:
            return False
        try:
            _, _, block_ip, block_user = cls._keys(request, username)
            return bool(client.get(block_ip) or client.get(block_user))
        except Exception as e:
            logger.warning("[LoginThrottle] 查询锁定状态失败，放行: %s", e)
            return False

    @classmethod
    def record_failed_login_attempt(cls, request, username: str) -> bool:
        """登录失败计数（IP + 用户名双维度）。返回是否触发锁定。"""
        if not cls.is_enabled():
            return False
        client = cls._client()
        if client is None:
            return False
        try:
            max_attempts, window, block = cls._settings()
            ip_key, user_key, block_ip, block_user = cls._keys(request, username)
            locked = False

            ip_attempts = client.incr(ip_key)
            if ip_attempts and int(ip_attempts) >= max_attempts:
                client.set(block_ip, "1", ex=block)
                locked = True
            client.expire(ip_key, window)

            user_attempts = client.incr(user_key)
            if user_attempts and int(user_attempts) >= max_attempts:
                client.set(block_user, "1", ex=block)
                locked = True
            client.expire(user_key, window)

            return locked
        except Exception as e:
            # Redis 故障 fail-open：不锁定、放行（登录可用性优先）
            logger.warning("[LoginThrottle] 失败计数异常，放行: %s", e)
            return False

    @classmethod
    def clear_failed_login_attempts(cls, request, username: str) -> None:
        """登录成功后清零两个维度的计数与锁定。"""
        if not cls.is_enabled():
            return
        client = cls._client()
        if client is None:
            return
        try:
            ip_key, user_key, block_ip, block_user = cls._keys(request, username)
            client.delete(ip_key, user_key, block_ip, block_user)
        except Exception as e:
            logger.warning("[LoginThrottle] 清零失败: %s", e)

    # 注册维度（IP 防刷，独立键前缀，不污染登录计数）

    @classmethod
    def is_register_enabled(cls) -> bool:
        try:
            return bool(getattr(settings, "REGISTER_RATE_LIMIT_ENABLED", True))
        except Exception:
            return True

    @classmethod
    def _register_settings(cls) -> tuple:
        """返回 (max_attempts, window_seconds, block_seconds)"""
        try:
            max_attempts = int(getattr(settings, "REGISTER_RATE_LIMIT_MAX_ATTEMPTS", 0) or 10)
            window = int(getattr(settings, "REGISTER_RATE_LIMIT_WINDOW_SECONDS", 0) or 3600)
            block = int(getattr(settings, "REGISTER_RATE_LIMIT_BLOCK_SECONDS", 0) or 3600)
        except Exception:
            max_attempts, window, block = 10, 3600, 3600
        return max_attempts, window, block

    @classmethod
    def _register_keys(cls, request) -> tuple:
        """返回 (ip_attempt, ip_block) 两个键"""
        ip = _get_client_ip(request)
        return (
            f"{_REGISTER_PREFIX}attempts:ip:{ip}",
            f"{_REGISTER_PREFIX}block:ip:{ip}",
        )

    @classmethod
    def is_register_rate_limited(cls, request) -> bool:
        """该 IP 是否被注册锁定 → True（应拒绝本次注册，建议 429）"""
        if not cls.is_register_enabled():
            return False
        client = cls._client()
        if client is None:
            return False
        try:
            _, block_ip = cls._register_keys(request)
            return bool(client.get(block_ip))
        except Exception as e:
            logger.warning("[RegisterThrottle] 查询锁定状态失败，放行: %s", e)
            return False

    @classmethod
    def record_register_attempt(cls, request) -> bool:
        """注册请求计数（成功 / 失败均计，IP 维度）。返回是否触发锁定。"""
        if not cls.is_register_enabled():
            return False
        client = cls._client()
        if client is None:
            return False
        try:
            max_attempts, window, block = cls._register_settings()
            ip_key, block_ip = cls._register_keys(request)
            attempts = client.incr(ip_key)
            if attempts and int(attempts) >= max_attempts:
                client.set(block_ip, "1", ex=block)
                return True
            client.expire(ip_key, window)
            return False
        except Exception as e:
            # Redis 故障 fail-open：不锁定、放行（注册可用性优先）
            logger.warning("[RegisterThrottle] 注册计数异常，放行: %s", e)
            return False

    @classmethod
    def clear_register_attempts(cls, request) -> None:
        """清除该 IP 的注册计数与锁定。

        注意：注册成功【不】自动调用 —— 防批量刷注册要求成功同样消耗窗口额度。
        本方法仅用于手动解除（后台运营）与测试隔离。
        """
        if not cls.is_register_enabled():
            return
        client = cls._client()
        if client is None:
            return
        try:
            ip_key, block_ip = cls._register_keys(request)
            client.delete(ip_key, block_ip)
        except Exception as e:
            logger.warning("[RegisterThrottle] 清零失败: %s", e)

    # 密码重置维度（IP + email 双维度，防邮件轰炸/防枚举）：每次重置请求
    # （成功/失败/用户不存在均计）对 IP 与 email 分别计数；任一维度达阈值即锁定
    # 该维度（期间请求 429）；⚠️ 成功【不】清零，锁随窗口/block TTL 自然过期

    @classmethod
    def is_password_reset_enabled(cls) -> bool:
        try:
            return bool(getattr(settings, "PASSWORD_RESET_RATE_LIMIT_ENABLED", True))
        except Exception:
            return True

    @classmethod
    def _password_reset_settings(cls) -> tuple:
        """返回 (max_attempts, window_seconds, block_seconds)"""
        try:
            max_attempts = int(getattr(settings, "PASSWORD_RESET_RATE_LIMIT_MAX_ATTEMPTS", 0) or 5)
            window = int(getattr(settings, "PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS", 0) or 3600)
            block = int(getattr(settings, "PASSWORD_RESET_RATE_LIMIT_BLOCK_SECONDS", 0) or 3600)
        except Exception:
            max_attempts, window, block = 5, 3600, 3600
        return max_attempts, window, block

    @classmethod
    def _password_reset_keys(cls, request, email: str) -> tuple:
        """返回 (ip_attempt, email_attempt, ip_block, email_block) 四个键"""
        ip = _get_client_ip(request)
        email = (email or "").strip().lower()
        return (
            f"{_PASSWORD_RESET_PREFIX}attempts:ip:{ip}",
            f"{_PASSWORD_RESET_PREFIX}attempts:email:{email}",
            f"{_PASSWORD_RESET_PREFIX}block:ip:{ip}",
            f"{_PASSWORD_RESET_PREFIX}block:email:{email}",
        )

    @classmethod
    def is_password_reset_rate_limited(cls, request, email: str) -> bool:
        """任一维度被锁定 → True（应拒绝本次重置请求，建议 429）"""
        if not cls.is_password_reset_enabled():
            return False
        client = cls._client()
        if client is None:
            return False
        try:
            _, _, block_ip, block_email = cls._password_reset_keys(request, email)
            return bool(client.get(block_ip) or client.get(block_email))
        except Exception as e:
            logger.warning("[PasswordResetThrottle] 查询锁定状态失败，放行: %s", e)
            return False

    @classmethod
    def record_password_reset_attempt(cls, request, email: str) -> bool:
        """重置请求计数（成功 / 失败 / 用户不存在均计，IP + email 双维度）。"""
        if not cls.is_password_reset_enabled():
            return False
        client = cls._client()
        if client is None:
            return False
        try:
            max_attempts, window, block = cls._password_reset_settings()
            ip_key, email_key, block_ip, block_email = cls._password_reset_keys(request, email)
            locked = False

            ip_attempts = client.incr(ip_key)
            if ip_attempts and int(ip_attempts) >= max_attempts:
                client.set(block_ip, "1", ex=block)
                locked = True
            client.expire(ip_key, window)

            email_attempts = client.incr(email_key)
            if email_attempts and int(email_attempts) >= max_attempts:
                client.set(block_email, "1", ex=block)
                locked = True
            client.expire(email_key, window)

            return locked
        except Exception as e:
            # Redis 故障 fail-open：不锁定、放行（可用性优先）
            logger.warning("[PasswordResetThrottle] 计数异常，放行: %s", e)
            return False
