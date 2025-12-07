import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from core_utils import wait_for_enter

#!/usr/bin/env python3
# Made by trex099
# https://github.com/Trex099/Glint
"""
Automated Backup System for Linux VMs

This module provides comprehensive backup capabilities including:
- Backup scheduling and retention policy management
- Incremental and differential backup strategies
- Backup verification and integrity checking
- Backup restoration procedures with point-in-time recovery
- Backup compression and encryption
"""

import os
import json
import shutil
import subprocess
import time
import hashlib
import gzip
import tarfile
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
from enum import Enum
import logging
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress
import questionary

# Import wait_for_enter from core_utils
import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..', '..')))
from core_utils import wait_for_enter

console = Console()

def check_backup_dependencies() -> Tuple[bool, List[str]]:
    """Check if all required dependencies for backup system are available"""
    missing_deps = []

    # Check for required system commands
    required_commands = [
        'tar',      # For creating archives
        'gzip',     # For compression
        'openssl',  # For encryption
        'qemu-img', # For VM disk operations
        'sha256sum' # For checksums (fallback to Python hashlib if not available)
    ]

    for cmd in required_commands:
        try:
            result = subprocess.run(['which', cmd], capture_output=True, text=True)
            if result.returncode != 0:
                if cmd == 'sha256sum':
                    # sha256sum is optional, we can use Python's hashlib
                    continue
                missing_deps.append(cmd)
        except Exception:
            if cmd != 'sha256sum':
                missing_deps.append(cmd)

    # Check for optional compression tools
    optional_commands = ['bzip2', 'xz', 'lz4']
    for cmd in optional_commands:
        try:
            result = subprocess.run(['which', cmd], capture_output=True, text=True)
            if result.returncode != 0:
                console.print(f"[yellow]Warning: Optional compression tool '{cmd}' not found[/yellow]")
        except Exception:
            pass

    return len(missing_deps) == 0, missing_deps

class BackupType(Enum):
    """Backup types"""
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"
    SNAPSHOT = "snapshot"

