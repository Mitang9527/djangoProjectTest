import os
import shutil
from loguru import logger


def del_file(path):
    """删除目录下的文件"""
    list_path = os.listdir(path)
    for i in list_path:
        c_path = os.path.join(path, i)
        if os.path.isdir(c_path):
            del_file(c_path)
        else:
            os.remove(c_path)


def del_sub_dir(path):
    list_path = os.listdir(path)
    for i in list_path:
        c_path = os.path.join(path, i)
        if os.path.isdir(c_path):
            shutil.rmtree(c_path)

#删除多个目录下的文件
def delete_files_in_directory(directories):
    """
    删除多个目录下的所有文件和子目录。

    参数:
    - directories: 包含多个目录路径的列表或元组。
    """
    for directory in directories:
        # 确保目录存在
        if not os.path.exists(directory):
            logger.info(f"目录 '{directory}' 不存在。")
            continue

        # 遍历目录中的所有文件和子目录
        for root, dirs, files in os.walk(directory):
            # 删除文件
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    os.remove(file_path)
                    logger.info(f"已删除文件: {file_path}")
                except Exception as e:
                    logger.error(f"删除文件 '{file_path}' 时出错: {str(e)}")

            # 删除子目录
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    shutil.rmtree(dir_path)
                    logger.info(f"已删除目录及其内容: {dir_path}")
                except Exception as e:
                    logger.error(f"删除目录 '{dir_path}' 及其内容时出错: {str(e)}")

        logger.info(f"已完成删除目录 '{directory}' 下的所有文件和子目录。")


#删除给定的目录及其所有内容
def remove_directories(directories):

    for directory in directories:
        if os.path.exists(directory):
            try:
                shutil.rmtree(directory)  # 删除目录及其所有内容
                logger.info(f"已删除目录: {directory}")
            except OSError as e:
                logger.error(f"删除目录 {directory} 失败: {e}")

