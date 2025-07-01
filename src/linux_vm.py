# Made by trex099
# https://github.com/Trex099/Glint
# pylint: disable=too-many-lines,too-many-arguments,too-many-locals
# pylint: disable=too-many-return-statements,too-many-branches,too-many-statements
"""
This module handles all Linux VM management functionality with improved
security, clarity, and robustness.
"""
import os
import subprocess
import sys
import shutil
import uuid
import random
import re
import time
import questionary
from rich.console import Console

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG, DISTRO_INFO
from file_transfer import transfer_files_menu
from core_utils import (
    print_header, print_info, print_success, print_warning, print_error, clear_screen,
    run_command_live, _run_command, launch_in_new_terminal_and_wait, remove_file, remove_dir,
    select_from_list, find_host_dns, find_unused_port, detect_distro, get_vm_config,
    identify_iso_type, find_first_existing_path, get_disk_size, is_vfio_module_loaded
)

console = Console()

def _detect_display_manager():
    """Detects the running display manager service."""
    try:
        result = run_command_live(["systemctl", "list-units", "--type=service", "--state=running"], quiet=True)
        for line in result.splitlines():
            if "display-manager.service" in line:
                return line.split()[0]
    except Exception:
        return None
    return None

def find_input_devices():
    """Finds keyboard and mouse event devices."""
    input_dir = "/dev/input/by-id"
    try:
        devices = os.listdir(input_dir)
        kbd = next((os.path.join(input_dir, d) for d in devices if "kbd" in d), None)
        mouse = next((os.path.join(input_dir, d) for d in devices if "mouse" in d), None)
        if not kbd or not mouse:
            print_error("Could not find keyboard or mouse in /dev/input/by-id.")
            return None
        return {"keyboard": kbd, "mouse": mouse}
    except FileNotFoundError:
        print_error("/dev/input/by-id not found. Cannot find input devices.")
        return None

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
        "session_info": os.path.join(vm_dir, "session.info")
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






def check_dependencies():
    """
    Checks for required system dependencies using the centralized UEFI path config.
    """
    print_header("System Dependency Check")
    distro_id = detect_distro()
    info = DISTRO_INFO.get(distro_id)
    
    # Find the UEFI code file using the centralized config
    uefi_code_path = find_first_existing_path(CONFIG['UEFI_CODE_PATHS'])

    if not info:
        print_warning(f"Unsupported host distro ('{distro_id}').")
        print_info("Please manually install 'qemu' and 'ovmf/edk2' packages.")
        return shutil.which(CONFIG['QEMU_BINARY']) and uefi_code_path

    missing_pkgs = []
    if not shutil.which(CONFIG['QEMU_BINARY']):
        missing_pkgs.append(info['pkgs']['qemu'])

    if not uefi_code_path:
        missing_pkgs.append(info['pkgs']['ovmf'])

    if not missing_pkgs:
        print_success("All required packages are installed.")
        return True

    print_error(f"Missing required software for host distro '{distro_id}'.")
    install_cmd_list = ["sudo"] + info['cmd'].split() + sorted(list(set(missing_pkgs)))
    
    print_info("To fix this, the recommended command is:")
    console.print(f"  [bold]{' '.join(install_cmd_list)}[/]")

    if questionary.confirm("Run this command now?").ask():
        if run_command_live(install_cmd_list, as_root=False) is not None:
            print_success("\nInstallation successful. Please re-run the script.")
        else:
            print_error("\nInstallation failed.")
        sys.exit()
        
    return False



def get_running_vm_info(vm_name):
    """
    Safely retrieves information about a running VM.
    """
    paths = get_vm_paths(vm_name)
    pid_file, session_info_file = paths['pid_file'], paths['session_info']
    
    if not os.path.exists(pid_file):
        return None
        
    try:
        with open(pid_file, 'r', encoding='utf-8') as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # Check if process exists
        
        with open(session_info_file, 'r', encoding='utf-8') as f:
            ssh_port = int(f.read().strip())
            
        return {'pid': pid, 'port': ssh_port}
    except (IOError, ValueError, ProcessLookupError, OSError):
        # Cleanup stale files if process is not running
        for f in [pid_file, session_info_file]:
            if os.path.exists(f):
                remove_file(f)
        return None


def is_vm_running(vm_name):
    """Checks if a VM is running."""
    return get_running_vm_info(vm_name) is not None


