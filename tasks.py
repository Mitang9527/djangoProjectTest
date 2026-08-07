"""
Invoke 命令行工具集 — 项目开发和运维统一入口。

用法:
    invoke -l                          # 列出所有命令
    invoke dev.run -p 9000             # 指定端口启动开发服务器
    invoke db.init                     # 初始化数据库
    invoke pro.api my_app              # 创建带 DRF 模板的新 app
    invoke log.errors                  # 查看最近错误日志
    invoke health.all                  # 系统健康检查

命名空间:
    dev      — 开发相关 (run/shell/install/init/doctor)
    db       — 数据库 (migrate/mm/resetdb/dump/load/init)
    code     — 代码质量 (lint/fmt/fix/check/test)
    pro      — 项目管理 (app/api/clean/static/schema/freeze/user)
    docker   — Docker (build/up/down/logs)
    git      — Git 工具 (status/add/commit/push/pull/branch/checkout/log/init)
    secret   — 密钥管理 (generate/rotate/check)
    log      — 日志查看 (tail/errors/clean)
    health   — 健康检查 (all/db/redis/celery)
    backup   — 数据备份 (create/list/restore)
"""

from __future__ import annotations

import os
import shutil
import sys
import datetime
import subprocess
from pathlib import Path
from collections import deque

# ---- Windows GBK 兼容: 强制 stdout/stderr 使用 UTF-8 ----
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from invoke import task, Collection
except ImportError:
    task = None
    Collection = None

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    import git
except ImportError:
    git = None

# 在任何可能导入 djangoProjectTest.model 的代码之前加载 .env
# (invoke 不走 manage.py, 所以不会自动加载环境变量)
try:
    from framework.core.env_loader import load_env_file
    load_env_file()
except Exception:
    pass

BASE_DIR = os.path.dirname(__file__)
APPS_DIR = os.path.join(BASE_DIR, "apps")


# =========================
# 通用辅助函数
# =========================

def get_repo():
    """获取 git 仓库对象"""
    if git is None:
        raise RuntimeError("GitPython 未安装：pip install GitPython")
    return git.Repo(BASE_DIR)


def django_manage(c, cmd: str, capture: bool = False):
    """运行 Django management 命令 (使用当前 Python 解释器)"""
    full_cmd = f'"{sys.executable}" manage.py {cmd}'
    return c.run(full_cmd, hide="stdout" if capture else None)


# =========================
# dev 命名空间 - 开发相关
# =========================

@task(help={"port": "HTTP 端口 (默认 8000)"})
def run(c, port=8000):
    """启动开发服务器 (Django runserver)"""
    logger.info(f"开发服务器启动中: http://127.0.0.1:{port}")
    c.run(f'"{sys.executable}" -u manage.py runserver 0.0.0.0:{port} --force-color')


@task
def shell(c):
    """进入 Django Shell (IPython / bpython / 标准)"""
    django_manage(c, "shell")


@task(help={"upgrade": "同时升级所有已安装的包"})
def install(c, upgrade=False):
    """安装项目依赖 (uv pip install)"""
    logger.info("安装依赖...")
    cmd = "uv pip install -r requirements.txt"
    if upgrade:
        cmd += " --upgrade"
    c.run(cmd)
    logger.info("依赖安装完成")


@task(help={"clean": "清理不在 lock 文件中的多余包"})
def sync(c, clean=False):
    """同步依赖环境 (uv sync，严格匹配 lock 文件)"""
    logger.info("同步依赖环境...")
    cmd = "uv sync"
    if clean:
        cmd += " --clean"
    c.run(cmd)
    logger.info("环境同步完成")


@task(help={"no_sync": "跳过 pip install 步骤"})
def init(c, no_sync=False):
    """一键初始化开发环境 (venv → install → migrate)"""
    logger.info("初始化项目...")
    if not os.path.exists(".venv"):
        logger.info("创建虚拟环境...")
        c.run("uv venv")
    if not no_sync:
        if os.path.exists("uv.lock"):
            c.run("uv sync")
        else:
            c.run("uv pip install -r requirements.txt")
    django_manage(c, "migrate")
    logger.info("初始化完成! 运行 invoke dev.run 启动服务器")


