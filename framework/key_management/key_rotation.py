import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import dataclass, asdict

# 添加项目根目录到路径
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

# 现在导入其他模块
from framework.key_management.security import generate_secret_key


@dataclass
class RotationKey:
    key: str
    created_at: str
    is_active: bool = True
    is_primary: bool = False


class KeyRotationManager:
    """
    Django SECRET_KEY 轮换管理器
    
    支持双密钥无缝过渡：
    - 主密钥：用于签名新数据
    - 副密钥：用于验证旧数据
    """
    
    def __init__(self, keys_file: Optional[str] = None):
        self.keys_file = keys_file or self._get_default_keys_file()
        self.keys: List[RotationKey] = []
        self._load_keys()
    
    def _get_default_keys_file(self) -> str:
        """获取默认的密钥文件路径"""
        base_dir = Path(__file__).resolve().parent.parent
        return str(base_dir / "data" / "secret_keys.json")
    
    def _load_keys(self):
        """从文件加载密钥"""
        keys_path = Path(self.keys_file)
        
        if not keys_path.exists():
            # 如果文件不存在，创建目录
            keys_path.parent.mkdir(parents=True, exist_ok=True)
            # 从环境变量初始化第一个密钥
            self._initialize_from_env()
            return
        
        try:
            with open(keys_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.keys = [RotationKey(**item) for item in data]
        except (json.JSONDecodeError, FileNotFoundError):
            self._initialize_from_env()
    
    def _initialize_from_env(self):
        """从环境变量初始化"""
        env_key = os.getenv('SECRET_KEY')
        if env_key:
            self.keys = [
                RotationKey(
                    key=env_key,
                    created_at=datetime.now().isoformat(),
                    is_active=True,
                    is_primary=True
                )
            ]
            self._save_keys()
    
    def _save_keys(self):
        """保存密钥到文件"""
        keys_path = Path(self.keys_file)
        keys_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(keys_path, 'w', encoding='utf-8') as f:
            json.dump([asdict(k) for k in self.keys], f, indent=2, ensure_ascii=False)
    
    def get_primary_key(self) -> Optional[str]:
        """获取当前主密钥"""
        for key in self.keys:
            if key.is_primary and key.is_active:
                return key.key
        return None
    
    def get_all_active_keys(self) -> List[str]:
        """获取所有有效的密钥（用于验证）"""
        return [k.key for k in self.keys if k.is_active]
    
    def rotate_key(self, keep_old_days: int = 7) -> str:
        """
        轮换密钥
        
        Args:
            keep_old_days: 旧密钥保留天数
            
        Returns:
            新的主密钥
        """
        # 1. 将当前主密钥降级为副密钥
        for key in self.keys:
            key.is_primary = False
        
        # 2. 生成新的主密钥
        new_key = RotationKey(
            key=generate_secret_key(),
            created_at=datetime.now().isoformat(),
            is_active=True,
            is_primary=True
        )
        
        # 3. 清理过期的旧密钥
        cutoff_date = datetime.now() - timedelta(days=keep_old_days)
        self.keys = [
            k for k in self.keys
            if datetime.fromisoformat(k.created_at) > cutoff_date
        ]
        
        # 4. 添加新密钥
        self.keys.insert(0, new_key)
        
        # 5. 保存
        self._save_keys()
        
        return new_key.key
    
    def deactivate_key(self, key: str):
        """停用指定密钥"""
        for k in self.keys:
            if k.key == key:
                k.is_active = False
                break
        self._save_keys()
    
    def get_key_info(self) -> List[Dict]:
        """获取密钥信息（安全，不显示完整密钥）"""
        info = []
        for key in self.keys:
            info.append({
                "prefix": key.key[:8] + "..." if len(key.key) > 8 else key.key,
                "created_at": key.created_at,
                "is_active": key.is_active,
                "is_primary": key.is_primary,
                "length": len(key.key)
            })
        return info


# 全局实例
_key_manager: Optional[KeyRotationManager] = None


def get_key_manager() -> KeyRotationManager:
    """获取密钥管理器单例"""
    global _key_manager
    if _key_manager is None:
        _key_manager = KeyRotationManager()
    return _key_manager


def get_rotatable_secret_key() -> str:
    """获取当前主密钥（用于 Django 配置）"""
    manager = get_key_manager()
    return manager.get_primary_key() or os.getenv('SECRET_KEY', '')


def get_all_secret_keys() -> List[str]:
    """获取所有有效的密钥（用于自定义验证）"""
    manager = get_key_manager()
    keys = manager.get_all_active_keys()
    if not keys:
        keys = [os.getenv('SECRET_KEY', '')]
    return keys


if __name__ == "__main__":
    print("=== Django SECRET_KEY 轮换管理工具 ===")
    
    if len(sys.argv) < 2:
        print("""
用法:
    python framework/key_management/key_rotation.py status          # 查看当前密钥状态
    python framework/key_management/key_rotation.py rotate [days]   # 轮换密钥（默认保留7天）
    python framework/key_management/key_rotation.py list            # 列出所有密钥信息
        """)
        sys.exit(0)
    
    command = sys.argv[1]
    manager = get_key_manager()
    
    if command == "status":
        print("\n当前密钥状态:")
        for info in manager.get_key_info():
            status = "🟢 PRIMARY" if info["is_primary"] else "🟡 ACTIVE" if info["is_active"] else "🔴 INACTIVE"
            print(f"  {status}: {info['prefix']} (created: {info['created_at']})")
    
    elif command == "rotate":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        new_key = manager.rotate_key(keep_old_days=days)
        print(f"\n✅ 密钥轮换成功！")
        print(f"新的主密钥已生成（旧密钥保留{days}天）")
        print(f"\n请更新 .env 文件:")
        print(f"SECRET_KEY={new_key}")
    
    elif command == "list":
        print("\n密钥详情:")
        for i, info in enumerate(manager.get_key_info(), 1):
            print(f"\n密钥 #{i}:")
            print(f"  前缀: {info['prefix']}")
            print(f"  创建时间: {info['created_at']}")
            print(f"  状态: {'主密钥' if info['is_primary'] else '活跃' if info['is_active'] else '已停用'}")
            print(f"  长度: {info['length']}")