def cleanup_stale_sessions():
    """Iterate through all VMs and clean up stale PID files."""
    vms_dir = CONFIG['VMS_DIR_LINUX']
    if not os.path.isdir(vms_dir):
        return
    for vm_name in os.listdir(vms_dir):
        if os.path.isdir(os.path.join(vms_dir, vm_name)):
            is_vm_running(vm_name)


def create_new_vm():
    """Guides the user through creating a new Linux VM."""
    clear_screen()
    print_header("Create New Linux VM")
    if not check_dependencies():
        return

    while True:
        vm_name = questionary.text("Enter a short name for new VM (e.g., arch-kde):").ask().strip()
        if not re.match(r"^[a-zA-Z0-9_-]+$", vm_name):
            print_warning("Invalid name. Use only letters, numbers, hyphens, and underscores.")
        elif os.path.exists(os.path.join(CONFIG['VMS_DIR_LINUX'], vm_name)):
            print_warning("A VM with this name already exists.")
        else:
            break

    paths = get_vm_paths(vm_name)
    iso_path = find_iso_path()
    if not iso_path:
        return

    disk = get_disk_size("Enter base disk size (GB)", CONFIG['BASE_DISK_SIZE'])

    vm_settings = get_vm_config({"VM_MEM": CONFIG['VM_MEM'], "VM_CPU": CONFIG['VM_CPU']})
    
    # Generate a new UUID for the VM
    vm_ids = {'uuid': str(uuid.uuid4()), 'mac': ''}
    
    ssh_port = find_unused_port()
    print_info(f"SSH will be available on host port {ssh_port}")
    with open(paths['session_info'], 'w', encoding='utf-8') as f:
        f.write(str(ssh_port))

    qemu_cmd = _get_qemu_command(vm_name, vm_settings, {}, vm_ids, find_host_dns(), ssh_port, iso_path=iso_path)

    uefi_vars_path = find_first_existing_path(CONFIG['UEFI_VARS_PATHS'])
    if not uefi_vars_path:
        print_error("Could not find a valid UEFI VARS template file. Cannot proceed.")
        return

    commands_to_run = [
        ("Creating directory structure", ["mkdir", "-p", paths['dir'], paths['shared_dir']]),
        ("Preparing UEFI seed", ["cp", uefi_vars_path, paths['seed']]),
        (f"Creating {disk}G base image", ["qemu-img", "create", "-f", "qcow2", paths['base'], f"{disk}G"]),
        ("Booting from ISO (Install your OS, then simply close this terminal window)", qemu_cmd)
    ]
    launch_in_new_terminal_and_wait(commands_to_run)


def _build_qemu_base_cmd(vm_name, vm_settings, ids):
    """Builds the base QEMU command list."""
    paths = get_vm_paths(vm_name)
    uefi_code_path = find_first_existing_path(CONFIG['UEFI_CODE_PATHS'])
    if not uefi_code_path:
        print_error("Could not find a valid UEFI firmware file. Cannot proceed.")
        return None

    return [
        CONFIG["QEMU_BINARY"],
        "-enable-kvm",
        "-m", vm_settings["VM_MEM"],
        "-smp", vm_settings["VM_CPU"],
        "-uuid", ids['uuid'],
        "-drive", f"if=pflash,format=raw,readonly=on,file={uefi_code_path}",
        "-fsdev", f"local,security_model=mapped-xattr,id=fsdev0,path={paths['shared_dir']}",
        "-device", f"virtio-9p-pci,fsdev=fsdev0,mount_tag={CONFIG['SHARED_DIR_MOUNT_TAG']}",
        "-pidfile", paths['pid_file']
    ]

def _add_network_args(qemu_cmd, ids, ssh_port, host_dns):
    """Adds networking arguments to the QEMU command."""
    if ssh_port > 0:
        qemu_cmd.extend([
            "-netdev", f"user,id=n1,dns={host_dns},hostfwd=tcp::{ssh_port}-:22",
            "-device", f"virtio-net-pci,netdev=n1,mac={ids['mac']}"
        ])
    else:
        qemu_cmd.extend(["-netdev", "user,id=n1", "-device", f"virtio-net-pci,netdev=n1,mac={ids['mac']}"])

