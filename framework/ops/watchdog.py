"""文件系统监控管理器。

基于 watchdog 监听指定目录的文件变化，将底层事件与上层业务逻辑解耦，供
热加载/文件变更触发等场景使用。
"""
import os
import time
import queue
import threading

from loguru import logger
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler


class FileMonitorManager:
    """文件系统监控管理器：将底层监控与上层业务逻辑彻底解耦"""

    def __init__(self, watch_path, patterns=None):
        self.watch_path = watch_path
        self.patterns = patterns or ["*"]  # 默认监控所有文件
        self.event_queue = queue.Queue()
        self.observer = None
        self.worker_thread = None

        # 绑定事件处理器
        self.handler = _InternalHandler(self.event_queue)

    # ================= 业务逻辑层（按需扩展）=================
    @staticmethod
    def compile_project(file_path):
        logger.info(f"🔨 [编译模块] 正在重新编译项目，触发源: {file_path}")
        time.sleep(0.5)  # 模拟耗时操作

    @staticmethod
    def sync_files(file_path):
        logger.info(f"☁️  [同步模块] 正在将变更同步至云端: {file_path}")
        time.sleep(0.3)

    @staticmethod
    def send_notification(message):
        logger.info(f"📢 [通知模块] 推送消息: {message}")

    # ================= 核心调度层 =================
    def _worker(self):
        """后台工作线程：从队列取出事件并分发到对应的业务方法"""
        while True:
            try:
                event = self.event_queue.get()
                if event is None: break  # 收到退出信号

                # 根据事件类型调用不同的业务方法
                if event.event_type == 'modified':
                    self.compile_project(event.src_path)
                    self.send_notification(f"检测到修改: {os.path.basename(event.src_path)}")

                elif event.event_type == 'created':
                    self.sync_files(event.src_path)
                    self.send_notification(f"新增文件: {os.path.basename(event.src_path)}")

                self.event_queue.task_done()
            except Exception as e:
                logger.error(f"[Worker] 处理异常: {e}")

    def start(self):
        """一键启动监控系统"""
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

        self.observer = Observer()
        self.observer.schedule(self.handler, self.watch_path, recursive=True)
        self.observer.start()

        logger.info(f"🚀 哨兵已就位，正在监控: {os.path.abspath(self.watch_path)}")

    def stop(self):
        """优雅停止并清理资源"""
        logger.info("⏹️ 收到中断信号，正在优雅退出...")
        if self.observer:
            self.observer.stop()
            self.observer.join()

        self.event_queue.put(None)  # 发送毒丸(Poison Pill)信号
        if self.worker_thread:
            self.worker_thread.join()

        logger.success("✅ 所有线程已安全退出。")


# ================= 内部防抖处理器 =================
class _InternalHandler(PatternMatchingEventHandler):
    def __init__(self, event_queue):
        super().__init__(patterns=["*.py", "*.txt"], ignore_patterns=[".*", "*.tmp"])
        self.event_queue = event_queue
        self.last_event_time = {}

    def handle_event(self, event):
        if event.is_directory: return
        current_time = time.time()
        last_time = self.last_event_time.get(event.src_path, 0)
        if current_time - last_time < 1.0: return  # 1秒内防抖
        self.last_event_time[event.src_path] = current_time
        self.event_queue.put(event)

    def on_modified(self, event):
        self.handle_event(event)

    def on_created(self, event):
        self.handle_event(event)


if __name__ == "__main__":
    manager = FileMonitorManager(watch_path=".")
    manager.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        manager.stop()