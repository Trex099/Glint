# Made by trex099
# https://github.com/Trex099/Glint
"""
Multi-Disk Support Module for Linux VMs

This module provides functionality to manage multiple disks for a VM.
"""

import os
import json
import subprocess
from enum import Enum
from dataclasses import dataclass
from typing import List

class DiskType(Enum):
    """Disk type enumeration"""
    DATA = "data"
    CACHE = "cache"
    BACKUP = "backup"


class DiskInterface(Enum):
    """Disk interface enumeration"""
    VIRTIO = "virtio"
    SCSI = "scsi"
    IDE = "ide"


@dataclass
class DiskConfig:
    """Disk configuration"""
    name: str
    size: str
    disk_type: DiskType
    encrypted: bool = False
    interface: DiskInterface = DiskInterface.VIRTIO
    path: str = ""


class DiskManager:
    """Multi-disk manager for Linux VMs"""
    
    def __init__(self, vm_name: str):
        """
        Initialize disk manager.
        
        Args:
            vm_name: Name of the VM
        """
        from ..main import get_vm_paths
        
        self.vm_name = vm_name
        self.paths = get_vm_paths(vm_name)
        self.config_file = os.path.join(self.paths["dir"], "disks.json")
        self.disks = self._load_disks()
    
    def _load_disks(self) -> List[DiskConfig]:
        """Load disk configurations from file"""
        if not os.path.exists(self.config_file):
            # Create default configuration with base disk
            base_disk = DiskConfig(
                name="base",
                size=self._get_disk_size(self.paths["base"]),
                disk_type=DiskType.DATA,
                path=self.paths["base"]
            )
            self._save_disks([base_disk])
            return [base_disk]
        
        try:
            with open(self.config_file, 'r') as f:
                disk_data = json.load(f)
            
            disks = []
            for disk in disk_data:
                disk_config = DiskConfig(
                    name=disk["name"],
                    size=disk["size"],
                    disk_type=DiskType[disk["disk_type"]],
                    encrypted=disk.get("encrypted", False),
                    interface=DiskInterface[disk.get("interface", "VIRTIO")],
                    path=disk.get("path", "")
                )
                
                # Set default path if not specified
                if not disk_config.path:
                    disk_config.path = os.path.join(self.paths["dir"], f"{disk_config.name}.qcow2")
                
                disks.append(disk_config)
            
            return disks
        except Exception:
            # Return default configuration on error
            base_disk = DiskConfig(
                name="base",
                size=self._get_disk_size(self.paths["base"]),
                disk_type=DiskType.DATA,
                path=self.paths["base"]
            )
            return [base_disk]
    
    def _save_disks(self, disks: List[DiskConfig]) -> bool:
        """Save disk configurations to file"""
        try:
            disk_data = []
            for disk in disks:
                disk_data.append({
                    "name": disk.name,
                    "size": disk.size,
                    "disk_type": disk.disk_type.name,
                    "encrypted": disk.encrypted,
                    "interface": disk.interface.name,
                    "path": disk.path
                })
            
            with open(self.config_file, 'w') as f:
                json.dump(disk_data, f, indent=2)
            
            return True
        except Exception:
            return False
    
    def _get_disk_size(self, disk_path: str) -> str:
        """Get disk size in human-readable format"""
        if not os.path.exists(disk_path):
            return "0G"
        
        try:
            result = subprocess.run(
                ['qemu-img', 'info', '--output=json', disk_path],
                capture_output=True,
                text=True,
                check=True
            )
            
            import json
            info = json.loads(result.stdout)
            
            # Convert to human-readable format
            size_bytes = info.get('virtual-size', 0)
            if size_bytes < 1024**3:
                return f"{size_bytes / 1024**2:.1f}M"
            else:
                return f"{size_bytes / 1024**3:.1f}G"
        except Exception:
            return "0G"
    
    def list_disks(self) -> List[DiskConfig]:
        """List all disks"""
        return self.disks
    
    def add_disk(self, disk_config: DiskConfig) -> bool:
        """
        Add a new disk.
        
        Args:
            disk_config: Disk configuration
            
        Returns:
            True if successful, False otherwise
        """
        # Check if disk already exists
        if any(disk.name == disk_config.name for disk in self.disks):
            return False
        
        # Set disk path if not specified
        if not disk_config.path:
            disk_config.path = os.path.join(self.paths["dir"], f"{disk_config.name}.qcow2")
        
        # Create disk
        try:
            if disk_config.encrypted:
                # Create encrypted disk using real LUKS encryption
                from .encryption import create_encrypted_disk
                from .secure_passphrase import get_passphrase_manager
                
                # Get passphrase from secure storage
                passphrase_manager = get_passphrase_manager(self.vm_name, self.paths["dir"])
                passphrase = passphrase_manager.get_passphrase()
                
                if not passphrase:
                    # Prompt for passphrase if not stored
                    import questionary
                    passphrase = questionary.password("Enter encryption passphrase for new disk:").ask()
                    if not passphrase:
                        return False
                
                # Update path to indicate encryption
                encrypted_path = disk_config.path.replace('.qcow2', '_encrypted.qcow2')
                
                success, result = create_encrypted_disk(
                    path=encrypted_path,
                    size=disk_config.size,
                    passphrase=passphrase
                )
                
                if not success:
                    return False
                
                disk_config.path = encrypted_path
            else:
                # Create unencrypted disk
                cmd = ['qemu-img', 'create', '-f', 'qcow2', disk_config.path, disk_config.size]
                subprocess.run(cmd, check=True, capture_output=True)
            
            # Add to disk list
            self.disks.append(disk_config)
            self._save_disks(self.disks)
            
            return True
        except Exception:
            return False
    
    def remove_disk(self, disk_name: str) -> bool:
        """
        Remove a disk.
        
        Args:
            disk_name: Name of the disk to remove
            
        Returns:
            True if successful, False otherwise
        """
        # Cannot remove base disk
        if disk_name == "base":
            return False
        
        # Find disk
        disk = next((d for d in self.disks if d.name == disk_name), None)
        if not disk:
            return False
        
        # Remove disk file
        try:
            if os.path.exists(disk.path):
                os.remove(disk.path)
            
            # Remove from disk list
            self.disks = [d for d in self.disks if d.name != disk_name]
            self._save_disks(self.disks)
            
            return True
        except Exception:
            return False
    
    def resize_disk(self, disk_name: str, new_size: str) -> bool:
        """
        Resize a disk.
        
        Args:
            disk_name: Name of the disk to resize
            new_size: New size (e.g., '50G', '100G')
            
        Returns:
            True if successful, False otherwise
        """
        # Find disk
        disk = next((d for d in self.disks if d.name == disk_name), None)
        if not disk:
            return False
        
        # Resize disk
        try:
            from .disk_resize import resize_disk as do_resize
            
            success = do_resize(disk.path, new_size)
            if success:
                # Update disk size
                disk.size = new_size
                self._save_disks(self.disks)
            
            return success
        except Exception:
            return False