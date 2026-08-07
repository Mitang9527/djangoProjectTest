import time
import subprocess
import platform
import queue
import threading
import traceback
from typing import List, Optional

from loguru import logger


def run_with_live_output(
    command: List[str],
    timeout: Optional[float] = None,
    encoding: Optional[str] = None,
) -> int:
    """
    【核心改进】双线程读取 stdout/stderr 字节流，防止死锁，并实时推送到 GUI
    """
    start_time = time.time()

    startupinfo = None
    creationflags = 0
    if platform.system() == "Windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NO_WINDOW

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            startupinfo=startupinfo,
            creationflags=creationflags,
            encoding=encoding,
        )
    except FileNotFoundError:
        logger.error(f"Command or file not found: {command[0]}")
        return -1
    except Exception as e:
        logger.critical(f"Failed to start process: {e}")
        return -1

    log_queue = queue.Queue(maxsize=1000)

    def reader_thread(stream, prefix: str = ""):
        try:
            for line in iter(stream.readline, ""):
                if line:
                    log_queue.put((prefix, line.rstrip("\n\r")))
            stream.close()
        except Exception as e:
            logger.error(f"Error reading subprocess output: {e}")
        finally:
            log_queue.put((None, None))

    t_out = threading.Thread(
        target=reader_thread, args=(process.stdout, ""), daemon=True
    )
    t_err = threading.Thread(
        target=reader_thread, args=(process.stderr, "[ERR] "), daemon=True
    )
    t_out.start()
    t_err.start()

    streams_to_read = 2

    while streams_to_read > 0:
        try:
            item = log_queue.get(timeout=0.1)

            if item[0] is None and item[1] is None:
                streams_to_read -= 1
                continue

            prefix, line_content = item
            logger.info(f"{prefix}{line_content}")

        except queue.Empty:
            if process.poll() is not None:
                remaining_timeout = (
                    timeout - (time.time() - start_time) if timeout else None
                )
                if remaining_timeout and remaining_timeout <= 0:
                    break
                continue

            if timeout is not None and (time.time() - start_time) > timeout:
                logger.error(
                    f"Execution timeout ({timeout}s), terminating..."
                )
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                return -1
        except Exception as e:
            logger.error(f"处理子进程输出时出错: {e}")
            traceback.print_exc()

    t_out.join()
    t_err.join()

    returncode = process.wait()
    logger.info(
        f"Command execution completed, return code: {returncode}"
    )
    return returncode