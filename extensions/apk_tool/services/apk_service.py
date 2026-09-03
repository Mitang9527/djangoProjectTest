"""
APK 构建核心服务 — 将 AutoApkTool 的核心逻辑适配为 Django Web 服务
"""
import os
import json
import re
import time
import shutil
import subprocess
import platform
import traceback
import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any

from loguru import logger
from ruamel.yaml import YAML

from .constants import (
    APKTOOL_JAR, ZIPALIGN_EXE, APKSIGNER_BAT, KEYSTORE_CONFIG,
    VALID_PACKAGE_NAMES, ANDROID_NAMESPACE,
    get_task_workdir, get_task_output_dir, get_decompile_dir,
    get_slclient_json_path, get_manifest_path, get_yml_path,
    get_input_json_path, INPUT_JSON_DEFAULT, TERMINAL_CONFIGS_DIR,
)


def run_command(command: List[str], timeout: Optional[float] = None) -> Dict[str, Any]:
    """
    执行子进程命令，收集 stdout/stderr 输出
    返回 {'returncode': int, 'stdout': str, 'stderr': str, 'logs': List[str]}
    """
    logs = []
    cmd_str = ' '.join(str(c) for c in command)
    logger.info(f"[APK] 执行命令: {cmd_str}")

    startupinfo = None
    creationflags = 0
    if platform.system() == 'Windows':
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
        )
    except FileNotFoundError as e:
        logger.error(f"[APK] 命令或文件未找到: {command[0]} — {e}")
        logs.append(f'[ERROR] 命令或文件未找到: {command[0]}')
        return {'returncode': -1, 'stdout': '', 'stderr': str(e), 'logs': logs}
    except Exception as e:
        logger.error(f"[APK] 启动进程失败: {e}")
        logs.append(f'[CRITICAL] 启动进程失败: {e}')
        return {'returncode': -1, 'stdout': '', 'stderr': str(e), 'logs': logs}

    stdout_lines = []
    stderr_lines = []

    try:
        stdout, stderr = process.communicate(timeout=timeout)
        if stdout:
            stdout_lines.extend(stdout.splitlines())
            logs.extend(stdout.splitlines())
        if stderr:
            stderr_lines.extend(stderr.splitlines())
            for line in stderr.splitlines():
                logs.append(f'[ERR] {line}')
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        logger.warning(f"[APK] 命令执行超时 ({timeout}s)，已终止: {cmd_str}")
        logs.append(f'[TIMEOUT] 执行超时 ({timeout}s)，已终止')
        return {
            'returncode': -1,
            'stdout': '\n'.join(stdout_lines),
            'stderr': '\n'.join(stderr_lines),
            'logs': logs,
        }

    returncode = process.returncode
    logs.append(f'[Result] 命令执行完成，退出码: {returncode}')
    if returncode != 0:
        logger.warning(f"[APK] 命令退出码非零 ({returncode}): {cmd_str}")
    else:
        logger.success(f"[APK] 命令执行成功: {cmd_str}")

    return {
        'returncode': returncode,
        'stdout': '\n'.join(stdout_lines),
        'stderr': '\n'.join(stderr_lines),
        'logs': logs,
    }