def _add_passthrough_args(qemu_cmd, passthrough_info, input_devices):
    """Adds PCI passthrough arguments to the QEMU command."""
    is_gpu = any(d.get('class_code') == '0300' for d in passthrough_info['devices'].values())
    
    if is_gpu:
        cpu_args = "host,kvm=off,hv_vendor_id=null" if passthrough_info['vendor'] == "NVIDIA" else "host"
        qemu_cmd.extend(["-cpu", cpu_args, "-nographic"])
        if input_devices:
            qemu_cmd.extend([
                "-object", f"input-linux,id=mouse,evdev={input_devices['mouse']}",
                "-object", f"input-linux,id=kbd,evdev={input_devices['keyboard']},grab_all=on,repeat=on"
            ])
    else:
        qemu_cmd.extend(["-cpu", "host", "-vga", "virtio", *CONFIG["QEMU_DISPLAY"]])

    # Add all PCI devices
    primary_gpu_pci = passthrough_info.get('vga_pci')
    is_vga_set = False
    for pci_id in passthrough_info['pci_ids']:
        device_args = ["-device", f"vfio-pci,host={pci_id}"]
        if is_gpu and primary_gpu_pci == pci_id and not is_vga_set:
            device_args.append("x-vga=on,rombar=0")
            is_vga_set = True
        qemu_cmd.extend(device_args)

def _get_qemu_command(vm_name, vm_settings, input_devices, ids, host_dns,
                      ssh_port, passthrough_info=None, iso_path=None):
    """
    Constructs the full QEMU command list by assembling modular parts.
    """
    paths = get_vm_paths(vm_name)
    qemu_cmd = _build_qemu_base_cmd(vm_name, vm_settings, ids)
    
    # Set UEFI vars path based on whether it's an install or run
    uefi_vars_path = paths['seed'] if iso_path else paths['instance']
    qemu_cmd.append(f"-drive,if=pflash,format=raw,file={uefi_vars_path}")

    _add_network_args(qemu_cmd, ids, ssh_port, host_dns)

    if passthrough_info:
        _add_passthrough_args(qemu_cmd, passthrough_info, input_devices)
        qemu_cmd.append(f"-drive,file={paths['base']},if=virtio")
    elif iso_path:
        # Standard install
        qemu_cmd.extend(["-cpu", "host", "-vga", "virtio", *CONFIG["QEMU_DISPLAY"]])
        qemu_cmd.extend(["-drive", f"file={paths['base']},if=virtio", "-cdrom", iso_path])
    else:
        # Standard run
        qemu_cmd.extend(["-cpu", "host", "-vga", "virtio", *CONFIG["QEMU_DISPLAY"]])
        qemu_cmd.append(f"-drive,file={paths['overlay']},if=virtio,cache=writeback")

    return qemu_cmd


def _prepare_vm_session(vm_name, is_fresh):
    """Handles the logic for starting a fresh or resuming a session."""
    if is_vm_running(vm_name):
        print_error(f"VM '{vm_name}' is already running.")
        return None, None

    paths = get_vm_paths(vm_name)
    if is_fresh:
        if not _nuke_session_files(paths):
            return None, None
    elif not os.path.exists(paths['overlay']):
        print_info("No existing session found. Starting a fresh one instead.")
        is_fresh = True

    # Generate or load session identifiers
    if is_fresh or not os.path.exists(paths['session_id']):
        new_uuid = str(uuid.uuid4())
        new_mac = f"52:54:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"
        print_header("Generating New Session Identifiers")
        print_info(f"System UUID: [bold]{new_uuid}[/]\nMAC Address: [bold]{new_mac}[/]")
        with open(paths['session_id'], 'w', encoding='utf-8') as f:
            f.write(f"{new_uuid}\n{new_mac}\n")
        ids = {'uuid': new_uuid, 'mac': new_mac}
    else:
        with open(paths['session_id'], 'r', encoding='utf-8') as f:
            lines = f.readlines()
        ids = {'uuid': lines[0].strip(), 'mac': lines[1].strip()}
        print_info(f"Resuming with System UUID: [bold]{ids['uuid']}[/]")

    # Prepare disk images
    if not os.path.exists(paths['instance']):
        run_command_live(["cp", paths['seed'], paths['instance']], check=True)
    if not os.path.exists(paths['overlay']):
        run_command_live(["qemu-img", "create", "-f", "qcow2", "-b", paths['base'], "-F", "qcow2", paths['overlay']], check=True)
        
    return paths, ids

