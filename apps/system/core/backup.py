"""
数据备份与恢复模块
"""
import os
import json
import subprocess
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field

from django.conf import settings
from django.core.management import call_command
from loguru import logger


@dataclass
class BackupInfo:
    """备份信息"""
    id: str
    name: str
    type: str  # 'database', 'media', 'full'
    created_at: datetime
    size_bytes: int
    checksum: str
    path: str
    is_compressed: bool = True


def _safe_extract_tar(tar, dest) -> None:
    """安全解压 tar 包，阻断路径穿越（tar slip）。

    备份包可能来自外部或不可信来源，恶意构造的成员名（``../``、绝对路径、指向外部的
    符号链接）会让 ``extractall`` 把文件写到目标目录之外。这里优先使用 Python 3.12+
    的 ``filter="data"``；低版本退化为逐成员手工校验。
    """
    try:
        tar.extractall(path=dest, filter="data")
        return
    except TypeError:
        pass  # Python < 3.11.4 无 filter 参数 → 走下面的手工校验

    target = Path(dest).resolve()
    for member in tar.getmembers():
        member_dest = (target / member.name).resolve()
        if member_dest != target and target not in member_dest.parents:
            raise ValueError(f"拒绝解压：备份包含越界成员 {member.name!r}")
    tar.extractall(path=dest)