def decompile_apk(task_id: str, apk_type: str = 'custom', custom_apk_path: Optional[str] = None) -> Dict[str, Any]:
    """
    反编译 APK（仅支持自定义上传 APK；内置模板包 DEF_APK 已移除）
    apk_type: 'custom'
    """
    logger.info(f"[APK] 开始反编译 — task_id={task_id}, apk_type={apk_type}")
    workdir = get_task_workdir(task_id)
    decompile_dir = get_decompile_dir(task_id)

    # 清理旧的反编译目录
    if decompile_dir.exists():
        shutil.rmtree(decompile_dir, ignore_errors=True)
        logger.debug(f"[APK] 清理旧反编译目录: {decompile_dir}")

    # 确定 APK 源文件（仅自定义上传路径）
    apk_source = Path(custom_apk_path) if (apk_type == 'custom' and custom_apk_path) else None

    if not apk_source or not apk_source.exists():
        logger.error(f"[APK] APK 文件不存在: {apk_source}")
        return {
            'success': False,
            'message': f'APK 文件不存在: {apk_source}',
            'logs': ['[ERROR] APK 文件不存在'],
        }

    logger.info(f"[APK] APK 源文件: {apk_source}")

    # 执行反编译
    command = [
        'java', '-jar', str(APKTOOL_JAR),
        'd', str(apk_source),
        '-s',  # 不反编译 dex，仅资源
        '-o', str(decompile_dir),
    ]

    result = run_command(command, timeout=120)

    if result['returncode'] != 0:
        logger.error(f"[APK] 反编译失败 — task_id={task_id}, 退出码={result['returncode']}")
        return {
            'success': False,
            'message': '反编译失败',
            'logs': result['logs'],
        }

    # 校验 package 名
    manifest_path = get_manifest_path(task_id)
    package_name = get_package_from_manifest(manifest_path)
    logger.info(f"[APK] 提取包名: {package_name}")

    if package_name not in VALID_PACKAGE_NAMES:
        # 非目标 APK，清理并报错
        if decompile_dir.exists():
            shutil.rmtree(decompile_dir, ignore_errors=True)
        logger.error(f"[APK] 非目标 APK (package: {package_name})，仅支持: {VALID_PACKAGE_NAMES}")
        return {
            'success': False,
            'message': f'非目标 APK (package: {package_name})，仅支持: {VALID_PACKAGE_NAMES}',
            'logs': result['logs'] + [f'[ERROR] 非目标 APK: {package_name}'],
        }

    # 加载 slclient.json 配置
    slclient_path = get_slclient_json_path(task_id)
    slclient_data = {}
    if slclient_path.exists():
        with open(slclient_path, 'r', encoding='utf-8') as f:
            slclient_data = json.load(f)
        logger.debug(f"[APK] 加载 slclient.json: {slclient_path}")

    # 复制默认 input.json 到工作区
    input_work = get_input_json_path(task_id)
    if INPUT_JSON_DEFAULT.exists() and not input_work.exists():
        shutil.copy2(INPUT_JSON_DEFAULT, input_work)
        logger.debug(f"[APK] 复制默认 input.json → {input_work}")

    logger.success(f"[APK] 反编译成功 — task_id={task_id}, package={package_name}")
    return {
        'success': True,
        'message': f'反编译成功 (package: {package_name})',
        'package_name': package_name,
        'slclient_data': slclient_data,
        'logs': result['logs'],
    }


