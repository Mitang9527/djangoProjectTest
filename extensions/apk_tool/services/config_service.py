"""
配置管理服务 — slclient.json / input.json 等配置的读写操作
"""
import json
import os
import shutil
from pathlib import Path
from typing import List, Any, Optional, Dict

from loguru import logger

from .constants import (
    get_slclient_json_path, get_input_json_path,
    LOGIN_TYPE_MAPPING, MAP_CONFIG_TEMPLATES,
    INPUT_JSON_DEFAULT, TERMINAL_CONFIGS_DIR,
    get_decompile_dir,
)


def load_slclient_json(task_id: str) -> Dict:
    """加载 slclient.json"""
    path = get_slclient_json_path(task_id)
    if not path.exists():
        logger.debug(f"[APK Config] slclient.json 不存在: {path}")
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if content:
                data = json.loads(content)
                logger.debug(f"[APK Config] 加载 slclient.json — task_id={task_id}, keys={list(data.keys())}")
                return data
    except Exception as e:
        logger.warning(f"[APK Config] 解析 slclient.json 异常 — task_id={task_id}: {e}")
    return {}


def save_slclient_json(task_id: str, data: Dict, indent: int = 4) -> bool:
    """保存 slclient.json"""
    path = get_slclient_json_path(task_id)
    if not path.exists():
        logger.warning(f"[APK Config] slclient.json 路径不存在，无法保存: {path}")
        return False
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        logger.debug(f"[APK Config] 保存 slclient.json — task_id={task_id}")
        return True
    except Exception as e:
        logger.error(f"[APK Config] 保存 slclient.json 异常 — task_id={task_id}: {e}")
        return False


def get_json_field(file_path: Path, field_path: List[str]) -> Any:
    """按路径读取 JSON 字段"""
    try:
        if not file_path.exists():
            return None
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        temp_data = data
        for key in field_path:
            if isinstance(temp_data, dict):
                temp_data = temp_data.get(key)
            else:
                return None
        return temp_data
    except Exception as e:
        logger.warning(f"[APK Config] 读取 JSON 字段异常 — {file_path}.{field_path}: {e}")
        return None


def set_json_field(file_path: Path, field_path: List[str], new_value: Any) -> bool:
    """按路径写入 JSON 字段"""
    try:
        if not file_path.exists():
            return False
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        temp_data = data
        for key in field_path[:-1]:
            if isinstance(temp_data, dict) and key in temp_data:
                temp_data = temp_data[key]
            else:
                return False
        target_key = field_path[-1]
        if isinstance(temp_data, dict):
            temp_data[target_key] = new_value
        else:
            return False
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.debug(f"[APK Config] 设置 JSON 字段 — {file_path}.{field_path}={new_value}")
        return True
    except Exception as e:
        logger.warning(f"[APK Config] 设置 JSON 字段异常: {e}")
        return False


# ==================== slclient.json 配置更新 ====================


def update_login_type(task_id: str, login_type_ui: str) -> bool:
    """更新登录方式"""
    path = get_slclient_json_path(task_id)
    if not path.exists():
        return False

    login_mode_val = 'account'
    for storage_key, names_dict in LOGIN_TYPE_MAPPING.items():
        if names_dict.get('zh') == login_type_ui or names_dict.get('en') == login_type_ui:
            login_mode_val = storage_key
            break

    logger.info(f"[APK Config] 更新登录方式 — task_id={task_id}, login_type={login_mode_val}")
    return set_json_field(path, ['profile', 'login_mode'], login_mode_val)


def update_map_type(task_id: str, map_source_key: str) -> bool:
    """更新地图源配置"""
    path = get_slclient_json_path(task_id)
    if not path.exists():
        return False

    try:
        data = load_slclient_json(task_id)
        template_config = MAP_CONFIG_TEMPLATES.get(map_source_key)
        if not template_config:
            logger.warning(f"[APK Config] 地图模板不存在: {map_source_key}")
            return False
        data.setdefault('lbs', {}).update(template_config['config'])
        logger.info(f"[APK Config] 更新地图源 — task_id={task_id}, map_type={map_source_key}")
        return save_slclient_json(task_id, data, indent=4)
    except Exception as e:
        logger.error(f"[APK Config] 更新地图源异常 — task_id={task_id}: {e}")
        return False


