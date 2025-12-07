# Made by trex099
# https://github.com/Trex099/Glint
"""
GPU/USB Passthrough Operations Module

Provides passthrough-related helper functions for Linux VMs:
- VFIO permission checks
- IOMMU group handling
- PCI device driver queries
"""

import os
import sys
import questionary
from rich.console import Console

# Use same import pattern as main.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core_utils import (
    print_info, print_warning, print_error, print_success,
    run_command_live, is_vfio_module_loaded
)

console = Console()


def _check_vfio_permissions():
    """
    Enhanced VFIO permissions check with automatic configuration option.
    Uses the new VFIOManager for comprehensive permission handling.
    """
    try:
        # Import the new VFIO manager
        from src.linux_vm.passthrough.vfio_manager import VFIOManager
        
        vfio_manager = VFIOManager()
        success, status_info = vfio_manager.check_vfio_permissions()
        
        if success:
            print_success("✅ VFIO permissions are configured correctly!")
            return True
        
        print_warning("⚠️  VFIO permissions need configuration.")
        
        # Display current status
        vfio_manager._display_status_info(status_info)
        
        # Offer automatic setup
        if questionary.confirm("Would you like to automatically configure VFIO permissions? (Recommended)").ask():
            return vfio_manager.setup_vfio_permissions_automatically()
        else:
            print_info("Manual setup instructions have been displayed above.")
            return False
            
    except ImportError:
        print_warning("Enhanced VFIO manager not available, using fallback method.")
        # Fallback to original simple check
        vfio_path = "/dev/vfio/vfio"
        if os.path.exists(vfio_path) and os.access(vfio_path, os.R_OK | os.W_OK):
            return True

        print_warning("VFIO permissions check failed.")
        print_info("To run QEMU for passthrough without root, your user needs read/write access to /dev/vfio/vfio.")
        
        instructions = """
  [bold]To set this up permanently, you need to create a udev rule.[/]
  1. Create a new udev rule file:
     [bold]sudo nano /etc/udev/rules.d/10-vfio.rules[/]
  2. Add the following line to the file:
     [bold]KERNEL=="vfio/vfio", GROUP="kvm", MODE="0660"[/]
     (Assuming your user is in the 'kvm' group. Use 'ls -l /dev/kvm' to check.)
  3. Add your user to the 'kvm' group if they aren't already:
     [bold]sudo usermod -aG kvm $USER[/]
  4. Apply the new rule and reboot:
     [bold]sudo udevadm control --reload-rules && sudo udevadm trigger[/]
     [bold]sudo reboot[/]
        """
        console.print(instructions)
        
        if questionary.confirm("Would you like to attempt to set permissions for the current session only? (Requires sudo)").ask():
            if run_command_live(["setfacl", "-m", f"u:{os.getlogin()}:rw", vfio_path], as_root=True):
                print_success("Temporary permissions set. This will reset on reboot.")
                return True
                
        return False
    except Exception as e:
        print_error(f"Error during VFIO permission check: {str(e)}")
        return False


def _get_pci_device_driver(pci_id):
    """Gets the current driver for a PCI device."""
    try:
        driver_path = f"/sys/bus/pci/devices/{pci_id}/driver"
        if os.path.islink(driver_path):
            return os.path.basename(os.readlink(driver_path))
    except FileNotFoundError:
        return None
    return None


def _check_and_load_vfio_module():
    """Checks for and offers to load the vfio-pci module."""
    if is_vfio_module_loaded():
        return True
    print_warning("vfio-pci module is not loaded.")
    if questionary.confirm("Load it now? (Requires sudo)").ask():
        if run_command_live(["modprobe", "vfio-pci"], as_root=True):
            return True
    return False


def _get_iommu_groups():
    """Gets a dictionary of IOMMU groups and their devices."""
    groups = {}
    iommu_path = "/sys/kernel/iommu_groups"
    try:
        for group in os.listdir(iommu_path):
            devices = os.listdir(os.path.join(iommu_path, group, "devices"))
            groups[group] = devices
    except FileNotFoundError:
        pass
    return groups


def _get_full_iommu_group_devices(pci_id, iommu_groups_out):
    """Gets all devices in the same IOMMU group as a given PCI ID."""
    for group, devices in iommu_groups_out.items():
        if pci_id in devices:
            return group, devices, [d for d in devices if d != pci_id]
    return None, [], []
