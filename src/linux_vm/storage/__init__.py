# Made by trex099
# https://github.com/Trex099/Glint
"""
Storage Management Module for Linux VMs

This module provides enhanced storage capabilities including:
- Multiple disk support
- Storage pools
- Disk encryption
- Snapshot management
- Backup operations
"""

from .multi_disk import DiskManager, DiskConfig, DiskType, DiskInterface
from .encryption import LUKSManager, EncryptionConfig, EncryptionStatus
from .snapshots import (
    SnapshotManager, SnapshotMetadata, SnapshotStatus, SnapshotType,
    RetentionPolicy as SnapshotRetentionPolicy, create_snapshot_dashboard
)
from .pools import (
    StoragePoolManager, PoolConfig, PoolQuota, PoolType, PoolStatus,
    PoolStats, ReplicationTarget, ReplicationStatus, 
    create_pool_dashboard, storage_pool_menu, format_bytes
)
from .monitoring import (
    DiskPerformanceMonitor, DiskMetrics, DiskPerformanceThresholds,
    DiskPerformanceAlert, DiskMetricType, create_disk_performance_dashboard,
    disk_performance_menu
)
from .integration import handle_snapshot_menu
from .disk_management import disk_management_menu
from .backup import (
    BackupManager, BackupType, BackupStatus, CompressionType,
    BackupSchedule, RetentionPolicy as BackupRetentionPolicy, BackupMetadata, BackupConfig,
    create_backup_dashboard, backup_management_menu
)
from .templates import (
    StorageTemplateManager, StorageTemplate, DiskTemplate, TemplateType,
    TemplateStatus, storage_templates_menu
)

__version__ = "1.0.0"
__all__ = [
    'DiskManager',
    'DiskConfig',
    'DiskType',
    'DiskInterface',
    'LUKSManager',
    'EncryptionConfig',
    'EncryptionStatus',
    'SnapshotManager',
    'SnapshotMetadata',
    'SnapshotStatus',
    'SnapshotType',
    'SnapshotRetentionPolicy',
    'create_snapshot_dashboard',
    'StoragePoolManager',
    'PoolConfig',
    'PoolQuota',
    'PoolType',
    'PoolStatus',
    'PoolStats',
    'ReplicationTarget',
    'ReplicationStatus',
    'create_pool_dashboard',
    'storage_pool_menu',
    'format_bytes',
    'DiskPerformanceMonitor',
    'DiskMetrics',
    'DiskPerformanceThresholds',
    'DiskPerformanceAlert',
    'DiskMetricType',
    'create_disk_performance_dashboard',
    'disk_performance_menu',
    'handle_snapshot_menu',
    'disk_management_menu',
    'BackupManager',
    'BackupType',
    'BackupStatus',
    'CompressionType',
    'BackupSchedule',
    'BackupRetentionPolicy',
    'BackupMetadata',
    'BackupConfig',
    'create_backup_dashboard',
    'backup_management_menu',
    'StorageTemplateManager',
    'StorageTemplate',
    'DiskTemplate',
    'TemplateType',
    'TemplateStatus',
    'storage_templates_menu'
]