class BackupStatus(Enum):
    """Backup status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    VERIFYING = "verifying"
    VERIFIED = "verified"

class CompressionType(Enum):
    """Compression types"""
    NONE = "none"
    GZIP = "gzip"
    BZIP2 = "bzip2"
    XZ = "xz"
    LZ4 = "lz4"

@dataclass
class BackupSchedule:
    """Backup schedule configuration"""
    name: str
    enabled: bool = True
    backup_type: BackupType = BackupType.INCREMENTAL
    frequency: str = "daily"  # daily, weekly, monthly, hourly
    time: str = "02:00"  # HH:MM format
    days_of_week: Optional[List[str]] = None  # For weekly: ["monday", "wednesday"]
    day_of_month: Optional[int] = None  # For monthly: 1-31
    retention_days: int = 30
    compression: CompressionType = CompressionType.GZIP
    encryption_enabled: bool = False
    verify_after_backup: bool = True
    created_at: Optional[datetime] = None
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None

@dataclass
class RetentionPolicy:
    """Backup retention policy"""
    daily_retention: int = 7  # Keep daily backups for 7 days
    weekly_retention: int = 4  # Keep weekly backups for 4 weeks
    monthly_retention: int = 12  # Keep monthly backups for 12 months
    yearly_retention: int = 5  # Keep yearly backups for 5 years
    max_total_backups: int = 100
    auto_cleanup: bool = True
    cleanup_schedule: str = "daily"

@dataclass
class BackupMetadata:
    """Backup metadata"""
    backup_id: str
    vm_name: str
    backup_type: BackupType
    status: BackupStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    size_bytes: int = 0
    compressed_size_bytes: int = 0
    file_count: int = 0
    checksum: str = ""
    compression: CompressionType = CompressionType.NONE
    encrypted: bool = False
    parent_backup_id: Optional[str] = None  # For incremental/differential
    verification_status: str = "pending"
    verification_checksum: str = ""
    error_message: str = ""
    backup_path: str = ""
    duration_seconds: float = 0.0

@dataclass
class BackupConfig:
    """Backup configuration"""
    vm_name: str
    backup_dir: str
    schedules: List[BackupSchedule]
    retention_policy: RetentionPolicy
    encryption_key: Optional[str] = None
    compression_level: int = 6  # 1-9 for gzip
    parallel_jobs: int = 1
    bandwidth_limit_mbps: Optional[int] = None
    exclude_patterns: Optional[List[str]] = None
    include_patterns: Optional[List[str]] = None
    pre_backup_script: Optional[str] = None
    post_backup_script: Optional[str] = None
    notification_email: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class BackupManager:
    """Automated backup system manager"""

    def __init__(self, config_dir: str = None):
        if config_dir is None:
            config_dir = os.path.expanduser("~/.glint/backup")

        self.config_dir = config_dir
        self.backup_config_file = os.path.join(config_dir, "backup_config.json")
        self.backup_metadata_file = os.path.join(config_dir, "backup_metadata.json")
        self.backup_logs_dir = os.path.join(config_dir, "logs")

        # Ensure directories exist
        os.makedirs(config_dir, exist_ok=True)
        os.makedirs(self.backup_logs_dir, exist_ok=True)

        self.backup_configs: Dict[str, BackupConfig] = {}
        self.backup_metadata: Dict[str, BackupMetadata] = {}
        self.scheduler_thread = None
        self.scheduler_running = False

        # Setup logging
        self.setup_logging()

        # Load existing configurations
        self.load_configurations()

    def setup_logging(self):
        """Setup backup logging"""
        log_file = os.path.join(self.backup_logs_dir, "backup.log")
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def load_configurations(self):
        """Load backup configurations from disk"""
        try:
            if os.path.exists(self.backup_config_file):
                with open(self.backup_config_file, 'r') as f:
                    data = json.load(f)
                    for vm_name, config_data in data.items():
                        if 'created_at' in config_data and config_data['created_at']:
                            config_data['created_at'] = datetime.fromisoformat(config_data['created_at'])
                        if 'updated_at' in config_data and config_data['updated_at']:
                            config_data['updated_at'] = datetime.fromisoformat(config_data['updated_at'])

                        schedules = []
                        for schedule_data in config_data.get('schedules', []):
                            if 'created_at' in schedule_data and schedule_data['created_at']:
                                schedule_data['created_at'] = datetime.fromisoformat(schedule_data['created_at'])
                            if 'last_run' in schedule_data and schedule_data['last_run']:
                                schedule_data['last_run'] = datetime.fromisoformat(schedule_data['last_run'])
                            if 'next_run' in schedule_data and schedule_data['next_run']:
                                schedule_data['next_run'] = datetime.fromisoformat(schedule_data['next_run'])

                            schedule_data['backup_type'] = BackupType(schedule_data['backup_type'])
                            schedule_data['compression'] = CompressionType(schedule_data['compression'])
                            schedules.append(BackupSchedule(**schedule_data))

                        config_data['schedules'] = schedules

                        if 'retention_policy' in config_data:
                            config_data['retention_policy'] = RetentionPolicy(**config_data['retention_policy'])

                        self.backup_configs[vm_name] = BackupConfig(**config_data)

            if os.path.exists(self.backup_metadata_file):
                with open(self.backup_metadata_file, 'r') as f:
                    data = json.load(f)
                    for backup_id, metadata in data.items():
                        metadata['created_at'] = datetime.fromisoformat(metadata['created_at'])
                        if metadata.get('completed_at'):
                            metadata['completed_at'] = datetime.fromisoformat(metadata['completed_at'])
                        metadata['backup_type'] = BackupType(metadata['backup_type'])
                        metadata['status'] = BackupStatus(metadata['status'])
                        metadata['compression'] = CompressionType(metadata['compression'])

                        self.backup_metadata[backup_id] = BackupMetadata(**metadata)

        except Exception as e:
            self.logger.error(f"Failed to load backup configurations: {e}")

    def save_configurations(self):
        """Save backup configurations to disk"""
        try:
            config_data = {}
            for vm_name, config in self.backup_configs.items():
                config_dict = asdict(config)
                if config_dict.get('created_at'):
                    config_dict['created_at'] = config_dict['created_at'].isoformat()
                if config_dict.get('updated_at'):
                    config_dict['updated_at'] = config_dict['updated_at'].isoformat()

                for schedule in config_dict.get('schedules', []):
                    if schedule.get('created_at'):
                        schedule['created_at'] = schedule['created_at'].isoformat()
                    if schedule.get('last_run'):
                        schedule['last_run'] = schedule['last_run'].isoformat()
                    if schedule.get('next_run'):
                        schedule['next_run'] = schedule['next_run'].isoformat()
                    schedule['backup_type'] = schedule['backup_type'].value
                    schedule['compression'] = schedule['compression'].value

                config_data[vm_name] = config_dict

            with open(self.backup_config_file, 'w') as f:
                json.dump(config_data, f, indent=2, default=str)

            metadata_data = {}
            for backup_id, metadata in self.backup_metadata.items():
                metadata_dict = asdict(metadata)
                metadata_dict['created_at'] = metadata_dict['created_at'].isoformat()
                if metadata_dict.get('completed_at'):
                    metadata_dict['completed_at'] = metadata_dict['completed_at'].isoformat()
                metadata_dict['backup_type'] = metadata_dict['backup_type'].value
                metadata_dict['status'] = metadata_dict['status'].value
                metadata_dict['compression'] = metadata_dict['compression'].value
                metadata_data[backup_id] = metadata_dict

            with open(self.backup_metadata_file, 'w') as f:
                json.dump(metadata_data, f, indent=2, default=str)

        except Exception as e:
            self.logger.error(f"Failed to save backup configurations: {e}")

    def create_backup_config(self, vm_name: str, backup_dir: str,
                           schedules: List[BackupSchedule] = None,
                           retention_policy: RetentionPolicy = None) -> bool:
        """Create backup configuration for a VM"""
        try:
            if schedules is None:
                schedules = [BackupSchedule(
                    name="daily_backup",
                    backup_type=BackupType.INCREMENTAL,
                    frequency="daily",
                    time="02:00",
                    retention_days=30,
                    created_at=datetime.now()
                )]

            if retention_policy is None:
                retention_policy = RetentionPolicy()

            config = BackupConfig(
                vm_name=vm_name,
                backup_dir=backup_dir,
                schedules=schedules,
                retention_policy=retention_policy,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )

            self.backup_configs[vm_name] = config
            self.save_configurations()

            self.logger.info(f"Created backup configuration for VM: {vm_name}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to create backup config for {vm_name}: {e}")
            return False

    def update_backup_config(self, vm_name: str, **kwargs) -> bool:
        """Update backup configuration for a VM"""
        try:
            if vm_name not in self.backup_configs:
                self.logger.error(f"No backup config found for VM: {vm_name}")
                return False

            config = self.backup_configs[vm_name]

            for key, value in kwargs.items():
                if hasattr(config, key):
                    setattr(config, key, value)

            config.updated_at = datetime.now()
            self.save_configurations()

            self.logger.info(f"Updated backup configuration for VM: {vm_name}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to update backup config for {vm_name}: {e}")
            return False

    def delete_backup_config(self, vm_name: str) -> bool:
        """Delete backup configuration for a VM"""
        try:
            if vm_name in self.backup_configs:
                del self.backup_configs[vm_name]
                self.save_configurations()
                self.logger.info(f"Deleted backup configuration for VM: {vm_name}")
                return True
            return False

        except Exception as e:
            self.logger.error(f"Failed to delete backup config for {vm_name}: {e}")
            return False

    def generate_backup_id(self, vm_name: str, backup_type: BackupType) -> str:
        """Generate unique backup ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{vm_name}_{backup_type.value}_{timestamp}"

    def calculate_checksum(self, file_path: str) -> str:
        """Calculate SHA256 checksum of a file"""
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except Exception as e:
            self.logger.error(f"Failed to calculate checksum for {file_path}: {e}")
            return ""

    def compress_file(self, source_path: str, target_path: str,
                     compression: CompressionType, level: int = 6) -> bool:
        """Compress a file using specified compression type"""
        try:
            if compression == CompressionType.GZIP:
                with open(source_path, 'rb') as f_in:
                    with gzip.open(target_path, 'wb', compresslevel=level) as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif compression == CompressionType.BZIP2:
                import bz2
                with open(source_path, 'rb') as f_in:
                    with bz2.open(target_path, 'wb', compresslevel=level) as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif compression == CompressionType.XZ:
                import lzma
                with open(source_path, 'rb') as f_in:
                    with lzma.open(target_path, 'wb', preset=level) as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif compression == CompressionType.LZ4:
                result = subprocess.run([
                    'lz4', '-z', f'-{level}', source_path, target_path
                ], capture_output=True, text=True)
                return result.returncode == 0
            else:
                shutil.copy2(source_path, target_path)

            return True

        except Exception as e:
            self.logger.error(f"Failed to compress {source_path}: {e}")
            return False

    def encrypt_file(self, file_path: str, encryption_key: str) -> bool:
        """Encrypt a file using OpenSSL (system command)"""
        try:
            encrypted_path = file_path + '.enc'

            cmd = [
                'openssl', 'enc', '-aes-256-cbc', '-salt',
                '-in', file_path,
                '-out', encrypted_path,
                '-pass', f'pass:{encryption_key}'
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                os.remove(file_path)
                os.rename(encrypted_path, file_path)
                return True
            else:
                self.logger.error(f"OpenSSL encryption failed: {result.stderr}")
                return False

        except Exception as e:
            self.logger.error(f"Failed to encrypt {file_path}: {e}")
            return False

    def create_backup(self, vm_name: str, backup_type: BackupType = BackupType.FULL,
                     compression: CompressionType = CompressionType.GZIP,
                     encrypt: bool = False) -> Optional[str]:
        """Create a backup of the specified VM"""
        backup_id = self.generate_backup_id(vm_name, backup_type)
        try:
            if vm_name not in self.backup_configs:
                self.logger.error(f"No backup configuration found for VM: {vm_name}")
                return None

            config = self.backup_configs[vm_name]

            metadata = BackupMetadata(
                backup_id=backup_id,
                vm_name=vm_name,
                backup_type=backup_type,
                status=BackupStatus.RUNNING,
                created_at=datetime.now(),
                compression=compression,
                encrypted=encrypt
            )

            self.backup_metadata[backup_id] = metadata
            self.save_configurations()

            self.logger.info(f"Starting {backup_type.value} backup for VM: {vm_name}")

            vm_path = os.path.expanduser(f"~/vms_linux/{vm_name}")
            if not os.path.exists(vm_path):
                raise Exception(f"VM path not found: {vm_path}")

            backup_dir = os.path.join(config.backup_dir, backup_id)
            os.makedirs(backup_dir, exist_ok=True)
            metadata.backup_path = backup_dir

            start_time = time.time()

            success = False
            if backup_type == BackupType.FULL:
                success = self._create_full_backup(vm_path, backup_dir, metadata)
            elif backup_type == BackupType.INCREMENTAL:
                success = self._create_incremental_backup(vm_path, backup_dir, metadata, config)
            elif backup_type == BackupType.DIFFERENTIAL:
                success = self._create_differential_backup(vm_path, backup_dir, metadata, config)
            elif backup_type == BackupType.SNAPSHOT:
                success = self._create_snapshot_backup(vm_path, backup_dir, metadata)
            else:
                raise Exception(f"Unsupported backup type: {backup_type}")

            end_time = time.time()
            metadata.duration_seconds = end_time - start_time
            metadata.completed_at = datetime.now()

            if success:
                metadata.size_bytes = self._calculate_directory_size(backup_dir)

                if compression != CompressionType.NONE:
                    compressed_path = f"{backup_dir}.tar.{compression.value}"
                    if self._create_compressed_archive(backup_dir, compressed_path, compression):
                        metadata.compressed_size_bytes = os.path.getsize(compressed_path)
                        shutil.rmtree(backup_dir)
                        metadata.backup_path = compressed_path

                if encrypt and config.encryption_key:
                    if self.encrypt_file(metadata.backup_path, config.encryption_key):
                        metadata.encrypted = True

                if os.path.isfile(metadata.backup_path):
                    metadata.checksum = self.calculate_checksum(metadata.backup_path)

                metadata.status = BackupStatus.COMPLETED
                self.logger.info(f"Backup completed successfully: {backup_id}")

                if config.schedules and any(s.verify_after_backup for s in config.schedules):
                    self._verify_backup(backup_id)

            else:
                metadata.status = BackupStatus.FAILED
                metadata.error_message = "Backup operation failed"
                self.logger.error(f"Backup failed: {backup_id}")

            self.save_configurations()
            return backup_id if success else None

        except Exception as e:
            self.logger.error(f"Failed to create backup for {vm_name}: {e}")
            if backup_id in self.backup_metadata:
                self.backup_metadata[backup_id].status = BackupStatus.FAILED
                self.backup_metadata[backup_id].error_message = str(e)
                self.save_configurations()
            return None

    def _create_full_backup(self, vm_path: str, backup_dir: str,
                           metadata: BackupMetadata) -> bool:
        """Create a full backup"""
        try:
            self.logger.info("Creating full backup...")

            for item in os.listdir(vm_path):
                source = os.path.join(vm_path, item)
                target = os.path.join(backup_dir, item)

                if os.path.isdir(source):
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)

            metadata.file_count = len(os.listdir(backup_dir))
            return True

        except Exception as e:
            self.logger.error(f"Full backup failed: {e}")
            return False

    def _create_incremental_backup(self, vm_path: str, backup_dir: str,
                                  metadata: BackupMetadata, config: BackupConfig) -> bool:
        """Create an incremental backup"""
        try:
            self.logger.info("Creating incremental backup...")

            last_backup = self._find_last_backup(metadata.vm_name)
            if not last_backup:
                self.logger.info("No previous backup found, creating full backup instead")
                return self._create_full_backup(vm_path, backup_dir, metadata)

            metadata.parent_backup_id = last_backup.backup_id
            last_backup_time = last_backup.created_at

            file_count = 0
            for root, dirs, files in os.walk(vm_path):
                for file in files:
                    source_path = os.path.join(root, file)

                    if os.path.getmtime(source_path) > last_backup_time.timestamp():
                        rel_path = os.path.relpath(source_path, vm_path)
                        target_path = os.path.join(backup_dir, rel_path)

                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        shutil.copy2(source_path, target_path)
                        file_count += 1

            metadata.file_count = file_count
            return True

        except Exception as e:
            self.logger.error(f"Incremental backup failed: {e}")
            return False

    def _create_differential_backup(self, vm_path: str, backup_dir: str,
                                   metadata: BackupMetadata, config: BackupConfig) -> bool:
        """Create a differential backup"""
        try:
            self.logger.info("Creating differential backup...")

            last_full_backup = self._find_last_full_backup(metadata.vm_name)
            if not last_full_backup:
                self.logger.info("No previous full backup found, creating full backup instead")
                return self._create_full_backup(vm_path, backup_dir, metadata)

            metadata.parent_backup_id = last_full_backup.backup_id
            last_full_backup_time = last_full_backup.created_at

            file_count = 0
            for root, dirs, files in os.walk(vm_path):
                for file in files:
                    source_path = os.path.join(root, file)

                    if os.path.getmtime(source_path) > last_full_backup_time.timestamp():
                        rel_path = os.path.relpath(source_path, vm_path)
                        target_path = os.path.join(backup_dir, rel_path)

                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        shutil.copy2(source_path, target_path)
                        file_count += 1

            metadata.file_count = file_count
            return True

        except Exception as e:
            self.logger.error(f"Differential backup failed: {e}")
            return False

    def _create_snapshot_backup(self, vm_path: str, backup_dir: str,
                               metadata: BackupMetadata) -> bool:
        """Create a snapshot-based backup"""
        try:
            self.logger.info("Creating snapshot backup...")

            config_file = os.path.join(vm_path, "config.json")
            if not os.path.exists(config_file):
                return self._create_full_backup(vm_path, backup_dir, metadata)

            with open(config_file, 'r') as f:
                # vm_config = json.load(f)
                json.load(f)  # Read config but don't store if not used

            disk_files = []
            for file in os.listdir(vm_path):
                if file.endswith(('.qcow2', '.img', '.raw')):
                    disk_files.append(os.path.join(vm_path, file))

            for disk_file in disk_files:
                snapshot_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                cmd = ['qemu-img', 'snapshot', '-c', snapshot_name, disk_file]
                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode != 0:
                    self.logger.warning(f"Failed to create snapshot for {disk_file}: {result.stderr}")
                    shutil.copy2(disk_file, os.path.join(backup_dir, os.path.basename(disk_file)))
                else:
                    snapshot_file = os.path.join(backup_dir, f"{os.path.basename(disk_file)}.snapshot")
                    cmd = ['qemu-img', 'convert', '-f', 'qcow2', '-O', 'qcow2',
                           f"{disk_file}@{snapshot_name}", snapshot_file]
                    subprocess.run(cmd, capture_output=True, text=True)

            for item in os.listdir(vm_path):
                if not item.endswith(('.qcow2', '.img', '.raw')):
                    source = os.path.join(vm_path, item)
                    target = os.path.join(backup_dir, item)

                    if os.path.isdir(source):
                        shutil.copytree(source, target)
                    else:
                        shutil.copy2(source, target)

            metadata.file_count = len(os.listdir(backup_dir))
            return True

        except Exception as e:
            self.logger.error(f"Snapshot backup failed: {e}")
            return False

    def _find_last_backup(self, vm_name: str) -> Optional[BackupMetadata]:
        """Find the last backup for a VM"""
        try:
            vm_backups = [b for b in self.backup_metadata.values()
                         if b.vm_name == vm_name and b.status == BackupStatus.COMPLETED]

            if not vm_backups:
                return None

            sorted_backups = sorted(vm_backups, key=lambda b: b.created_at, reverse=True)
            return sorted_backups[0]

        except Exception as e:
            self.logger.error(f"Failed to find last backup: {e}")
            return None

    def _find_last_full_backup(self, vm_name: str) -> Optional[BackupMetadata]:
        """Find the last full backup for a VM"""
        try:
            full_backups = [b for b in self.backup_metadata.values()
                           if b.vm_name == vm_name and
                           b.backup_type == BackupType.FULL and
                           b.status == BackupStatus.COMPLETED]

            if not full_backups:
                return None

            sorted_backups = sorted(full_backups, key=lambda b: b.created_at, reverse=True)
            return sorted_backups[0]

        except Exception as e:
            self.logger.error(f"Failed to find last full backup: {e}")
            return None

    def _calculate_directory_size(self, directory: str) -> int:
        """Calculate total size of a directory in bytes"""
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(directory):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if os.path.exists(filepath) and os.path.isfile(filepath):
                        total_size += os.path.getsize(filepath)
        except Exception as e:
            self.logger.error(f"Failed to calculate directory size: {e}")
        return total_size

    def _create_compressed_archive(self, source_dir: str, target_path: str,
                                  compression: CompressionType) -> bool:
        """Create compressed archive of directory"""
        try:
            self.logger.info(f"Creating compressed archive: {target_path}")
            mode = 'w'
            if compression == CompressionType.GZIP:
                mode = 'w:gz'
            elif compression == CompressionType.BZIP2:
                mode = 'w:bz2'
            elif compression == CompressionType.XZ:
                mode = 'w:xz'
            elif compression == CompressionType.LZ4:
                tar_file = f"{target_path}.tar"
                with tarfile.open(tar_file, "w") as tar:
                    tar.add(source_dir, arcname=os.path.basename(source_dir))

                result = subprocess.run(['lz4', '-z', tar_file, target_path], capture_output=True, text=True)

                if os.path.exists(tar_file):
                    os.remove(tar_file)

                return result.returncode == 0

            with tarfile.open(target_path, mode) as tar:
                tar.add(source_dir, arcname=os.path.basename(source_dir))

            return True

        except Exception as e:
            self.logger.error(f"Failed to create compressed archive: {e}")
            return False

    def _verify_backup(self, backup_id: str) -> bool:
        """Verify backup integrity"""
        try:
            if backup_id not in self.backup_metadata:
                self.logger.error(f"Backup ID not found: {backup_id}")
                return False

            metadata = self.backup_metadata[backup_id]
            metadata.status = BackupStatus.VERIFYING
            self.save_configurations()

            self.logger.info(f"Verifying backup: {backup_id}")

            if not os.path.exists(metadata.backup_path):
                self.logger.error(f"Backup path not found: {metadata.backup_path}")
                metadata.verification_status = "failed"
                metadata.status = BackupStatus.FAILED
                metadata.error_message = "Backup files not found"
                self.save_configurations()
                return False

            if os.path.isfile(metadata.backup_path):
                verification_checksum = self.calculate_checksum(metadata.backup_path)

                if metadata.checksum and metadata.checksum != verification_checksum:
                    self.logger.error(f"Checksum mismatch for backup {backup_id}")
                    metadata.verification_status = "failed"
                    metadata.status = BackupStatus.FAILED
                    metadata.error_message = "Checksum verification failed"
                    self.save_configurations()
                    return False

                metadata.verification_checksum = verification_checksum
            else:
                if not os.path.isdir(metadata.backup_path):
                    self.logger.error(f"Backup path is neither file nor directory: {metadata.backup_path}")
                    metadata.verification_status = "failed"
                    metadata.status = BackupStatus.FAILED
                    metadata.error_message = "Invalid backup format"
                    self.save_configurations()
                    return False

                if metadata.file_count > 0:
                    actual_file_count = sum(len(files) for _, _, files in os.walk(metadata.backup_path))
                    if actual_file_count < metadata.file_count:
                        self.logger.warning(f"File count mismatch: expected {metadata.file_count}, found {actual_file_count}")

            metadata.verification_status = "verified"
            metadata.status = BackupStatus.VERIFIED
            self.save_configurations()

            self.logger.info(f"Backup verification completed successfully: {backup_id}")
            return True

        except Exception as e:
            self.logger.error(f"Backup verification failed: {e}")
            if backup_id in self.backup_metadata:
                self.backup_metadata[backup_id].verification_status = "failed"
                self.backup_metadata[backup_id].status = BackupStatus.FAILED
                self.backup_metadata[backup_id].error_message = str(e)
                self.save_configurations()
            return False

    def restore_backup(self, backup_id: str, restore_path: str = None,
                      point_in_time: datetime = None) -> bool:
        """Restore a backup with point-in-time recovery"""
        try:
            if backup_id not in self.backup_metadata:
                self.logger.error(f"Backup not found: {backup_id}")
                return False

            metadata = self.backup_metadata[backup_id]

            if metadata.status not in [BackupStatus.COMPLETED, BackupStatus.VERIFIED]:
                self.logger.error(f"Cannot restore backup with status: {metadata.status}")
                return False

            self.logger.info(f"Starting restore of backup: {backup_id}")

            if restore_path is None:
                restore_path = os.path.expanduser(f"~/vms_linux/{metadata.vm_name}_restored")

            os.makedirs(restore_path, exist_ok=True)

            if point_in_time:
                return self._restore_point_in_time(metadata, restore_path, point_in_time)

            backup_path = metadata.backup_path

            if metadata.encrypted:
                decrypted_path = backup_path + '.decrypted'
                if not self._decrypt_backup(backup_path, decrypted_path, metadata.vm_name):
                    return False
                backup_path = decrypted_path

            if backup_path.endswith(('.tar.gz', '.tar.bz2', '.tar.xz', '.tar')):
                with tarfile.open(backup_path, 'r:*') as tar:
                    tar.extractall(path=restore_path)
            elif backup_path.endswith('.tar.lz4'):
                 temp_tar = os.path.join(restore_path, "temp.tar")
                 result = subprocess.run(['lz4', '-d', backup_path, temp_tar], capture_output=True, text=True)
                 if result.returncode == 0:
                     with tarfile.open(temp_tar, 'r') as tar:
                         tar.extractall(path=restore_path)
                     if os.path.exists(temp_tar):
                         os.remove(temp_tar)
                 else:
                     self.logger.error(f"Failed to decompress lz4 archive: {result.stderr}")
            else:
                if os.path.isdir(backup_path):
                    shutil.copytree(backup_path, restore_path, dirs_exist_ok=True)
                else:
                    shutil.copy2(backup_path, restore_path)

            if metadata.encrypted and os.path.exists(backup_path + '.decrypted'):
                os.remove(backup_path + '.decrypted')

            self.logger.info(f"Backup restored successfully to: {restore_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to restore backup {backup_id}: {e}")
            return False

    def _restore_point_in_time(self, metadata: BackupMetadata, restore_path: str,
                              target_time: datetime) -> bool:
        """Restore to a specific point in time"""
        try:
            self.logger.info(f"Performing point-in-time restore to: {target_time}")

            vm_backups = [
                backup for backup in self.backup_metadata.values()
                if (backup.vm_name == metadata.vm_name and
                    backup.created_at <= target_time and
                    backup.status in [BackupStatus.COMPLETED, BackupStatus.VERIFIED])
            ]

            if not vm_backups:
                self.logger.error("No backups found for point-in-time restore")
                return False

            vm_backups.sort(key=lambda b: b.created_at)

            full_backup = next((b for b in vm_backups if b.backup_type == BackupType.FULL), None)

            if not full_backup:
                self.logger.error("No full backup found for point-in-time restore")
                return False

            if not self.restore_backup(full_backup.backup_id, restore_path):
                return False

            for backup in vm_backups:
                if (backup.backup_type in [BackupType.INCREMENTAL, BackupType.DIFFERENTIAL] and
                    backup.created_at > full_backup.created_at):

                    temp_restore_path = restore_path + '_temp'
                    if self.restore_backup(backup.backup_id, temp_restore_path):
                        self._merge_backup_changes(temp_restore_path, restore_path)
                        shutil.rmtree(temp_restore_path)

            self.logger.info(f"Point-in-time restore completed to: {target_time}")
            return True

        except Exception as e:
            self.logger.error(f"Point-in-time restore failed: {e}")
            return False

    def _decrypt_backup(self, encrypted_path: str, decrypted_path: str, vm_name: str) -> bool:
        """Decrypt an encrypted backup using OpenSSL"""
        try:
            if vm_name not in self.backup_configs:
                return False

            config = self.backup_configs[vm_name]
            if not config.encryption_key:
                return False

            cmd = [
                'openssl', 'enc', '-aes-256-cbc', '-d', '-salt',
                '-in', encrypted_path,
                '-out', decrypted_path,
                '-pass', f'pass:{config.encryption_key}'
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                return True
            else:
                self.logger.error(f"OpenSSL decryption failed: {result.stderr}")
                return False

        except Exception as e:
            self.logger.error(f"Failed to decrypt backup: {e}")
            return False

    def _merge_backup_changes(self, source_path: str, target_path: str):
        """Merge changes from incremental/differential backup"""
        try:
            for root, dirs, files in os.walk(source_path):
                for file in files:
                    source_file = os.path.join(root, file)
                    rel_path = os.path.relpath(source_file, source_path)
                    target_file = os.path.join(target_path, rel_path)

                    os.makedirs(os.path.dirname(target_file), exist_ok=True)
                    shutil.copy2(source_file, target_file)

        except Exception as e:
            self.logger.error(f"Failed to merge backup changes: {e}")

    def list_backups(self, vm_name: str = None) -> List[BackupMetadata]:
        """List all backups, optionally filtered by VM name"""
        backups = list(self.backup_metadata.values())

        if vm_name:
            backups = [b for b in backups if b.vm_name == vm_name]

        backups.sort(key=lambda b: b.created_at, reverse=True)
        return backups

    def delete_backup(self, backup_id: str) -> bool:
        """Delete a backup"""
        try:
            if backup_id not in self.backup_metadata:
                return False

            metadata = self.backup_metadata[backup_id]

            if os.path.exists(metadata.backup_path):
                if os.path.isdir(metadata.backup_path):
                    shutil.rmtree(metadata.backup_path)
                else:
                    os.remove(metadata.backup_path)

            del self.backup_metadata[backup_id]
            self.save_configurations()

            self.logger.info(f"Deleted backup: {backup_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to delete backup {backup_id}: {e}")
            return False

    def cleanup_old_backups(self, vm_name: str = None) -> int:
        """Clean up old backups based on retention policy"""
        try:
            cleaned_count = 0
            vms_to_clean = [vm_name] if vm_name else list(self.backup_configs.keys())

            for vm in vms_to_clean:
                if vm not in self.backup_configs:
                    continue

                config = self.backup_configs[vm]
                retention = config.retention_policy

                if not retention.auto_cleanup:
                    continue

                vm_backups = self.list_backups(vm)

                if len(vm_backups) <= retention.max_total_backups:
                    continue

                vm_backups.sort(key=lambda b: b.created_at)

                now = datetime.now()
                backups_to_keep = set()

                # Daily
                for d in range(retention.daily_retention):
                    day_cutoff = now - timedelta(days=d)
                    day_backups = [b for b in vm_backups if b.created_at.date() == day_cutoff.date()]
                    if day_backups:
                        backups_to_keep.add(max(day_backups, key=lambda x: x.created_at).backup_id)

                # Weekly
                for w in range(retention.weekly_retention):
                    week_cutoff = now - timedelta(weeks=w)
                    week_backups = [b for b in vm_backups if b.created_at.isocalendar()[1] == week_cutoff.isocalendar()[1] and b.created_at.year == week_cutoff.year]
                    if week_backups:
                        backups_to_keep.add(max(week_backups, key=lambda x: x.created_at).backup_id)

                # Monthly
                for m in range(retention.monthly_retention):
                    month_cutoff = now - timedelta(days=m*30)
                    month_backups = [b for b in vm_backups if b.created_at.month == month_cutoff.month and b.created_at.year == month_cutoff.year]
                    if month_backups:
                        backups_to_keep.add(max(month_backups, key=lambda x: x.created_at).backup_id)

                # Yearly
                for y in range(retention.yearly_retention):
                    year_cutoff = now - timedelta(days=y*365)
                    year_backups = [b for b in vm_backups if b.created_at.year == year_cutoff.year]
                    if year_backups:
                        backups_to_keep.add(max(year_backups, key=lambda x: x.created_at).backup_id)

                # Delete backups not in the keep set
                for backup in vm_backups:
                    if backup.backup_id not in backups_to_keep:
                        if self.delete_backup(backup.backup_id):
                            cleaned_count += 1

            self.logger.info(f"Cleaned up {cleaned_count} old backups")
            return cleaned_count

        except Exception as e:
            self.logger.error(f"Failed to cleanup old backups: {e}")
            return 0

    def start_scheduler(self):
        """Start the backup scheduler"""
        if self.scheduler_running:
            return

        self.scheduler_running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        self.logger.info("Backup scheduler started")

    def stop_scheduler(self):
        """Stop the backup scheduler"""
        self.scheduler_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        self.logger.info("Backup scheduler stopped")

    def _scheduler_loop(self):
        """Main scheduler loop"""
        while self.scheduler_running:
            try:
                for vm_name, config in self.backup_configs.items():
                    for schedule in config.schedules:
                        if schedule.enabled and self._should_run_backup(schedule):
                            self.logger.info(f"Running scheduled backup: {schedule.name} for {vm_name}")

                            backup_id = self.create_backup(
                                vm_name=vm_name,
                                backup_type=schedule.backup_type,
                                compression=schedule.compression,
                                encrypt=schedule.encryption_enabled
                            )

                            if backup_id:
                                schedule.last_run = datetime.now()
                                schedule.next_run = self._calculate_next_run(schedule)
                                self.save_configurations()

                self._run_scheduled_cleanup()
                time.sleep(60)

            except Exception as e:
                self.logger.error(f"Scheduler error: {e}")
                time.sleep(60)

    def _should_run_backup(self, schedule: BackupSchedule) -> bool:
        """Check if a backup should run based on schedule"""
        now = datetime.now()

        if schedule.next_run and now < schedule.next_run:
            return False

        if not self._is_scheduled_time(schedule, now):
            return False

        if schedule.frequency == "weekly" and not self._is_scheduled_day(schedule, now):
            return False

        if schedule.frequency == "monthly" and now.day != schedule.day_of_month:
            return False

        return True

    def _is_scheduled_time(self, schedule: BackupSchedule, now: datetime) -> bool:
        """Check if current time matches scheduled time"""
        if not schedule.time:
            return True

        try:
            scheduled_hour, scheduled_minute = map(int, schedule.time.split(':'))
            return (now.hour == scheduled_hour and abs(now.minute - scheduled_minute) < 2)
        except:
            return True

    def _is_scheduled_day(self, schedule: BackupSchedule, now: datetime) -> bool:
        """Check if current day matches scheduled days"""
        if not schedule.days_of_week:
            return True

        current_day = now.strftime("%A").lower()
        return current_day in [day.lower() for day in schedule.days_of_week]

    def _calculate_next_run(self, schedule: BackupSchedule) -> datetime:
        """Calculate next run time for a schedule"""
        now = datetime.now()

        if schedule.frequency == "hourly":
            return now + timedelta(hours=1)

        hour, minute = 0, 0
        if schedule.time:
            try:
                hour, minute = map(int, schedule.time.split(':'))
            except ValueError:
                pass

        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if next_run <= now:
            next_run += timedelta(days=1)

        if schedule.frequency == "daily":
            return next_run

        elif schedule.frequency == "weekly":
            if schedule.days_of_week:
                days_of_week = [d.lower() for d in schedule.days_of_week]
                day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
                day_nums = sorted([day_map[d] for d in days_of_week if d in day_map])

                current_day_num = now.weekday()

                for day_num in day_nums:
                    if day_num >= current_day_num:
                        days_ahead = day_num - current_day_num
                        if days_ahead == 0 and now.time() > next_run.time():
                            continue
                        return next_run + timedelta(days=days_ahead)

                # If no day this week, go to the first scheduled day of next week
                days_ahead = 7 - current_day_num + day_nums[0]
                return next_run + timedelta(days=days_ahead)

        elif schedule.frequency == "monthly":
            day = schedule.day_of_month or 1

            try:
                next_run = next_run.replace(day=day)
            except ValueError: # Handle cases like day 31 in a 30-day month
                next_run = next_run.replace(day=1, month=next_run.month+1)

            if next_run <= now:
                if now.month == 12:
                    next_run = next_run.replace(year=now.year + 1, month=1)
                else:
                    next_run = next_run.replace(month=now.month + 1)
            return next_run

        return now + timedelta(days=1)

    def _run_scheduled_cleanup(self):
        """Run scheduled cleanup of old backups"""
        try:
            for vm_name, config in self.backup_configs.items():
                retention = config.retention_policy
                if retention.auto_cleanup:
                    last_cleanup_file = os.path.join(self.config_dir, f".last_cleanup_{vm_name}")

                    should_cleanup = True
                    if os.path.exists(last_cleanup_file):
                        with open(last_cleanup_file, 'r') as f:
                            last_cleanup = datetime.fromisoformat(f.read().strip())

                        if retention.cleanup_schedule == "daily":
                            should_cleanup = (datetime.now() - last_cleanup).days >= 1
                        elif retention.cleanup_schedule == "weekly":
                            should_cleanup = (datetime.now() - last_cleanup).days >= 7

                    if should_cleanup:
                        self.cleanup_old_backups(vm_name)
                        with open(last_cleanup_file, 'w') as f:
                            f.write(datetime.now().isoformat())

        except Exception as e:
            self.logger.error(f"Scheduled cleanup failed: {e}")

def create_backup_dashboard(vm_name: str = None) -> Panel:
    """Create backup management dashboard"""
    backup_manager = BackupManager()
    backups = backup_manager.list_backups(vm_name)

    table = Table(title=f"Backup Dashboard{' - ' + vm_name if vm_name else ''}")
    table.add_column("Backup ID", style="cyan", no_wrap=True)
    table.add_column("VM", style="green")
    table.add_column("Type", style="yellow")
    table.add_column("Status", style="blue")
    table.add_column("Size", style="magenta")
    table.add_column("Created", style="white")
    table.add_column("Duration", style="red")

    for backup in backups[:20]:
        size = format_bytes(backup.compressed_size_bytes or backup.size_bytes)
        duration = f"{backup.duration_seconds:.1f}s" if backup.duration_seconds > 0 else "N/A"

        status_emoji = {
            BackupStatus.COMPLETED: "✅", BackupStatus.VERIFIED: "🔒",
            BackupStatus.FAILED: "❌", BackupStatus.RUNNING: "🔄",
            BackupStatus.PENDING: "⏳", BackupStatus.CANCELLED: "🚫",
            BackupStatus.VERIFYING: "🔍"
        }
        status_text = f"{status_emoji.get(backup.status, '❓')} {backup.status.value}"

        table.add_row(
            backup.backup_id[:20] + ("..." if len(backup.backup_id) > 20 else ""),
            backup.vm_name,
            backup.backup_type.value.title(),
            status_text,
            size,
            backup.created_at.strftime("%Y-%m-%d %H:%M"),
            duration
        )

    return Panel(table, border_style="blue", title="🗄️ Backup Management")

def format_bytes(bytes_value: int) -> str:
    """Format bytes to human readable format"""
    if bytes_value is None or bytes_value == 0: return "0 B"
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_index = 0
    size = float(bytes_value)
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.1f} {units[unit_index]}"

