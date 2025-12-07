# Made by trex099
# https://github.com/Trex099/Glint
"""
Advanced Snapshot Management System for Linux VMs

This module provides comprehensive snapshot capabilities including:
- Branching snapshot support with tree structure
- Snapshot metadata management (descriptions, timestamps, tags)
- Snapshot tree visualization and navigation
- Snapshot merging and differential backup capabilities
- Snapshot cleanup and retention policy management
"""

import os
import json
import time
import uuid
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

from rich.console import Console
from rich.table import Table
from rich.tree import Tree
from rich.panel import Panel
# from rich.progress import Progress

console = Console()


class SnapshotStatus(Enum):
    """Snapshot status enumeration"""
    ACTIVE = "active"
    CREATING = "creating"
    MERGING = "merging"
    DELETING = "deleting"
    ERROR = "error"


class SnapshotType(Enum):
    """Snapshot type enumeration"""
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    BACKUP = "backup"
    CHECKPOINT = "checkpoint"


@dataclass
class SnapshotMetadata:
    """Snapshot metadata structure"""
    id: str
    name: str
    description: str
    timestamp: str
    tags: List[str]
    parent_id: Optional[str]
    children_ids: List[str]
    vm_name: str
    disk_path: str
    snapshot_path: str
    size_bytes: int
    status: SnapshotStatus
    snapshot_type: SnapshotType
    created_by: str
    retention_days: Optional[int]
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['status'] = self.status.value
        data['snapshot_type'] = self.snapshot_type.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SnapshotMetadata':
        """Create from dictionary"""
        data['status'] = SnapshotStatus(data['status'])
        data['snapshot_type'] = SnapshotType(data['snapshot_type'])
        return cls(**data)


@dataclass
class RetentionPolicy:
    """Snapshot retention policy configuration"""
    max_snapshots: int = 50
    max_age_days: int = 30
    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 12
    auto_cleanup: bool = True
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'RetentionPolicy':
        return cls(**data)