@task
def doctor(c):
    """Django 配置完整性检查"""
    logger.info("检查项目配置...")
    django_manage(c, "check")


dev = Collection("dev")
dev.add_task(run)
dev.add_task(shell)
dev.add_task(install)
dev.add_task(init)
dev.add_task(sync)
dev.add_task(doctor)


# =========================
# db 命名空间 - 数据库
# =========================

@task
def migrate(c):
    """完整迁移 (makemigrations + migrate)"""
    logger.info("生成迁移文件...")
    django_manage(c, "makemigrations")
    logger.info("应用迁移...")
    django_manage(c, "migrate")
    logger.info("数据库迁移完成")


@task
def mm(c):
    """仅生成迁移文件 (makemigrations)"""
    django_manage(c, "makemigrations")


@task
def resetdb(c):
    """删除并重建数据库 (SQLite 适用)"""
    db_path = Path(BASE_DIR) / "db.sqlite3"
    if db_path.exists():
        logger.warning("删除旧数据库...")
        db_path.unlink()
    logger.info("重新迁移...")
    django_manage(c, "migrate")


@task(help={"app": "仅初始化指定 app 的数据 (如 saas)"})
def init(c, app=None):
    """初始化基础数据 (init_permissions + init_gateway)"""
    if not app or app == "permissions":
        logger.info("初始化权限数据...")
        django_manage(c, "init_permissions")
    if not app or app == "gateway":
        logger.info("初始化网关规则...")
        django_manage(c, "init_gateway")
    logger.info("数据初始化完成")


@task(help={"file": "导出文件名 (默认 backup.json)"})
def dump(c, file="backup.json"):
    """导出全量数据到 JSON 文件"""
    logger.info(f"导出数据 -> {file}")
    django_manage(c, f"dumpdata > {file}")


@task(help={"file": "导入文件名 (默认 backup.json)"})
def load(c, file="backup.json"):
    """从 JSON 文件导入数据"""
    logger.info(f"导入数据 <- {file}")
    django_manage(c, f"loaddata {file}")


@task
def show(c):
    """显示数据库连接和表信息"""
    django_manage(c, "dbshell -- -c '\\dt'")


db = Collection("db")
db.add_task(migrate)
db.add_task(mm)
db.add_task(resetdb, "reset")
db.add_task(init)
db.add_task(dump)
db.add_task(load)
db.add_task(show)


# =========================
# code 命名空间 - 代码质量 (已集成到顶级命令)
# =========================

@task
def lint(c):
    """Ruff 代码检查"""
    logger.info("检查代码...")
    try:
        c.run("ruff check .")
    except Exception:
        logger.warning("Ruff 未安装，跳过")


@task
def fmt(c):
    """Black 代码格式化"""
    logger.info("格式化代码...")
    try:
        c.run("black .")
    except Exception:
        logger.warning("Black 未安装，跳过")


@task
def fix(c):
    """Ruff 自动修复"""
    logger.info("自动修复代码...")
    try:
        c.run("ruff check . --fix")
    except Exception:
        logger.warning("Ruff 未安装，跳过")


@task
def check(c):
    """一键检查 (fix + fmt)"""
    logger.info("执行代码检查...")
    try:
        c.run("ruff check . --fix")
        c.run("black .")
    except Exception:
        logger.warning("代码检查工具未安装")
    logger.info("检查完成")


@task(help={"path": "测试文件/目录路径 (默认全部)", "verbose": "详细输出"})
def test(c, path="", verbose=False):
    """运行测试 (pytest)"""
    logger.info("运行测试...")
    cmd = "pytest -v" if verbose else "pytest"
    if path:
        cmd += f" {path}"
    try:
        c.run(cmd)
    except Exception:
        logger.warning("Pytest 未安装或无测试文件")


