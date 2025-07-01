# Made by trex099
# https://github.com/Trex099/Glint
# pylint: disable=too-many-lines,too-many-arguments,too-many-locals
# pylint: disable=too-many-return-statements,too-many-branches,too-many-statements
"""
This module handles all Windows VM management functionality with improved
security, clarity, and performance defaults.
"""
import os
import sys
import re
import uuid
import json
import questionary
from rich.console import Console

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG
from file_transfer import transfer_files_menu
from core_utils import (
    print_header, print_info, print_warning, print_error, clear_screen,
    run_command_live, launch_in_new_terminal_and_wait, select_from_list,
    remove_dir, print_success, get_vm_config, identify_iso_type, find_first_existing_path,
    get_disk_size, find_unused_port
)

console = Console()


def get_vm_paths(vm_name):
    """
    Returns a dictionary of paths for a given VM name.
    """
    vm_dir = os.path.abspath(os.path.join(CONFIG['VMS_DIR_WINDOWS'], vm_name))
    return {
        "dir": vm_dir,
        "base": os.path.join(vm_dir, "base.qcow2"),
        "overlay": os.path.join(vm_dir, "overlay.qcow2"),
        "uefi_vars": os.path.join(vm_dir, "uefi_vars.fd"),
        "config": os.path.join(vm_dir, "config.json"),
        "pid_file": os.path.join(vm_dir, "qemu.pid"),
    }


def find_iso_path(prompt_text="Select Windows Installation ISO"):
    """
    Finds and allows selection of a Windows installation ISO.
    """
    print_header(prompt_text)
    try:
        all_isos = [f for f in os.listdir('.') if f.endswith('.iso')]
        windows_isos = [iso for iso in all_isos if identify_iso_type(iso) == 'windows']
        
        if not windows_isos:
            print_error("No Windows installation ISO found in the current directory.")
            print_info("Please ensure a Windows installation .iso file is present.")
            return None
            
        if len(windows_isos) > 1:
            iso_path = select_from_list(windows_isos, "Choose a Windows ISO")
        else:
            iso_path = windows_isos[0]
            
        if iso_path:
            iso_abs_path = os.path.abspath(iso_path)
            print_info(f"Using ISO: {iso_abs_path}")
            return iso_abs_path
            
    except OSError as e:
        print_error(f"Error reading current directory: {e}")
    return None


def find_virtio_iso_path():
    """
    Finds and allows selection of a VirtIO drivers ISO.
    """
    print_header("Select VirtIO Drivers ISO")
    try:
        all_isos = [f for f in os.listdir('.') if f.endswith('.iso')]
        virtio_isos = [iso for iso in all_isos if identify_iso_type(iso) == 'virtio']

        if not virtio_isos:
            print_warning("No VirtIO drivers ISO found. This is highly recommended for performance.")
            if not questionary.confirm("Continue without VirtIO drivers?").ask():
                return None
            return ""

        if len(virtio_isos) > 1:
            iso_path = select_from_list(virtio_isos, "Choose a VirtIO drivers ISO")
        else:
            iso_path = virtio_isos[0]

        if iso_path:
            iso_abs_path = os.path.abspath(iso_path)
            print_info(f"Using VirtIO drivers: {iso_abs_path}")
            return iso_abs_path
            
    except OSError as e:
        print_error(f"Error reading directory for VirtIO drivers: {e}")
    return None

def create_new_windows_vm():
    """
    Guides the user through creating a new Windows VM with secure commands.
    """
    clear_screen()
    print_header("Create New Windows VM")

    while True:
        vm_name = questionary.text("Enter a short name for new VM (e.g., win11):").ask().strip()
        if not re.match(r"^[a-zA-Z0-9_-]+$", vm_name):
            print_warning("Invalid name. Use letters, numbers, hyphens, or underscores.")
        elif os.path.exists(os.path.join(CONFIG['VMS_DIR_WINDOWS'], vm_name)):
            print_warning("A VM with this name already exists.")
        else:
            break

    paths = get_vm_paths(vm_name)
    iso_path = find_iso_path()
    if not iso_path:
        return

    virtio_path = find_virtio_iso_path()
    if virtio_path is None: # User cancelled
        return

    disk_size = get_disk_size("Enter base disk size (e.g., 100G)", "64G")

    vm_settings = get_vm_config({"VM_MEM": "8G", "VM_CPU": "4"})
    
    print_info("Preparing VM files...")
    # Ensure both the main VM directory and the shared folder are created
    os.makedirs(os.path.join(paths['dir'], 'shared'), exist_ok=True)
    
    with open(paths['config'], 'w', encoding='utf-8') as f:
        json.dump(vm_settings, f, indent=4)
        
    # Use secure run_command_live instead of os.system
    uefi_vars_path = find_first_existing_path(CONFIG['UEFI_VARS_PATHS'])
    if not uefi_vars_path:
        print_error("Could not find UEFI VARS template file. Aborting.")
        return
    run_command_live(["cp", uefi_vars_path, paths['uefi_vars']], quiet=True)
    run_command_live(["qemu-img", "create", "-f", "qcow2", paths['base'], disk_size], quiet=True)
    print_success("VM files created successfully.")

    ssh_port = find_unused_port()
    print_info(f"SSH will be available on host port {ssh_port}")
    with open(os.path.join(paths['dir'], 'session.info'), 'w', encoding='utf-8') as f:
        f.write(str(ssh_port))

    qemu_cmd = _get_qemu_command(vm_name, vm_settings, {'uuid': str(uuid.uuid4())}, ssh_port, iso_path=iso_path, virtio_path=virtio_path)

    launch_in_new_terminal_and_wait([("Booting from ISO for Installation", qemu_cmd)])