class SnapshotManager:
    """Advanced snapshot management system with branching support"""
    
    def __init__(self, vm_name: str, base_path: str = None):
        self.vm_name = vm_name
        self.base_path = base_path or f"vms_linux/{vm_name}"
        self.snapshots_dir = os.path.join(self.base_path, "snapshots")
        self.metadata_file = os.path.join(self.snapshots_dir, "metadata.json")
        self.policy_file = os.path.join(self.snapshots_dir, "retention_policy.json")
        
        # Ensure directories exist
        os.makedirs(self.snapshots_dir, exist_ok=True)
        
        # Load existing data
        self.snapshots: Dict[str, SnapshotMetadata] = self._load_metadata()
        self.retention_policy = self._load_retention_policy()
    
    def _load_metadata(self) -> Dict[str, SnapshotMetadata]:
        """Load snapshot metadata from file"""
        if not os.path.exists(self.metadata_file):
            return {}
        
        try:
            with open(self.metadata_file, 'r') as f:
                data = json.load(f)
                return {
                    snap_id: SnapshotMetadata.from_dict(snap_data)
                    for snap_id, snap_data in data.items()
                }
        except Exception as e:
            console.print(f"[red]Error loading snapshot metadata: {e}[/red]")
            return {}
    
    def _save_metadata(self):
        """Save snapshot metadata to file"""
        try:
            data = {
                snap_id: snap.to_dict()
                for snap_id, snap in self.snapshots.items()
            }
            with open(self.metadata_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            console.print(f"[red]Error saving snapshot metadata: {e}[/red]")
    
    def _load_retention_policy(self) -> RetentionPolicy:
        """Load retention policy from file"""
        if not os.path.exists(self.policy_file):
            policy = RetentionPolicy()
            self._save_retention_policy(policy)
            return policy
        
        try:
            with open(self.policy_file, 'r') as f:
                data = json.load(f)
                return RetentionPolicy.from_dict(data)
        except Exception as e:
            console.print(f"[red]Error loading retention policy: {e}[/red]")
            return RetentionPolicy()
    
    def _save_retention_policy(self, policy: RetentionPolicy):
        """Save retention policy to file"""
        try:
            with open(self.policy_file, 'w') as f:
                json.dump(policy.to_dict(), f, indent=2)
        except Exception as e:
            console.print(f"[red]Error saving retention policy: {e}[/red]")
    
    def _generate_snapshot_id(self) -> str:
        """Generate unique snapshot ID"""
        return str(uuid.uuid4())[:8]
    
    def _get_disk_size(self, disk_path: str) -> int:
        """Get disk size in bytes"""
        try:
            result = subprocess.run(
                ['qemu-img', 'info', '--output=json', disk_path],
                capture_output=True, text=True, check=True
            )
            info = json.loads(result.stdout)
            return info.get('actual-size', 0)
        except Exception:
            return 0
    
    def create_snapshot(self, 
                       name: str,
                       description: str = "",
                       tags: List[str] = None,
                       parent_id: str = None,
                       snapshot_type: SnapshotType = SnapshotType.MANUAL,
                       retention_days: int = None) -> str:
        """Create a new snapshot with metadata"""
        
        # Generate snapshot ID and paths
        snapshot_id = self._generate_snapshot_id()
        timestamp = datetime.now().isoformat()
        
        # Determine base disk path
        base_disk = os.path.join(self.base_path, "base.qcow2")
        if not os.path.exists(base_disk):
            raise FileNotFoundError(f"Base disk not found: {base_disk}")
        
        # Create snapshot path
        snapshot_path = os.path.join(self.snapshots_dir, f"snapshot_{snapshot_id}.qcow2")
        
        try:
            # Update parent's children list if parent specified
            if parent_id and parent_id in self.snapshots:
                self.snapshots[parent_id].children_ids.append(snapshot_id)
            
            # Create snapshot metadata
            metadata = SnapshotMetadata(
                id=snapshot_id,
                name=name,
                description=description,
                timestamp=timestamp,
                tags=tags or [],
                parent_id=parent_id,
                children_ids=[],
                vm_name=self.vm_name,
                disk_path=base_disk,
                snapshot_path=snapshot_path,
                size_bytes=0,  # Will be updated after creation
                status=SnapshotStatus.CREATING,
                snapshot_type=snapshot_type,
                created_by="glint",
                retention_days=retention_days
            )
            
            # Add to snapshots dict
            self.snapshots[snapshot_id] = metadata
            self._save_metadata()
            
            # Create the actual snapshot
            console.print(f"[yellow]Creating snapshot '{name}'...[/yellow]")
            
            # Use qemu-img to create snapshot
            cmd = [
                'qemu-img', 'create', '-f', 'qcow2',
                '-b', base_disk,
                '-F', 'qcow2',
                snapshot_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Failed to create snapshot: {result.stderr}")
            
            # Update metadata with actual size and status
            metadata.size_bytes = self._get_disk_size(snapshot_path)
            metadata.status = SnapshotStatus.ACTIVE
            self._save_metadata()
            
            console.print(f"[green]Snapshot '{name}' created successfully (ID: {snapshot_id})[/green]")
            return snapshot_id
            
        except Exception as e:
            # Clean up on error
            if snapshot_id in self.snapshots:
                del self.snapshots[snapshot_id]
                self._save_metadata()
            
            if os.path.exists(snapshot_path):
                os.remove(snapshot_path)
            
            console.print(f"[red]Error creating snapshot: {e}[/red]")
            raise
    
    def delete_snapshot(self, snapshot_id: str, force: bool = False) -> bool:
        """Delete a snapshot and handle dependencies"""
        
        if snapshot_id not in self.snapshots:
            console.print(f"[red]Snapshot {snapshot_id} not found[/red]")
            return False
        
        snapshot = self.snapshots[snapshot_id]
        
        # Check for children
        if snapshot.children_ids and not force:
            console.print("[red]Cannot delete snapshot with children. Use force=True to delete entire branch.[/red]")
            return False
        
        try:
            snapshot.status = SnapshotStatus.DELETING
            self._save_metadata()
            
            # Delete children first if force is True
            if force and snapshot.children_ids:
                for child_id in snapshot.children_ids.copy():
                    self.delete_snapshot(child_id, force=True)
            
            # Remove from parent's children list
            if snapshot.parent_id and snapshot.parent_id in self.snapshots:
                parent = self.snapshots[snapshot.parent_id]
                if snapshot_id in parent.children_ids:
                    parent.children_ids.remove(snapshot_id)
            
            # Delete the actual snapshot file
            if os.path.exists(snapshot.snapshot_path):
                os.remove(snapshot.snapshot_path)
            
            # Remove from metadata
            del self.snapshots[snapshot_id]
            self._save_metadata()
            
            console.print(f"[green]Snapshot {snapshot_id} deleted successfully[/green]")
            return True
            
        except Exception as e:
            console.print(f"[red]Error deleting snapshot: {e}[/red]")
            if snapshot_id in self.snapshots:
                self.snapshots[snapshot_id].status = SnapshotStatus.ERROR
                self._save_metadata()
            return False
    
    def restore_snapshot(self, snapshot_id: str) -> bool:
        """Restore VM to a specific snapshot"""
        
        if snapshot_id not in self.snapshots:
            console.print(f"[red]Snapshot {snapshot_id} not found[/red]")
            return False
        
        snapshot = self.snapshots[snapshot_id]
        
        if snapshot.status != SnapshotStatus.ACTIVE:
            console.print(f"[red]Cannot restore from snapshot with status: {snapshot.status.value}[/red]")
            return False
        
        try:
            # Create backup of current state
            backup_name = f"pre_restore_backup_{int(time.time())}"
            backup_id = self.create_snapshot(
                name=backup_name,
                description=f"Automatic backup before restoring to {snapshot.name}",
                snapshot_type=SnapshotType.BACKUP
            )
            
            # Copy snapshot to overlay
            overlay_path = os.path.join(self.base_path, "overlay.qcow2")
            
            # Create new overlay based on the snapshot
            cmd = [
                'qemu-img', 'create', '-f', 'qcow2',
                '-b', snapshot.snapshot_path,
                '-F', 'qcow2',
                overlay_path + ".new"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Failed to create new overlay: {result.stderr}")
            
            # Replace old overlay
            if os.path.exists(overlay_path):
                os.remove(overlay_path)
            if os.path.exists(overlay_path + ".new"):
                os.rename(overlay_path + ".new", overlay_path)
            
            console.print(f"[green]Successfully restored to snapshot '{snapshot.name}'[/green]")
            console.print(f"[yellow]Backup created: {backup_name} (ID: {backup_id})[/yellow]")
            return True
            
        except Exception as e:
            console.print(f"[red]Error restoring snapshot: {e}[/red]")
            return False
    
    def merge_snapshots(self, source_id: str, target_id: str) -> bool:
        """Merge source snapshot into target snapshot"""
        
        if source_id not in self.snapshots or target_id not in self.snapshots:
            console.print("[red]One or both snapshots not found[/red]")
            return False
        
        source = self.snapshots[source_id]
        target = self.snapshots[target_id]
        
        try:
            source.status = SnapshotStatus.MERGING
            target.status = SnapshotStatus.MERGING
            self._save_metadata()
            
            # Create merged snapshot
            # merged_path = os.path.join(self.snapshots_dir, f"merged_{int(time.time())}.qcow2")
            
            # Use qemu-img commit to merge
            cmd = ['qemu-img', 'commit', source.snapshot_path]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise RuntimeError(f"Failed to merge snapshots: {result.stderr}")
            
            # Update target metadata
            target.description += f" (merged with {source.name})"
            target.tags.extend([tag for tag in source.tags if tag not in target.tags])
            target.size_bytes = self._get_disk_size(target.snapshot_path)
            target.status = SnapshotStatus.ACTIVE
            
            # Remove source snapshot
            self.delete_snapshot(source_id, force=True)
            
            console.print("[green]Successfully merged snapshots[/green]")
            return True
            
        except Exception as e:
            console.print(f"[red]Error merging snapshots: {e}[/red]")
            # Restore status on error
            if source_id in self.snapshots:
                self.snapshots[source_id].status = SnapshotStatus.ACTIVE
            if target_id in self.snapshots:
                self.snapshots[target_id].status = SnapshotStatus.ACTIVE
            self._save_metadata()
            return False   
 
    def list_snapshots(self, include_metadata: bool = True) -> Dict[str, Any]:
        """List all snapshots with optional metadata"""
        
        if not include_metadata:
            return {snap_id: snap.name for snap_id, snap in self.snapshots.items()}
        
        return {
            snap_id: {
                'name': snap.name,
                'description': snap.description,
                'timestamp': snap.timestamp,
                'tags': snap.tags,
                'parent_id': snap.parent_id,
                'children_ids': snap.children_ids,
                'size_mb': round(snap.size_bytes / (1024 * 1024), 2),
                'status': snap.status.value,
                'type': snap.snapshot_type.value
            }
            for snap_id, snap in self.snapshots.items()
        }
    
    def get_snapshot_tree(self) -> Dict[str, Any]:
        """Get snapshot tree structure for visualization"""
        
        # Find root snapshots (no parent)
        roots = [snap for snap in self.snapshots.values() if snap.parent_id is None]
        
        def build_tree_node(snapshot: SnapshotMetadata) -> Dict[str, Any]:
            children = []
            for child_id in snapshot.children_ids:
                if child_id in self.snapshots:
                    children.append(build_tree_node(self.snapshots[child_id]))
            
            return {
                'id': snapshot.id,
                'name': snapshot.name,
                'description': snapshot.description,
                'timestamp': snapshot.timestamp,
                'tags': snapshot.tags,
                'status': snapshot.status.value,
                'type': snapshot.snapshot_type.value,
                'size_mb': round(snapshot.size_bytes / (1024 * 1024), 2),
                'children': children
            }
        
        return {
            'vm_name': self.vm_name,
            'total_snapshots': len(self.snapshots),
            'roots': [build_tree_node(root) for root in roots]
        }
    
    def visualize_snapshot_tree(self) -> Tree:
        """Create Rich Tree visualization of snapshots"""
        
        tree_data = self.get_snapshot_tree()
        tree = Tree(f"📸 Snapshots for {self.vm_name}")
        
        def add_tree_nodes(parent_tree: Tree, nodes: List[Dict]):
            for node in nodes:
                # Create node label with status indicators
                status_icon = {
                    'active': '✅',
                    'creating': '🔄',
                    'merging': '🔀',
                    'deleting': '🗑️',
                    'error': '❌'
                }.get(node['status'], '❓')
                
                type_icon = {
                    'manual': '👤',
                    'automatic': '🤖',
                    'backup': '💾',
                    'checkpoint': '🏁'
                }.get(node['type'], '📸')
                
                label = f"{status_icon} {type_icon} {node['name']} ({node['size_mb']} MB)"
                if node['description']:
                    label += f" - {node['description'][:50]}..."
                
                node_tree = parent_tree.add(label)
                
                # Add children recursively
                if node['children']:
                    add_tree_nodes(node_tree, node['children'])
        
        if tree_data['roots']:
            add_tree_nodes(tree, tree_data['roots'])
        else:
            tree.add("No snapshots found")
        
        return tree
    
    def search_snapshots(self, 
                        name_pattern: str = None,
                        tags: List[str] = None,
                        date_from: str = None,
                        date_to: str = None,
                        snapshot_type: SnapshotType = None) -> List[str]:
        """Search snapshots by various criteria"""
        
        results = []
        
        for snap_id, snapshot in self.snapshots.items():
            match = True
            
            # Name pattern matching
            if name_pattern and name_pattern.lower() not in snapshot.name.lower():
                match = False
            
            # Tag matching
            if tags and not any(tag in snapshot.tags for tag in tags):
                match = False
            
            # Date range matching
            if date_from or date_to:
                snap_date = datetime.fromisoformat(snapshot.timestamp)
                if date_from and snap_date < datetime.fromisoformat(date_from):
                    match = False
                if date_to and snap_date > datetime.fromisoformat(date_to):
                    match = False
            
            # Type matching
            if snapshot_type and snapshot.snapshot_type != snapshot_type:
                match = False
            
            if match:
                results.append(snap_id)
        
        return results
    
    def get_snapshot_info(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific snapshot"""
        
        if snapshot_id not in self.snapshots:
            return None
        
        snapshot = self.snapshots[snapshot_id]
        
        # Calculate relationships
        parent_name = None
        if snapshot.parent_id and snapshot.parent_id in self.snapshots:
            parent_name = self.snapshots[snapshot.parent_id].name
        
        children_names = []
        for child_id in snapshot.children_ids:
            if child_id in self.snapshots:
                children_names.append(self.snapshots[child_id].name)
        
        return {
            'id': snapshot.id,
            'name': snapshot.name,
            'description': snapshot.description,
            'timestamp': snapshot.timestamp,
            'tags': snapshot.tags,
            'parent_id': snapshot.parent_id,
            'parent_name': parent_name,
            'children_ids': snapshot.children_ids,
            'children_names': children_names,
            'vm_name': snapshot.vm_name,
            'disk_path': snapshot.disk_path,
            'snapshot_path': snapshot.snapshot_path,
            'size_bytes': snapshot.size_bytes,
            'size_mb': round(snapshot.size_bytes / (1024 * 1024), 2),
            'status': snapshot.status.value,
            'type': snapshot.snapshot_type.value,
            'created_by': snapshot.created_by,
            'retention_days': snapshot.retention_days,
            'age_days': (datetime.now() - datetime.fromisoformat(snapshot.timestamp)).days
        }
    
    def update_snapshot_metadata(self, 
                               snapshot_id: str,
                               name: str = None,
                               description: str = None,
                               tags: List[str] = None,
                               retention_days: int = None) -> bool:
        """Update snapshot metadata"""
        
        if snapshot_id not in self.snapshots:
            console.print(f"[red]Snapshot {snapshot_id} not found[/red]")
            return False
        
        snapshot = self.snapshots[snapshot_id]
        
        if name is not None:
            snapshot.name = name
        if description is not None:
            snapshot.description = description
        if tags is not None:
            snapshot.tags = tags
        if retention_days is not None:
            snapshot.retention_days = retention_days
        
        self._save_metadata()
        console.print("[green]Snapshot metadata updated successfully[/green]")
        return True
    
    def set_retention_policy(self, policy: RetentionPolicy):
        """Set snapshot retention policy"""
        self.retention_policy = policy
        self._save_retention_policy(policy)
        console.print("[green]Retention policy updated[/green]")
    
    def get_retention_policy(self) -> RetentionPolicy:
        """Get current retention policy"""
        return self.retention_policy
    
    def apply_retention_policy(self, dry_run: bool = False) -> Dict[str, List[str]]:
        """Apply retention policy and clean up old snapshots"""
        
        if not self.retention_policy.auto_cleanup:
            console.print("[yellow]Auto cleanup is disabled[/yellow]")
            return {'deleted': [], 'kept': []}
        
        now = datetime.now()
        to_delete = []
        to_keep = []
        
        # Group snapshots by type and age
        snapshots_by_age = []
        for snap_id, snapshot in self.snapshots.items():
            age_days = (now - datetime.fromisoformat(snapshot.timestamp)).days
            snapshots_by_age.append((age_days, snap_id, snapshot))
        
        # Sort by age (oldest first)
        snapshots_by_age.sort(key=lambda x: x[0], reverse=True)
        
        # Apply retention rules
        kept_count = 0
        daily_kept = {}
        weekly_kept = {}
        monthly_kept = {}
        
        for age_days, snap_id, snapshot in snapshots_by_age:
            should_keep = False
            
            # Check if snapshot has children (never delete if it has children)
            if snapshot.children_ids:
                should_keep = True
                to_keep.append(snap_id)
                continue
            
            # Check retention days for individual snapshots
            if snapshot.retention_days and age_days < snapshot.retention_days:
                should_keep = True
            
            # Check max age
            elif age_days < self.retention_policy.max_age_days:
                # Check daily retention
                if age_days < 7 and len(daily_kept) < self.retention_policy.keep_daily:
                    day_key = (now - timedelta(days=age_days)).strftime('%Y-%m-%d')
                    if day_key not in daily_kept:
                        daily_kept[day_key] = snap_id
                        should_keep = True
                
                # Check weekly retention
                elif age_days < 30 and len(weekly_kept) < self.retention_policy.keep_weekly:
                    week_key = (now - timedelta(days=age_days)).strftime('%Y-W%U')
                    if week_key not in weekly_kept:
                        weekly_kept[week_key] = snap_id
                        should_keep = True
                
                # Check monthly retention
                elif len(monthly_kept) < self.retention_policy.keep_monthly:
                    month_key = (now - timedelta(days=age_days)).strftime('%Y-%m')
                    if month_key not in monthly_kept:
                        monthly_kept[month_key] = snap_id
                        should_keep = True
            
            # Check max snapshots limit
            if should_keep and kept_count < self.retention_policy.max_snapshots:
                to_keep.append(snap_id)
                kept_count += 1
            else:
                to_delete.append(snap_id)
        
        # Execute deletions if not dry run
        if not dry_run and to_delete:
            console.print(f"[yellow]Applying retention policy: deleting {len(to_delete)} snapshots[/yellow]")
            for snap_id in to_delete:
                self.delete_snapshot(snap_id, force=False)
        
        return {
            'deleted': to_delete,
            'kept': to_keep,
            'policy': self.retention_policy.to_dict()
        }
    
    def export_snapshot_metadata(self, output_file: str = None) -> str:
        """Export snapshot metadata to JSON file"""
        
        if not output_file:
            output_file = f"{self.vm_name}_snapshots_export_{int(time.time())}.json"
        
        export_data = {
            'vm_name': self.vm_name,
            'export_timestamp': datetime.now().isoformat(),
            'snapshots': {snap_id: snap.to_dict() for snap_id, snap in self.snapshots.items()},
            'retention_policy': self.retention_policy.to_dict(),
            'tree_structure': self.get_snapshot_tree()
        }
        
        try:
            with open(output_file, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            console.print(f"[green]Snapshot metadata exported to {output_file}[/green]")
            return output_file
            
        except Exception as e:
            console.print(f"[red]Error exporting metadata: {e}[/red]")
            raise
    
    def import_snapshot_metadata(self, import_file: str, merge: bool = False) -> bool:
        """Import snapshot metadata from JSON file"""
        
        try:
            with open(import_file, 'r') as f:
                import_data = json.load(f)
            
            if not merge:
                # Replace all snapshots
                self.snapshots = {
                    snap_id: SnapshotMetadata.from_dict(snap_data)
                    for snap_id, snap_data in import_data['snapshots'].items()
                }
            else:
                # Merge with existing snapshots
                for snap_id, snap_data in import_data['snapshots'].items():
                    if snap_id not in self.snapshots:
                        self.snapshots[snap_id] = SnapshotMetadata.from_dict(snap_data)
            
            # Import retention policy if present
            if 'retention_policy' in import_data:
                self.retention_policy = RetentionPolicy.from_dict(import_data['retention_policy'])
                self._save_retention_policy(self.retention_policy)
            
            self._save_metadata()
            console.print("[green]Snapshot metadata imported successfully[/green]")
            return True
            
        except Exception as e:
            console.print(f"[red]Error importing metadata: {e}[/red]")
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive snapshot statistics"""
        
        if not self.snapshots:
            return {
                'total_snapshots': 0,
                'total_size_mb': 0,
                'by_status': {},
                'by_type': {},
                'oldest': None,
                'newest': None,
                'average_age_days': 0
            }
        
        now = datetime.now()
        total_size = sum(snap.size_bytes for snap in self.snapshots.values())
        ages = [(now - datetime.fromisoformat(snap.timestamp)).days for snap in self.snapshots.values()]
        
        # Count by status
        by_status = {}
        for snap in self.snapshots.values():
            status = snap.status.value
            by_status[status] = by_status.get(status, 0) + 1
        
        # Count by type
        by_type = {}
        for snap in self.snapshots.values():
            snap_type = snap.snapshot_type.value
            by_type[snap_type] = by_type.get(snap_type, 0) + 1
        
        # Find oldest and newest
        sorted_snaps = sorted(self.snapshots.values(), key=lambda x: x.timestamp)
        oldest = sorted_snaps[0] if sorted_snaps else None
        newest = sorted_snaps[-1] if sorted_snaps else None
        
        return {
            'total_snapshots': len(self.snapshots),
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'by_status': by_status,
            'by_type': by_type,
            'oldest': {
                'name': oldest.name,
                'timestamp': oldest.timestamp,
                'age_days': max(ages)
            } if oldest else None,
            'newest': {
                'name': newest.name,
                'timestamp': newest.timestamp,
                'age_days': min(ages)
            } if newest else None,
            'average_age_days': round(sum(ages) / len(ages), 1) if ages else 0
        }


def create_snapshot_dashboard(vm_name: str) -> Panel:
    """Create a comprehensive snapshot dashboard"""
    
    manager = SnapshotManager(vm_name)
    stats = manager.get_statistics()
    
    # Create main table
    table = Table(title=f"Snapshot Dashboard - {vm_name}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Total Snapshots", str(stats['total_snapshots']))
    table.add_row("Total Size", f"{stats['total_size_mb']} MB")
    table.add_row("Average Age", f"{stats['average_age_days']} days")
    
    if stats['oldest']:
        table.add_row("Oldest Snapshot", f"{stats['oldest']['name']} ({stats['oldest']['age_days']} days)")
    
    if stats['newest']:
        table.add_row("Newest Snapshot", f"{stats['newest']['name']} ({stats['newest']['age_days']} days)")
    
    # Add status breakdown
    for status, count in stats['by_status'].items():
        table.add_row(f"Status: {status.title()}", str(count))
    
    # Add type breakdown
    for snap_type, count in stats['by_type'].items():
        table.add_row(f"Type: {snap_type.title()}", str(count))
    
    return Panel(table, border_style="blue", title="📸 Snapshot Statistics")