def _show_backup_list(backup_manager: BackupManager):
    """Show detailed backup list"""
    vm_name = questionary.text("Filter by VM name (leave empty for all):").ask()
    vm_name = vm_name if vm_name else None

    backups = backup_manager.list_backups(vm_name)

    if not backups:
        console.print("❌ No backups found")
        wait_for_enter()
        return

    table = Table(title="Backup Details")
    table.add_column("ID", style="cyan")
    table.add_column("VM", style="green")
    table.add_column("Type", style="yellow")
    table.add_column("Status", style="blue")
    table.add_column("Size", style="magenta")
    table.add_column("Files", style="white")
    table.add_column("Created", style="red")
    table.add_column("Path", style="dim")

    for backup in backups:
        size = format_bytes(backup.compressed_size_bytes or backup.size_bytes)
        table.add_row(
            backup.backup_id, backup.vm_name, backup.backup_type.value,
            backup.status.value, size, str(backup.file_count),
            backup.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            backup.backup_path[:50] + ("..." if len(backup.backup_path) > 50 else "")
        )

    console.print(table)
    wait_for_enter()

def _create_manual_backup(backup_manager: BackupManager):
    """Create a manual backup"""
    vms_dir = os.path.expanduser("~/vms_linux")
    if not os.path.exists(vms_dir):
        console.print("❌ No VMs directory found")
        wait_for_enter()
        return

    vm_names = [d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))]

    if not vm_names:
        console.print("❌ No VMs found")
        wait_for_enter()
        return

    vm_name = questionary.select("Select VM to backup:", choices=vm_names).ask()
    if not vm_name: return

    backup_type = questionary.select(
        "Backup type:",
        choices=[
            questionary.Choice(title, value=bt) for title, bt in [
                ("Full Backup", BackupType.FULL),
                ("Incremental Backup", BackupType.INCREMENTAL),
                ("Differential Backup", BackupType.DIFFERENTIAL),
                ("Snapshot Backup", BackupType.SNAPSHOT)
            ]
        ]
    ).ask()

    compression = questionary.select(
        "Compression:",
        choices=[
            questionary.Choice(title, value=ct) for title, ct in [
                ("GZIP (Recommended)", CompressionType.GZIP),
                ("BZIP2 (Better compression)", CompressionType.BZIP2),
                ("XZ (Best compression)", CompressionType.XZ),
                ("None", CompressionType.NONE)
            ]
        ]
    ).ask()

    encrypt = questionary.confirm("Enable encryption?", default=False).ask()

    if vm_name not in backup_manager.backup_configs:
        backup_dir = os.path.expanduser(f"~/.glint/backups/{vm_name}")
        backup_manager.create_backup_config(vm_name, backup_dir)

    console.print(f"🔄 Creating {backup_type.value} backup for {vm_name}...")

    with Progress() as progress:
        task = progress.add_task("Creating backup...", total=None)
        backup_id = backup_manager.create_backup(vm_name, backup_type, compression, encrypt)
        progress.update(task, completed=1)

    if backup_id:
        console.print(f"✅ Backup created successfully: {backup_id}")
    else:
        console.print("❌ Backup creation failed")

    wait_for_enter()