@task
def coverage(c):
    """运行测试并生成覆盖率报告"""
    logger.info("运行测试并计算覆盖率...")
    try:
        c.run("pytest --cov=. --cov-report=html --cov-report=term")
        logger.info("覆盖率报告: htmlcov/index.html")
    except Exception:
        logger.warning("pytest-cov 未安装")


code = Collection("code")
code.add_task(lint)
code.add_task(fmt)
code.add_task(fix)
code.add_task(check)
code.add_task(test)
code.add_task(coverage)


# =========================
# pro 命名空间 - 项目管理
# =========================

@task(help={"name": "App 名称 (如 my_feature)"})
def app(c, name):
    """创建普通 Django app: invoke pro.app {name}"""
    create_app(c, name, drf=False)


@task(help={"name": "App 名称 (如 my_api)"})
def api(c, name):
    """创建 DRF app (含 Model/Serializer/ViewSet): invoke pro.api {name}"""
    create_app(c, name, drf=True)


@task
def clean(c):
    """清理项目中的 __pycache__ 和 .pyc 编译文件"""
    logger.info("清理缓存文件...")
    count = 0
    for root, dirs, files in os.walk(BASE_DIR):
        if ".venv" in root or "node_modules" in root:
            continue
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d))
                count += 1
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                os.remove(os.path.join(root, f))
                count += 1
    logger.info(f"清理完成, 移除了 {count} 个文件/目录")


@task
def static(c):
    """收集静态文件 (python manage.py collectstatic)"""
    logger.info("收集静态文件...")
    django_manage(c, "collectstatic --noinput")
    logger.info("静态文件收集完成")


@task
def schema(c):
    """生成 OpenAPI 3.0 接口定义文件 (schema.yml)"""
    logger.info("生成 OpenAPI 定义文件...")
    django_manage(c, "spectacular --file schema.yml")
    logger.info("schema.yml 生成成功")


@task
def freeze(c):
    """更新 requirements.txt (uv pip freeze)"""
    logger.info("更新依赖列表...")
    c.run("uv pip freeze > requirements.txt")
    logger.info("requirements.txt 更新成功")


@task
def user(c):
    """创建超级管理员账号 (交互式)"""
    django_manage(c, "createsuperuser")


@task(help={"email": "管理员邮箱 (可用 DJANGO_SUPERUSER_EMAIL 环境变量)", "username": "用户名 (可用 DJANGO_SUPERUSER_USERNAME 环境变量)", "password": "密码 (可用 DJANGO_SUPERUSER_PASSWORD 环境变量, 不传则随机生成)"})
def admin(c, email=None, username=None, password=None):
    """非交互式创建超级管理员 (密码不指定时自动生成随机密码)"""
    if email:
        os.environ["DJANGO_SUPERUSER_EMAIL"] = email
    if username:
        os.environ["DJANGO_SUPERUSER_USERNAME"] = username
    if password:
        os.environ["DJANGO_SUPERUSER_PASSWORD"] = password
    django_manage(c, "check_admin")


@task
def show_urls(c):
    """列出所有已注册的 URL 路由"""
    django_manage(c, "show_urls")


pro = Collection("pro")
pro.add_task(app)
pro.add_task(api)
pro.add_task(clean)
pro.add_task(static)
pro.add_task(schema)
pro.add_task(freeze)
pro.add_task(user)
pro.add_task(admin)
pro.add_task(show_urls, "list")


# =========================
# docker 命名空间
# =========================

@task
def build(c):
    """构建 Docker 镜像"""
    c.run("docker compose build")


@task
def up(c):
    """启动 Docker 服务 (后台)"""
    c.run("docker compose up -d")


@task
def down(c):
    """停止 Docker 服务"""
    c.run("docker compose down")


@task(help={"service": "指定服务名 (如 web/celery-worker)"})
def logs(c, service=""):
    """查看 Docker 日志 (支持指定服务)"""
    cmd = "docker compose logs -f"
    if service:
        cmd += f" {service}"
    c.run(cmd)


@task
def restart(c):
    """重启所有 Docker 服务"""
    c.run("docker compose restart")