def update_profile(task_id: str, dns: List[str], context: str,
                   upgrade_url: Optional[str] = None, env_key: Optional[str] = None) -> bool:
    """更新服务器节点配置"""
    path = get_slclient_json_path(task_id)
    if not path.exists():
        return False

    try:
        data = load_slclient_json(task_id)
        profile = data.setdefault('profile', {})
        profile['dns'] = dns
        profile['context'] = context
        if upgrade_url is not None:
            profile['upgrade_url'] = upgrade_url
        if env_key is not None:
            profile['env_key'] = env_key
        logger.info(f"[APK Config] 更新服务器配置 — task_id={task_id}, env_key={env_key}")
        return save_slclient_json(task_id, data, indent=4)
    except Exception as e:
        logger.error(f"[APK Config] 更新服务器配置异常 — task_id={task_id}: {e}")
        return False


def set_sound_codec(task_id: str, codec: str) -> bool:
    """设置音频编码"""
    logger.info(f"[APK Config] 设置音频编码 — task_id={task_id}, codec={codec}")
    path = get_slclient_json_path(task_id)
    if not path.exists():
        return False
    try:
        data = load_slclient_json(task_id)
        data.setdefault('sound', {})['codec'] = codec
        return save_slclient_json(task_id, data, indent=4)
    except Exception as e:
        logger.error(f"[APK Config] 设置音频编码异常: {e}")
        return False


def set_dsp_provider(task_id: str, provider: str) -> bool:
    """设置 DSP 提供商"""
    logger.info(f"[APK Config] 设置 DSP — task_id={task_id}, provider={provider}")
    path = get_slclient_json_path(task_id)
    if not path.exists():
        return False
    try:
        data = load_slclient_json(task_id)
        data.setdefault('dsp', {})['provider'] = provider
        return save_slclient_json(task_id, data, indent=4)
    except Exception as e:
        logger.error(f"[APK Config] 设置 DSP 异常: {e}")
        return False


def set_play_stream(task_id: str, play_stream: str) -> bool:
    """设置播放流"""
    path = get_slclient_json_path(task_id)
    if not path.exists():
        return False
    try:
        data = load_slclient_json(task_id)
        data.setdefault('dsp', {})['play_stream'] = play_stream
        return save_slclient_json(task_id, data, indent=4)
    except Exception as e:
        logger.error(f"[APK Config] 设置播放流异常: {e}")
        return False


def set_record_stream(task_id: str, record_stream: str) -> bool:
    """设置录音流"""
    path = get_slclient_json_path(task_id)
    if not path.exists():
        return False
    try:
        data = load_slclient_json(task_id)
        data.setdefault('dsp', {})['record_stream'] = record_stream
        return save_slclient_json(task_id, data, indent=4)
    except Exception as e:
        logger.error(f"[APK Config] 设置录音流异常: {e}")
        return False


def set_tone_enabled(task_id: str, is_enabled: bool) -> bool:
    """设置提示音开关"""
    logger.info(f"[APK Config] 设置提示音 — task_id={task_id}, enabled={is_enabled}")
    path = get_slclient_json_path(task_id)
    if not path.exists():
        return False
    try:
        data = load_slclient_json(task_id)
        data.setdefault('sound', {})['tone_enabled'] = bool(is_enabled)
        return save_slclient_json(task_id, data, indent=4)
    except Exception as e:
        logger.error(f"[APK Config] 设置提示音异常: {e}")
        return False


def set_tts_enabled(task_id: str, is_enabled: bool) -> bool:
    """设置 TTS 开关"""
    logger.info(f"[APK Config] 设置 TTS — task_id={task_id}, enabled={is_enabled}")
    path = get_slclient_json_path(task_id)
    if not path.exists():
        return False
    try:
        data = load_slclient_json(task_id)
        data.setdefault('tts', {})['enabled'] = bool(is_enabled)
        return save_slclient_json(task_id, data, indent=4)
    except Exception as e:
        logger.error(f"[APK Config] 设置 TTS 异常: {e}")
        return False


