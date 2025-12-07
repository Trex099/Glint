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
import random # Moved import to the top
import questionary
from rich.console import Console

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG
from file_transfer import transfer_files_menu
from core_utils import (
    print_header, print_info, print_warning, print_error, clear_screen,
    run_command_live, launch_in_new_terminal_and_wait, select_from_list,
    remove_dir, print_success, get_vm_config, identify_iso_type, find_first_existing_path,
    get_disk_size, find_unused_port, download_file, remove_file
)

console = Console()


def _ensure_virtio_drivers():
    """
    Checks for local VirtIO drivers, and if not found, offers to download them.
    Returns the path to the VirtIO ISO or an empty string. Returns None on cancellation.
    """
    print_header("Checking for VirtIO Drivers")
    try:
        all_isos = [f for f in os.listdir('.') if f.endswith('.iso')]
        virtio_isos = [os.path.abspath(iso) for iso in all_isos if identify_iso_type(iso) == 'virtio']

        options = []
        if virtio_isos:
            print_info("Found local VirtIO driver ISO(s).")
            options.extend(virtio_isos)
            options.append(questionary.Separator())

        download_option = "Download latest stable VirtIO drivers from Fedora"
        options.append(download_option)
        options.append("Continue without VirtIO drivers (Not Recommended)")
        options.append("Cancel")

        choice = select_from_list(options, "Select a VirtIO driver source:")

        if choice is None or choice == "Cancel":
            return None # Abort creation

        if choice == "Continue without VirtIO drivers (Not Recommended)":
            print_warning("Proceeding without VirtIO drivers. Performance will be degraded.")
            return ""

        if choice == download_option:
            url = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso"
            destination = "virtio-win.iso"
            print_info(f"Downloading from: {url}")
            if download_file(url, destination):
                return os.path.abspath(destination)
            else:
                print_error("Download failed. Please try again or download it manually.")
                return None # Abort creation

        # A local ISO was selected
        print_success(f"Using selected VirtIO drivers: {os.path.basename(choice)}")
        return choice

    except OSError as e:
        print_error(f"Error while searching for VirtIO drivers: {e}")
        return None


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
        "session_info": os.path.join(vm_dir, "session.info"),
    }


def get_running_vm_info(vm_name):
    """
    Safely retrieves information about a running VM.
    """
    paths = get_vm_paths(vm_name)
    pid_file, session_info_file = paths['pid_file'], paths.get('session_info')

    if not pid_file or not os.path.exists(pid_file):
        return None

    try:
        with open(pid_file, 'r', encoding='utf-8') as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # Check if process exists

        ssh_port = None
        if session_info_file and os.path.exists(session_info_file):
            with open(session_info_file, 'r', encoding='utf-8') as f:
                ssh_port = int(f.read().strip())

        return {'pid': pid, 'port': ssh_port}
    except (IOError, ValueError, ProcessLookupError, OSError):
        # Cleanup stale files if process is not running
        files_to_clean = [pid_file]
        if session_info_file:
            files_to_clean.append(session_info_file)
        for f_path in files_to_clean:
            if os.path.exists(f_path):
                remove_file(f_path)
        return None


def is_vm_running(vm_name):
    """Checks if a VM is running."""
    return get_running_vm_info(vm_name) is not None


def select_vm(action_text, running_only=False):
    """
    Prompts the user to select a VM from the list of available Windows VMs.
    """
    print_header(f"Select VM to {action_text}")
    vms_dir = CONFIG['VMS_DIR_WINDOWS']
    if not os.path.isdir(vms_dir) or not os.listdir(vms_dir):
        print_error("No Windows VMs found.")
        return None

    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])

    if running_only:
        vm_list = [vm for vm in vm_list if is_vm_running(vm)]
        if not vm_list:
            print_error("No running VMs found.")
            return None

    if not vm_list:
        print_error("No Windows VMs found.")
        return None

    return select_from_list(vm_list, "Choose a VM")


def stop_vm(vm_name=None, force=False):
    """Stops a running VM gracefully."""
    if not vm_name:
        clear_screen()
        vm_name = select_vm("Stop", running_only=True)
    if not vm_name:
        return

    vm_info = get_running_vm_info(vm_name)
    if vm_info:
        print_info(f"Stopping VM '{vm_name}' (PID: {vm_info['pid']})...")
        try:
            os.kill(vm_info['pid'], 15)  # SIGTERM
            print_success(f"Stop signal sent to VM '{vm_name}'.")
        except ProcessLookupError:
            print_warning("Process already stopped.")
        except OSError as e:
            print_error(f"Failed to send stop signal to VM: {e}")

        # Clean up PID files regardless of signal success
        import time
        time.sleep(1)
        paths = get_vm_paths(vm_name)
        files_to_clean = [paths['pid_file']]
        if 'session_info' in paths and paths['session_info']:
            files_to_clean.append(paths['session_info'])
        for f_path in files_to_clean:
            if os.path.exists(f_path):
                remove_file(f_path)
    elif not force:
        print_error(f"Could not get running info for '{vm_name}'. It may not be running.")


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