def _get_qemu_command(vm_name, vm_settings, ids, ssh_port, iso_path=None, virtio_path=None, use_overlay=False):
    """
    Builds a standardized and performant QEMU command for a Windows VM.
    """
    paths = get_vm_paths(vm_name)
    disk_path = paths['overlay'] if use_overlay and os.path.exists(paths['overlay']) else paths['base']
    
    qemu_cmd = [
        CONFIG["QEMU_BINARY"],
        "-enable-kvm",
        "-m", vm_settings["VM_MEM"],
        "-smp", f"cores={int(vm_settings['VM_CPU']) // 2},threads=2,sockets=1", # Assume 2 threads per core
        "-cpu", "host,hv_relaxed,hv_spinlocks=0x1fff,hv_vapic,hv_time", # Hyper-V enlightenments
        "-uuid", ids['uuid'],
        "-drive", f"if=pflash,format=raw,readonly=on,file={find_first_existing_path(CONFIG['UEFI_CODE_PATHS'])}",
        "-drive", f"if=pflash,format=raw,file={paths['uefi_vars']}",
        "-drive", f"file={disk_path},if=virtio,cache=writeback,aio=threads",
        "-netdev", f"user,id=n1,hostfwd=tcp::{ssh_port}-:22",
        "-device", "virtio-net-pci,netdev=n1", # Use virtio-net for better performance
        "-vga", "virtio",
        "-display", "sdl,gl=on", # Enable hardware acceleration
        "-device", "qemu-xhci",
        "-device", "usb-tablet",
        "-pidfile", paths['pid_file'],
        # Add shared folder support
        "-fsdev", f"local,security_model=passthrough,id=fsdev0,path={os.path.join(paths['dir'], 'shared')}",
        "-device", "virtio-9p-pci,id=fs0,fsdev=fsdev0,mount_tag=host_share",
    ]

    if iso_path:
        qemu_cmd.extend(["-cdrom", iso_path])
    if virtio_path:
        qemu_cmd.extend(["-drive", f"file={virtio_path},media=cdrom,index=3"])

    return qemu_cmd