def batch_update_config(task_id: str, config_data: Dict) -> bool:
    """批量更新 slclient.json 配置（接收前端提交的配置字典）"""
    logger.info(f"[APK Config] 批量更新配置 — task_id={task_id}, keys={list(config_data.keys())}")
    path = get_slclient_json_path(task_id)
    if not path.exists():
        logger.warning(f"[APK Config] slclient.json 不存在，无法批量更新 — task_id={task_id}")
        return False
    try:
        data = load_slclient_json(task_id)

        # 环境配置
        if 'env_key' in config_data:
            from .constants import ENV_CONF
            env_key = config_data['env_key']
            env_data = ENV_CONF.get(env_key, {})
            if env_data:
                data.setdefault('profile', {}).update({
                    'dns': env_data['ip_address'].split(',') if isinstance(env_data['ip_address'], str) else env_data['ip_address'],
                    'context': env_data['context'],
                    'upgrade_url': env_data['upgrade_url'],
                    'env_key': env_key,
                })
                logger.debug(f"[APK Config] 环境配置已更新: env_key={env_key}")

        # 登录方式
        if 'login_type' in config_data:
            login_val = config_data['login_type']
            for storage_key, names_dict in LOGIN_TYPE_MAPPING.items():
                if names_dict.get('zh') == login_val or names_dict.get('en') == login_val or storage_key == login_val:
                    data.setdefault('profile', {})['login_mode'] = storage_key
                    logger.debug(f"[APK Config] 登录方式已更新: {storage_key}")
                    break

        # 地图
        if 'map_type' in config_data:
            map_key = config_data['map_type']
            template = MAP_CONFIG_TEMPLATES.get(map_key)
            if template:
                data.setdefault('lbs', {}).update(template['config'])
                logger.debug(f"[APK Config] 地图配置已更新: {map_key}")

        # 音频
        if 'sound_codec' in config_data:
            data.setdefault('sound', {})['codec'] = config_data['sound_codec']
        if 'dsp_provider' in config_data:
            data.setdefault('dsp', {})['provider'] = config_data['dsp_provider']
        if 'play_stream' in config_data:
            data.setdefault('dsp', {})['play_stream'] = config_data['play_stream']
        if 'record_stream' in config_data:
            data.setdefault('dsp', {})['record_stream'] = config_data['record_stream']
        if 'tone_enabled' in config_data:
            data.setdefault('sound', {})['tone_enabled'] = bool(config_data['tone_enabled'])
        if 'tts_enabled' in config_data:
            data.setdefault('tts', {})['enabled'] = bool(config_data['tts_enabled'])

        # Launcher
        if 'launcher_module' in config_data:
            launcher = config_data['launcher_module']
            if launcher and launcher != 'none':
                data.setdefault('ui', {})['launcherModule'] = launcher
                logger.debug(f"[APK Config] Launcher 已设置: {launcher}")
            else:
                if 'ui' in data and 'launcherModule' in data['ui']:
                    del data['ui']['launcherModule']
                    logger.debug("[APK Config] Launcher 已移除")

        # Recorder
        if 'recorder_enable' in config_data:
            data.setdefault('recorder', {})['enable'] = bool(config_data['recorder_enable'])

        # 设备名称
        if 'device_name' in config_data:
            data.setdefault('device', {})['name'] = config_data['device_name']
        # device_model 字段兼容
        if 'device_model' in config_data:
            data.setdefault('device', {})['name'] = config_data['device_model']

        result = save_slclient_json(task_id, data, indent=4)
        if result:
            logger.success(f"[APK Config] 批量配置更新成功 — task_id={task_id}")
        else:
            logger.error(f"[APK Config] 批量配置保存失败 — task_id={task_id}")
        return result
    except Exception as e:
        logger.error(f"[APK Config] 批量配置更新异常 — task_id={task_id}: {e}")
        return False


# ==================== input.json 按键配置 ====================


def load_input_json(task_id: str) -> Dict:
    """加载 input.json"""
    path = get_input_json_path(task_id)
    if not path.exists():
        if INPUT_JSON_DEFAULT.exists():
            shutil.copy2(INPUT_JSON_DEFAULT, path)
            logger.debug(f"[APK Config] 复制默认 input.json → {path}")
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[APK Config] 解析 input.json 异常 — task_id={task_id}: {e}")
        return {}


def save_input_json(task_id: str, data: Dict) -> bool:
    """保存 input.json"""
    path = get_input_json_path(task_id)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.debug(f"[APK Config] 保存 input.json — task_id={task_id}")
        return True
    except Exception as e:
        logger.error(f"[APK Config] 保存 input.json 异常 — task_id={task_id}: {e}")
        return False