def run_or_nuke_vm(vm_name, is_fresh):
    """
    Runs or nukes a VM session with clearer logic.
    """
    session_type = "Nuke & Boot" if is_fresh else "Run / Resume"
    print_header(f"{session_type}: '{vm_name}'")
    
    paths, ids = _prepare_vm_session(vm_name, is_fresh)
    if not paths:
        return

    vm_settings = get_vm_config({"VM_MEM": CONFIG['VM_MEM'], "VM_CPU": CONFIG['VM_CPU']})
    host_dns = find_host_dns()
    ssh_port = find_unused_port()
    print_info(f"SSH will be available on host port {ssh_port}")
    with open(paths['session_info'], 'w', encoding='utf-8') as f:
        f.write(str(ssh_port))

    qemu_cmd = _get_qemu_command(vm_name, vm_settings, {}, ids, host_dns, ssh_port)
    launch_in_new_terminal_and_wait([("Booting VM", qemu_cmd)])


def _nuke_session_files(paths):
    """Deletes session-specific files for a VM."""
    files_to_nuke = [paths['overlay'], paths['instance'], paths['session_id'], paths['pid_file'], paths['session_info']]
    if not any(os.path.exists(f) for f in files_to_nuke):
        print_info("No session files found to nuke for this VM.")
        return True

    print_warning(f"You are about to permanently delete the current session for '{os.path.basename(paths['dir'])}'.")
    if not questionary.confirm("Are you sure?").ask():
        print_info("Operation cancelled.")
        return False

    if is_vm_running(os.path.basename(paths['dir'])):
        print_info("VM is running, stopping it first...")
        stop_vm(vm_name=os.path.basename(paths['dir']), force=True)

    for f in files_to_nuke:
        if os.path.exists(f):
            remove_file(f)

    print_success("Nuke operation complete.")
    return True


def nuke_vm_completely():
    """Permanently deletes an entire VM and its directory."""
    clear_screen()
    vm_name = select_vm("Nuke Completely")
    if not vm_name:
        return
    if is_vm_running(vm_name):
        print_error(f"Cannot nuke '{vm_name}' while it is running. Please stop it first.")
        return

    print_warning(f"This will permanently delete the entire VM '{vm_name}', including its base image.\nThis action CANNOT be undone.")
    confirm = questionary.text(f"To confirm, please type the name of the VM ({vm_name}):").ask().strip()
    if confirm == vm_name:
        remove_dir(get_vm_paths(vm_name)['dir'])
    else:
        print_error("Confirmation failed. Aborting.")


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
        time.sleep(1)
        paths = get_vm_paths(vm_name)
        for f in [paths['pid_file'], paths['session_info']]:
            if os.path.exists(f):
                remove_file(f)
    elif not force:
        print_error(f"Could not get running info for '{vm_name}'. It may not be running.")


def transfer_files():
    """Transfers files to/from a running VM via SCP."""
    clear_screen()
    vm_name = select_vm("Transfer Files with", running_only=True)
    if not vm_name:
        return

    vm_info = get_running_vm_info(vm_name)
    if not vm_info:
        print_error(f"VM '{vm_name}' is not running or its session info is invalid.")
        return

    print_header(f"File Transfer for '{vm_name}'")
    while True:
        direction = questionary.select("Direction?", choices=["Host to VM", "VM to Host"]).ask()
        if direction:
            break
        print_warning("Invalid choice.")

    while True:
        local_path = os.path.expanduser(questionary.text("Enter path on LOCAL host:").ask().strip())
        if os.path.exists(local_path):
            break
        print_warning(f"Local path not found: '{local_path}'. Please check for typos.")

    remote_path = questionary.text("Enter full path on REMOTE vm (use quotes if needed):").ask().strip()
    vm_user = questionary.text("Enter username inside the VM:").ask().strip()

    port = vm_info['port']
    src, dest = (local_path, f"{vm_user}@localhost:{remote_path}") if direction == "Host to VM" else (f"{vm_user}@localhost:{remote_path}", local_path)

    scp_cmd = ["scp", "-r", "-P", str(port), src, dest]
    run_command_live(scp_cmd)


def gpu_passthrough_menu():
    """Menu for GPU passthrough on Linux VMs."""
    clear_screen()
    print_header("Passthrough & Performance (Linux)")
    
    choice = questionary.select(
        "Select an option:",
        choices=[
            "1. Run VM with Live Passthrough",
            "2. System Compatibility Check",
            "3. Return to Linux VM Menu"
        ]
    ).ask()

    if choice == "1. Run VM with Live Passthrough":
        run_vm_with_live_passthrough()
    elif choice == "2. System Compatibility Check":
        run_gpu_passthrough_check()
    else:
        return

def _get_gpus():
    """Gets a list of GPUs."""
    return _find_pci_devices_by_class("0300")

def _get_usb_controllers():
    """Gets a list of USB controllers."""
    return _find_pci_devices_by_class("0c03")