def _configure_backup_schedule(backup_manager: BackupManager):
    """Configure backup schedule for a VM"""
    console.print("🚧 Schedule configuration coming soon...")
    wait_for_enter()

def _restore_backup_menu(backup_manager: BackupManager):
    """Restore backup menu"""
    backups = [b for b in backup_manager.list_backups() if b.status in [BackupStatus.COMPLETED, BackupStatus.VERIFIED]]

    if not backups:
        console.print("❌ No completed backups available for restore")
        wait_for_enter()
        return

    backup_choices = [
        questionary.Choice(f"{b.vm_name} - {b.backup_type.value} - {b.created_at.strftime('%Y-%m-%d %H:%M')}", value=b.backup_id)
        for b in backups
    ]

    backup_id = questionary.select("Select backup to restore:", choices=backup_choices).ask()
    if not backup_id: return

    restore_path = questionary.text("Restore path (leave empty for default):", default="").ask()
    restore_path = restore_path if restore_path else None

    console.print(f"🔄 Restoring backup {backup_id}...")

    if backup_manager.restore_backup(backup_id, restore_path):
        console.print("✅ Backup restored successfully")
    else:
        console.print("❌ Backup restore failed")

    wait_for_enter()

def _delete_backup_menu(backup_manager: BackupManager):
    """Delete backup menu"""
    backups = backup_manager.list_backups()
    if not backups:
        console.print("❌ No backups available")
        wait_for_enter()
        return

    backup_choices = [
        questionary.Choice(f"{b.vm_name} - {b.backup_type.value} - {b.created_at.strftime('%Y-%m-%d %H:%M')} - {b.status.value}", value=b.backup_id)
        for b in backups
    ]

    backup_id = questionary.select("Select backup to delete:", choices=backup_choices).ask()
    if not backup_id: return

    if questionary.confirm("Are you sure you want to delete this backup?", default=False).ask():
        if backup_manager.delete_backup(backup_id):
            console.print("✅ Backup deleted successfully")
        else:
            console.print("❌ Failed to delete backup")

    wait_for_enter()