def get_formatted_key_configs(task_id: str) -> List[Dict]:
    """解析 input.json 返回格式化按键配置列表"""
    logger.debug(f"[APK Config] 获取按键配置 — task_id={task_id}")
    data = load_input_json(task_id)
    intents = data.get('intent', {})
    stdkeys = data.get('stdkey', {})
    actions_data = data.get('action', {})

    valid_names = set(stdkeys.keys()) & set(intents.keys())
    sortable_items = []

    for name in valid_names:
        sk = stdkeys.get(name, {})
        key_val = sk.get('key')
        sortable_items.append((name, key_val if isinstance(key_val, int) else float('inf')))

    sortable_items.sort(key=lambda x: x[1], reverse=False)

    formatted_items = []
    for name, _ in sortable_items:
        sk = stdkeys.get(name, {})
        ac = actions_data.get(name, {})
        info = intents.get(name, {})

        event_str = sk.get('event', 'N/A')
        key_val = sk.get('key', 'N/A')
        action_str = info.get('action', '—')
        cmds = ac.get('default', [])

        cmd_str = ', '.join(
            filter(None, [c.get('command', {}).get('id', '') for c in cmds if isinstance(c, dict)])
        ) if isinstance(cmds, list) else '—'

        formatted_items.append({
            'name': name,
            'event': event_str,
            'key': key_val,
            'action': action_str,
            'cmd': cmd_str or '—',
        })

    return formatted_items


# ==================== 终端配置导入 ====================


def list_terminal_configs() -> List[Dict]:
    """列出所有可用的终端预设配置"""
    logger.debug("[APK Config] 列出终端预设配置")
    configs = []
    if not TERMINAL_CONFIGS_DIR.exists():
        logger.warning(f"[APK Config] 终端配置目录不存在: {TERMINAL_CONFIGS_DIR}")
        return configs

    for folder_name in sorted(os.listdir(TERMINAL_CONFIGS_DIR)):
        folder_path = TERMINAL_CONFIGS_DIR / folder_name
        if not folder_path.is_dir():
            continue

        slclient_path = folder_path / 'slclient.json'
        if not slclient_path.exists():
            continue

        try:
            with open(slclient_path, 'r', encoding='utf-8') as f:
                sc_data = json.load(f)
            device_name = sc_data.get('device', {}).get('name', folder_name)
            configs.append({
                'folder': folder_name,
                'device_name': device_name,
            })
        except Exception as e:
            logger.warning(f"[APK Config] 解析终端配置异常: {folder_name} — {e}")
            configs.append({
                'folder': folder_name,
                'device_name': folder_name,
            })

    logger.info(f"[APK Config] 终端预设配置共 {len(configs)} 个")
    return configs


def import_terminal_config(task_id: str, folder_name: str) -> Dict:
    """导入终端预设配置到当前构建任务"""
    logger.info(f"[APK Config] 导入终端配置 — task_id={task_id}, folder={folder_name}")
    source_dir = TERMINAL_CONFIGS_DIR / folder_name
    decompile_dir = get_decompile_dir(task_id)

    if not source_dir.exists():
        logger.error(f"[APK Config] 终端配置不存在: {folder_name}")
        return {'success': False, 'message': f'终端配置不存在: {folder_name}'}

    if not decompile_dir.exists():
        logger.error(f"[APK Config] 反编译目录不存在，无法导入终端配置 — task_id={task_id}")
        return {'success': False, 'message': '请先反编译 APK'}

    assets_dir = decompile_dir / 'assets'
    slclient_dir = assets_dir / 'slclient'
    slclient_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 复制 4 个配置文件
        shutil.copy2(source_dir / 'slclient.json', assets_dir / 'slclient.json')

        slclient_sub = source_dir / 'slclient'
        if slclient_sub.exists():
            shutil.copy2(slclient_sub / 'input.json', slclient_dir / 'input.json')
            shutil.copy2(slclient_sub / 'led.json', slclient_dir / 'led.json')
            shutil.copy2(slclient_sub / 'reaction.json', slclient_dir / 'reaction.json')

        # 重新加载配置返回
        new_data = load_slclient_json(task_id)
        logger.success(f"[APK Config] 终端配置导入成功 — task_id={task_id}, folder={folder_name}")
        return {
            'success': True,
            'message': f'已导入终端配置: {folder_name}',
            'slclient_data': new_data,
        }
    except Exception as e:
        logger.error(f"[APK Config] 终端配置导入异常 — task_id={task_id}: {e}")
        return {'success': False, 'message': f'导入失败: {str(e)}'}