class BackupManager:
    """备份管理器"""
    
    def __init__(self):
        self.backup_dir = Path(getattr(settings, "BACKUP_DIR", "backups"))
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
    def _generate_backup_id(self) -> str:
        """生成备份ID"""
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    
    def _calculate_checksum(self, file_path: Path) -> str:
        """计算文件SHA256校验和"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def backup_database(self, name: Optional[str] = None) -> BackupInfo:
        """备份数据库"""
        backup_id = self._generate_backup_id()
        name = name or f"db_backup_{backup_id}"
        
        backup_path = self.backup_dir / f"{name}.json"
        
        logger.info(f"Starting database backup: {name}")
        
        with open(backup_path, "w", encoding="utf-8") as f:
            call_command("dumpdata", "--natural-foreign", "--natural-primary", stdout=f)
        
        # 压缩备份
        import gzip
        compressed_path = self.backup_dir / f"{name}.json.gz"
        with open(backup_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb") as f_out:
                f_out.writelines(f_in)
        
        backup_path.unlink()  # 删除未压缩文件
        
        size_bytes = compressed_path.stat().st_size
        checksum = self._calculate_checksum(compressed_path)
        
        backup_info = BackupInfo(
            id=backup_id,
            name=name,
            type="database",
            created_at=datetime.now(),
            size_bytes=size_bytes,
            checksum=checksum,
            path=str(compressed_path),
            is_compressed=True
        )
        
        self._save_backup_info(backup_info)
        logger.info(f"Database backup completed: {compressed_path}, size: {size_bytes} bytes")
        
        return backup_info
    
    def backup_media(self, name: Optional[str] = None) -> BackupInfo:
        """备份媒体文件"""
        import tarfile
        
        backup_id = self._generate_backup_id()
        name = name or f"media_backup_{backup_id}"
        backup_path = self.backup_dir / f"{name}.tar.gz"
        
        media_root = getattr(settings, "MEDIA_ROOT", "media")
        if not Path(media_root).exists():
            raise ValueError("MEDIA_ROOT does not exist")
        
        logger.info(f"Starting media backup: {name}")
        
        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(media_root, arcname="media")
        
        size_bytes = backup_path.stat().st_size
        checksum = self._calculate_checksum(backup_path)
        
        backup_info = BackupInfo(
            id=backup_id,
            name=name,
            type="media",
            created_at=datetime.now(),
            size_bytes=size_bytes,
            checksum=checksum,
            path=str(backup_path),
            is_compressed=True
        )
        
        self._save_backup_info(backup_info)
        logger.info(f"Media backup completed: {backup_path}, size: {size_bytes} bytes")
        
        return backup_info
    
    def backup_full(self, name: Optional[str] = None) -> Tuple[BackupInfo, BackupInfo]:
        """完整备份（数据库+媒体）"""
        db_backup = self.backup_database(name)
        media_backup = self.backup_media(name)
        return db_backup, media_backup
    
    def list_backups(self, backup_type: Optional[str] = None) -> List[BackupInfo]:
        """列出所有备份"""
        info_file = self.backup_dir / "backup_info.json"
        if not info_file.exists():
            return []
        
        with open(info_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        backups = []
        for item in data:
            backup = BackupInfo(
                id=item["id"],
                name=item["name"],
                type=item["type"],
                created_at=datetime.fromisoformat(item["created_at"]),
                size_bytes=item["size_bytes"],
                checksum=item["checksum"],
                path=item["path"],
                is_compressed=item.get("is_compressed", True)
            )
            if backup_type is None or backup.type == backup_type:
                backups.append(backup)
        
        # 按创建时间倒序
        backups.sort(key=lambda x: x.created_at, reverse=True)
        return backups
    
    def restore_database(self, backup_id: str) -> bool:
        """恢复数据库"""
        backup = self._get_backup(backup_id, "database")
        if not backup:
            raise ValueError(f"Backup not found: {backup_id}")
        
        # 验证校验和
        actual_checksum = self._calculate_checksum(Path(backup.path))
        if actual_checksum != backup.checksum:
            raise ValueError("Backup checksum mismatch")
        
        logger.warning(f"Starting database restore from: {backup.path}")
        
        # 解压备份
        import gzip
        temp_path = self.backup_dir / f"restore_{backup_id}.json"
        
        with gzip.open(backup.path, "rb") as f_in:
            with open(temp_path, "wb") as f_out:
                f_out.write(f_in.read())
        
        # 清除数据并恢复
        call_command("flush", "--noinput")
        call_command("loaddata", str(temp_path))
        
        temp_path.unlink()
        
        logger.info(f"Database restored successfully from: {backup.path}")
        return True
    
    def restore_media(self, backup_id: str) -> bool:
        """恢复媒体文件"""
        backup = self._get_backup(backup_id, "media")
        if not backup:
            raise ValueError(f"Backup not found: {backup_id}")
        
        # 验证校验和
        actual_checksum = self._calculate_checksum(Path(backup.path))
        if actual_checksum != backup.checksum:
            raise ValueError("Backup checksum mismatch")
        
        logger.warning(f"Starting media restore from: {backup.path}")
        
        import tarfile
        media_root = Path(getattr(settings, "MEDIA_ROOT", "media"))
        
        # 备份当前媒体目录
        if media_root.exists():
            temp_media = self.backup_dir / f"media_backup_before_restore_{self._generate_backup_id()}"
            media_root.rename(temp_media)
        
        media_root.mkdir(parents=True, exist_ok=True)
        
        with tarfile.open(backup.path, "r:gz") as tar:
            _safe_extract_tar(tar, media_root.parent)
        
        logger.info(f"Media restored successfully from: {backup.path}")
        return True
    
    def delete_backup(self, backup_id: str) -> bool:
        """删除备份"""
        backup = self._get_backup(backup_id)
        if not backup:
            return False
        
        backup_path = Path(backup.path)
        if backup_path.exists():
            backup_path.unlink()
        
        # 更新备份信息
        backups = self.list_backups()
        backups = [b for b in backups if b.id != backup_id]
        self._save_all_backup_info(backups)
        
        logger.info(f"Backup deleted: {backup_id}")
        return True
    
    def _get_backup(self, backup_id: str, backup_type: Optional[str] = None) -> Optional[BackupInfo]:
        """获取备份信息"""
        backups = self.list_backups(backup_type)
        for backup in backups:
            if backup.id == backup_id:
                return backup
        return None
    
    def _save_backup_info(self, backup_info: BackupInfo) -> None:
        """保存备份信息"""
        backups = self.list_backups()
        backups.append(backup_info)
        self._save_all_backup_info(backups)
    
    def _save_all_backup_info(self, backups: List[BackupInfo]) -> None:
        """保存所有备份信息"""
        data = []
        for backup in backups:
            data.append({
                "id": backup.id,
                "name": backup.name,
                "type": backup.type,
                "created_at": backup.created_at.isoformat(),
                "size_bytes": backup.size_bytes,
                "checksum": backup.checksum,
                "path": backup.path,
                "is_compressed": backup.is_compressed
            })
        
        info_file = self.backup_dir / "backup_info.json"
        with open(info_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