def _cleanup_backups_menu(backup_manager: BackupManager):
    """Cleanup old backups menu"""
    vm_name = questionary.text("VM name (leave empty for all VMs):").ask()
    vm_name = vm_name if vm_name else None

    console.print("🧹 Cleaning up old backups...")
    cleaned_count = backup_manager.cleanup_old_backups(vm_name)
    console.print(f"✅ Cleaned up {cleaned_count} old backups")
    wait_for_enter()

def _verify_backup_menu(backup_manager: BackupManager):
    """Verify backup menu"""
    backups = [b for b in backup_manager.list_backups() if b.status == BackupStatus.COMPLETED]
    if not backups:
        console.print("❌ No completed backups available for verification")
        wait_for_enter()
        return

    backup_choices = [
        questionary.Choice(f"{b.vm_name} - {b.backup_type.value} - {b.created_at.strftime('%Y-%m-%d %H:%M')}", value=b.backup_id)
        for b in backups
    ]

    backup_id = questionary.select("Select backup to verify:", choices=backup_choices).ask()
    if not backup_id: return

    console.print(f"🔍 Verifying backup {backup_id}...")

    if backup_manager._verify_backup(backup_id):
        console.print("✅ Backup verification successful")
    else:
        console.print("❌ Backup verification failed")

    wait_for_enter()

