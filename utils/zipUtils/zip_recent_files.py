import os
import time
import zipfile
import shutil

from loguru import logger


def zip_and_delete_subfolders(parent_path, days=7):
    """
    将指定文件夹中超过 N 天未修改的子文件夹打包并删除源文件夹。
    """
    if not os.path.exists(parent_path):
        logger.error(f"❌ 目录不存在: {parent_path}")
        return

    logger.info(f"🔍 正在扫描目录: {parent_path}，处理 {days} 天前的文件")
    time_threshold = time.time() - (days * 24 * 60 * 60)

    processed_count = 0

    try:
        # 1. 遍历父目录下的所有内容
        for item in os.listdir(parent_path):
            item_path = os.path.join(parent_path, item)

            if os.path.isdir(item_path):
                # 使用 mtime (最后修改时间) 通常比 ctime (创建时间) 更能反映文件活跃度
                folder_mtime = os.path.getmtime(item_path)
                
                if folder_mtime <= time_threshold:
                    zip_path = f"{item_path}.zip"
                    try:
                        logger.info(f"📦 正在打包: {item}")
                        # 检查 zip 文件是否已存在，避免覆盖
                        if os.path.exists(zip_path):
                            logger.warning(f"⚠️ 压缩包已存在，将跳过: {zip_path}")
                            continue

                        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_LZMA, compresslevel=6) as zipf:
                            for root, dirs, files in os.walk(item_path):
                                for file in files:
                                    file_path = os.path.join(root, file)
                                    arcname = os.path.relpath(file_path, item_path)
                                    zipf.write(file_path, arcname)

                        # 校验压缩包是否损坏
                        with zipfile.ZipFile(zip_path, 'r') as zipf:
                            if zipf.testzip() is not None:
                                raise zipfile.BadZipFile("压缩包校验失败")

                        # 删除整个目录树
                        shutil.rmtree(item_path)
                        logger.info(f"✅ 成功: {item} -> {item}.zip 并已删除原文件夹")
                        processed_count += 1

                    except Exception as e:
                        logger.error(f"❌ 处理 {item} 失败: {e}")
                        # 如果压缩失败但创建了残留文件，清理它
                        if os.path.exists(zip_path):
                            os.remove(zip_path)
                else:
                    logger.debug(f"⏭️ 跳过较新的文件夹: {item}")
    except Exception as e:
        logger.critical(f"扫描目录时发生严重错误: {e}")

    logger.info(f"🎉 任务结束，共处理了 {processed_count} 个文件夹。")