docker = Collection("docker")
docker.add_task(build)
docker.add_task(up)
docker.add_task(down)
docker.add_task(logs)
docker.add_task(restart)


# =========================
# git 命名空间 (挂载为顶级 git_* 命令)
# =========================

@task
def ginit(c):
    """初始化 Git 仓库"""
    git.Repo.init(BASE_DIR)
    logger.info("Git 仓库初始化完成")


@task
def status(c):
    """查看 Git 状态"""
    repo = get_repo()
    logger.info(repo.git.status())


@task(help={"path": "文件/目录路径 (默认 .)"})
def add(c, path="."):
    """添加到暂存区"""
    repo = get_repo()
    repo.git.add(path)


@task(help={"msg": "提交信息 (默认 'update')"})
def commit(c, msg="update"):
    """提交代码"""
    repo = get_repo()
    repo.git.commit("-m", msg)


@task(help={"remote": "远程仓库 (默认 origin)", "branch": "分支 (默认 main)"})
def push(c, remote="origin", branch="main"):
    """推送代码"""
    repo = get_repo()
    repo.git.push(remote, branch)


@task(help={"remote": "远程仓库 (默认 origin)", "branch": "分支 (默认 main)"})
def pull(c, remote="origin", branch="main"):
    """拉取代码"""
    repo = get_repo()
    repo.git.pull(remote, branch)


@task
def branch(c):
    """查看分支列表"""
    repo = get_repo()
    logger.info(repo.git.branch())


@task(help={"name": "目标分支名"})
def checkout(c, name):
    """切换分支"""
    repo = get_repo()
    repo.git.checkout(name)


@task(help={"n": "显示最近 N 条 (默认 10)"})
def log(c, n=10):
    """查看提交记录"""
    repo = get_repo()
    logger.info(repo.git.log(f"-{n}", "--oneline"))


git_ns = Collection("git")
git_ns.add_task(ginit)
git_ns.add_task(status)
git_ns.add_task(add)
git_ns.add_task(commit)
git_ns.add_task(push)
git_ns.add_task(pull)
git_ns.add_task(branch)
git_ns.add_task(checkout)
git_ns.add_task(log)


# =========================
# secret 命名空间 - 密钥管理
# =========================

@task
def sgenerate(c):
    """生成新的 SECRET_KEY 并备份旧密钥"""
    logger.info("生成新的 SECRET_KEY...")
    django_manage(c, "rotate_secret_key")


@task(help={"username": "关联的用户名 (默认 admin)", "prefix": "Key 前缀 (默认 sk-)"})
def apikey(c, username="admin", prefix="sk-"):
    """生成 API Key (用于外部系统对接)"""
    from framework.drf.api_key_auth import generate_api_key
    api_key = generate_api_key(prefix=prefix)
    logger.info(f"生成 API Key (关联用户: {username}):")
    logger.info(f"  {api_key}")
    logger.info("")
    logger.info("使用方式:")
    logger.info(f"  curl -H 'X-API-Key: {api_key}' http://localhost:8000/api/")
    logger.info("")
    logger.info("在 settings 或 .env 中配置 API_KEYS 字典以启用:")
    logger.info(f'  API_KEYS = {{ "{api_key}": "{username}" }}')


@task
def scheck(c):
    """检查当前密钥配置是否安全"""
    from djangoProjectTest.model import global_config
    key = global_config.SECRET_KEY
    length = len(key) if key else 0
    has_default = key and "django-insecure" not in key

    logger.info(f"密钥长度: {length} 字符")
    logger.info(f"使用默认值: {'否 ✅' if has_default else '是 ⚠️'}")

    if length < 50:
        logger.warning("⚠️ 密钥长度不足 50 字符，建议运行 invoke secret.generate")
    elif not has_default:
        logger.warning("⚠️ 仍在使用默认不安全密钥，请运行 invoke secret.generate")


secret = Collection("secret")
secret.add_task(sgenerate, "generate")
secret.add_task(apikey, "apikey")
secret.add_task(scheck, "check")


