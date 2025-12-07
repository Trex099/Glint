# Made by trex099
# https://github.com/Trex099/Glint
"""
VM Path Utilities Module

Provides path-related utilities for Linux VMs.
"""

import os
import sys

# Use same import pattern as main.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG
from core_utils import (
    print_header, print_error, print_info,
    select_from_list, identify_iso_type
)


def get_vm_paths(vm_name):
    """
    Returns a dictionary of paths for a given VM name.
    """
    vm_dir = os.path.abspath(os.path.join(CONFIG['VMS_DIR_LINUX'], vm_name))
    return {
        "dir": vm_dir,
        "base": os.path.join(vm_dir, "base.qcow2"),
        "overlay": os.path.join(vm_dir, "overlay.qcow2"),
        "seed": os.path.join(vm_dir, "uefi-seed.fd"),
        "instance": os.path.join(vm_dir, "uefi-instance.fd"),
        "session_id": os.path.join(vm_dir, "session.id"),
        "shared_dir": os.path.join(vm_dir, "shared"),
        "pid_file": os.path.join(vm_dir, "qemu.pid"),
        "session_info": os.path.join(vm_dir, "session.info"),
        "config": os.path.join(vm_dir, "config.json")
    }


def select_vm(action_text, running_only=False):
    """
    Prompts the user to select a VM from the list of available Linux VMs.
    """
    print_header(f"Select VM to {action_text}")
    vms_dir = CONFIG['VMS_DIR_LINUX']
    if not os.path.isdir(vms_dir) or not os.listdir(vms_dir):
        print_error("No Linux VMs found.")
        return None

    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])
    
    if running_only:
        # Lazy import to prevent circular dependency
        from linux_vm.main import is_vm_running
        vm_list = [vm for vm in vm_list if is_vm_running(vm)]
        if not vm_list:
            print_error("No running VMs found.")
            return None
            
    if not vm_list:
        print_error("No Linux VMs found.")
        return None

    return select_from_list(vm_list, "Choose a VM")


def find_iso_path():
    """
    Finds and allows selection of a Linux installation ISO.
    """
    print_header("Select Linux Installation ISO")
    try:
        # Filter for .iso files and identify them
        all_isos = [f for f in os.listdir('.') if f.endswith('.iso')]
        linux_isos = [iso for iso in all_isos if identify_iso_type(iso) == 'linux']
        
        if not linux_isos:
            print_error("No Linux installation ISO found in the current directory.")
            print_info("Please ensure a Linux-based .iso file is present.")
            return None
        
        # Let the user choose if there are multiple options
        if len(linux_isos) > 1:
            iso_path = select_from_list(linux_isos, "Choose a Linux ISO")
        else:
            iso_path = linux_isos[0]
            
        if iso_path:
            iso_abs_path = os.path.abspath(iso_path)
            print_info(f"Using ISO: {iso_abs_path}")
            return iso_abs_path
            
    except OSError as e:
        print_error(f"Error reading current directory: {e}")
    return None