def _get_nvme_drives():
    """Gets a list of NVMe drives."""
    return _find_pci_devices_by_class("0108")

def _select_guest_gpu():
    """Prompts the user to select a GPU for passthrough."""
    gpus = _get_gpus()
    if not gpus:
        print_error("No GPUs found.")
        return None
    return select_from_list(gpus, "Select the GPU to pass through to the guest", 'display')

def _check_vfio_binding_status(guest_gpu):
    """Checks if the selected GPU is bound to the vfio-pci driver."""
    print_header("3. VFIO Driver Binding Check")
    if guest_gpu['driver'] == 'vfio-pci':
        print_success(f"Guest GPU {guest_gpu['pci']} is correctly bound to vfio-pci.")
        return True
    
    print_warning(f"Guest GPU {guest_gpu['pci']} is currently using the '{guest_gpu['driver']}' driver.")
    print_info("The script can attempt to unbind it and bind to vfio-pci at runtime, but permanent binding is recommended for stability.")
    return False

def _check_nvidia_quirks(guest_gpu):
    """Checks for common NVIDIA-related passthrough issues."""
    if not guest_gpu['ids'].startswith('10de'): # Not an NVIDIA GPU
        return

    print_header("4. NVIDIA Specific Checks")
    try:
        dmesg_out = _run_command(["dmesg"])
        if "NVRM: an NVIDIA GPU is found" in dmesg_out and "NVRM: loading NVIDIA UNIX" in dmesg_out:
            print_warning("NVIDIA host drivers appear to be loaded. This can interfere with passthrough.")
            print_info("It's recommended to blacklist the NVIDIA drivers (nouveau, nvidia, nvidia_drm, etc.) on the host.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_warning("Could not check dmesg for NVIDIA driver status.")

def _check_iommu_groups_sanity(guest_gpu):
    """Checks the IOMMU group of the selected GPU for other devices."""
    print_header("5. IOMMU Group Sanity Check")
    iommu_groups = _get_iommu_groups()
    group, devices, others = _get_full_iommu_group_devices(guest_gpu['pci'], iommu_groups)

    if not group:
        print_error(f"Could not determine IOMMU group for {guest_gpu['pci']}.")
        return False

    print_info(f"GPU {guest_gpu['pci']} is in IOMMU Group {group}.")
    if not others:
        print_success("GPU is in a clean IOMMU group.")
        return True

    print_warning("This GPU is in an IOMMU group with other devices:")
    for dev in devices:
        console.print(f"  - {dev}")
    print_info("Passing this GPU will require passing all devices in this group.")
    return True


def _check_system_type():
    """Checks if the system is a laptop based on chassis type."""
    try:
        chassis_type = _run_command(["cat", "/sys/class/dmi/id/chassis_type"], as_root=True)
        return chassis_type in ['8', '9', '10', '11', '12', '14', '30', '31', '32']
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_warning("Could not determine chassis type.")
        return False

def _fix_grub_cmdline(param_to_add):
    """
    Advises the user on how to manually add a kernel parameter to GRUB,
    instead of modifying the file directly.
    """
    grub_file = "/etc/default/grub"
    distro = detect_distro()
    update_cmd = DISTRO_INFO.get(distro, {}).get("grub_update", "sudo update-grub")

    print_warning("ACTION REQUIRED: Manual GRUB update needed.")
    print_info(f"To enable IOMMU, you need to add '{param_to_add}' to your kernel boot parameters.")
    console.print(f"""
  1. Open the GRUB configuration file:
     [bold]sudo nano {grub_file}[/]
  2. Find the line starting with [cyan]GRUB_CMDLINE_LINUX_DEFAULT[/].
  3. Add [bold]{param_to_add}[/] inside the quotes.
     Example: GRUB_CMDLINE_LINUX_DEFAULT="quiet splash {param_to_add}"
  4. Save the file and exit the editor.
  5. Update GRUB with the command:
     [bold]{update_cmd}[/]
  6. Reboot your system for the changes to take effect:
     [bold]sudo reboot[/]
    """)


def _check_iommu_support():
    """Checks for CPU and BIOS support for IOMMU."""
    print_header("2. CPU & BIOS IOMMU Check")
    try:
        cpu_info = _run_command(["lscpu"])
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_error("`lscpu` command failed. Is `pciutils` installed?")
        return False

    vendor = "Intel" if "GenuineIntel" in cpu_info else "AMD"
    virt_feature = "VT-x" if vendor == "Intel" else "svm"
    iommu_feature = "VT-d" if vendor == "Intel" else "AMD-Vi"

    if virt_feature not in cpu_info:
        print_error(f"FATAL: CPU does not support virtualization ({virt_feature}).")
        return False
    print_success(f"CPU supports virtualization ({virt_feature}).")

    iommu_groups_path = "/sys/kernel/iommu_groups/"
    if os.path.exists(iommu_groups_path) and os.listdir(iommu_groups_path):
        print_success(f"IOMMU ({iommu_feature}) is active in the kernel.")
        return True

    print_error(f"FAIL: IOMMU ({iommu_feature}) does not appear to be active in the kernel.")
    print_info("This is usually because it's disabled in the BIOS/UEFI or the required kernel parameter is missing.")

    param = "intel_iommu=on" if vendor == "Intel" else "amd_iommu=on"
    if questionary.confirm(f"Would you like instructions on how to add the '{param}' kernel parameter to GRUB?").ask():
        _fix_grub_cmdline(param)
    
    return False


def _find_pci_devices_by_class(class_code):
    """Finds PCI devices by their class code."""
    try:
        lspci_out = _run_command(["lspci", "-nnk"])
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_error("`lspci` command failed. Is `pciutils` installed?")
        return []

    devices = []
    pci_regex = re.compile(
        r"^([\da-f:.]+)\s"
        r".*?\[" + class_code + r"\]:\s+"
        r"(.*?)\s+"
        r"\[([\da-f]{4}:[\da-f]{4})\]"
        r"(?:.|\n)*?"
        r"^\s+Kernel driver in use:\s+(\S+)",
        re.MULTILINE
    )

    for match in pci_regex.finditer(lspci_out):
        pci, name, vdid, drv = match.groups()
        devices.append({
            "pci": pci.strip(), "name": name.strip(), "ids": vdid.strip(),
            "driver": drv.strip(), "class_code": class_code,
            "display": f"[{pci.strip()}] {name.strip()} (driver: {drv.strip()})"
        })
    return devices

# ... (rest of the passthrough functions remain largely the same but will call the refactored helpers) ...

def run_gpu_passthrough_check():
    """Runs the GPU passthrough compatibility check."""
    clear_screen()
    print_header("GPU Passthrough System Compatibility Check")
    if _check_system_type():
        print_warning("Laptop detected. Passthrough is extremely difficult and success is highly unlikely.")
    else:
        print_success("Desktop system detected. Ideal for passthrough.")

    if not _check_iommu_support():
        return

    guest_gpu = _select_guest_gpu()
    if not guest_gpu:
        return

    _check_vfio_binding_status(guest_gpu)
    _check_nvidia_quirks(guest_gpu)

    if not _check_iommu_groups_sanity(guest_gpu):
        return

    print_header("🎉 Checklist Complete! 🎉")
    print_info("Review output. If any checks failed, they must be resolved before proceeding.")
    print_warning("If you made any changes (like updating GRUB), a reboot is required.")


def _execute_passthrough_lifecycle(vm_name, passthrough_info, vm_settings, input_devices):
    """
    Manages the entire lifecycle of a passthrough VM with more robust error checking
    and step-by-step verification.
    """
    dm_service = _detect_display_manager()
    original_drivers = {}
    bound_to_vfio = set()

    try:
        # --- PRE-LAUNCH: Prepare Host ---
        print_header("Preparing Host for Passthrough")
        if dm_service:
            print_info(f"Stopping display manager ({dm_service})...")
            if run_command_live(["systemctl", "stop", dm_service], as_root=True) is None:
                raise RuntimeError(f"Failed to stop display manager {dm_service}.")
            print_success("Display manager stopped.")
            time.sleep(3)

        for pci_id in passthrough_info['pci_ids']:
            original_drivers[pci_id] = _get_pci_device_driver(pci_id)
            if original_drivers[pci_id]:
                print_info(f"Unbinding {pci_id} from host driver '{original_drivers[pci_id]}'...")
                run_command_live(["bash", "-c", f"echo {pci_id} > /sys/bus/pci/devices/{pci_id}/driver/unbind"], as_root=True)
                if _get_pci_device_driver(pci_id) is not None:
                    raise RuntimeError(f"Failed to unbind {pci_id} from {original_drivers[pci_id]}.")
                print_success(f"Successfully unbound {pci_id}.")

            print_info(f"Binding {pci_id} to vfio-pci...")
            if run_command_live(["bash", "-c", f"echo {pci_id} > /sys/bus/pci/drivers/vfio-pci/bind"], as_root=True, quiet=True) is None:
                raise RuntimeError(f"Failed to bind {pci_id} to vfio-pci.")
            
            # Verify binding
            if _get_pci_device_driver(pci_id) != "vfio-pci":
                 raise RuntimeError(f"Verification failed: {pci_id} is not bound to vfio-pci.")
            print_success(f"Successfully bound {pci_id} to vfio-pci.")
            bound_to_vfio.add(pci_id)

        print_success("Host prepared. Launching VM...")

        # --- LAUNCH: Run QEMU ---
        ids = {'uuid': str(uuid.uuid4()), 'mac': f"52:54:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"}
        qemu_cmd = _get_qemu_command(
            vm_name, vm_settings, input_devices, ids, find_host_dns(), 0, passthrough_info
        )
        if qemu_cmd is None:
            raise RuntimeError("Failed to construct QEMU command.")
            
        run_command_live(qemu_cmd, as_root=True)

    except Exception as e:
        print_error(f"An error occurred during passthrough lifecycle: {e}")
        print_warning("Attempting to restore host state...")
    finally:
        # --- POST-LAUNCH: Restore Host ---
        print_header("Restoring Host State")
        for pci_id in passthrough_info['pci_ids']:
            # Only try to rebind if it was successfully bound to vfio-pci
            if pci_id in bound_to_vfio:
                print_info(f"Unbinding {pci_id} from vfio-pci...")
                run_command_live(["bash", "-c", f"echo {pci_id} > /sys/bus/pci/drivers/vfio-pci/unbind"], as_root=True, quiet=True, check=False)

            original_driver = original_drivers.get(pci_id)
            if original_driver:
                print_info(f"Rebinding {pci_id} to its original driver '{original_driver}'...")
                run_command_live(["bash", "-c", f"echo {pci_id} > /sys/bus/pci/drivers/{original_driver}/bind"], as_root=True, quiet=True, check=False)
        
        if dm_service:
            print_info(f"Restarting display manager ({dm_service})...")
            run_command_live(["systemctl", "start", dm_service], as_root=True)
            
        print_success("Host state restoration complete.")


def run_vm_with_live_passthrough():
    """
    Guides the user through selecting devices and running a VM with live passthrough.
    """
    clear_screen()
    print_header("Run VM with Live Passthrough")

    if not _check_and_load_vfio_module():
        print_error("Launch aborted. Please resolve VFIO module issues and try again.")
        return

    vm_name = select_vm("run with Live Passthrough")
    if not vm_name:
        return

    passthrough_devices = {}
    while True:
        clear_screen()
        print_header("Select Devices for Passthrough")
        
        if passthrough_devices:
            console.print("[bold]Selected Devices:[/]")
            for i, dev in enumerate(passthrough_devices.values(), 1):
                console.print(f"  {i}. {dev['display']}")
        else:
            console.print("[dim]No devices selected yet.[/]")

        choices = {
            "1": ("GPU", _get_gpus),
            "2": ("USB Controller", _get_usb_controllers),
            "3": ("NVMe Drive", _get_nvme_drives),
            "4": ("Done Selecting", None)
        }
        
        console.print("\n[bold]Add a device:[/]")
        for key, (name, _) in choices.items():
            console.print(f"  [cyan]{key}.[/] {name}")
            
        choice = questionary.text("Select an option:").ask().strip()

        if choice == '4':
            if not passthrough_devices:
                print_warning("No devices were selected. Aborting launch.")
                return
            break
        
        if choice in choices:
            name, func = choices[choice]
            available_devices = [dev for dev in func() if dev['pci'] not in passthrough_devices]
            
            if not available_devices:
                print_warning(f"No available {name}s found to add.")
                time.sleep(2)
                continue

            selected_dev = select_from_list(available_devices, f"Choose a {name} to pass through", 'display')
            if selected_dev:
                passthrough_devices[selected_dev['pci']] = selected_dev
        else:
            print_warning("Invalid option.")
            time.sleep(1)

    # --- Gather all necessary info before execution ---
    print_header("Gathering All VM Information")
    final_pci_ids_to_bind = set()
    iommu_groups_out = _get_iommu_groups()

    for pci_id in passthrough_devices:
        _, group_pci_ids, _ = _get_full_iommu_group_devices(pci_id, iommu_groups_out)
        if not group_pci_ids:
            print_error(f"Could not find IOMMU group for {pci_id}. Aborting.")
            return
        final_pci_ids_to_bind.update(group_pci_ids)

    input_devices = find_input_devices()
    if not input_devices:
        return
    vm_settings = get_vm_config({"VM_MEM": CONFIG['VM_MEM'], "VM_CPU": CONFIG['VM_CPU']})

    primary_gpu = next((d for d in passthrough_devices.values() if d['class_code'] == '0300'), None)
    vendor = "NVIDIA" if any(dev['ids'].startswith('10de') for dev in passthrough_devices.values()) else ""
    
    passthrough_info = {
        "vga_pci": primary_gpu['pci'] if primary_gpu else list(final_pci_ids_to_bind)[0],
        "pci_ids": sorted(list(final_pci_ids_to_bind)),
        "vendor": vendor,
        "devices": passthrough_devices
    }

    # --- Pre-flight checklist and final confirmation ---
    clear_screen()
    print_header("Pre-Flight Checklist")
    console.print(f"[bold]VM Name:[/][/] {vm_name}")
    console.print(f"[bold]Memory:[/][/] {vm_settings['VM_MEM']}, [bold]CPU Cores:[/][/] {vm_settings['VM_CPU']}")
    console.print(f"[bold]Passthrough Devices:[/][/] {', '.join(sorted(list(final_pci_ids_to_bind)))}")
    console.print(f"[bold]Input Devices:[/][/] Keyboard: {input_devices['keyboard']}, Mouse: {input_devices['mouse']}")

    dm_service = _detect_display_manager()
    if dm_service:
        print_warning("\nCRITICAL WARNING: This process will stop your graphical desktop session.")
        if _check_system_type(): # is_laptop
            console.print("[red][bold]Your built-in screen WILL go black. This is NORMAL.[/]")
            console.print("[green]To see the VM, you MUST connect an external monitor to your laptop's HDMI/DisplayPort.[/]")
        else:
            console.print("[red][bold]Your primary monitor WILL go black. This is NORMAL.[/]")
            console.print("[green]You must connect a second monitor to the passed-through GPU to see the VM.[/]")
        console.print("[green]Your desktop will automatically return when the VM shuts down.[/]")

    if not questionary.confirm("Proceed with launch?").ask():
        return

    _execute_passthrough_lifecycle(vm_name, passthrough_info, vm_settings, input_devices)




def linux_vm_menu():
    """Main menu for Linux VM management."""
    os.makedirs(CONFIG['VMS_DIR_LINUX'], exist_ok=True)
    while True:
        cleanup_stale_sessions()
        clear_screen()
        console.print("[bold]Linux VM Management[/]")
        console.print("───────────────────────────────────────────────")
        try:
            choice = questionary.select(
                "Select an option",
                choices=[
                    "1. Create New Linux VM",
                    "2. Run / Resume VM Session (Standard Graphics)",
                    "3. Nuke & Boot a Fresh Session",
                    "4. Transfer Files (SFTP)",
                    "5. Passthrough & Performance (Advanced)",
                    "6. Stop a Running VM",
                    "7. Nuke VM Completely",
                    "8. Return to Main Menu",
                ]
            ).ask()
            action_taken = True
            if choice == "1. Create New Linux VM": create_new_vm()
            elif choice == "2. Run / Resume VM Session (Standard Graphics)":
                vm_name = select_vm("Run / Resume")
                if vm_name: run_or_nuke_vm(vm_name, is_fresh=False)
            elif choice == "3. Nuke & Boot a Fresh Session":
                vm_name = select_vm("Nuke & Boot")
                if vm_name: run_or_nuke_vm(vm_name, is_fresh=True)
            elif choice == "4. Transfer Files (SFTP)":
                vm_name = select_vm("Transfer Files with", running_only=True)
                if vm_name:
                    vm_dir = get_vm_paths(vm_name)['dir']
                    transfer_files_menu(vm_name, "linux", vm_dir)
            elif choice == "5. Passthrough & Performance (Advanced)": gpu_passthrough_menu()
            elif choice == "6. Stop a Running VM": stop_vm()
            elif choice == "7. Nuke VM Completely": nuke_vm_completely()
            elif choice == "8. Return to Main Menu": break
            else:
                print_warning("Invalid option.")
                action_taken = False

            if action_taken:
                questionary.text("\nPress Enter to return to the menu...").ask()
        except (KeyboardInterrupt, EOFError):
            break
        except RuntimeError as e:
            if "lost sys.stdin" in str(e):
                print_error("This script is interactive and cannot be run in this environment.")
                break
            raise e