def _show_backup_statistics(backup_manager: BackupManager):
    """Show backup statistics"""
    backups = backup_manager.list_backups()
    if not backups:
        console.print("❌ No backup statistics available")
        wait_for_enter()
        return

    total_backups = len(backups)
    total_size = sum(b.compressed_size_bytes or b.size_bytes for b in backups)
    status_counts = {s.value: 0 for s in BackupStatus}
    type_counts = {t.value: 0 for t in BackupType}

    for b in backups:
        status_counts[b.status.value] += 1
        type_counts[b.backup_type.value] += 1

    stats_table = Table(title="Backup Statistics")
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Value", style="green")
    stats_table.add_row("Total Backups", str(total_backups))
    stats_table.add_row("Total Size", format_bytes(total_size))
    stats_table.add_row("Average Size", format_bytes(total_size // total_backups if total_backups > 0 else 0))
    console.print(stats_table)

    status_table = Table(title="Status Breakdown")
    status_table.add_column("Status", style="yellow")
    status_table.add_column("Count", style="blue")
    for status, count in status_counts.items():
        if count > 0: status_table.add_row(status.title(), str(count))
    console.print(status_table)

    wait_for_enter()

def backup_management_menu(vm_name=None, vm_paths=None):
    """Interactive backup management menu"""
    backup_manager = BackupManager()

    if vm_name and vm_name not in backup_manager.backup_configs:
        from .backup_integration import configure_vm_for_backup # Lazy import
        clear_screen()
        console.print(f"[bold blue]Backup Management - {vm_name}[/bold blue]\n[yellow]VM '{vm_name}' is not configured for backup.[/yellow]")
        if questionary.confirm("Would you like to configure it now?").ask():
            if configure_vm_for_backup(backup_manager, vm_name, vm_paths):
                console.print("[green]VM configured for backup successfully![/green]")
            else:
                console.print("[yellow]Backup configuration cancelled.[/yellow]")
        wait_for_enter()

    while True:
        clear_screen()
        console.print(create_backup_dashboard(vm_name))

        choice = questionary.select(
            "Backup Management",
            choices=[
                "📋 Show Backup List", "📦 Create Manual Backup", "⏱️ Configure Backup Schedule",
                "🔄 Restore Backup", "🗑️ Delete Backup", "🧹 Cleanup Old Backups",
                "✅ Verify Backup", "📊 Show Backup Statistics", questionary.Separator(), "🔙 Back"
            ],
            use_indicator=True
        ).ask()

        if choice == "🔙 Back" or choice is None: break

        menu_map = {
            "📋 Show Backup List": _show_backup_list,
            "📦 Create Manual Backup": _create_manual_backup,
            "⏱️ Configure Backup Schedule": _configure_backup_schedule,
            "🔄 Restore Backup": _restore_backup_menu,
            "🗑️ Delete Backup": _delete_backup_menu,
            "🧹 Cleanup Old Backups": _cleanup_backups_menu,
            "✅ Verify Backup": _verify_backup_menu,
            "📊 Show Backup Statistics": _show_backup_statistics
        }

        if choice in menu_map:
            menu_map[choice](backup_manager)

def clear_screen():
    """Clear the terminal screen"""
    os.system('cls' if os.name == 'nt' else 'clear')