# =========================
# log 命名空间 - 日志查看 (纯 Python, 跨平台兼容 Windows/Linux/macOS)
# =========================

LOG_DIR = Path(BASE_DIR) / "logs"

# ANSI 颜色 (仅在终端输出时使用)
_COLORS = {
    "TRACE":    "\033[90m",   # 灰色
    "DEBUG":    "\033[36m",   # 青色
    "INFO":     "\033[32m",   # 绿色
    "SUCCESS":  "\033[92m",   # 亮绿
    "WARNING":  "\033[33m",   # 黄色
    "ERROR":    "\033[31m",   # 红色
    "CRITICAL": "\033[35m",   # 紫色
    "RESET":    "\033[0m",
}


def _find_latest_log(log_type: str = "app") -> Path | None:
    """
    查找最新日志文件。

    log_type: "app" | "celery" | "api" | "error"
    """
    patterns = {
        "app":    "????-??-??.log",        # 2026-07-15.log
        "celery": "celery-????-??-??.log",
        "api":    "api-????-??-??.log",
        "error":  "error-????-??-??.log",
    }
    pattern = patterns.get(log_type, patterns["app"])
    log_files = sorted(LOG_DIR.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    return log_files[0] if log_files else None


def _read_last_lines(filepath: Path, n: int, level_filter: str = "") -> list[str]:
    """
    纯 Python 读取日志文件最后 N 行, 支持按级别过滤。

    采用滑动窗口流式读取, 避免大文件 OOM。
    返回符合过滤条件的最后 N 条日志行 (含 ANSI 颜色)。
    """
    if not filepath.exists():
        return []

    pattern = f"| {level_filter} " if level_filter else None
    matched_lines: deque[str] = deque(maxlen=n)

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if pattern:
                    if pattern not in line:
                        continue
                matched_lines.append(line.rstrip("\n"))
    except Exception as exc:
        return [f"[读取失败] {filepath}: {exc}"]

    return list(matched_lines)


def _colorize_line(line: str) -> str:
    """为日志行添加 ANSI 颜色"""
    try:
        parts = line.split("|", 2)
        if len(parts) >= 2:
            level = parts[1].strip()
            color = _COLORS.get(level, "")
            if color:
                return f"{color}{line}{_COLORS['RESET']}"
    except Exception:
        pass
    return line


@task(help={"n": "显示最近 N 条 (默认 20)", "level": "过滤级别 (如 ERROR/WARNING/INFO)", "type": "日志类型: app/celery/api/error", "file": "指定日志文件名 (优先级最高)"})
def tail(c, n=20, level="", type="", file=""):
    """
    查看最新日志 (后 N 条)。

    示例:
        invoke log.tail                         # 最新 20 条 (app 日志)
        invoke log.tail -n 50 -l ERROR          # 最新 50 条错误
        invoke log.tail -t api                  # API 请求日志
        invoke log.tail -t celery               # Celery 任务日志
        invoke log.tail -t error                # 聚合错误日志
        invoke log.tail -f error-2026-07-15.log # 指定文件
    """
    if file:
        target = LOG_DIR / file
        if not target.exists():
            logger.error(f"日志文件不存在: {file}")
            return
    else:
        log_type = type or "app"
        target = _find_latest_log(log_type=log_type)
        if not target:
            available = ", ".join(
                t for t in ["app", "celery", "api", "error"]
                if _find_latest_log(log_type=t)
            )
            logger.warning(
                f"logs/ 目录下没有 {log_type} 类型日志\n"
                f"  可用的日志类型: {available or '(无)'}\n"
                f"  运行 invoke dev.run 启动服务器自动创建"
            )
            return

    desc = f"类型={type}" if type else f"文件={target.name}"
    logger.info(f"日志: {desc}  (最后 {n} 条{', 级别=' + level if level else ''})")
    logger.info("-" * 60)

    lines = _read_last_lines(target, n=n, level_filter=level)
    if not lines:
        logger.info("(无匹配记录)")
        return

    # 终端输出带颜色, CI 环境纯文本
    use_color = sys.stdout.isatty()
    for line in lines:
        if use_color:
            print(_colorize_line(line))
        else:
            print(line)


@task(help={"n": "显示最近 N 条 (默认 10)", "type": "日志类型: app/celery/api/error (默认全部)", "file": "指定日志文件名"})
def errors(c, n=10, type="", file=""):
    """
    查看最近的错误日志 (ERROR + CRITICAL)。

    示例:
        invoke log.errors                    # 所有日志源最近 10 条错误
        invoke log.errors -t app             # 仅 app 日志的错误
        invoke log.errors -t api -n 20       # API 日志最近 20 条错误
        invoke log.errors -t error           # 聚合错误日志 (推荐)
    """
    # 如果指定了 --type error, 直接读 error 聚合日志 (因为已全是错误)
    if type == "error":
        # error 日志已全是 ERROR+, 直接 tail
        target = _find_latest_log(log_type="error")
        if not target:
            logger.warning("error 日志不存在")
            return
        logger.info(f"聚合错误日志: {target.name}  (最近 {n} 条)")
        logger.info("-" * 60)
        lines = _read_last_lines(target, n=n)
        use_color = sys.stdout.isatty()
        for line in lines:
            print(_colorize_line(line) if use_color else line)
        return

    # 指定文件
    if file:
        targets = [LOG_DIR / file]
        if not targets[0].exists():
            logger.error(f"日志文件不存在: {file}")
            return
    elif type:
        # 从指定类型的日志中提取 ERROR/CRITICAL
        t = _find_latest_log(log_type=type)
        targets = [t] if t else []
    else:
        # 扫描所有日志类型
        targets = []
        for lt in ["app", "celery", "api", "error"]:
            t = _find_latest_log(log_type=lt)
            if t:
                targets.append(t)

    if not targets:
        logger.warning("logs/ 目录下没有日志文件")
        return

    logger.info(f"错误日志 (最近 {n} 条):")
    logger.info("-" * 60)

    # 从各日志文件提取 ERROR/CRITICAL
    seen = set()
    all_lines = []
    for target in targets:
        for level_filter in ("CRITICAL", "ERROR"):
            for line in _read_last_lines(target, n=n * 5, level_filter=level_filter):
                if line not in seen:
                    seen.add(line)
                    all_lines.append(line)

    all_lines = all_lines[-n:]

    if not all_lines:
        logger.info("(无错误记录)")
        return

    use_color = sys.stdout.isatty()
    for line in all_lines:
        print(_colorize_line(line) if use_color else line)


@task(help={"days": "保留最近 N 天 (默认 7)", "dry_run": "仅预览, 不删除"})
def cleanlogs(c, days=7, dry_run=False):
    """清理指定天数之前的旧日志文件"""
    import time
    cutoff = time.time() - days * 86400
    to_delete = []

    for f in LOG_DIR.glob("*.log*"):
        if f.stat().st_mtime < cutoff:
            to_delete.append(f)

    if not to_delete:
        logger.info(f"没有超过 {days} 天的旧日志")
        return

    if dry_run:
        logger.info(f"将清理 {len(to_delete)} 个文件 (预览模式):")
        for f in sorted(to_delete):
            mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            logger.info(f"  {f.name}  ({mtime})")
        logger.info(f"确认后运行: invoke log.clean -d {days}")
        return

    for f in to_delete:
        f.unlink()
    logger.info(f"清理了 {len(to_delete)} 个旧日志文件")


log_ns = Collection("log")
log_ns.add_task(tail)
log_ns.add_task(errors)
log_ns.add_task(cleanlogs, "clean")


# =========================
# health 命名空间 - 健康检查 (纯 Python, 跨平台)
# =========================

def _shell_out(cmd: str, timeout: int = 10) -> str:
    """运行 shell 命令并返回 stdout 文本 (跨平台)"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=BASE_DIR,
        )
        return (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return "[超时]"
    except Exception as e:
        return f"[错误: {e}]"


def _print_header(title: str) -> None:
    """打印带分隔线的节标题"""
    bar = "─" * 40
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar)


@task
def hall(c):
    """完整系统健康检查 (配置 + DB + Redis + Celery)"""
    from djangoProjectTest.model import global_config

    _print_header("系统健康检查")

    # 1. Django 配置检查
    _print_header("[1/4] Django 配置")
    output = _shell_out(f'"{sys.executable}" manage.py check --deploy 2>&1')
    # 只显示前 20 行
    lines = output.split("\n")[:20]
    for line in lines:
        print(f"  {line}")
    if len(output.split("\n")) > 20:
        print("  ... (已截断)")

    # 2. 数据库
    _print_header("[2/4] 数据库连接")
    output = _shell_out(
        f'"{sys.executable}" -c "import django; django.setup(); '
        "from django.db import connection; connection.ensure_connection(); "
        "print('数据库连接正常')\""
    )
    print(f"  {output}")

    # 3. Redis
    _print_header("[3/4] Redis")
    if global_config.redis.enabled:
        output = _shell_out(
            f'"{sys.executable}" -c "import redis; '
            f"r=redis.Redis(host='{global_config.redis.host}',port={global_config.redis.port},"
            f"password='{global_config.redis.password}',socket_connect_timeout=3); "
            "r.ping(); print('Redis 连接正常')\""
        )
        print(f"  {output}")
    else:
        print("  Redis 未启用 (跳过)")

    # 4. Celery
    _print_header("[4/4] Celery Worker")
    output = _shell_out(f'"{sys.executable}" manage.py celery status 2>&1')
    if "Error" in output or "error" in output.lower():
        print("  Celery 未运行或未配置")
    else:
        print(f"  {output}")

    _print_header("检查完成")


@task
def dbh(c):
    """仅检查数据库连接"""
    output = _shell_out(
        f'"{sys.executable}" -c "import django; django.setup(); '
        "from django.db import connection; connection.ensure_connection(); "
        'print(\'数据库连接正常\')\"'
    )
    print(output)


health = Collection("health")
health.add_task(hall, "all")
health.add_task(dbh, "db")


# =========================
# backup 命名空间 - 备份/恢复
# =========================

@task(help={"name": "备份文件名 (默认自动生成 timestamp)"})
def bcreate(c, name=""):
    """创建数据库备份 (dumpdata)"""
    if not name:
        name = datetime.datetime.now().strftime("backup_%Y%m%d_%H%M%S.json")
    backup_dir = Path(BASE_DIR) / "backups"
    backup_dir.mkdir(exist_ok=True)

    output = backup_dir / name
    logger.info(f"创建备份: {output}")
    django_manage(c, f"dumpdata saas users --indent 2 --output {output}")
    size = output.stat().st_size
    logger.info(f"备份完成: {name} ({size / 1024:.1f} KB)")


@task
def blist(c):
    """列出所有备份文件"""
    backup_dir = Path(BASE_DIR) / "backups"
    if not backup_dir.exists():
        logger.info("backups/ 目录不存在")
        return

    files = sorted(backup_dir.glob("*.json"), reverse=True)
    if not files:
        logger.info("没有备份文件")
        return

    logger.info(f"{'文件名':<40} {'大小':>10} {'日期'}")
    logger.info("-" * 70)
    for f in files:
        stat = f.stat()
        size_kb = stat.st_size / 1024
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        logger.info(f"{f.name:<40} {size_kb:>8.1f}KB  {mtime}")


@task(help={"name": "备份文件名"})
def brestore(c, name):
    """从备份文件恢复数据 (⚠️ 危险操作)"""
    backup_dir = Path(BASE_DIR) / "backups"
    backup_file = backup_dir / name

    if not backup_file.exists():
        logger.error(f"备份文件不存在: {backup_file}")
        return

    logger.warning(f"⚠️ 即将从 {name} 恢复数据，这将覆盖现有数据!")
    # TODO: 添加确认步骤 (invoke 不方便交互, 仅在命令行提示)
    django_manage(c, f"loaddata {backup_file}")
    logger.info("数据恢复完成")


backup = Collection("backup")
backup.add_task(bcreate, "create")
backup.add_task(blist, "list")
backup.add_task(brestore, "restore")


# =========================
# 根命名空间注册
# =========================

ns = Collection()
ns.add_collection(dev, "dev")
ns.add_collection(db, "db")
# ns.add_collection(code, "code")
ns.add_collection(pro, "pro")
ns.add_collection(docker, "docker")
# ns.add_collection(git_ns, "git")
ns.add_collection(secret, "secret")
ns.add_collection(log_ns, "log")
# ns.add_collection(health, "health")
# ns.add_collection(backup, "backup")


# =========================
# 创建 app 辅助函数
# =========================

def create_app(c, name, drf=False):
    """创建新 Django app 到 apps/ 目录"""
    os.makedirs(APPS_DIR, exist_ok=True)
    app_path = os.path.join(APPS_DIR, name)

    if os.path.exists(app_path):
        logger.info(f"apps/{name} 已存在")
        return

    logger.info(f"创建 app: {app_path}")
    tmp_name = name
    c.run(f"django-admin startapp {tmp_name}")
    shutil.move(tmp_name, app_path)

    if not drf:
        write_file(app_path, "urls.py", f"""from django.urls import path
from . import views

urlpatterns = [
    # 在此添加 {name} 应用的路由
]
""")

    if drf:
        generate_drf(app_path, name)

    logger.info(f"\nApp '{name}' 创建成功, 已自动加入 INSTALLED_APPS")


def generate_drf(app_path, name):
    """生成 DRF 标准模板 (Model/Serializer/ViewSet/urls/admin/services)"""
    model_class = name.capitalize()

    write_file(app_path, "models.py", f"""from django.db import models

class {model_class}(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name
""")

    write_file(app_path, "serializers.py", f"""from rest_framework import serializers
from .models import {model_class}

class {model_class}Serializer(serializers.ModelSerializer):
    class Meta:
        model = {model_class}
        # 显式声明字段，避免使用 '__all__' 导致敏感字段意外暴露
        fields = ('id', 'name')
""")

    write_file(app_path, "views.py", f"""from rest_framework import permissions
from drf_spectacular.utils import extend_schema, extend_schema_view
from djangoProjectTest.viewsets import BaseModelViewSet
from .models import {model_class}
from .serializers import {model_class}Serializer

@extend_schema_view(
    list=extend_schema(summary="获取{model_class}列表", tags=["{name}"]),
    create=extend_schema(summary="创建{model_class}", tags=["{name}"]),
    retrieve=extend_schema(summary="获取{model_class}详情", tags=["{name}"]),
    update=extend_schema(summary="更新{model_class}", tags=["{name}"]),
    partial_update=extend_schema(summary="部分更新{model_class}", tags=["{name}"]),
    destroy=extend_schema(summary="删除{model_class}", tags=["{name}"]),
)
class {model_class}ViewSet(BaseModelViewSet):
    \"\"\"{name} 模块 CRUD 接口\"\"\"
    queryset = {model_class}.objects.all()
    serializer_class = {model_class}Serializer
    filterset_fields = ['name']
    search_fields = ['name']
    ordering_fields = ['id', 'name']
""")

    write_file(app_path, "urls.py", f"""from rest_framework.routers import DefaultRouter
from .views import {model_class}ViewSet

router = DefaultRouter()
router.register(r'', {model_class}ViewSet, basename='{name}')
urlpatterns = router.urls
""")

    write_file(app_path, "services.py", f"""\"\"\"{name} 应用 - 业务逻辑层\"\"\"

class {model_class}Service:
    \"\"\"{model_class} 业务服务\"\"\"
    pass
""")

    write_file(app_path, "admin.py", f"""from django.contrib import admin
from .models import {model_class}

@admin.register({model_class})
class {model_class}Admin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']
""")

    logger.info("DRF 模板生成完成 (含 services.py)")


def write_file(app_path, filename, content):
    """写入文件到 app 目录"""
    file_path = os.path.join(app_path, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