# --- FIX: Consolidated the multiple _generate_mac_address functions into one ---
def _generate_mac_address():
    """Generates a random, valid MAC address in the QEMU format."""
    # QEMU OUI 52:54:00, followed by 3 random bytes
    mac = [ 0x52, 0x54, 0x00,
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff) ]
    return ':'.join(f'{b:02x}' for b in mac)


def create_new_windows_vm():
    """
    Guides the user through creating a new Windows VM with secure commands.
    """
    clear_screen()
    print_header("Create New Windows VM")

    while True:
        result = questionary.text("Enter a short name for new VM (e.g., win11):").ask()
        if result is None:
            print_info("VM creation cancelled.")
            return
        vm_name = result.strip()
        if not vm_name:
            continue
        if not re.match(r"^[a-zA-Z0-9_-]+$", vm_name):
            print_warning("Invalid name. Use letters, numbers, hyphens, or underscores.")
        elif os.path.exists(os.path.join(CONFIG['VMS_DIR_WINDOWS'], vm_name)):
            print_warning("A VM with this name already exists.")
        else:
            break

    virtio_path = _ensure_virtio_drivers()
    if virtio_path is None: # User cancelled the download or selection
        print_error("VirtIO driver selection was cancelled. Aborting VM creation.")
        return

    paths = get_vm_paths(vm_name)
    iso_path = find_iso_path()
    if not iso_path:
        return

    disk_size = get_disk_size("Enter base disk size (e.g., 100G)", "64G")

    vm_settings = get_vm_config({"VM_MEM": "8G", "VM_CPU": "4"})

    # Add persistent hardware identifiers
    vm_settings['uuid'] = str(uuid.uuid4())
    vm_settings['mac_addr'] = _generate_mac_address()

    print_info("Preparing VM files...")
    os.makedirs(os.path.join(paths['dir'], 'shared'), exist_ok=True)

    with open(paths['config'], 'w', encoding='utf-8') as f:
        json.dump(vm_settings, f, indent=4)

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

    qemu_cmd = _get_qemu_command(vm_name, vm_settings, ssh_port, iso_path=iso_path, virtio_path=virtio_path)

    debug_mode = questionary.select(
        "Select a debug mode:",
        choices=["None", "Show QEMU command", "Verbose Debug (run in this terminal)"]
    ).ask()

    if debug_mode == "Show QEMU command":
        print_info("QEMU command:")
        print(" ".join(qemu_cmd))
        launch_in_new_terminal_and_wait([("Booting from ISO for Installation", qemu_cmd)])
    elif debug_mode == "Verbose Debug (run in this terminal)":
        print_info("Running QEMU in verbose mode...")
        run_command_live(qemu_cmd)
    else:
        launch_in_new_terminal_and_wait([("Booting from ISO for Installation", qemu_cmd)])


def _get_qemu_command(vm_name, vm_settings, ssh_port, iso_path=None, virtio_path=None, use_overlay=False):
    """
    Builds a standardized and performant QEMU command for a Windows VM.
    """
    paths = get_vm_paths(vm_name)
    disk_path = paths['overlay'] if use_overlay and os.path.exists(paths['overlay']) else paths['base']

    qemu_cmd = [
        CONFIG["QEMU_BINARY"],
        "-enable-kvm",
        "-m", vm_settings["VM_MEM"],
        "-smp", f"cores={int(vm_settings['VM_CPU']) // 2},threads=2,sockets=1",
        "-cpu", "host,hv_relaxed,hv_spinlocks=0x1fff,hv_vapic,hv_time",
        "-uuid", vm_settings['uuid'],
        "-drive", f"if=pflash,format=raw,readonly=on,file={find_first_existing_path(CONFIG['UEFI_CODE_PATHS'])}",
        "-drive", f"if=pflash,format=raw,file={paths['uefi_vars']}",
        "-drive", f"file={disk_path},if=virtio,cache=writeback,aio=threads",
        "-net", f"nic,model=virtio,macaddr={vm_settings['mac_addr']}",
        "-net", f"user,hostfwd=tcp::{ssh_port}-:22",
        "-vga", "qxl",
        "-global", "qxl-vga.vram_size=134217728",
        "-display", "gtk",
        "-device", "qemu-xhci",
        "-device", "usb-tablet",
        "-pidfile", paths['pid_file'],
        "-fsdev", f"local,security_model=passthrough,id=fsdev0,path={os.path.join(paths['dir'], 'shared')}",
        "-device", "virtio-9p-pci,id=fs0,fsdev=fsdev0,mount_tag=host_share",
    ]

    if iso_path:
        qemu_cmd.extend(["-cdrom", iso_path])
    if virtio_path:
        qemu_cmd.extend(["-drive", f"file={virtio_path},media=cdrom,index=3"])

    return qemu_cmd


