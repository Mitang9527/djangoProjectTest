import os
import shutil
from pathlib import Path
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

BASE_DIR = os.path.dirname(__file__)
APPS_DIR = os.path.join(BASE_DIR, "apps")


# =========================
# Git 工具函数
# =========================

def get_repo():
    """获取 git 仓库对象"""
    if git is None:
        raise RuntimeError("GitPython 未安装：pip install GitPython")
    return git.Repo(BASE_DIR)

# =========================
# dev 命名空间 - 开发相关
# =========================

@task
def run(c, port=8000):
    """启动开发服务器 (默认端口 8000)"""
    logger.info(f"正在启动开发服务器，访问地址: http://127.0.0.1:{port}")
    c.run(f"python -u manage.py runserver 0.0.0.0:{port} --force-color")

@task
def shell(c):
    """进入 Django Shell"""
    c.run("python manage.py shell")

@task
def install(c, upgrade=False):
    """安装项目依赖 """
    logger.info("安装依赖...")
    cmd = "uv pip install -r requirements.txt"
    if upgrade:
        cmd += " --upgrade"
    c.run(cmd)
    logger.info("依赖安装完成")

@task
def sync(c, clean=False):
    """同步依赖环境 (使用 uv sync，严格匹配 lock 文件)"""
    logger.info("同步依赖环境...")
    cmd = "uv sync"
    if clean:
        cmd += " --clean"  # 移除不在 lock 文件中的包
    c.run(cmd)
    logger.info("环境同步完成")


@task
def init(c, no_sync=False):
    """初始化开发环境 (使用 uv)"""
    logger.info("初始化项目...")

    # 检查是否已有虚拟环境，没有则创建
    if not os.path.exists(".venv"):
        logger.info("创建虚拟环境...")
        c.run("uv venv")

    # 安装依赖
    if not no_sync:
        if os.path.exists("uv.lock"):
            logger.info("检测到 uv.lock，执行 uv sync...")
            c.run("uv sync")
        else:
            logger.info("未检测到 uv.lock，执行 uv pip install...")
            c.run("uv pip install -r requirements.txt")

    # 执行数据库迁移
    logger.info("执行数据库迁移...")
    c.run("python manage.py migrate")

    logger.info("初始化完成")

@task
def doctor(c):
    """检查 Django 配置"""
    logger.info("检查项目配置...")
    c.run("python manage.py check")

dev = Collection("dev")
dev.add_task(run)
dev.add_task(shell)
dev.add_task(install)
dev.add_task(init)
dev.add_task(sync)
dev.add_task(doctor)


# =========================
# db 命名空间 - 数据库相关
# =========================

@task
def migrate(c):
    """同步数据库 (makemigrations + migrate)"""
    logger.info("开始扫描模型变更...")
    c.run("python manage.py makemigrations")
    logger.info("开始执行数据库迁移...")
    c.run("python manage.py migrate")
    logger.info("数据库迁移完成")

@task
def mm(c):
    """仅生成迁移文件 (makemigrations)"""
    c.run("python manage.py makemigrations")

@task
def resetdb(c):
    """重建 SQLite 数据库"""
    db_path = Path(BASE_DIR) / "db.sqlite3"
    
    if db_path.exists():
        logger.warning("删除旧数据库...")
        db_path.unlink()
    
    logger.info("重新迁移数据库...")
    c.run("python manage.py migrate")

@task
def dump(c, file="backup.json"):
    """导出数据"""
    logger.info(f"导出数据 -> {file}")
    c.run(f"python manage.py dumpdata > {file}")

@task
def load(c, file="backup.json"):
    """导入数据"""
    logger.info(f"导入数据 <- {file}")
    c.run(f"python manage.py loaddata {file}")

db = Collection("db")
db.add_task(migrate)
db.add_task(mm)
db.add_task(resetdb)
db.add_task(dump)
db.add_task(load)


# =========================
# code 命名空间 - 代码相关
# =========================

@task
def lint(c):
    """Ruff 检查"""
    logger.info("检查代码...")
    try:
        c.run("ruff check .")
    except Exception:
        logger.warning("Ruff 未安装或未找到，请检查")

@task
def fmt(c):
    """Black 格式化"""
    logger.info("格式化代码...")
    try:
        c.run("black .")
    except Exception:
        logger.warning("Black 未安装或未找到，请检查")

@task
def fix(c):
    """Ruff 自动修复"""
    logger.info("自动修复代码...")
    try:
        c.run("ruff check . --fix")
    except Exception:
        logger.warning("Ruff 未安装或未找到，请检查")

@task
def check(c):
    """一键检查 (fix + fmt)"""
    logger.info("执行代码检查...")
    try:
        c.run("ruff check . --fix")
        c.run("black .")
    except Exception:
        logger.warning("代码检查工具可能未安装，请检查")
    logger.info("检查完成")

@task
def test(c):
    """运行测试 (pytest)"""
    logger.info("运行测试...")
    try:
        c.run("pytest")
    except Exception:
        logger.warning("Pytest 未安装或未找到，请检查")

code = Collection("code")
code.add_task(lint)
code.add_task(fmt)
code.add_task(fix)
code.add_task(check)
code.add_task(test)


# =========================
# project 命名空间 - 项目相关
# =========================

@task
def app(c, name):
    """创建普通 app: invoke project.app {name}"""
    create_app(c, name, drf=False)

@task
def api(c, name):
    """创建 DRF app: invoke project.api {name}"""
    create_app(c, name, drf=True)

