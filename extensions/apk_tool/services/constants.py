import os
from pathlib import Path
from django.conf import settings

# ==================== Django 适配的路径常量 ====================

# 资源根目录（app 自带资源，不依赖项目级 resources 目录）
APP_DIR = Path(__file__).resolve().parent.parent  # extensions/apk_tool/
RESOURCE_BASE = APP_DIR / 'resources'

# 工作目录（MEDIA 下的动态文件）
WORKSPACE_BASE = Path(settings.MEDIA_ROOT) / 'apk_tool'

# apktool.jar
APKTOOL_JAR = RESOURCE_BASE / 'apktool.jar'

# 内置 APK 路径
APK_LARGE = RESOURCE_BASE / 'DEF_APK' / 'LargeApp.apk'
APK_SMALL = RESOURCE_BASE / 'DEF_APK' / 'SmallApp.apk'
APK_SCREENLESS = RESOURCE_BASE / 'DEF_APK' / 'Screenless.apk'

# 签名证书
KEYSTORE_BIG = RESOURCE_BASE / 'cert' / 'shanli.jks'
KEYSTORE_SMALL = RESOURCE_BASE / 'cert' / 'shanlitech.keystore'

KEYSTORE_CONFIG = {
    'large': {'path': str(KEYSTORE_BIG), 'password': '123456'},
    'middle': {'path': str(KEYSTORE_BIG), 'password': '123456'},
    'small': {'path': str(KEYSTORE_SMALL), 'password': 'Lgsj829517'},
    'none': {'path': str(KEYSTORE_SMALL), 'password': 'Lgsj829517'},
}

# 工具链路径
ZIPALIGN_EXE = str(RESOURCE_BASE / 'win' / 'zipalign.exe')
APKSIGNER_BAT = str(RESOURCE_BASE / 'win' / 'apksigner.bat')

# 终端预设配置目录
TERMINAL_CONFIGS_DIR = RESOURCE_BASE / 'terminal_configs'

# 默认按键映射
INPUT_JSON_DEFAULT = RESOURCE_BASE / 'input_default.json'

# 环境配置
ENV_CONF = {
    'overseas': {
        'ip_address': 'sgdns.shanlipoc.com:10200,usdns.shanlipoc.com:10200',
        'context': 'pocstar',
        'upgrade_url': 'upgrade.pocstar.com',
    },
    'domestic_v2': {
        'ip_address': 'cndns.shanliptt.com:10200',
        'context': 'show',
        'upgrade_url': 'upgrade.shanliptt.com',
    },
}

ENV_DISPLAY_NAMES = {
    'overseas': {'zh': '海外环境', 'en': 'Overseas Env'},
    'domestic_v2': {'zh': '国内环境2.0', 'en': 'Domestic 2.0'},
}

LOGIN_TYPE_MAPPING = {
    'account': {'zh': '账号登录', 'en': 'Account Login'},
    'serial': {'zh': 'IMEI登录', 'en': 'IMEI Login'},
    'iccid': {'zh': 'ICCID登录', 'en': 'ICCID Login'},
}

MAP_CONFIG_TEMPLATES = {
    'google': {
        'display_name': {'zh': 'GPS[谷歌地图]', 'en': 'GPS[Google Map]'},
        'config': {
            'enabled': True,
            'report': True,
            'map_type': 'google',
            'provider': 'google',
            'coor': 'wgs84',
            'update_period_sec': 40,
            'report_period_sec': 40,
        },
    },
    'baidu_domestic': {
        'display_name': {'zh': '百度 [国内]', 'en': 'Baidu [Domestic]'},
        'config': {
            'enabled': True,
            'report': True,
            'map_type': 'baidu',
            'provider': 'baidu',
            'coor': 'bd09ll',
            'update_period_sec': 40,
            'report_period_sec': 40,
        },
    },
    'baidu_oversea': {
        'display_name': {'zh': '百度 [海外]', 'en': 'Baidu [Oversea]'},
        'config': {
            'enabled': True,
            'report': True,
            'map_type': 'baidu',
            'provider': 'baidu',
            'coor': 'wgs84',
            'update_period_sec': 40,
            'report_period_sec': 40,
        },
    },
    'none': {
        'display_name': {'zh': 'GPS', 'en': 'GPS'},
        'config': {
            'enabled': True,
            'report': True,
            'map_type': 'none',
            'provider': 'default',
            'coor': 'wgs84',
            'update_period_sec': 40,
            'report_period_sec': 40,
        },
    },
}

# Android XML 命名空间
ANDROID_NAMESPACE = 'http://schemas.android.com/apk/res/android'

# 业务路径
LAUNCHER_MODULE_PATH = ['ui', 'launcherModule']
RECORDER_ENABLE_PATH = ['recorder', 'enable']
LBS_COOR_PATH = ['lbs', 'coor']
LBS_MAP_TYPE = ['lbs', 'map_type']

DEFAULT_CUSTOM_LIST = [
    'join_next_group',
    'switch_group_name_tts',
    'switch_group_click',
    'join_prev_group',
    'new_call_in',
]

# 合法的 POC APK 包名
VALID_PACKAGE_NAMES = [
    'com.shanli.pocstar',
    'com.shanlitech.ptt',
    'com.shanlitech.noscreen',
    'com.shli.interphone',
]

# 产物文件名前缀规则
APK_NAME_PREFIX_RULES = {
    'recorder_true_launcher_large': 'BSAPP',
    'recorder_true_launcher_middle': 'MSAPP',
    'recorder_true_launcher_small': 'SSAPP',
    'recorder_true_no_launcher': 'RSAPP',
    'recorder_false_launcher_large': 'BSAPP',
    'recorder_false_launcher_middle': 'MSAPP',
    'recorder_false_launcher_small': 'SSAPP',
    'recorder_false_no_launcher': 'NSAPP',
    'no_launcher_module_recorder_true': 'RSAPP',
    'no_launcher_module_recorder_false': 'ASAPP',
}


def get_task_workdir(task_id: str) -> Path:
    """获取某个构建任务的工作目录"""
    workdir = WORKSPACE_BASE / 'tasks' / task_id
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def get_task_output_dir(task_id: str) -> Path:
    """获取构建产物输出目录"""
    from datetime import datetime
    date_str = datetime.now().strftime('%Y_%m_%d')
    outdir = WORKSPACE_BASE / 'APK' / date_str
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def get_decompile_dir(task_id: str) -> Path:
    """获取反编译输出目录"""
    return get_task_workdir(task_id) / 'app_out'


def get_slclient_json_path(task_id: str) -> Path:
    """获取 slclient.json 路径"""
    return get_decompile_dir(task_id) / 'assets' / 'slclient.json'


def get_input_json_path(task_id: str) -> Path:
    """获取 input.json 源路径（工作区）"""
    return get_task_workdir(task_id) / 'input.json'


def get_manifest_path(task_id: str) -> Path:
    """获取 AndroidManifest.xml 路径"""
    return get_decompile_dir(task_id) / 'AndroidManifest.xml'


def get_yml_path(task_id: str) -> Path:
    """获取 apktool.yml 路径"""
    return get_decompile_dir(task_id) / 'apktool.yml'
