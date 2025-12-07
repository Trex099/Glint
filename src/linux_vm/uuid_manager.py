# Made by trex099
# https://github.com/Trex099/Glint
"""
UUID and System Identifier Management Module

This module handles the generation and management of unique identifiers
for Linux VMs to ensure each VM has completely unique system identifiers.
"""

import os
import sys
import uuid
import random
import subprocess
import json
import hashlib
from typing import Dict, Optional, List, Any
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core_utils import print_info, print_success, print_warning, print_error, run_command_live


class SystemIdentifiers:
    """Container for all system identifiers"""
    
    def __init__(self):
        self.vm_uuid = str(uuid.uuid4())
        self.machine_id = self._generate_machine_id()
        self.mac_address = self._generate_mac_address()
        self.disk_uuid = str(uuid.uuid4())
        self.partition_uuid = str(uuid.uuid4())
        self.filesystem_uuid = str(uuid.uuid4())
        self.boot_uuid = str(uuid.uuid4())
        self.swap_uuid = str(uuid.uuid4())
        self.dmi_uuid = str(uuid.uuid4())
        self.smbios_uuid = str(uuid.uuid4())
        self.cpu_serial = self._generate_cpu_serial()
        self.motherboard_serial = self._generate_motherboard_serial()
        self.bios_uuid = str(uuid.uuid4())
        self.created_at = datetime.now().isoformat()
    
    def _generate_machine_id(self) -> str:
        """Generate a unique 32-character machine ID"""
        return hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
    
    def _generate_mac_address(self) -> str:
        """Generate a unique MAC address with proper vendor prefix"""
        # Use QEMU's vendor prefix (52:54:00) for consistency
        return f"52:54:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"
    
    def _generate_cpu_serial(self) -> str:
        """Generate a unique CPU serial number"""
        return f"CPU{random.randint(100000, 999999)}{random.randint(1000, 9999)}"
    
    def _generate_motherboard_serial(self) -> str:
        """Generate a unique motherboard serial number"""
        return f"MB{random.randint(100000, 999999)}{random.randint(1000, 9999)}"
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for serialization"""
        return {
            'vm_uuid': self.vm_uuid,
            'machine_id': self.machine_id,
            'mac_address': self.mac_address,
            'disk_uuid': self.disk_uuid,
            'partition_uuid': self.partition_uuid,
            'filesystem_uuid': self.filesystem_uuid,
            'boot_uuid': self.boot_uuid,
            'swap_uuid': self.swap_uuid,
            'dmi_uuid': self.dmi_uuid,
            'smbios_uuid': self.smbios_uuid,
            'cpu_serial': self.cpu_serial,
            'motherboard_serial': self.motherboard_serial,
            'bios_uuid': self.bios_uuid,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> 'SystemIdentifiers':
        """Create from dictionary"""
        instance = cls()
        for key, value in data.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        return instance


class UUIDManager:
    """
    Manages UUID and system identifier generation and persistence for Linux VMs
    """
    
    def __init__(self, vms_dir: str = None):
        """Initialize the UUID manager"""
        from config import CONFIG
        self.vms_dir = vms_dir or CONFIG['VMS_DIR_LINUX']
    
    def get_vm_paths(self, vm_name: str) -> Dict[str, str]:
        """Get all paths for a VM"""
        vm_dir = os.path.abspath(os.path.join(self.vms_dir, vm_name))
        return {
            "dir": vm_dir,
            "base": os.path.join(vm_dir, "base.qcow2"),
            "overlay": os.path.join(vm_dir, "overlay.qcow2"),
            "seed": os.path.join(vm_dir, "uefi-seed.fd"),
            "instance": os.path.join(vm_dir, "uefi-instance.fd"),
            "identifiers": os.path.join(vm_dir, "identifiers.json"),
            "shared_dir": os.path.join(vm_dir, "shared"),
            "config": os.path.join(vm_dir, "config.json")
        }
    
    def generate_fresh_identifiers(self, vm_name: str, force_regenerate: bool = False) -> SystemIdentifiers:
        """
        Generate fresh system identifiers for a VM
        
        Args:
            vm_name: Name of the VM
            force_regenerate: If True, regenerate even if identifiers exist
        
        Returns:
            SystemIdentifiers object with all unique identifiers
        """
        paths = self.get_vm_paths(vm_name)
        
        # Check if identifiers already exist
        if not force_regenerate and os.path.exists(paths['identifiers']):
            try:
                with open(paths['identifiers'], 'r', encoding='utf-8') as f:
                    data = json.load(f)
                print_info(f"Using existing identifiers for VM '{vm_name}'")
                return SystemIdentifiers.from_dict(data)
            except (json.JSONDecodeError, KeyError) as e:
                print_warning(f"Corrupted identifiers file for VM '{vm_name}', regenerating: {e}")
        
        # Generate new identifiers
        identifiers = SystemIdentifiers()
        
        # Save identifiers to file
        os.makedirs(paths['dir'], exist_ok=True)
        with open(paths['identifiers'], 'w', encoding='utf-8') as f:
            json.dump(identifiers.to_dict(), f, indent=2)
        
        print_success(f"Generated fresh identifiers for VM '{vm_name}'")
        return identifiers
    
    def regenerate_disk_identifiers(self, vm_name: str) -> SystemIdentifiers:
        """
        Regenerate disk-specific identifiers (for overlay/base image recreation)
        
        This is called when creating new overlays or regenerating base images
        to ensure disk UUIDs are unique.
        """
        paths = self.get_vm_paths(vm_name)
        
        # Load existing identifiers
        identifiers = self.generate_fresh_identifiers(vm_name, force_regenerate=False)
        
        # Regenerate disk-specific UUIDs
        identifiers.disk_uuid = str(uuid.uuid4())
        identifiers.partition_uuid = str(uuid.uuid4())
        identifiers.filesystem_uuid = str(uuid.uuid4())
        identifiers.boot_uuid = str(uuid.uuid4())
        identifiers.swap_uuid = str(uuid.uuid4())
        
        # Save updated identifiers
        with open(paths['identifiers'], 'w', encoding='utf-8') as f:
            json.dump(identifiers.to_dict(), f, indent=2)
        
        print_success(f"Regenerated disk identifiers for VM '{vm_name}'")
        return identifiers
    
    def reset_uefi_variables(self, vm_name: str) -> bool:
        """
        Reset UEFI variables by recreating the OVMF_VARS.fd file
        
        This ensures TPM/Secure Boot/UEFI variables are fresh for each VM instance
        """
        try:
            from config import CONFIG
            from core_utils import find_first_existing_path
            
            paths = self.get_vm_paths(vm_name)
            
            # Find the UEFI VARS template
            uefi_vars_template = find_first_existing_path(CONFIG['UEFI_VARS_PATHS'])
            if not uefi_vars_template:
                print_error("Could not find UEFI VARS template file")
                return False
            
            # Reset the seed file (used as template)
            if os.path.exists(paths['seed']):
                os.remove(paths['seed'])
            
            # Copy fresh template
            subprocess.run(['cp', uefi_vars_template, paths['seed']], check=True)
            
            # Reset instance file if it exists
            if os.path.exists(paths['instance']):
                os.remove(paths['instance'])
            
            print_success(f"Reset UEFI variables for VM '{vm_name}'")
            return True
            
        except Exception as e:
            print_error(f"Failed to reset UEFI variables for VM '{vm_name}': {e}")
            return False
    
    def apply_identifiers_to_qemu_command(self, base_command: List[str], 
                                        identifiers: SystemIdentifiers) -> List[str]:
        """
        Apply system identifiers to QEMU command line
        
        Args:
            base_command: Base QEMU command as list of strings
            identifiers: SystemIdentifiers object
        
        Returns:
            Modified command with identifier parameters
        """
        # Create a copy to avoid modifying the original
        command = base_command.copy()
        
        # Find and replace or add UUID parameter
        uuid_added = False
        for i, arg in enumerate(command):
            if arg == '-uuid':
                if i + 1 < len(command):
                    command[i + 1] = identifiers.vm_uuid
                    uuid_added = True
                break
        
        if not uuid_added:
            command.extend(['-uuid', identifiers.vm_uuid])
        
        # Add SMBIOS information for hardware identifiers
        smbios_args = [
            '-smbios', f'type=1,manufacturer=QEMU,product=Standard PC,version=pc-i440fx-2.12,serial={identifiers.motherboard_serial},uuid={identifiers.smbios_uuid}',
            '-smbios', f'type=2,manufacturer=QEMU,product=Standard PC,version=pc-i440fx-2.12,serial={identifiers.motherboard_serial}',
            '-smbios', f'type=3,manufacturer=QEMU,version=pc-i440fx-2.12,serial={identifiers.cpu_serial}'
        ]
        command.extend(smbios_args)
        
        # Add machine-specific parameters
        machine_args = [
            '-machine', f'pc,accel=kvm,dump-guest-core=off'
        ]
        
        # Find existing machine parameter and replace or add
        machine_added = False
        for i, arg in enumerate(command):
            if arg == '-machine':
                if i + 1 < len(command):
                    # Preserve existing machine settings but ensure our settings are included
                    existing = command[i + 1]
                    if 'accel=kvm' not in existing:
                        existing += ',accel=kvm'
                    if 'dump-guest-core=off' not in existing:
                        existing += ',dump-guest-core=off'
                    command[i + 1] = existing
                    machine_added = True
                break
        
        if not machine_added:
            command.extend(machine_args)
        
        return command
    
    def create_post_install_script(self, vm_name: str, identifiers: SystemIdentifiers) -> str:
        """
        Create both automated and manual post-installation scripts
        
        This creates:
        1. An automated setup system that runs on first boot
        2. A legacy manual script for fallback
        """
        paths = self.get_vm_paths(vm_name)
        
        # Create the automated post-installation system
        try:
            from .auto_post_install import create_automated_post_install_system
            
            identifiers_dict = {
                'machine_id': identifiers.machine_id,
                'vm_uuid': identifiers.vm_uuid,
                'mac_address': identifiers.mac_address,
                'disk_uuid': identifiers.disk_uuid,
                'motherboard_serial': identifiers.motherboard_serial,
                'cpu_serial': identifiers.cpu_serial,
                'smbios_uuid': identifiers.smbios_uuid
            }
            
            # Create automated system
            create_automated_post_install_system(vm_name, paths['dir'], identifiers_dict)
            
        except Exception as e:
            print_warning(f"Failed to create automated post-install system: {e}")
            print_info("Falling back to manual script only")
        
        # Create legacy manual script for compatibility
        script_path = os.path.join(paths['shared_dir'], 'set_identifiers.sh')
        
        script_content = f"""#!/bin/bash