def build_apk(task_id: str, model_name: str = '', launcher_module: str = 'none',
              recorder_enable: bool = False) -> Dict[str, Any]:
    """
    构建签名 APK — 反编译 → 配置注入 → 重打包 → 对齐 → 签名
    """
    logger.info(f"[APK] 开始构建 — task_id={task_id}, model={model_name}, launcher={launcher_module}, recorder={recorder_enable}")
    decompile_dir = get_decompile_dir(task_id)
    workdir = get_task_workdir(task_id)
    output_dir = get_task_output_dir(task_id)

    if not decompile_dir.exists():
        logger.error(f"[APK] 构建失败 — 反编译目录不存在: {decompile_dir}")
        return {'success': False, 'message': '请先反编译 APK', 'logs': []}

    # 1. 复制 input.json 到 APK 内部 assets
    assets_slclient_dir = decompile_dir / 'assets' / 'slclient'
    assets_slclient_dir.mkdir(parents=True, exist_ok=True)
    input_src = get_input_json_path(task_id)
    input_dst = assets_slclient_dir / 'input.json'
    if input_src.exists():
        shutil.copy2(input_src, input_dst)
        logger.debug(f"[APK] 复制 input.json → {input_dst}")

    # 2. 更新 launcher 配置
    slclient_path = get_slclient_json_path(task_id)
    if slclient_path.exists():
        with open(slclient_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 设置 launcherModule
        if launcher_module and launcher_module != 'none':
            data.setdefault('ui', {})['launcherModule'] = launcher_module
            logger.debug(f"[APK] 设置 launcherModule={launcher_module}")
        elif launcher_module == 'none':
            if 'ui' in data and 'launcherModule' in data['ui']:
                del data['ui']['launcherModule']
                logger.debug("[APK] 移除 launcherModule")
        # 设置 recorder enable
        data.setdefault('recorder', {})['enable'] = recorder_enable
        # 设置设备名称
        if model_name:
            data.setdefault('device', {})['name'] = model_name
        with open(slclient_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.debug(f"[APK] 更新 slclient.json")

    # 3. 修改 AndroidManifest (Launcher)
    manifest_path = get_manifest_path(task_id)
    if manifest_path.exists():
        modify_manifest(manifest_path, is_enabled=(launcher_module != 'none'))
        logger.debug(f"[APK] 修改 AndroidManifest — launcher={launcher_module != 'none'}")

    # 4. 更新版本号
    yml_path = get_yml_path(task_id)
    if yml_path.exists():
        update_version_info(yml_path)
        logger.debug(f"[APK] 更新版本号")

    # 5. 重打包
    logger.info("[APK] 步骤 5/9 — 重打包")
    unsigned_unaligned = workdir / 'app-unsigned-unaligned.apk'
    command = [
        'java', '-jar', str(APKTOOL_JAR),
        'b', str(decompile_dir),
        '-o', str(unsigned_unaligned),
    ]
    result = run_command(command, timeout=180)
    if result['returncode'] != 0:
        logger.error(f"[APK] 重打包失败 — task_id={task_id}")
        return {'success': False, 'message': '重打包失败', 'logs': result['logs']}

    # 6. 对齐
    logger.info("[APK] 步骤 6/9 — zipalign 对齐")
    unsigned_apk = workdir / 'app-unsigned.apk'
    command = [ZIPALIGN_EXE, '-v', '-p', '4', str(unsigned_unaligned), str(unsigned_apk)]
    result = run_command(command, timeout=60)
    if result['returncode'] != 0:
        logger.error(f"[APK] zipalign 对齐失败 — task_id={task_id}")
        return {'success': False, 'message': 'APK 对齐失败', 'logs': result['logs']}

    # 7. 确定签名证书
    keystore_cfg = KEYSTORE_CONFIG.get(launcher_module, KEYSTORE_CONFIG['small'])
    logger.info(f"[APK] 步骤 7/9 — 使用签名证书: {keystore_cfg['path']}")

    # 8. 生成产物文件名
    yml_data = load_yml(yml_path)
    version_name = ''
    if yml_data:
        version_name = yml_data.get('versionInfo', {}).get('versionName', '')

    prefix = build_apk_name_prefix(recorder_enable, launcher_module)
    final_name = f'{prefix}_{version_name}_{model_name}.apk' if model_name else f'{prefix}_{version_name}.apk'
    final_apk = output_dir / final_name
    logger.info(f"[APK] 步骤 8/9 — 产物文件名: {final_name}")

    # 9. 签名
    logger.info("[APK] 步骤 9/9 — apksigner 签名")
    command = [
        APKSIGNER_BAT, 'sign',
        '--ks', keystore_cfg['path'],
        '--ks-pass', f'pass:{keystore_cfg["password"]}',
        '--out', str(final_apk),
        str(unsigned_apk),
    ]
    result = run_command(command, timeout=60)
    if result['returncode'] != 0:
        logger.error(f"[APK] 签名失败 — task_id={task_id}")
        return {'success': False, 'message': 'APK 签名失败', 'logs': result['logs']}

    # 10. 清理临时文件
    for tmp_file in [unsigned_unaligned, unsigned_apk]:
        if tmp_file.exists():
            try:
                os.remove(tmp_file)
            except Exception:
                pass
    logger.debug("[APK] 清理临时文件完成")

    # 11. 还原 input.json（从默认复制回去）
    if INPUT_JSON_DEFAULT.exists():
        shutil.copy2(INPUT_JSON_DEFAULT, input_src)

    # 构建产物相对路径（用于 URL 下载）
    from django.conf import settings as django_settings
    relative_path = str(final_apk.relative_to(Path(django_settings.MEDIA_ROOT))) if final_apk.exists() else ''

    logger.success(f"[APK] 构建成功 — task_id={task_id}, 产物={final_name}, 大小={final_apk.stat().st_size if final_apk.exists() else 0}")
    return {
        'success': True,
        'message': f'APK 构建成功: {final_name}',
        'apk_name': final_name,
        'apk_path': str(final_apk),
        'apk_relative_path': relative_path,
        'apk_size': final_apk.stat().st_size if final_apk.exists() else 0,
        'logs': result['logs'] + [f'[OK] 产物: {final_name}'],
    }


def build_apk_name_prefix(recorder_enable: bool, launcher_module: str) -> str:
    """根据配置生成 APK 文件名前缀"""
    if not launcher_module or launcher_module == 'none':
        return 'RSAPP' if recorder_enable else 'ASAPP'

    prefix_map = {
        'large': 'BSAPP',
        'middle': 'MSAPP',
        'small': 'SSAPP',
    }
    base = prefix_map.get(launcher_module, 'NSAPP')
    return f'R{base}' if recorder_enable else base


# ==================== Manifest 操作 ====================


def android_attr(name: str) -> str:
    return f'{{{ANDROID_NAMESPACE}}}{name}'


def get_package_from_manifest(manifest_path: Path) -> Optional[str]:
    """从 AndroidManifest.xml 提取 package 名"""
    try:
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        return root.get('package')
    except Exception as e:
        logger.warning(f"[APK] 解析 Manifest 失败: {e}")
        return None


def modify_manifest(manifest_path: Path, is_enabled: bool) -> bool:
    """修改 AndroidManifest.xml 的 HOME category，控制 Launcher"""
    if not manifest_path.exists():
        logger.warning(f"[APK] Manifest 不存在: {manifest_path}")
        return False

    try:
        ET.register_namespace('android', ANDROID_NAMESPACE)
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        application = root.find('application')
        if application is None:
            logger.warning("[APK] Manifest 中未找到 <application> 节点")
            return False

        candidate_activity_names = [
            'com.shanli.pocstar.SplashActivity',
            'com.shanlitech.ptt.SplashActivity',
            'com.shanlitech.noscreen.SplashActivity',
        ]

        target_activity = None
        for activity in application.findall('activity'):
            name = activity.attrib.get(android_attr('name'), '')
            if name in candidate_activity_names:
                target_activity = activity
                break

        if target_activity is None:
            logger.warning("[APK] 未找到目标 SplashActivity")
            return False

        intent_filter = target_activity.find('intent-filter')
        if intent_filter is None:
            logger.warning("[APK] SplashActivity 无 intent-filter")
            return False

        home_category_elem = None
        for category in intent_filter.findall('category'):
            if category.attrib.get(android_attr('name')) == 'android.intent.category.HOME':
                home_category_elem = category
                break

        if is_enabled and home_category_elem is None:
            ET.SubElement(intent_filter, 'category',
                          {android_attr('name'): 'android.intent.category.HOME'})
            write_pretty_xml(tree, manifest_path)
            logger.debug("[APK] Manifest: 添加 HOME category")
        elif not is_enabled and home_category_elem is not None:
            intent_filter.remove(home_category_elem)
            write_pretty_xml(tree, manifest_path)
            logger.debug("[APK] Manifest: 移除 HOME category")

        return True
    except Exception as e:
        logger.error(f"[APK] 修改 Manifest 异常: {e}")
        return False


def write_pretty_xml(tree, file_path: Path):
    """美化 XML 输出"""
    rough_string = ET.tostring(tree.getroot(), encoding='utf-8')
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent='    ')
    pretty_xml = '\n'.join([line for line in pretty_xml.split('\n') if line.strip()])
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(pretty_xml)


# ==================== YAML 操作 ====================


def load_yml(yml_path: Path) -> Optional[Dict]:
    yaml = YAML()
    if not yml_path.exists():
        return None
    try:
        with open(yml_path, 'r', encoding='utf-8') as f:
            return yaml.load(f)
    except Exception as e:
        logger.warning(f"[APK] 加载 YML 失败: {yml_path} — {e}")
        return None


def update_version_info(yml_path: Path) -> None:
    """自动递增 versionCode 并更新 versionName"""
    yaml = YAML()
    data = load_yml(yml_path)
    if not data:
        logger.warning("[APK] update_version_info: YML 数据为空")
        return

    version_info = data.get('versionInfo', {})
    old_code = version_info.get('versionCode')
    old_name = version_info.get('versionName')

    if not old_code or not old_name:
        logger.warning("[APK] versionCode/versionName 缺失，跳过更新")
        return

    new_code = int(old_code) + 1
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    pattern = r'(POCSTARS_)\d+$'
    new_name = re.sub(pattern, rf'\1{timestamp}', old_name)
    if new_name == old_name:
        new_name = f'{old_name}_{timestamp}'

    version_info['versionCode'] = new_code
    version_info['versionName'] = new_name
    logger.info(f"[APK] 版本更新: code={old_code}→{new_code}, name={old_name}→{new_name}")

    with open(yml_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f)


def get_version_info(yml_path: Path) -> tuple:
    data = load_yml(yml_path)
    if data:
        version_info = data.get('versionInfo', {})
        return version_info.get('versionCode'), version_info.get('versionName')
    return None, None


# 导入 settings 用于 build_apk 中的路径计算
import django