# --- FIX: Removed the duplicated and buggy _prepare_run_session function ---
# The correct version is below.
def _prepare_run_session(vm_name):
    """Prepares a VM for running by ensuring its files exist."""
    paths = get_vm_paths(vm_name)
    if not os.path.exists(paths['base']):
        print_error(f"Base disk for '{vm_name}' not found. Cannot run.")
        return None, None

    # Load saved config or create it if it's missing
    vm_settings = {}
    if os.path.exists(paths['config']):
        try:
            with open(paths['config'], 'r', encoding='utf-8') as f:
                vm_settings = json.load(f)
        except (json.JSONDecodeError, IOError):
            print_warning("Could not load saved config, using defaults.")

    # Use defaults for any missing critical settings
    if "VM_MEM" not in vm_settings: vm_settings["VM_MEM"] = "8G"
    if "VM_CPU" not in vm_settings: vm_settings["VM_CPU"] = "4"

    # Ensure persistent hardware identifiers exist and are correct
    if 'uuid' not in vm_settings:
        vm_settings['uuid'] = str(uuid.uuid4())
    if 'mac_addr' not in vm_settings:
        vm_settings['mac_addr'] = _generate_mac_address()

    # Save the potentially updated config
    with open(paths['config'], 'w', encoding='utf-8') as f:
        json.dump(vm_settings, f, indent=4)

    # Create overlay if it doesn't exist
    if not os.path.exists(paths['overlay']):
        print_info("No existing session found. Creating a new one (overlay disk).")
        run_command_live(["qemu-img", "create", "-f", "qcow2", "-b", paths['base'], "-F", "qcow2", paths['overlay']], check=True)

    return paths, vm_settings


def run_windows_vm():
    """
    Runs an existing Windows VM with clearer session logic.
    """
    clear_screen()
    vm_name = select_vm("Run / Resume")
    if not vm_name:
        return

    if is_vm_running(vm_name):
        print_error(f"VM '{vm_name}' is already running.")
        return

    paths, vm_settings = _prepare_run_session(vm_name)
    if not paths:
        return

    # Ask for memory and CPU at runtime
    runtime_settings = get_vm_config({
        "VM_MEM": vm_settings.get('VM_MEM', '8G'),
        "VM_CPU": vm_settings.get('VM_CPU', '4')
    })
    vm_settings.update(runtime_settings)

    ssh_port = find_unused_port()
    print_info(f"SSH will be available on host port {ssh_port}")
    with open(os.path.join(paths['dir'], 'session.info'), 'w', encoding='utf-8') as f:
        f.write(str(ssh_port))

    virtio_path = find_virtio_iso_path()
    if virtio_path is None:
        print_error("VirtIO driver selection was cancelled. Aborting VM run.")
        return

    qemu_cmd = _get_qemu_command(vm_name, vm_settings, ssh_port, use_overlay=True, virtio_path=virtio_path)

    debug_mode = questionary.select(
        "Select a debug mode:",
        choices=["None", "Show QEMU command", "Verbose Debug (run in this terminal)"]
    ).ask()

    if debug_mode == "Show QEMU command":
        print_info("QEMU command:")
        print(" ".join(qemu_cmd))
        launch_in_new_terminal_and_wait([("Booting Windows VM", qemu_cmd)])
    elif debug_mode == "Verbose Debug (run in this terminal)":
        print_info("Running QEMU in verbose mode...")
        run_command_live(qemu_cmd)
    else:
        launch_in_new_terminal_and_wait([("Booting Windows VM", qemu_cmd)])


