"""
备份管理命令
"""
from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from system.core.backup import BackupManager


class Command(BaseCommand):
    help = "Manage database and media backups"

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=["list", "create", "restore", "delete"],
            help="Action to perform"
        )
        parser.add_argument(
            "--type",
            choices=["database", "media", "full"],
            default="database",
            help="Backup type"
        )
        parser.add_argument(
            "--id",
            help="Backup ID for restore/delete"
        )
        parser.add_argument(
            "--name",
            help="Backup name for create"
        )

    def handle(self, *args, **options):
        action = options["action"]
        backup_type = options["type"]
        backup_id = options.get("id")
        backup_name = options.get("name")

        manager = BackupManager()

        if action == "list":
            self._list_backups(manager, backup_type)
        elif action == "create":
            self._create_backup(manager, backup_type, backup_name)
        elif action == "restore":
            if not backup_id:
                raise CommandError("--id is required for restore")
            self._restore_backup(manager, backup_id, backup_type)
        elif action == "delete":
            if not backup_id:
                raise CommandError("--id is required for delete")
            self._delete_backup(manager, backup_id)

    def _list_backups(self, manager: BackupManager, backup_type: str):
        backups = manager.list_backups(backup_type)
        
        if not backups:
            self.stdout.write("No backups found.")
            return
        
        self.stdout.write("\nBackups:")
        self.stdout.write("-" * 80)
        for backup in backups:
            size_mb = backup.size_bytes / (1024 * 1024)
            self.stdout.write(
                f"ID: {backup.id} | Type: {backup.type:8} | Name: {backup.name:30} | "
                f"Size: {size_mb:.2f} MB | Created: {backup.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        self.stdout.write("-" * 80)

    def _create_backup(self, manager: BackupManager, backup_type: str, name: str):
        self.stdout.write(f"Creating {backup_type} backup...")
        
        if backup_type == "full":
            db_backup, media_backup = manager.backup_full(name)
            self.stdout.write(f"Success! Database backup ID: {db_backup.id}")
            self.stdout.write(f"Success! Media backup ID: {media_backup.id}")
        elif backup_type == "database":
            backup = manager.backup_database(name)
            self.stdout.write(f"Success! Backup ID: {backup.id}")
        elif backup_type == "media":
            backup = manager.backup_media(name)
            self.stdout.write(f"Success! Backup ID: {backup.id}")

    def _restore_backup(self, manager: BackupManager, backup_id: str, backup_type: str):
        confirm = input(
            f"WARNING: This will overwrite your {backup_type} with backup {backup_id}.\n"
            "Are you sure? Type 'YES' to confirm: "
        )
        
        if confirm != "YES":
            self.stdout.write("Restore cancelled.")
            return
        
        try:
            if backup_type == "database":
                manager.restore_database(backup_id)
            elif backup_type == "media":
                manager.restore_media(backup_id)
            
            self.stdout.write(f"Successfully restored backup {backup_id}")
        except Exception as e:
            raise CommandError(f"Restore failed: {str(e)}")

    def _delete_backup(self, manager: BackupManager, backup_id: str):
        if manager.delete_backup(backup_id):
            self.stdout.write(f"Successfully deleted backup {backup_id}")
        else:
            raise CommandError(f"Backup {backup_id} not found")
