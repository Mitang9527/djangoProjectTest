"""Celery 应用定义（独立通知服务）。

worker 启动命令：celery -A notice_service worker -l info -Q notice.send
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "notice_service.settings")

app = Celery("notice_service")
# 使用 Django settings 中 CELERY_ 前缀的配置
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# ---------------------------------------------------------------------------
# Worker 心跳：消费/等待队列期间每 5 秒打印一次日志，确认进程存活。
# 用后台守护线程实现；仅在处理任务「空闲」时打印，避免任务执行中刷屏。
# worker_init / worker_process_init 都会调用，但每个进程只启一个线程。
# ---------------------------------------------------------------------------
import logging as _hb_logging
import threading as _hb_threading
import time as _hb_time

from celery import signals as _celery_signals

_heartbeat_logger = _hb_logging.getLogger("notice_service.heartbeat")
_heartbeat_lock = _hb_threading.Lock()
_heartbeat_started = False
_active_tasks = 0
_active_tasks_lock = _hb_threading.Lock()


def _start_heartbeat(interval: int = 5, queue: str = "notice.send"):
    """启动 worker 心跳线程（空闲时每 interval 秒打印一次等待日志）。"""
    global _heartbeat_started
    with _heartbeat_lock:
        if _heartbeat_started:
            return
        _heartbeat_started = True

    def _beat():
        while True:
            _hb_time.sleep(interval)
            with _active_tasks_lock:
                busy = _active_tasks > 0
            if not busy:
                _heartbeat_logger.info(
                    "[NOTICE] worker 心跳: 正在等待消费队列 %s (idle)", queue
                )

    _hb_threading.Thread(
        target=_beat, name="notice-heartbeat", daemon=True
    ).start()


@_celery_signals.task_prerun.connect
def _on_task_prerun(sender, task_id, task, args, kwargs, **opts):
    """任务开始执行 -> 标记忙碌，心跳暂停打印。"""
    global _active_tasks
    with _active_tasks_lock:
        _active_tasks += 1


@_celery_signals.task_postrun.connect
def _on_task_postrun(sender, task_id, task, args, kwargs, state, **opts):
    """任务结束 -> 解除忙碌，心跳恢复打印。"""
    global _active_tasks
    with _active_tasks_lock:
        _active_tasks = max(0, _active_tasks - 1)


# 服务启动横幅: worker 启动时标识当前是哪一个 Celery worker。
# 仅在 worker 进程触发, 不影响 web 进程 (Daphne/runserver 不会触发这两个信号)。
try:
    from framework.log_utils.service_banner import emit_startup_banner
except Exception:  # pragma: no cover - framework 不可用时降级
    def emit_startup_banner(key, extra=None):
        print(f"\n=== SERVICE START: {key} ===\n", flush=True)


@_celery_signals.worker_init.connect
def _on_celery_master_init(sender, **kwargs):
    os.environ.setdefault("WORKER_TYPE", "celery")
    emit_startup_banner("celery_notice", extra=f"host={getattr(sender, 'hostname', '?')}")
    _start_heartbeat()


@_celery_signals.worker_process_init.connect
def _on_celery_worker_init(sender, **kwargs):
    os.environ.setdefault("WORKER_TYPE", "celery")
    emit_startup_banner("celery_notice", extra=f"host={getattr(sender, 'hostname', '?')}")
    _start_heartbeat()


@app.task(bind=True)
def debug_task(self):
    print(f"debug_task run on {self.request.id}")