# Legacy manual post-installation script to set unique system identifiers
# Generated for VM: {vm_name}
# Created: {identifiers.created_at}

echo "Setting unique system identifiers for VM: {vm_name}"

# Set machine-id
echo "Setting machine-id..."
echo "{identifiers.machine_id}" | sudo tee /etc/machine-id > /dev/null
echo "{identifiers.machine_id}" | sudo tee /var/lib/dbus/machine-id > /dev/null

# Regenerate SSH host keys
echo "Regenerating SSH host keys..."
sudo rm -f /etc/ssh/ssh_host_*
sudo ssh-keygen -A

# Set hostname to include unique identifier
HOSTNAME_SUFFIX=$(echo "{identifiers.machine_id}" | cut -c1-8)
NEW_HOSTNAME="{vm_name}-$HOSTNAME_SUFFIX"
echo "Setting hostname to: $NEW_HOSTNAME"
echo "$NEW_HOSTNAME" | sudo tee /etc/hostname > /dev/null
sudo hostnamectl set-hostname "$NEW_HOSTNAME" 2>/dev/null || true

# Update /etc/hosts
sudo sed -i "s/127.0.1.1.*/127.0.1.1\\t$NEW_HOSTNAME/" /etc/hosts

# Clear systemd journal machine-id cache
sudo systemctl restart systemd-journald 2>/dev/null || true