@task
def clean(c):
    """清理项目中的 __pycache__ 和编译文件"""
    logger.info("正在清理缓存文件...")
    for root, dirs, files in os.walk(BASE_DIR):
        for d in dirs:
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d))
        for f in files:
            if f.endswith(".pyc") or f.endswith(".pyo"):
                os.remove(os.path.join(root, f))
    logger.info("清理完成")

@task
def static(c):
    """收集静态文件 (collectstatic)"""
    logger.info("正在收集静态文件...")
    c.run("python manage.py collectstatic --noinput")
    logger.info("静态文件收集完成")

@task
def schema(c):
    """生成 OpenAPI 3.0 接口定义文件 """
    logger.info("正在生成 OpenAPI 定义文件...")
    c.run("python manage.py spectacular --file schema.yml")
    logger.info("schema.yml 生成成功")

@task
def freeze(c):
    """更新 requirements.txt 依赖列表"""
    logger.info("正在更新依赖列表...")
    c.run("pip freeze > requirements.txt")
    logger.info("requirements.txt 更新成功")

@task
def user(c):
    """创建超级管理员账号"""
    c.run("python manage.py createsuperuser")

pro = Collection("pro")
pro.add_task(app)
pro.add_task(api)
pro.add_task(clean)
pro.add_task(static)
pro.add_task(schema)
pro.add_task(freeze)
pro.add_task(user)


# =========================
# docker 命名空间 - Docker 相关
# =========================

@task
def build(c):
    """构建 Docker 镜像"""
    c.run("docker compose build")

@task
def up(c):
    """启动 Docker 服务"""
    c.run("docker compose up -d")

@task
def down(c):
    """停止 Docker 服务"""
    c.run("docker compose down")

@task
def logs(c):
    """查看 Docker 日志"""
    c.run("docker compose logs -f")

docker = Collection("docker")
docker.add_task(build)
docker.add_task(up)
docker.add_task(down)
docker.add_task(logs)


# =========================
# Git 命名空间
# =========================

def get_repo():
    """获取当前 Git 仓库对象"""
    if git is None:
        raise RuntimeError("未安装 GitPython")
    return git.Repo(BASE_DIR)


@task
def ginit(c):
    """初始化 Git 仓库"""
    git.Repo.init(BASE_DIR)
    logger.info("Git 初始化完成")


@task
def status(c):
    """查看 Git 状态"""
    repo = get_repo()
    logger.info(repo.git.status())


@task
def add(c, path="."):
    """添加文件到暂存区"""
    repo = get_repo()
    repo.git.add(path)


@task
def commit(c, msg="update"):
    """提交代码"""
    repo = get_repo()
    repo.git.commit("-m", msg)


@task
def push(c, remote="origin", branch="main"):
    """推送代码"""
    repo = get_repo()
    repo.git.push(remote, branch)


@task
def pull(c, remote="origin", branch="main"):
    """拉取代码"""
    repo = get_repo()
    repo.git.pull(remote, branch)


@task
def branch(c):
    """查看分支"""
    repo = get_repo()
    logger.info(repo.git.branch())


@task
def checkout(c, name):
    """切换分支"""
    repo = get_repo()
    repo.git.checkout(name)


@task
def log(c, n=10):
    """查看提交记录"""
    repo = get_repo()
    logger.info(repo.git.log(f"-{n}", "--oneline"))

git_ns = Collection("git")
git_ns.add_task(status)
git_ns.add_task(add)
git_ns.add_task(commit)
git_ns.add_task(push)
git_ns.add_task(pull)
git_ns.add_task(branch)
git_ns.add_task(checkout)
git_ns.add_task(log)
git_ns.add_task(ginit)


# =========================
# 命名空间注册到根集合
# =========================

ns = Collection()
ns.add_collection(dev)
ns.add_collection(db)
# ns.add_collection(code)
ns.add_collection(pro)
ns.add_collection(docker)
ns.add_collection(git_ns)


# =========================
# 创建 app 辅助函数
# =========================

def create_app(c, name, drf=False):
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
    
    logger.info("\n完成")
    logger.info(f" App '{name}' 已成功创建")
    logger.info(f"已开启自动发现，该 App 已自动加入 INSTALLED_APPS")


def generate_drf(app_path, name):
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
    \"\"\"{model_class} 序列化器\"\"\"
    class Meta:
        model = {model_class}
        fields = '__all__'
""")
    
    write_file(app_path, "views.py", f"""from rest_framework import viewsets, permissions
from drf_spectacular.utils import extend_schema, extend_schema_view
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
class {model_class}ViewSet(viewsets.ModelViewSet):
    \"\"\"
    {name} 模块接口
    
    提供 {model_class} 模型的增删改查标准 API。
    \"\"\"
    queryset = {model_class}.objects.all()
    serializer_class = {model_class}Serializer
    permission_classes = [permissions.IsAuthenticated]
""")
    
    write_file(app_path, "urls.py", f"""from rest_framework.routers import DefaultRouter
from .views import {model_class}ViewSet

router = DefaultRouter()
router.register(r'', {model_class}ViewSet, basename='{name}')

urlpatterns = router.urls
""")
    
    write_file(app_path, "admin.py", f"""from django.contrib import admin
from .models import {model_class}

admin.site.register({model_class})
""")
    
    logger.info("DRF 模板生成完成")


def write_file(app_path, filename, content):
    file_path = os.path.join(app_path, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