def _prepare_run_session(vm_name):
    """Prepares a VM for running by ensuring its files exist."""
    paths = get_vm_paths(vm_name)
    if not os.path.exists(paths['base']):
        print_error(f"Base disk for '{vm_name}' not found. Cannot run.")
        return None, None

    # Load saved config or use defaults
    defaults = {"VM_MEM": "8G", "VM_CPU": "4"}
    if os.path.exists(paths['config']):
        try:
            with open(paths['config'], 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
            defaults['VM_MEM'] = saved_config.get('VM_MEM', defaults['VM_MEM'])
            defaults['VM_CPU'] = saved_config.get('VM_CPU', defaults['VM_CPU'])
        except (json.JSONDecodeError, IOError):
            print_warning("Could not load saved config, using defaults.")

    # Create overlay if it doesn't exist
    if not os.path.exists(paths['overlay']):
        print_info("No existing session found. Creating a new one (overlay disk).")
        run_command_live(["qemu-img", "create", "-f", "qcow2", "-b", paths['base'], "-F", "qcow2", paths['overlay']], check=True)
        
    return paths, defaults


def run_windows_vm():
    """
    Runs an existing Windows VM with clearer session logic.
    """
    clear_screen()
    print_header("Run Existing Windows VM")

    vm_name = select_from_list([d for d in os.listdir(CONFIG['VMS_DIR_WINDOWS']) if os.path.isdir(os.path.join(CONFIG['VMS_DIR_WINDOWS'], d))], "Choose a VM to run")
    if not vm_name:
        return

    paths, defaults = _prepare_run_session(vm_name)
    if not paths:
        return

    vm_settings = get_vm_config(defaults)
    ssh_port = find_unused_port()
    print_info(f"SSH will be available on host port {ssh_port}")
    with open(os.path.join(paths['dir'], 'session.info'), 'w', encoding='utf-8') as f:
        f.write(str(ssh_port))

    qemu_cmd = _get_qemu_command(vm_name, vm_settings, {'uuid': str(uuid.uuid4())}, ssh_port, use_overlay=True)
    launch_in_new_terminal_and_wait([("Booting Windows VM", qemu_cmd)])


def nuke_and_recreate_windows_vm():
    """
    Nukes the overlay disk of a VM to start a fresh session.
    """
    clear_screen()
    print_header("Nuke & Boot a Fresh Session")

    vm_name = select_from_list([d for d in os.listdir(CONFIG['VMS_DIR_WINDOWS']) if os.path.isdir(os.path.join(CONFIG['VMS_DIR_WINDOWS'], d))], "Choose a VM to nuke")
    if not vm_name:
        return

    paths, defaults = _prepare_run_session(vm_name)
    if not paths:
        return

    if os.path.exists(paths['overlay']):
        print_warning(f"You are about to permanently delete the current session for '{vm_name}'.")
        if not questionary.confirm("Are you sure?").ask():
            print_info("Operation cancelled.")
            return
        os.remove(paths['overlay'])
        print_success("Session overlay disk has been nuked.")

    # Re-create the overlay
    run_command_live(["qemu-img", "create", "-f", "qcow2", "-b", paths['base'], "-F", "qcow2", paths['overlay']], check=True)

    vm_settings = get_vm_config(defaults)
    qemu_cmd = _get_qemu_command(vm_name, vm_settings, {'uuid': str(uuid.uuid4())}, use_overlay=True)
    launch_in_new_terminal_and_wait([("Booting Fresh VM Session", qemu_cmd)])


def delete_windows_vm():
    """
    Completely and permanently deletes a Windows VM directory.
    """
    clear_screen()
    print_header("Delete Windows VM Completely")

    vm_name = select_from_list([d for d in os.listdir(CONFIG['VMS_DIR_WINDOWS']) if os.path.isdir(os.path.join(CONFIG['VMS_DIR_WINDOWS'], d))], "Choose a VM to delete")
    if not vm_name:
        return

    print_warning(f"This will permanently delete the entire VM '{vm_name}', including its virtual disk.\nThis action CANNOT be undone.")
    confirm = questionary.text(f"To confirm, please type the name of the VM ({vm_name}):").ask().strip()
    if confirm == vm_name:
        remove_dir(get_vm_paths(vm_name)['dir'])
    else:
        print_error("Confirmation failed. Aborting.")


def windows_vm_menu():
    """
    Displays the main menu for Windows VM management.
    """
    os.makedirs(CONFIG['VMS_DIR_WINDOWS'], exist_ok=True)
    while True:
        clear_screen()
        console.print("[bold]Windows VM Management[/]")
        console.print("─────────────────────────────────────────��─────")
        choice = questionary.select(
            "Select an option",
            choices=[
                "1. Create New Windows VM",
                "2. Run Existing Windows VM",
                "3. Nuke & Boot a Fresh Session",
                "4. Transfer Files (SFTP)",
                "5. Delete Windows VM Completely",
                "6. Return to Main Menu",
            ]
        ).ask()
        action_taken = True
        if choice == "1. Create New Windows VM": create_new_windows_vm()
        elif choice == "2. Run Existing Windows VM": run_windows_vm()
        elif choice == "3. Nuke & Boot a Fresh Session": nuke_and_recreate_windows_vm()
        elif choice == "4. Transfer Files (SFTP)":
            vm_name = select_from_list([d for d in os.listdir(CONFIG['VMS_DIR_WINDOWS']) if os.path.isdir(os.path.join(CONFIG['VMS_DIR_WINDOWS'], d))], "Choose a VM")
            if vm_name:
                vm_dir = get_vm_paths(vm_name)['dir']
                transfer_files_menu(vm_name, "windows", vm_dir)
        elif choice == "5. Delete Windows VM Completely": delete_windows_vm()
        elif choice == "6. Return to Main Menu": break
        else:
            print_warning("Invalid option.")
            action_taken = False
        
        if action_taken:
            questionary.text("\nPress Enter to return to the menu...").ask()



if __name__ == '__main__':
    windows_vm_menu()