# Regenerate any cached network configurations
if command -v netplan >/dev/null 2>&1; then
    echo "Regenerating netplan configuration..."
    sudo netplan generate 2>/dev/null || true
fi

# Clear any cached hardware information
sudo rm -f /var/lib/dhcp/dhclient.leases 2>/dev/null || true
sudo rm -f /var/lib/NetworkManager/*.lease 2>/dev/null || true

# Update GRUB if present (to reflect new machine-id in boot entries)
if command -v update-grub >/dev/null 2>&1; then
    echo "Updating GRUB configuration..."
    sudo update-grub 2>/dev/null || true
fi

echo "System identifiers have been set successfully!"
echo "Machine ID: {identifiers.machine_id}"
echo "VM UUID: {identifiers.vm_uuid}"
echo "MAC Address: {identifiers.mac_address}"
echo ""
echo "Please reboot the VM to ensure all changes take effect."
"""
        
        # Write script to shared directory
        os.makedirs(paths['shared_dir'], exist_ok=True)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        # Make script executable
        os.chmod(script_path, 0o755)
        
        print_success(f"Created post-install identifier script: {script_path}")
        return script_path
    
    def nuke_and_regenerate_all(self, vm_name: str) -> SystemIdentifiers:
        """
        Nuclear option: Regenerate ALL identifiers and reset UEFI variables
        
        This is called when doing a complete fresh start of a VM.
        """
        print_info(f"🔥 NUKE: Regenerating ALL identifiers for VM '{vm_name}'")
        
        # Generate completely fresh identifiers
        identifiers = self.generate_fresh_identifiers(vm_name, force_regenerate=True)
        
        # Reset UEFI variables
        self.reset_uefi_variables(vm_name)
        
        # Create post-install script
        self.create_post_install_script(vm_name, identifiers)
        
        print_success(f"🔥 NUKE complete: All identifiers regenerated for VM '{vm_name}'")
        return identifiers
    
    def get_identifiers(self, vm_name: str) -> Optional[SystemIdentifiers]:
        """Get existing identifiers for a VM"""
        paths = self.get_vm_paths(vm_name)
        
        if not os.path.exists(paths['identifiers']):
            return None
        
        try:
            with open(paths['identifiers'], 'r', encoding='utf-8') as f:
                data = json.load(f)
            return SystemIdentifiers.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            print_warning(f"Corrupted identifiers file for VM '{vm_name}': {e}")
            return None
    
    def list_vm_identifiers(self, vm_name: str = None) -> Dict[str, SystemIdentifiers]:
        """List identifiers for all VMs or a specific VM"""
        result = {}
        
        if vm_name:
            identifiers = self.get_identifiers(vm_name)
            if identifiers:
                result[vm_name] = identifiers
        else:
            # List all VMs
            if os.path.isdir(self.vms_dir):
                for vm_dir in os.listdir(self.vms_dir):
                    vm_path = os.path.join(self.vms_dir, vm_dir)
                    if os.path.isdir(vm_path):
                        identifiers = self.get_identifiers(vm_dir)
                        if identifiers:
                            result[vm_dir] = identifiers
        
        return result


# Global UUID manager instance
_uuid_manager = None

def get_uuid_manager() -> UUIDManager:
    """Get the global UUID manager instance"""
    global _uuid_manager
    if _uuid_manager is None:
        _uuid_manager = UUIDManager()
    return _uuid_manager