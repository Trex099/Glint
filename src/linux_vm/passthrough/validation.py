# Made by trex099
# https://github.com/Trex099/Glint
"""
Passthrough Validation and Troubleshooting Module

This module provides comprehensive validation for PCI passthrough setup,
including IOMMU groups, device compatibility, and system requirements.
"""

import os
import sys
import logging
import subprocess
from typing import Dict, List, Optional, Tuple
# from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core_utils import (
    print_header, print_info, print_error
)

# Import the new error handling system
# from src.linux_vm.error_handling import (
#     GlintError, ErrorSeverity, ErrorCategory, get_error_handler,
#     safe_operation, HardwareError, ValidationError, SystemError
# )

logger = logging.getLogger(__name__)


class PassthroughValidator:
    """
    Comprehensive PCI Passthrough Validation System
    
    This class validates system requirements, IOMMU groups, and device
    compatibility for PCI passthrough operations.
    """
    
    def __init__(self):
        """Initialize the passthrough validator"""
        self.logger = logging.getLogger('glint.passthrough_validator')
        self.iommu_groups_path = "/sys/kernel/iommu_groups"
        self.pci_devices_path = "/sys/bus/pci/devices"
        
        self.logger.info("PassthroughValidator initialized")
    
    def validate_system_requirements(self) -> Tuple[bool, Dict[str, any]]:
        """
        Validate system requirements for PCI passthrough
        
        Returns:
            Tuple[bool, Dict]: (success, validation_info)
        """
        validation_info = {
            'virtualization_support': False,
            'iommu_support': False,
            'iommu_enabled': False,
            'vfio_support': False,
            'issues': [],
            'suggestions': []
        }
        
        try:
            # Check CPU virtualization support
            validation_info['virtualization_support'] = self._check_virtualization_support()
            if not validation_info['virtualization_support']:
                validation_info['issues'].append("CPU does not support virtualization (VT-x/AMD-V)")
                validation_info['suggestions'].append("Enable virtualization in BIOS/UEFI settings")
            
            # Check IOMMU support
            validation_info['iommu_support'] = self._check_iommu_support()
            if not validation_info['iommu_support']:
                validation_info['issues'].append("IOMMU is not supported or not enabled")
                validation_info['suggestions'].append("Enable IOMMU in BIOS and add intel_iommu=on or amd_iommu=on to kernel parameters")
            
            # Check if IOMMU is enabled
            validation_info['iommu_enabled'] = self._check_iommu_enabled()
            if not validation_info['iommu_enabled']:
                validation_info['issues'].append("IOMMU is not enabled in kernel")
                validation_info['suggestions'].append("Add intel_iommu=on or amd_iommu=on to GRUB_CMDLINE_LINUX in /etc/default/grub")
            
            # Check VFIO support
            validation_info['vfio_support'] = self._check_vfio_support()
            if not validation_info['vfio_support']:
                validation_info['issues'].append("VFIO kernel modules are not available")
                validation_info['suggestions'].append("Install kernel modules or recompile kernel with VFIO support")
            
            # Overall success
            success = all([
                validation_info['virtualization_support'],
                validation_info['iommu_support'],
                validation_info['iommu_enabled'],
                validation_info['vfio_support']
            ])
            
            self.logger.debug(f"System requirements validation completed. Success: {success}")
            return success, validation_info
            
        except Exception as e:
            self.logger.error(f"Error during system requirements validation: {e}")
            validation_info['issues'].append(f"Validation failed: {str(e)}")
            return False, validation_info
    
    def _check_virtualization_support(self) -> bool:
        """Check if CPU supports virtualization"""
        try:
            with open('/proc/cpuinfo', 'r') as f:
                content = f.read()
                return 'vmx' in content or 'svm' in content
        except Exception:
            return False
    
    def _check_iommu_support(self) -> bool:
        """Check if IOMMU is supported"""
        try:
            return os.path.exists(self.iommu_groups_path) and os.listdir(self.iommu_groups_path)
        except Exception:
            return False
    
    def _check_iommu_enabled(self) -> bool:
        """Check if IOMMU is enabled in kernel"""
        try:
            # Check kernel command line
            with open('/proc/cmdline', 'r') as f:
                cmdline = f.read()
                return 'intel_iommu=on' in cmdline or 'amd_iommu=on' in cmdline
        except Exception:
            return False
    
    def _check_vfio_support(self) -> bool:
        """Check if VFIO modules are available"""
        try:
            # Check if VFIO modules exist
            result = subprocess.run(['modinfo', 'vfio-pci'], 
                                  capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def get_iommu_groups(self) -> Dict[str, List[str]]:
        """
        Get all IOMMU groups and their devices
        
        Returns:
            Dict[str, List[str]]: Dictionary mapping group IDs to device lists
        """
        groups = {}
        
        try:
            if not os.path.exists(self.iommu_groups_path):
                return groups
            
            for group_id in os.listdir(self.iommu_groups_path):
                devices_path = os.path.join(self.iommu_groups_path, group_id, "devices")
                if os.path.exists(devices_path):
                    devices = os.listdir(devices_path)
                    groups[group_id] = sorted(devices)
            
            self.logger.debug(f"Found {len(groups)} IOMMU groups")
            return groups
            
        except Exception as e:
            self.logger.error(f"Error getting IOMMU groups: {e}")
            return groups
    
    def get_device_info(self, pci_id: str) -> Optional[Dict[str, str]]:
        """
        Get detailed information about a PCI device
        
        Args:
            pci_id: PCI device ID (e.g., "0000:01:00.0")
            
        Returns:
            Optional[Dict[str, str]]: Device information or None if not found
        """
        try:
            device_path = os.path.join(self.pci_devices_path, pci_id)
            if not os.path.exists(device_path):
                return None
            
            device_info = {'pci_id': pci_id}
            
            # Read device class
            class_file = os.path.join(device_path, 'class')
            if os.path.exists(class_file):
                with open(class_file, 'r') as f:
                    device_info['class'] = f.read().strip()
            
            # Read vendor and device IDs
            vendor_file = os.path.join(device_path, 'vendor')
            if os.path.exists(vendor_file):
                with open(vendor_file, 'r') as f:
                    device_info['vendor'] = f.read().strip()
            
            device_file = os.path.join(device_path, 'device')
            if os.path.exists(device_file):
                with open(device_file, 'r') as f:
                    device_info['device'] = f.read().strip()
            
            # Get current driver
            driver_path = os.path.join(device_path, 'driver')
            if os.path.islink(driver_path):
                device_info['driver'] = os.path.basename(os.readlink(driver_path))
            else:
                device_info['driver'] = None
            
            # Get device description using lspci
            try:
                result = subprocess.run(['lspci', '-s', pci_id], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    # Parse lspci output
                    lines = result.stdout.strip().split('\n')
                    if lines:
                        # Extract description after the PCI ID
                        parts = lines[0].split(' ', 1)
                        if len(parts) > 1:
                            device_info['description'] = parts[1]
            except Exception:
                pass
            
            return device_info
            
        except Exception as e:
            self.logger.error(f"Error getting device info for {pci_id}: {e}")
            return None
    
    def validate_device_passthrough(self, pci_id: str) -> Tuple[bool, Dict[str, any]]:
        """
        Validate if a specific device can be passed through
        
        Args:
            pci_id: PCI device ID to validate
            
        Returns:
            Tuple[bool, Dict]: (can_passthrough, validation_info)
        """
        validation_info = {
            'device_exists': False,
            'device_info': None,
            'iommu_group': None,
            'group_devices': [],
            'driver_bound': False,
            'vfio_compatible': False,
            'issues': [],
            'suggestions': []
        }
        
        try:
            # Check if device exists
            device_info = self.get_device_info(pci_id)
            if device_info:
                validation_info['device_exists'] = True
                validation_info['device_info'] = device_info
            else:
                validation_info['issues'].append(f"Device {pci_id} not found")
                return False, validation_info
            
            # Find IOMMU group
            iommu_groups = self.get_iommu_groups()
            for group_id, devices in iommu_groups.items():
                if pci_id in devices:
                    validation_info['iommu_group'] = group_id
                    validation_info['group_devices'] = devices
                    break
            
            if not validation_info['iommu_group']:
                validation_info['issues'].append(f"Device {pci_id} not found in any IOMMU group")
                validation_info['suggestions'].append("Check if IOMMU is enabled in kernel")
                return False, validation_info
            
            # Check if device has a driver bound
            if device_info.get('driver'):
                validation_info['driver_bound'] = True
                if device_info['driver'] != 'vfio-pci':
                    validation_info['suggestions'].append(f"Unbind device from {device_info['driver']} driver and bind to vfio-pci")
            
            # Check VFIO compatibility
            validation_info['vfio_compatible'] = self._check_device_vfio_compatibility(device_info)
            if not validation_info['vfio_compatible']:
                validation_info['issues'].append("Device may not be compatible with VFIO passthrough")
            
            # Check for group conflicts
            if len(validation_info['group_devices']) > 1:
                validation_info['suggestions'].append(
                    f"IOMMU group {validation_info['iommu_group']} contains multiple devices. "
                    "All devices in the group must be passed through together or unbound from their drivers."
                )
            
            # Overall success
            success = (
                validation_info['device_exists'] and
                validation_info['iommu_group'] is not None and
                validation_info['vfio_compatible']
            )
            
            return success, validation_info
            
        except Exception as e:
            self.logger.error(f"Error validating device passthrough for {pci_id}: {e}")
            validation_info['issues'].append(f"Validation failed: {str(e)}")
            return False, validation_info
    
    def _check_device_vfio_compatibility(self, device_info: Dict[str, str]) -> bool:
        """Check if a device is compatible with VFIO passthrough"""
        try:
            # Most PCI devices are compatible with VFIO
            # Some specific checks could be added here for known problematic devices
            # device_class = device_info.get('class', '')
            
            # Graphics cards (class 0x030000) are generally compatible
            # Network cards (class 0x020000) are generally compatible
            # USB controllers (class 0x0c0300) are generally compatible
            
            # For now, assume compatibility unless we have specific exclusions
            return True
            
        except Exception:
            return False
    
    def display_iommu_groups(self):
        """Display all IOMMU groups and their devices in a formatted table"""
        from rich.console import Console
        from rich.table import Table
        
        console = Console()
        
        print_header("IOMMU Groups and Devices")
        
        iommu_groups = self.get_iommu_groups()
        
        if not iommu_groups:
            print_error("No IOMMU groups found. IOMMU may not be enabled.")
            return
        
        table = Table(title="IOMMU Groups")
        table.add_column("Group", style="cyan", width=8)
        table.add_column("PCI ID", style="yellow", width=12)
        table.add_column("Description", style="white")
        table.add_column("Driver", style="green", width=15)
        
        for group_id in sorted(iommu_groups.keys(), key=int):
            devices = iommu_groups[group_id]
            
            for i, pci_id in enumerate(devices):
                device_info = self.get_device_info(pci_id)
                
                group_display = group_id if i == 0 else ""
                description = device_info.get('description', 'Unknown Device') if device_info else 'Unknown Device'
                driver = device_info.get('driver', 'None') if device_info else 'None'
                
                table.add_row(group_display, pci_id, description, driver)
        
        console.print(table)
        
        print_info(f"Found {len(iommu_groups)} IOMMU groups with {sum(len(devices) for devices in iommu_groups.values())} devices")
    
    def display_validation_results(self, validation_info: Dict[str, any]):
        """Display validation results in a formatted way"""
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        
        console = Console()
        
        # System requirements table
        if 'virtualization_support' in validation_info:
            table = Table(title="System Requirements Validation")
            table.add_column("Requirement", style="cyan")
            table.add_column("Status", style="bold")
            table.add_column("Details")
            
            table.add_row(
                "CPU Virtualization",
                "✅ OK" if validation_info['virtualization_support'] else "❌ Failed",
                "VT-x/AMD-V support detected" if validation_info['virtualization_support'] else "No virtualization support found"
            )
            
            table.add_row(
                "IOMMU Support",
                "✅ OK" if validation_info['iommu_support'] else "❌ Failed",
                "IOMMU groups found" if validation_info['iommu_support'] else "No IOMMU groups found"
            )
            
            table.add_row(
                "IOMMU Enabled",
                "✅ OK" if validation_info['iommu_enabled'] else "❌ Failed",
                "IOMMU enabled in kernel" if validation_info['iommu_enabled'] else "IOMMU not enabled in kernel"
            )
            
            table.add_row(
                "VFIO Support",
                "✅ OK" if validation_info['vfio_support'] else "❌ Failed",
                "VFIO modules available" if validation_info['vfio_support'] else "VFIO modules not found"
            )
            
            console.print(table)
        
        # Device-specific validation
        if 'device_info' in validation_info and validation_info['device_info']:
            device_info = validation_info['device_info']
            
            device_panel = f"""[bold]Device Information:[/bold]
PCI ID: {device_info['pci_id']}
Description: {device_info.get('description', 'Unknown')}
Vendor: {device_info.get('vendor', 'Unknown')}
Device: {device_info.get('device', 'Unknown')}
Class: {device_info.get('class', 'Unknown')}
Current Driver: {device_info.get('driver', 'None')}

[bold]IOMMU Information:[/bold]
IOMMU Group: {validation_info.get('iommu_group', 'Not found')}
Group Devices: {len(validation_info.get('group_devices', []))} device(s)
"""
            
            console.print(Panel(device_panel, title="Device Validation", border_style="blue"))
        
        # Issues and suggestions
        if validation_info.get('issues'):
            console.print("\n[bold red]Issues Found:[/bold red]")
            for issue in validation_info['issues']:
                console.print(f"  • {issue}")
        
        if validation_info.get('suggestions'):
            console.print("\n[bold yellow]Suggested Actions:[/bold yellow]")
            for suggestion in validation_info['suggestions']:
                console.print(f"  • {suggestion}")


# Convenience functions for backward compatibility
def validate_passthrough_requirements() -> bool:
    """
    Validate system requirements for PCI passthrough
    
    Returns:
        bool: True if all requirements are met
    """
    validator = PassthroughValidator()
    success, _ = validator.validate_system_requirements()
    return success


def get_iommu_groups() -> Dict[str, List[str]]:
    """
    Get all IOMMU groups and their devices
    
    Returns:
        Dict[str, List[str]]: Dictionary mapping group IDs to device lists
    """
    validator = PassthroughValidator()
    return validator.get_iommu_groups()