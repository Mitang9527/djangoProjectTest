"""AI 创作工作室 - 信号

新用户注册（User 创建）时自动建额度账户并发放注册赠送额度，
使「注册即可见免费额度」的体验成立（避免首次调用 AI 才出现余额）。
"""


def ensure_quota_on_register(sender, instance, created, **kwargs):
    if not created:
        return
    from .services import get_or_create_quota
    get_or_create_quota(instance)