def nuke_and_recreate_windows_vm():
    """
    Nukes the overlay disk and UEFI vars of a VM to start a fresh session.
    """
    clear_screen()
    vm_name = select_vm("Nuke & Boot a Fresh Session")
    if not vm_name:
        return

    if is_vm_running(vm_name):
        print_error(f"Cannot nuke session for '{vm_name}' while it is running. Please stop it first.")
        return

    paths, vm_settings = _prepare_run_session(vm_name)
    if not paths:
        return

    if os.path.exists(paths['overlay']):
        print_warning(f"You are about to permanently delete the current session for '{vm_name}'.")
        if not questionary.confirm("Are you sure?").ask():
            print_info("Operation cancelled.")
            return
        os.remove(paths['overlay'])
        print_success("Session overlay disk has been nuked.")

    # Reset UEFI variables to factory default
    uefi_vars_path = find_first_existing_path(CONFIG['UEFI_VARS_PATHS'])
    if not uefi_vars_path:
        print_error("Could not find UEFI VARS template file. Aborting.")
        return
    run_command_live(["cp", uefi_vars_path, paths['uefi_vars']], quiet=True)
    print_success("UEFI variables have been reset.")

    # Re-create the overlay
    run_command_live(["qemu-img", "create", "-f", "qcow2", "-b", paths['base'], "-F", "qcow2", paths['overlay']], check=True)

    # Ask for memory and CPU at runtime
    runtime_settings = get_vm_config({
        "VM_MEM": vm_settings.get('VM_MEM', '8G'),
        "VM_CPU": vm_settings.get('VM_CPU', '4')
    })
    vm_settings.update(runtime_settings)

    ssh_port = find_unused_port()
    print_info(f"SSH will be available on host port {ssh_port}")
    with open(os.path.join(paths['dir'], 'session.info'), 'w', encoding='utf-8') as f:
        f.write(str(ssh_port))

    virtio_path = find_virtio_iso_path()
    if virtio_path is None:
        print_error("VirtIO driver selection was cancelled. Aborting VM run.")
        return

    qemu_cmd = _get_qemu_command(vm_name, vm_settings, ssh_port, use_overlay=True, virtio_path=virtio_path)

    debug_mode = questionary.select(
        "Select a debug mode:",
        choices=["None", "Show QEMU command", "Verbose Debug (run in this terminal)"]
    ).ask()

    if debug_mode == "Show QEMU command":
        print_info("QEMU command:")
        print(" ".join(qemu_cmd))
        launch_in_new_terminal_and_wait([("Booting Fresh VM Session", qemu_cmd)])
    elif debug_mode == "Verbose Debug (run in this terminal)":
        print_info("Running QEMU in verbose mode...")
        run_command_live(qemu_cmd)
    else:
        launch_in_new_terminal_and_wait([("Booting Fresh VM Session", qemu_cmd)])


def delete_windows_vm():
    """
    Completely and permanently deletes a Windows VM directory.
    """
    clear_screen()
    vm_name = select_vm("Delete Completely")
    if not vm_name:
        return

    if is_vm_running(vm_name):
        print_error(f"Cannot delete '{vm_name}' while it is running. Please stop it first.")
        return

    print_warning(f"This will permanently delete the entire VM '{vm_name}', including its virtual disk.\nThis action CANNOT be undone.")
    result = questionary.text(f"To confirm, please type the name of the VM ({vm_name}):").ask()
    if result is None:
        print_info("Deletion cancelled.")
        return
    confirm = result.strip()
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
        console.rule(style="dim")
        choice = questionary.select(
            "Select an option",
            choices=[
                "1. Create New Windows VM",
                "2. Run Existing Windows VM",
                "3. Nuke & Boot a Fresh Session",
                "4. Stop a Running VM",
                "5. Transfer Files (SFTP)",
                "6. Delete Windows VM Completely",
                "7. Return to Main Menu",
            ]
        ).ask()

        if not choice: # Handle Ctrl+C
            break

        action_taken = True
        if "1." in choice: create_new_windows_vm()
        elif "2." in choice: run_windows_vm()
        elif "3." in choice: nuke_and_recreate_windows_vm()
        elif "4." in choice: stop_vm()
        elif "5." in choice:
            vm_name = select_vm("Transfer Files with", running_only=True)
            if vm_name:
                vm_dir = get_vm_paths(vm_name)['dir']
                transfer_files_menu(vm_name, "windows", vm_dir)
        elif "6." in choice: delete_windows_vm()
        elif "7." in choice: break
        else:
            print_warning("Invalid option.")
            action_taken = False

        if action_taken and choice != "7. Return to Main Menu":
            questionary.text("\nPress Enter to return to the menu...").ask()


if __name__ == '__main__':
    windows_vm_menu()
