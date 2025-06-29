import os
import subprocess
import sys
import shutil
import uuid
import random
import re
import time
import socket
import shlex

from config import CONFIG, DISTRO_INFO
from core_utils import (
    Style, print_header, print_info, print_success, print_warning, print_error, clear_screen,
    run_command_live, _run_command, launch_in_new_terminal_and_wait, remove_file, remove_dir,
    select_from_list, find_host_dns, find_unused_port, detect_distro
)


def get_vm_paths(vm_name):
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
    print_header(f"Select VM to {action_text}")
    vms_dir = CONFIG['VMS_DIR_LINUX']
    if not os.path.isdir(vms_dir) or not os.listdir(vms_dir):
        print_error("No Linux VMs found to list.")
        return None
    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])
    if running_only:
        vm_list = [vm for vm in vm_list if is_vm_running(vm)]
    if not vm_list:
        print_error("No running VMs found." if running_only else "No Linux VMs found.")
        return None
    return select_from_list(vm_list, "Choose a VM")


def get_vm_config(defaults):
    config = {}
    print_header("Configure Virtual Machine")
    while True:
        mem = input(f"{Style.BOLD}Enter Memory (e.g., 4G) [default: {defaults['VM_MEM']}]: {Style.ENDC}").strip().upper() or defaults['VM_MEM']
        if re.match(r"^\d+[MG]$", mem):
            config['VM_MEM'] = mem
            break
        else:
            print_warning("Invalid format. Use a number followed by 'M' or 'G'.")
    while True:
        cpu = input(f"{Style.BOLD}Enter CPU cores [default: {defaults['VM_CPU']}]: {Style.ENDC}").strip() or defaults['VM_CPU']
        if cpu.isdigit() and int(cpu) > 0:
            config['VM_CPU'] = cpu
            break
        else:
            print_warning("Invalid input.")
    return config


def find_iso_path():
    print_header("Select Installation ISO")
    isos = [f for f in os.listdir('.') if f.endswith('.iso')]
    if not isos:
        print_error("No .iso file found in the current directory.")
        return None
    iso_path = select_from_list(isos, "Choose an ISO") if len(isos) > 1 else isos[0]
    iso_abs_path = os.path.abspath(iso_path)
    print_info(f"Using ISO: {iso_abs_path}")
    return iso_abs_path


def check_dependencies():
    print_header("System Dependency Check")
    distro_id = detect_distro()
    info = DISTRO_INFO.get(distro_id)
    if not info:
        print_warning(f"Unsupported host distro ('{distro_id}'). Please manually install 'qemu' and 'ovmf/edk2' packages.")
        return shutil.which(CONFIG['QEMU_BINARY']) and os.path.exists(CONFIG['UEFI_CODE'])
    
    missing_pkgs = []
    if not shutil.which(CONFIG['QEMU_BINARY']):
        missing_pkgs.append(info['pkgs']['qemu'])
    
    uefi_path = "/usr/share/OVMF/OVMF_CODE.fd" if distro_id in ["debian", "ubuntu"] else CONFIG['UEFI_CODE']
    if not os.path.exists(uefi_path):
        missing_pkgs.append(info['pkgs']['ovmf'])
    
    if not missing_pkgs:
        print_success("All required packages are installed.")
        return True
    
    print_error(f"Missing required software for host distro '{distro_id}'.")
    install_cmd = f"sudo {info['cmd']} {' '.join(sorted(list(set(missing_pkgs))))}"
    print_info(f"To fix this, the recommended command is:\n  {Style.BOLD}{install_cmd}{Style.ENDC}")
    
    if input("Run this command now? (y/N): ").strip().lower() == 'y':
        if os.system(install_cmd) == 0:
            print_success("\nInstallation successful. Please re-run the script.")
        else:
            print_error("\nInstallation failed.")
        sys.exit()
    return False


def get_running_vm_info(vm_name):
    paths = get_vm_paths(vm_name)
    pid_file, session_info_file = paths['pid_file'], paths['session_info']
    if not os.path.exists(pid_file):
        return None
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # Check if the process exists
        with open(session_info_file, 'r') as f:
            ssh_port = int(f.read().strip())
        return {'pid': pid, 'port': ssh_port}
    except (IOError, ValueError, ProcessLookupError, OSError):
        for f in [pid_file, session_info_file]:
            if os.path.exists(f):
                remove_file(f)
        return None


def is_vm_running(vm_name):
    return get_running_vm_info(vm_name) is not None


def cleanup_stale_sessions():
    """Iterate through all VMs and clean up stale PID files."""
    vms_dir = CONFIG['VMS_DIR_LINUX']
    if not os.path.isdir(vms_dir):
        return
    vm_list = [d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))]
    for vm in vm_list:
        is_vm_running(vm)


def create_new_vm():
    clear_screen()
    print_header("Create New Linux VM")
    if not check_dependencies():
        return
    
    while True:
        vm_name = input(f"{Style.BOLD}Enter a short name for new VM (e.g., arch-kde): {Style.ENDC}").strip()
        if not re.match(r"^[a-zA-Z0-9_-]+$", vm_name):
            print_warning("Invalid name.")
        elif os.path.exists(os.path.join(CONFIG['VMS_DIR_LINUX'], vm_name)):
            print_warning("A VM with this name already exists.")
        else:
            break
            
    paths = get_vm_paths(vm_name)
    iso_path = find_iso_path()
    if not iso_path:
        return
        
    while True:
        disk = input(f"{Style.BOLD}Enter base disk size (GB) [default: {CONFIG['BASE_DISK_SIZE']}]: {Style.ENDC}").strip() or CONFIG['BASE_DISK_SIZE']
        if disk.isdigit() and int(disk) > 0:
            break
        else:
            print_warning("Invalid input.")
            
    vm_settings = get_vm_config({"VM_MEM": CONFIG['VM_MEM'], "VM_CPU": CONFIG['VM_CPU']})
    qemu_cmd = _get_qemu_command(vm_name, vm_settings, {}, {'uuid': str(uuid.uuid4()), 'mac': ''}, "", 0, iso_path=iso_path)
    
    commands_to_run = [
        ("Creating directory structure", ["mkdir", "-p", paths['dir'], paths['shared_dir']]),
        ("Preparing UEFI seed", ["cp", CONFIG['UEFI_VARS_TEMPLATE'], paths['seed']]),
        (f"Creating {disk}G base image", ["qemu-img", "create", "-f", "qcow2", paths['base'], f"{disk}G"]),
        ("Booting from ISO (Install your OS, then simply close this terminal window)", qemu_cmd)
    ]
    launch_in_new_terminal_and_wait(commands_to_run)


def _get_qemu_command(vm_name, vm_settings, input_devices, ids, host_dns, ssh_port, passthrough_info=None, iso_path=None):
    paths = get_vm_paths(vm_name)
    qemu_cmd = [
        CONFIG["QEMU_BINARY"],
        "-enable-kvm",
        "-m", vm_settings["VM_MEM"],
        "-smp", vm_settings["VM_CPU"],
        "-uuid", ids['uuid'],
        "-drive", f"if=pflash,format=raw,readonly=on,file={CONFIG['UEFI_CODE']}",
        "-drive", f"if=pflash,format=raw,file={paths['seed'] if iso_path else paths['instance']}",
        "-fsdev", f"local,security_model=mapped-xattr,id=fsdev0,path={paths['shared_dir']}",
        "-device", f"virtio-9p-pci,fsdev=fsdev0,mount_tag={CONFIG['SHARED_DIR_MOUNT_TAG']}",
        "-pidfile", paths['pid_file']
    ]

    if ssh_port > 0:
        qemu_cmd.extend(["-netdev", f"user,id=n1,dns={host_dns},hostfwd=tcp::{ssh_port}-:22", "-device", f"virtio-net-pci,netdev=n1,mac={ids['mac']}"])
    else:
        qemu_cmd.extend(["-netdev", "user,id=n1", "-device", "virtio-net-pci,netdev=n1"])

    if passthrough_info:
        is_gpu_passthrough = any(d.get('class_code') == '0300' for d in passthrough_info['devices'].values())
        if is_gpu_passthrough:
            qemu_cmd.extend(["-cpu", "host,kvm=off,hv_vendor_id=null" if passthrough_info['vendor'] == "NVIDIA" else "host"])
            qemu_cmd.append("-nographic")
            if input_devices:
                qemu_cmd.extend([
                    "-object", f"input-linux,id=mouse,evdev={input_devices['mouse']}",
                    "-object", f"input-linux,id=kbd,evdev={input_devices['keyboard']},grab_all=on,repeat=on"
                ])

            is_vga_set = False
            primary_gpu_pci = passthrough_info.get('vga_pci')
            for pci_id in passthrough_info['pci_ids']:
                if primary_gpu_pci == pci_id and not is_vga_set:
                    qemu_cmd.extend(["-device", f"vfio-pci,host={pci_id},x-vga=on,rombar=0"])
                    is_vga_set = True
                else:
                    qemu_cmd.extend(["-device", f"vfio-pci,host={pci_id}"])
        else:  # Passthrough for non-GPU devices
            qemu_cmd.extend(["-cpu", "host", "-vga", "virtio", *CONFIG["QEMU_DISPLAY"]])
            for pci_id in passthrough_info['pci_ids']:
                qemu_cmd.extend(["-device", f"vfio-pci,host={pci_id}"])
        qemu_cmd.extend(["-drive", f"file={paths['base']},if=virtio"])
    elif iso_path:  # Standard Install
        qemu_cmd.extend(["-cpu", "host", "-vga", "virtio", *CONFIG["QEMU_DISPLAY"]])
        qemu_cmd.extend(["-drive", f"file={paths['base']},if=virtio", "-cdrom", iso_path])
    else:  # Standard Run
        qemu_cmd.extend(["-cpu", "host", "-vga", "virtio", *CONFIG["QEMU_DISPLAY"]])
        qemu_cmd.extend(["-drive", f"file={paths['overlay']},if=virtio,cache=writeback"])

    return qemu_cmd


def run_or_nuke_vm(vm_name, is_fresh):
    session_type = "Nuke & Boot" if is_fresh else "Run / Resume"
    print_header(f"{session_type}: '{vm_name}'")
    if is_vm_running(vm_name):
        print_error(f"VM '{vm_name}' is already running.")
        return
        
    paths = get_vm_paths(vm_name)
    if is_fresh:
        if not _nuke_session_files(paths):
            return
    elif not os.path.exists(paths['overlay']):
        print_info("No existing session found. Starting a fresh one instead.")
        is_fresh = True

    vm_settings = get_vm_config({"VM_MEM": CONFIG['VM_MEM'], "VM_CPU": CONFIG['VM_CPU']})
    host_dns = find_host_dns()
    ssh_port = find_unused_port()

    if is_fresh or not os.path.exists(paths['session_id']):
        new_uuid = str(uuid.uuid4())
        new_mac = f"52:54:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"
        print_header("Generating New Session Identifiers")
        print_info(f"System UUID: {Style.BOLD}{new_uuid}{Style.ENDC}\nMAC Address: {Style.BOLD}{new_mac}{Style.ENDC}")
        with open(paths['session_id'], 'w') as f:
            f.write(f"{new_uuid}\n{new_mac}\n")
        ids = {'uuid': new_uuid, 'mac': new_mac}
    else:
        ids = {'uuid': str(uuid.uuid4()), 'mac': f"52:54:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"}
        if os.path.exists(paths['session_id']):
            with open(paths['session_id'], 'r') as f:
                lines = f.readlines()
            if len(lines) >= 2:
                ids['uuid'], ids['mac'] = lines[0].strip(), lines[1].strip()
        print_info(f"Resuming with System UUID: {Style.BOLD}{ids['uuid']}{Style.ENDC}")

    if not os.path.exists(paths['instance']):
        run_command_live(["cp", paths['seed'], paths['instance']], as_root=False, check=True)
    if not os.path.exists(paths['overlay']):
        run_command_live(["qemu-img", "create", "-f", "qcow2", "-b", paths['base'], "-F", "qcow2", paths['overlay']], as_root=False, check=True)

    qemu_cmd = _get_qemu_command(vm_name, vm_settings, {}, ids, host_dns, ssh_port)
    launch_in_new_terminal_and_wait([("Booting VM", qemu_cmd)])


def _nuke_session_files(paths):
    files_to_nuke = [paths['overlay'], paths['instance'], paths['session_id'], paths['pid_file'], paths['session_info']]
    if not any(os.path.exists(f) for f in files_to_nuke):
        print_info("No session files found to nuke for this VM.")
        return True
        
    print_warning(f"You are about to permanently delete the current session for '{os.path.basename(paths['dir'])}'.")
    if input("Are you sure? (y/N): ").strip().lower() != 'y':
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
    clear_screen()
    vm_name = select_vm("Nuke Completely")
    if not vm_name:
        return
    if is_vm_running(vm_name):
        print_error(f"Cannot nuke '{vm_name}' while it is running. Please stop it first.")
        return
        
    print_warning(f"This will permanently delete the entire VM '{vm_name}', including its base image.\nThis action CANNOT be undone.")
    confirm = input(f"To confirm, please type the name of the VM ({vm_name}): ").strip()
    if confirm == vm_name:
        remove_dir(get_vm_paths(vm_name)['dir'])
    else:
        print_error("Confirmation failed. Aborting.")


def stop_vm(vm_name=None, force=False):
    if not vm_name:
        clear_screen()
        vm_name = select_vm("Stop", running_only=True)
    if not vm_name:
        return
        
    vm_info = get_running_vm_info(vm_name)
    if vm_info:
        print_info(f"Stopping VM '{vm_name}' (PID: {vm_info['pid']})...")
        try:
            os.kill(vm_info['pid'], 15)
            print_success(f"Stop signal sent to VM '{vm_name}'.")
        except ProcessLookupError:
            print_warning("Process already stopped.")
        except Exception as e:
            print_error(f"Failed to send stop signal to VM: {e}")
            
        time.sleep(1)
        paths = get_vm_paths(vm_name)
        for f in [paths['pid_file'], paths['session_info']]:
            if os.path.exists(f):
                remove_file(f)
    elif not force:
        print_error(f"Could not get running info for '{vm_name}'.")


def transfer_files():
    clear_screen()
    vm_name = select_vm("Transfer Files with", running_only=True)
    if not vm_name:
        return
        
    vm_info = get_running_vm_info(vm_name)
    if not vm_info:
        print_error(f"VM '{vm_name}' is not running or its PID file is invalid.")
        return
        
    print_header(f"File Transfer for '{vm_name}'")
    while True:
        direction = input(f"{Style.BOLD}Direction? [1] Host to VM, [2] VM to Host: {Style.ENDC}").strip()
        if direction in ["1", "2"]:
            break
        else:
            print_warning("Invalid choice.")
            
    while True:
        local_path = os.path.expanduser(input(f"{Style.BOLD}Enter path on LOCAL host: {Style.ENDC}").strip())
        if os.path.exists(local_path):
            break
        else:
            print_warning(f"Local path not found: '{local_path}'. Please check typos.")
            
    remote_path = input(f"{Style.BOLD}Enter full path on REMOTE vm (use quotes if needed): {Style.ENDC}").strip()
    vm_user = input(f"{Style.BOLD}Enter username inside the VM: {Style.ENDC}").strip()
    
    port = vm_info['port']
    src, dest = (local_path, f"{vm_user}@localhost:{remote_path}") if direction == "1" else (f"{vm_user}@localhost:{remote_path}", local_path)
    
    scp_cmd = ["scp", "-r", "-P", str(port), src, dest]
    run_command_live(scp_cmd)


def _check_system_type():
    chassis_type = _run_command(["cat", "/sys/class/dmi/id/chassis_type"], as_root=True)
    return chassis_type in ['8', '9', '10', '11', '12', '14', '30', '31', '32']


def _fix_grub_cmdline(param_to_add):
    grub_file = "/etc/default/grub"
    if not os.path.exists(grub_file):
        print_error(f"{grub_file} not found. Cannot apply GRUB fix automatically.")
        return

    backup_file = f"{grub_file}.vm_manager.bak"
    if not os.path.exists(backup_file):
        print_info(f"Modifying '{grub_file}'. A backup will be saved to '{backup_file}'.")
        if run_command_live(['cp', grub_file, backup_file], as_root=True) is None:
            print_error("Failed to create backup. Aborting modification.")
            return
        print_success(f"Original file backed up to: {backup_file}")

    with open(grub_file, 'r') as f:
        original_content = f.read()
    if param_to_add in original_content:
        print_info(f"Parameter '{param_to_add}' already exists in GRUB config. No changes needed.")
        return

    new_content = re.sub(r'^(GRUB_CMDLINE_LINUX_DEFAULT=")(.*)(")', rf'\1\2 {param_to_add}\3', original_content, 1, re.M)
    if new_content == original_content:
        print_error("Could not automatically modify GRUB_CMDLINE_LINUX_DEFAULT. Please add it manually.")
        return

    print_info(f"Writing new configuration to {grub_file}...")
    tmp_path = f"/tmp/vm_manager_grub_{os.getpid()}.tmp"
    with open(tmp_path, 'w') as f:
        f.write(new_content)
        
    if run_command_live(['cp', tmp_path, grub_file], as_root=True) is not None:
        os.remove(tmp_path)
        print_success("GRUB configuration updated.")
        distro = detect_distro()
        update_cmd = DISTRO_INFO.get(distro, {}).get("grub_update", "sudo update-grub (or equivalent for your OS)")
        print_warning("ACTION REQUIRED: You must now apply this change and reboot.")
        print_info(f"Run the command: {Style.BOLD}{update_cmd}{Style.ENDC} and then {Style.BOLD}sudo reboot{Style.ENDC}")
    else:
        os.remove(tmp_path)
        print_error(f"Failed to write to {grub_file}. Restoring from backup.")
        run_command_live(['cp', backup_file, grub_file], as_root=True)


def _check_iommu_support():
    print_header("2. CPU & BIOS IOMMU Check")
    cpu_info = _run_command(["lscpu"])
    vendor = "Intel" if "GenuineIntel" in cpu_info else "AMD"
    virt_feature = "VT-x" if vendor == "Intel" else "svm"
    iommu_feature = "VT-d" if vendor == "Intel" else "AMD-Vi"

    if virt_feature not in cpu_info:
        print_error(f"FATAL: CPU does not support virtualization ({virt_feature}).")
        return False
    print_success(f"CPU supports virtualization ({virt_feature}).")

    iommu_groups_path = "/sys/kernel/iommu_groups/"
    if os.path.exists(iommu_groups_path) and len(os.listdir(iommu_groups_path)) > 0:
        print_success(f"IOMMU ({iommu_feature}) is active in the kernel.")
        return True

    print_error(f"FAIL: IOMMU ({iommu_feature}) does not appear to be active in the kernel.")
    print_info("This is usually because it's disabled in the BIOS/UEFI or the required kernel parameter is missing.")

    param = "intel_iommu=on" if vendor == "Intel" else "amd_iommu=on"
    if input(f"Would you like this tool to attempt to add the '{param}' kernel parameter to GRUB? (y/N): ").lower() == 'y':
        _fix_grub_cmdline(param)
        return False

    if input("Skip this check and proceed anyway? (Not Recommended) (y/N): ").lower() == 'y':
        return 'skipped'

    return False


def _find_pci_devices_by_class(class_code):
    lspci_out = _run_command(["lspci", "-nnk"])
    if not lspci_out:
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
            "pci": pci.strip(),
            "name": name.strip(),
            "ids": vdid.strip(),
            "driver": drv.strip(),
            "class_code": class_code,
            "display": f"[{pci.strip()}] {name.strip()} (driver: {drv.strip()})"
        })

    return devices


def _get_gpus():
    return _find_pci_devices_by_class("0300")


def _get_usb_controllers():
    return _find_pci_devices_by_class("0c03")


def _get_nvme_drives():
    return _find_pci_devices_by_class("0108")


def _select_guest_gpu():
    print_header("3. GPU Detection and Strategy")
    gpus = _get_gpus()

    if not gpus:
        print_error("FATAL: No 'VGA compatible controllers' with PCI Class [0300] and an active kernel driver were found.")
        # ... (rest of the error handling)
        return None

    print_info(f"Found {len(gpus)} GPU(s):")
    for gpu in gpus:
        print(f"  - {gpu['display']}")
        
    if len(gpus) == 1:
        gpu = gpus[0]
        is_apu = "APU" in gpu['name'] or ("Vega" in gpu['name'] and "Radeon" in gpu['name'])
        vendor = "NVIDIA" if gpu['ids'].startswith("10de") else "AMD" if gpu['ids'].startswith("1002") else "Intel"
        if vendor in ["NVIDIA", "AMD"] and not is_apu:
            print_error(f"FATAL: Single {vendor} dGPU detected. Passthrough requires a second GPU.")
            return None
        if is_apu:
            print_warning("Single AMD APU detected. This implies a single-GPU passthrough (headless host).")
            if input("Acknowledge and proceed? (y/N): ").strip().lower() != 'y':
                return None
            return gpu
    elif len(gpus) > 1:
        print_info("Multiple GPUs detected. This is a supported 'Two-GPU Passthrough' configuration.")
        return select_from_list(gpus, "Select the GPU to pass through to the GUEST VM", display_key='display')
        
    return gpus[0]


def _get_iommu_groups():
    return _run_command(["bash", "-c", "for d in /sys/kernel/iommu_groups/*/devices/*; do n=${d#*/iommu_groups/*}; n=${n%%/*}; printf 'IOMMU Group %s ' \"$n\"; lspci -nns \"${d##*/}\"; done"])


def _get_full_iommu_group_devices(pci_id, groups_out):
    device_group_num = next((line.split()[2] for line in groups_out.splitlines() if pci_id in line), None)
    if not device_group_num:
        return None, [], []
        
    pci_ids, vendor_ids = [], []
    for line in groups_out.splitlines():
        if f"IOMMU Group {device_group_num}" in line:
            parts = line.split()
            if len(parts) > 3 and re.match(r'^[\da-f:.]+
                pci_ids.append(parts[3])

            vdid_match = re.search(r'\[([\da-f]{4}:[\da-f]{4})\]', line)
            if vdid_match:
                vendor_ids.append(vdid_match.group(1))

    return device_group_num, sorted(list(set(pci_ids))), sorted(list(set(vendor_ids)))


def _check_vfio_binding_status(guest_gpu):
    print_header("4. Driver Binding Check")
    if guest_gpu['driver'] == 'vfio-pci':
        print_success("GPU is currently bound to 'vfio-pci', as expected for a static setup.")
    else:
        print_success(f"GPU is currently bound to its host driver ('{guest_gpu['driver']}'). This is correct for Live Passthrough.")
    return True


def _check_nvidia_quirks(guest_gpu):
    vendor_id = guest_gpu['ids'].split(':')[0]
    if vendor_id != "10de":
        return True, ""
    print_header('5. NVIDIA "Error 43" Bypass Check')
    print_warning("NVIDIA GPU detected. Special configuration is needed to prevent 'Error 43'.")
    print_info(f"This tool will automatically apply {Style.BOLD}-cpu host,kvm=off,hv_vendor_id=null{Style.ENDC} at launch.")
    return True, "NVIDIA"


def _check_and_load_vfio_module():
    print_header("Live Passthrough Prerequisite: VFIO Module")
    lsmod_out = _run_command(["lsmod"])
    if 'vfio_pci' in lsmod_out:
        print_success("`vfio-pci` kernel module is loaded.")
        return True

    print_error("FAIL: The `vfio-pci` kernel module is not loaded.")
    print_info("For 'Live Passthrough' to work, this module must be loaded at boot.")

    conf_file = "/etc/modules-load.d/vfio-pci.conf"
    conf_file_bak = f"{conf_file}.vm_manager.bak"
    if os.path.exists(conf_file) and not os.path.exists(conf_file_bak):
        print_info(f"Backing up existing '{conf_file}' to '{conf_file_bak}'")
        run_command_live(['cp', conf_file, conf_file_bak], as_root=True)

    print_warning(f"This tool can create a configuration file to load it automatically:")
    print(f"  File:    {conf_file}\n  Content: vfio-pci")

    if input("Create this file now? (y/N): ").strip().lower() == 'y':
        tmp_path = f"/tmp/vm_manager_vfio_{os.getpid()}.tmp"
        with open(tmp_path, 'w') as f:
            f.write("vfio-pci\n")
        if run_command_live(['cp', tmp_path, conf_file], as_root=True) is not None:
            print_success(f"File '{conf_file}' created.")
            print_warning("A ONE-TIME REBOOT is required for this change to take effect.")
            print_info(f"Please run '{Style.BOLD}sudo reboot{Style.ENDC}' and then run this script again.")
        else:
            print_error(f"Failed to write file: {conf_file}")
        os.remove(tmp_path)
    else:
        print_info("Configuration skipped. Live passthrough will fail until the module is loaded.")

    return False


def _check_iommu_groups_sanity(guest_gpu):
    print_header("6. IOMMU Group & VFIO Module Sanity Check")
    if not _check_and_load_vfio_module():
        return False

    groups_out = _get_iommu_groups()
    if not groups_out:
        print_error("Could not read IOMMU groups.")
        return False
        
    group_num, _, _ = _get_full_iommu_group_devices(guest_gpu['pci'], groups_out)
    if not group_num:
        print_error("Could not find IOMMU group for GPU.")
        return False
        
    print_info(f"Selected GPU is in IOMMU Group {group_num}. Checking for safety...")
    is_clean = True
    group_members = [line for line in groups_out.splitlines() if f"IOMMU Group {group_num}" in line]
    for member in group_members:
        is_vga = "VGA compatible controller" in member or "[0300]" in member
        if is_vga and guest_gpu['pci'] not in member:
            print_error(f"FATAL: Host GPU in same group: {member}")
            is_clean = False
        if any(c in member for c in ["USB", "SATA", "Ethernet", "Non-Volatile memory"]) and not is_vga:
            print_error(f"FATAL: Critical device in same group: {member}")
            is_clean = False
            
    print("\n--- Group Members ---\n" + "\n".join(group_members) + "\n---------------------")
    if not is_clean:
        print_error("\nIOMMU group is unsafe. Passthrough would crash the host.")
        return False
        
    print_success("IOMMU Group is clean and appears safe for passthrough.")
    return True


def run_gpu_passthrough_check():
    clear_screen()
    print_header("GPU Passthrough System Compatibility Check")
    is_laptop = _check_system_type()
    if is_laptop:
        print_warning("Laptop detected. Passthrough is extremely difficult and success is highly unlikely.")
    else:
        print_success("Desktop system detected. Ideal for passthrough.")

    iommu_status = _check_iommu_support()
    if iommu_status is False:
        return
        
    guest_gpu = _select_guest_gpu()
    if not guest_gpu:
        return
        
    if iommu_status == 'skipped':
        print_warning("IOMMU check was skipped. Group sanity check may be unreliable.")
        
    _check_vfio_binding_status(guest_gpu)
    _check_nvidia_quirks(guest_gpu)
    
    if not _check_iommu_groups_sanity(guest_gpu):
        return
        
    print_header("🎉 Checklist Complete! 🎉")
    print_info("Review output. If any checks failed, they must be resolved before proceeding.")
    print_warning("If you made any changes (like updating GRUB), a reboot is required.")


def _get_pci_device_driver(pci_id):
    try:
        driver_path = f"/sys/bus/pci/devices/{pci_id}/driver"
        if os.path.islink(driver_path):
            return os.path.basename(os.readlink(driver_path))
    except Exception:
        pass
    return None


def _detect_display_manager():
    """Detects the active display manager service."""
    for dm in ["gdm", "lightdm", "sddm", "lxdm", "xdm"]:
        result = subprocess.run(["systemctl", "is-active", f"{dm}.service"], capture_output=True, text=True)
        if result.returncode == 0:
            return f"{dm}.service"
    return None


def find_input_devices():
    """Finds keyboard and mouse event devices for passthrough."""
    print_header("Input Device Selection")
    print_info("Please select the primary keyboard and mouse to pass to the VM.")
    print_warning("The selected devices will become unavailable to the host while the VM is running.")
    
    try:
        with open('/proc/bus/input/devices', 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print_error("Could not read /proc/bus/input/devices. Cannot select input devices.")
        return None

    devices = []
    for block in content.strip().split('\n\n'):
        name_line = re.search(r'N: Name="([^"]+)"', block)
        handlers_line = re.search(r'H: Handlers=([^\n]+)', block)
        if not name_line or not handlers_line:
            continue
        
        name = name_line.group(1)
        handlers = handlers_line.group(1).split()
        event_dev = next((h for h in handlers if h.startswith('event')), None)
        
        if event_dev:
            devices.append({"name": name, "event": event_dev, "path": f"/dev/input/{event_dev}"})

    keyboards = [d for d in devices if "keyboard" in d['name'].lower()]
    mice = [d for d in devices if "mouse" in d['name'].lower()]

    if not keyboards or not mice:
        print_error("Could not automatically identify a keyboard and mouse.")
        print_info("You may need to manually identify the /dev/input/eventX paths for your devices.")
        return None

    print_info("Available Keyboards:")
    selected_keyboard = select_from_list(keyboards, "Select a keyboard", display_key='name')
    
    print_info("\nAvailable Mice:")
    selected_mouse = select_from_list(mice, "Select a mouse", display_key='name')

    if selected_keyboard and selected_mouse:
        print_success(f"Selected Keyboard: {selected_keyboard['path']}")
        print_success(f"Selected Mouse: {selected_mouse['path']}")
        return {"keyboard": selected_keyboard['path'], "mouse": selected_mouse['path']}
    
    return None


def run_vm_with_live_passthrough():
    clear_screen()
    print_header("Run VM with Live Passthrough")

    if not _check_and_load_vfio_module():
        print_error("Launch aborted. Please reboot and try again after `vfio-pci` module is loaded.")
        return

    dm_service = _detect_display_manager()
    if dm_service is None and os.environ.get("DISPLAY"):
        print_error("Unsupported Host Configuration for Live Passthrough")
        print_warning("A graphical session (X11/Wayland) is running, but it was not started by a recognized display manager service (gdm, sddm, etc.).")
        print_info("This is common for minimalist window managers started with `startx`.")
        print_warning("\nThis script cannot safely stop your graphical session automatically.")
        print_info(f"To proceed, please do the following:\n  1. Log out of your graphical session.\n  2. Switch to a TTY (text console) using {Style.BOLD}Ctrl+Alt+F3{Style.ENDC}.\n  3. Log in there and run this script again.")
        return

    vm_name = select_vm("run with Live Passthrough")
    if not vm_name:
        return

    passthrough_devices = {}
    while True:
        print_header("Select Devices for Passthrough")
        print(f"Current devices: {list(d['display'] for d in passthrough_devices.values()) or 'None'}")
        choice = input(f"{Style.BOLD}Add device: [1] GPU, [2] USB Controller, [3] NVMe Drive, [4] Done: {Style.ENDC}").strip()
        if choice == '1':
            devices = _get_gpus()
            name = "GPU"
        elif choice == '2':
            devices = _get_usb_controllers()
            name = "USB Controller"
        elif choice == '3':
            devices = _get_nvme_drives()
            name = "NVMe Drive"
        elif choice == '4':
            break
        else:
            print_warning("Invalid choice.")
            continue

        if not devices:
            print_error(f"No {name} devices found.")
            continue
        devices = [d for d in devices if d['pci'] not in passthrough_devices]
        if not devices:
            print_error(f"All available {name}s already selected.")
            continue

        selected_dev = select_from_list(devices, f"Choose a {name} to pass through", 'display')
        passthrough_devices[selected_dev['pci']] = selected_dev

    if not passthrough_devices:
        print_info("No devices selected. Aborting.")
        return

    print_header("Gathering All VM Information")
    final_pci_ids_to_bind = set()
    final_vendor_ids_to_register = set()
    original_drivers = {}
    iommu_groups_out = _get_iommu_groups()

    for pci_id in passthrough_devices:
        _, group_pci_ids, group_vendor_ids = _get_full_iommu_group_devices(pci_id, iommu_groups_out)
        if not group_pci_ids:
            print_error(f"Could not find IOMMU group for {pci_id}. Aborting.")
            return

        for dev_id in group_pci_ids:
            if not re.match(r'^[\da-f:.]+
, dev_id):
                print_error(f"FATAL: Collected an invalid device ID '{dev_id}' for IOMMU group of {pci_id}. Aborting.")
                return
            original_drivers[dev_id] = _get_pci_device_driver(dev_id)

        print_info(f"Adding IOMMU group for {pci_id}: {', '.join(group_pci_ids)}")
        final_pci_ids_to_bind.update(group_pci_ids)
        final_vendor_ids_to_register.update(group_vendor_ids)

    input_devices = find_input_devices()
    if not input_devices:
        return
    vm_settings = get_vm_config({"VM_MEM": CONFIG['VM_MEM'], "VM_CPU": CONFIG['VM_CPU']})

    is_laptop = _check_system_type()

    print_header("Pre-Flight Checklist")
    print_info(f"VM Name: {vm_name}")
    print_info(f"Memory: {vm_settings['VM_MEM']}, CPU Cores: {vm_settings['VM_CPU']}")
    print_info(f"Passthrough Devices: {', '.join(sorted(list(final_pci_ids_to_bind)))}")

    if dm_service:
        print_warning("\nCRITICAL WARNING: This process will stop your graphical desktop session.")
        if is_laptop:
            print(f"{Style.FAIL}{Style.BOLD}Your built-in screen WILL go black. This is NORMAL.{Style.ENDC}")
            print(f"{Style.OKGREEN}To see the VM, you MUST connect an external monitor to your laptop's HDMI/DisplayPort.{Style.ENDC}")
        else:
            print(f"{Style.FAIL}{Style.BOLD}Your primary monitor WILL go black. This is NORMAL.{Style.ENDC}")
            print(f"{Style.OKGREEN}You must connect a second monitor to the passed-through GPU to see the VM.{Style.ENDC}")
        print(f"{Style.OKGREEN}Your desktop will automatically return when the VM shuts down.{Style.ENDC}")

    if input("\nProceed with launch? (y/N): ").strip().lower() != 'y':
        return

    script_path = f"/tmp/vm_passthrough_launcher_{os.getpid()}.sh"
    log_path = f"/tmp/vm_passthrough_launcher_{os.getpid()}.log"

    host_dns, ssh_port = find_host_dns(), find_unused_port()
    ids = {'uuid': str(uuid.uuid4()), 'mac': f"52:54:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"}
    vendor = "NVIDIA" if any(dev['ids'].startswith('10de') for dev in passthrough_devices.values()) else ""
    primary_gpu = next((d for d in passthrough_devices.values() if d['class_code'] == '0300'), None)
    passthrough_info = {
        "vga_pci": primary_gpu['pci'] if primary_gpu else list(final_pci_ids_to_bind)[0],
        "pci_ids": list(final_pci_ids_to_bind),
        "vendor": vendor,
        "devices": passthrough_devices
    }

    qemu_cmd_list = _get_qemu_command(vm_name, vm_settings, input_devices, ids, host_dns, ssh_port, passthrough_info)

    with open(script_path, 'w') as f:
        f.write("#!/bin/bash\n")
        f.write(f"# This script requires root. It will be executed with sudo.\n")
        f.write(f"exec &> {log_path}\n")
        f.write("set -x\n")

        post_cmds = []
        if dm_service:
            post_cmds.append(f"echo 'Restarting graphical session...' && systemctl start {dm_service}")
        for pci_id in reversed(sorted(list(final_pci_ids_to_bind))):
            original_driver = original_drivers.get(pci_id)
            if original_driver:
                post_cmds.insert(0, f"echo 'Rebinding {pci_id} to {original_driver}' && echo {pci_id} > /sys/bus/pci/drivers/{original_driver}/bind || true")
                post_cmds.insert(0, f"echo {pci_id} > /sys/bus/pci/drivers/vfio-pci/unbind || true")
        for vdid in final_vendor_ids_to_register:
            post_cmds.insert(0, f"echo {vdid.replace(':', ' ')} > /sys/bus/pci/drivers/vfio-pci/remove_id || true")

        f.write("function cleanup {\n")
        f.write("    echo '--- Running cleanup ---\n")
        for cmd in post_cmds:
            f.write(f"    {cmd}\n")
        f.write("    echo '--- Cleanup complete ---\n")
        f.write("}\n")
        f.write("trap cleanup EXIT\n\n")

        if dm_service:
            f.write(f"echo 'Stopping graphical session...' && systemctl stop {dm_service}\n")
            f.write("sleep 3\n")

        for vdid in final_vendor_ids_to_register:
            f.write(f"echo {vdid.replace(':', ' ')} > /sys/bus/pci/drivers/vfio-pci/new_id || true\n")
        for pci_id in final_pci_ids_to_bind:
            f.write(f"echo 'Unbinding {pci_id}' && echo {pci_id} > /sys/bus/pci/devices/{pci_id}/driver/unbind || true\n")
            f.write(f"echo 'Binding {pci_id} to vfio-pci' && echo {pci_id} > /sys/bus/pci/drivers/vfio-pci/bind\n")

        f.write("\n\necho '--- Launching QEMU ---\n")
        f.write(' '.join(shlex.quote(s) for s in qemu_cmd_list))
        f.write("\n\necho '--- QEMU process finished, exiting script. Cleanup trap will run. ---\n")

    os.chmod(script_path, 0o755)

    print_info(f"Handing off to independent launcher script: {script_path}")
    print_warning("This script will now exit. The background process is in control.")
    print_warning(f"Your screen should go black shortly. To debug, check the log file at: {log_path}")

    launch_cmd = ['nohup', 'sudo', 'bash', script_path]
    subprocess.Popen(launch_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
    sys.exit(0)


def revert_system_changes():
    clear_screen()
    print_header("Revert System to Pre-Passthrough State")
    files_to_revert = {
        "/etc/default/grub": "GRUB configuration",
        "/etc/modprobe.d/vfio.conf": "VFIO static binding",
        "/etc/modules-load.d/vfio-pci.conf": "VFIO module auto-load config"
    }
    backups_found = {}
    files_to_delete = []

    for f_path, desc in files_to_revert.items():
        backup_path = f"{f_path}.vm_manager.bak"
        if os.path.exists(backup_path):
            backups_found[backup_path] = f_path
        elif os.path.exists(f_path):
            files_to_delete.append((f_path, desc))

    if not backups_found and not files_to_delete:
        print_info("No backup or generated files found. System appears to be in a clean state.")
        return

    print_warning("The following changes can be reverted:")
    for backup, original in backups_found.items():
        print(f"  - Restore '{original}' from backup '{backup}'")
    for f_path, desc in files_to_delete:
        print(f"  - Delete generated file for '{desc}': {f_path}")

    if input("Are you sure you want to proceed? (y/N): ").strip().lower() != 'y':
        print_info("Operation cancelled.")
        return

    for backup, original in backups_found.items():
        if run_command_live(['mv', backup, original], as_root=True) is not None:
            print_success(f"Restored {original}")
        else:
            print_error(f"Failed to restore {original}")

    for f_path, _ in files_to_delete:
        remove_file(f_path, as_root=True)

    print_header("Revert Complete")
    distro = detect_distro()
    update_grub_cmd = DISTRO_INFO.get(distro, {}).get("grub_update", "sudo update-grub")
    update_initramfs_cmd = DISTRO_INFO.get(distro, {}).get("initramfs_update", "sudo update-initramfs -u")
    print_warning("ACTION REQUIRED: To finalize the revert, you may need to update system configs and reboot.")
    print_info(f"If GRUB or initramfs were affected, run these commands:\n  {Style.BOLD}{update_grub_cmd}\n  {update_initramfs_cmd}{Style.ENDC}")
    print_info(f"Then reboot with: {Style.BOLD}sudo reboot{Style.ENDC}")


def display_passthrough_guide():
    clear_screen()
    print_header("What to Expect & How to Use Passthrough")
    print(f"""
{Style.BOLD}Understanding the "Headless Host" Concept{Style.ENDC}
When you pass a GPU to a VM, your main operating system (the "host") can no longer use it. For this to work without crashing, we must completely stop the host's graphical desktop environment before the VM starts.

{Style.WARNING}This means your screen WILL go black and show a text cursor. This is normal!{Style.ENDC}

The host is now "headless" (it has no display). The VM, however, now has full control of the GPU.

{Style.BOLD}How Do I See the VM's Display?{Style.ENDC}
You need to connect a monitor to a port that is physically wired to the passed-through GPU.

  - {Style.OKCYAN}For Laptops:{Style.ENDC}
    This almost always means you {Style.BOLD}MUST connect an external monitor or TV{Style.ENDC} to your laptop's {Style.OKGREEN}HDMI or DisplayPort{Style.ENDC}.
    The VM will appear on the external monitor. Your built-in laptop screen will remain black.

  - {Style.OKCYAN}For Desktops:{Style.ENDC}
    You need two monitors. One connected to your host GPU, and a second one connected to the GPU you are passing to the VM.
    Your host monitor will go black, and the VM will appear on the second monitor.

{Style.BOLD}What Happens When I Shut Down the VM?{Style.ENDC}
The script will automatically perform a cleanup sequence:
1. It gives the GPU back to the host system.
2. It restarts your graphical desktop environment.
3. You will be returned to your normal login screen.

{Style.BOLD}Alternative: Remote Desktop{Style.ENDC}
If you do not have an external monitor, you can install remote desktop software (like VNC, XRDP, or NoMachine) inside your VM's operating system. You can then connect to the VM's desktop from another computer on your network.
    """)


def gpu_passthrough_menu():
    if not shutil.which("lspci"):
        print_error("`lspci` command not found. Please install `pciutils` for your distribution.")
        return
    while True:
        clear_screen()
        print(f"\n{Style.HEADER}{Style.BOLD}Passthrough & Performance (Advanced){Style.ENDC}\n───────────────────────────────────────────────")
        print(f"{Style.OKBLUE}1.{Style.ENDC} {Style.BOLD}Run VM with 'Live' Passthrough (GPU, USB, NVMe){Style.ENDC}")
        print(f"{Style.OKCYAN}2.{Style.ENDC} {Style.BOLD}Run System Compatibility Checklist{Style.ENDC}")
        print(f"{Style.OKGREEN}3.{Style.ENDC} {Style.BOLD}What to Expect & How to Use Passthrough{Style.ENDC}")
        print(f"{Style.FAIL}4.{Style.ENDC} {Style.BOLD}Revert ALL Passthrough-Related System Changes{Style.ENDC}")
        print(f"{Style.WARNING}5.{Style.ENDC} {Style.BOLD}Return to Linux VM Menu{Style.ENDC}")
        print("───────────────────────────────────────────────")
        choice = input(f"{Style.BOLD}Select an option [1-5]: {Style.ENDC}").strip()
        action_taken = True
        if choice == "1":
            run_vm_with_live_passthrough()
        elif choice == "2":
            run_gpu_passthrough_check()
        elif choice == "3":
            display_passthrough_guide()
        elif choice == "4":
            revert_system_changes()
        elif choice == "5":
            break
        else:
            print_warning("Invalid option.")
            action_taken = False
        if action_taken:
            input("\nPress Enter to return to the menu...")


def linux_vm_menu():
    os.makedirs(CONFIG['VMS_DIR_LINUX'], exist_ok=True)
    while True:
        cleanup_stale_sessions()
        clear_screen()
        print(f"\n{Style.HEADER}{Style.BOLD}Linux VM Management{Style.ENDC}\n───────────────────────────────────────────────")
        print(f"{Style.OKBLUE}1.{Style.ENDC} {Style.BOLD}Create New Linux VM{Style.ENDC}")
        print(f"{Style.OKCYAN}2.{Style.ENDC} {Style.BOLD}Run / Resume VM Session (Standard Graphics){Style.ENDC}")
        print(f"{Style.OKBLUE}3.{Style.ENDC} {Style.BOLD}Nuke & Boot a Fresh Session{Style.ENDC}")
        print(f"{Style.OKGREEN}4.{Style.ENDC} {Style.BOLD}Transfer Files to/from a Running VM{Style.ENDC}")
        print(f"{Style.OKCYAN}5.{Style.ENDC} {Style.BOLD}Passthrough & Performance (Advanced){Style.ENDC}")
        print(f"{Style.WARNING}6.{Style.ENDC} {Style.BOLD}Stop a Running VM{Style.ENDC}")
        print(f"{Style.FAIL}7.{Style.ENDC} {Style.BOLD}Nuke VM Completely{Style.ENDC}")
        print(f"{Style.OKBLUE}8.{Style.ENDC} {Style.BOLD}Return to Main Menu{Style.ENDC}")
        print("───────────────────────────────────────────────")
        try:
            choice = input(f"{Style.BOLD}Select an option [1-8]: {Style.ENDC}").strip()
            action_taken, vm_name = True, None
            if choice == "1":
                create_new_vm()
            elif choice == "2":
                vm_name = select_vm("Run / Resume")
                if vm_name:
                    run_or_nuke_vm(vm_name, is_fresh=False)
            elif choice == "3":
                vm_name = select_vm("Nuke & Boot")
                if vm_name:
                    run_or_nuke_vm(vm_name, is_fresh=True)
            elif choice == "4":
                transfer_files()
            elif choice == "5":
                gpu_passthrough_menu()
                action_taken = False
            elif choice == "6":
                stop_vm()
            elif choice == "7":
                nuke_vm_completely()
            elif choice == "8":
                break
            else:
                print_warning("Invalid option.")
                action_taken = False

            if action_taken:
                input("\nPress Enter to return to the menu...")
        except (KeyboardInterrupt, EOFError):
            break
        except RuntimeError as e:
            if "lost sys.stdin" in str(e):
                print_error("This script is interactive and cannot be run in this environment.")
                break
            else:
                raise e
, parts[3]):
                pci_ids.append(parts[3])

            vdid_match = re.search(r'\[([\da-f]{4}:[\da-f]{4})\]', line)
            if vdid_match:
                vendor_ids.append(vdid_match.group(1))

    return device_group_num, sorted(list(set(pci_ids))), sorted(list(set(vendor_ids)))


def _check_vfio_binding_status(guest_gpu):
    print_header("4. Driver Binding Check")
    if guest_gpu['driver'] == 'vfio-pci':
        print_success("GPU is currently bound to 'vfio-pci', as expected for a static setup.")
    else:
        print_success(f"GPU is currently bound to its host driver ('{guest_gpu['driver']}'). This is correct for Live Passthrough.")
    return True


def _check_nvidia_quirks(guest_gpu):
    vendor_id = guest_gpu['ids'].split(':')[0]
    if vendor_id != "10de":
        return True, ""
    print_header('5. NVIDIA "Error 43" Bypass Check')
    print_warning("NVIDIA GPU detected. Special configuration is needed to prevent 'Error 43'.")
    print_info(f"This tool will automatically apply {Style.BOLD}-cpu host,kvm=off,hv_vendor_id=null{Style.ENDC} at launch.")
    return True, "NVIDIA"


def _check_and_load_vfio_module():
    print_header("Live Passthrough Prerequisite: VFIO Module")
    lsmod_out = _run_command(["lsmod"])
    if 'vfio_pci' in lsmod_out:
        print_success("`vfio-pci` kernel module is loaded.")
        return True

    print_error("FAIL: The `vfio-pci` kernel module is not loaded.")
    print_info("For 'Live Passthrough' to work, this module must be loaded at boot.")

    conf_file = "/etc/modules-load.d/vfio-pci.conf"
    conf_file_bak = f"{conf_file}.vm_manager.bak"
    if os.path.exists(conf_file) and not os.path.exists(conf_file_bak):
        print_info(f"Backing up existing '{conf_file}' to '{conf_file_bak}'")
        run_command_live(['cp', conf_file, conf_file_bak], as_root=True)

    print_warning(f"This tool can create a configuration file to load it automatically:")
    print(f"  File:    {conf_file}\n  Content: vfio-pci")

    if input("Create this file now? (y/N): ").strip().lower() == 'y':
        tmp_path = f"/tmp/vm_manager_vfio_{os.getpid()}.tmp"
        with open(tmp_path, 'w') as f:
            f.write("vfio-pci\n")
        if run_command_live(['cp', tmp_path, conf_file], as_root=True) is not None:
            print_success(f"File '{conf_file}' created.")
            print_warning("A ONE-TIME REBOOT is required for this change to take effect.")
            print_info(f"Please run '{Style.BOLD}sudo reboot{Style.ENDC}' and then run this script again.")
        else:
            print_error(f"Failed to write file: {conf_file}")
        os.remove(tmp_path)
    else:
        print_info("Configuration skipped. Live passthrough will fail until the module is loaded.")

    return False


def _check_iommu_groups_sanity(guest_gpu):
    print_header("6. IOMMU Group & VFIO Module Sanity Check")
    if not _check_and_load_vfio_module():
        return False

    groups_out = _get_iommu_groups()
    if not groups_out:
        print_error("Could not read IOMMU groups.")
        return False
        
    group_num, _, _ = _get_full_iommu_group_devices(guest_gpu['pci'], groups_out)
    if not group_num:
        print_error("Could not find IOMMU group for GPU.")
        return False
        
    print_info(f"Selected GPU is in IOMMU Group {group_num}. Checking for safety...")
    is_clean = True
    group_members = [line for line in groups_out.splitlines() if f"IOMMU Group {group_num}" in line]
    for member in group_members:
        is_vga = "VGA compatible controller" in member or "[0300]" in member
        if is_vga and guest_gpu['pci'] not in member:
            print_error(f"FATAL: Host GPU in same group: {member}")
            is_clean = False
        if any(c in member for c in ["USB", "SATA", "Ethernet", "Non-Volatile memory"]) and not is_vga:
            print_error(f"FATAL: Critical device in same group: {member}")
            is_clean = False
            
    print("\n--- Group Members ---\n" + "\n".join(group_members) + "\n---------------------")
    if not is_clean:
        print_error("\nIOMMU group is unsafe. Passthrough would crash the host.")
        return False
        
    print_success("IOMMU Group is clean and appears safe for passthrough.")
    return True


def run_gpu_passthrough_check():
    clear_screen()
    print_header("GPU Passthrough System Compatibility Check")
    is_laptop = _check_system_type()
    if is_laptop:
        print_warning("Laptop detected. Passthrough is extremely difficult and success is highly unlikely.")
    else:
        print_success("Desktop system detected. Ideal for passthrough.")

    iommu_status = _check_iommu_support()
    if iommu_status is False:
        return
        
    guest_gpu = _select_guest_gpu()
    if not guest_gpu:
        return
        
    if iommu_status == 'skipped':
        print_warning("IOMMU check was skipped. Group sanity check may be unreliable.")
        
    _check_vfio_binding_status(guest_gpu)
    _check_nvidia_quirks(guest_gpu)
    
    if not _check_iommu_groups_sanity(guest_gpu):
        return
        
    print_header("🎉 Checklist Complete! 🎉")
    print_info("Review output. If any checks failed, they must be resolved before proceeding.")
    print_warning("If you made any changes (like updating GRUB), a reboot is required.")


def _get_pci_device_driver(pci_id):
    try:
        driver_path = f"/sys/bus/pci/devices/{pci_id}/driver"
        if os.path.islink(driver_path):
            return os.path.basename(os.readlink(driver_path))
    except Exception:
        pass
    return None


def _detect_display_manager():
    """Detects the active display manager service."""
    for dm in ["gdm", "lightdm", "sddm", "lxdm", "xdm"]:
        result = subprocess.run(["systemctl", "is-active", f"{dm}.service"], capture_output=True, text=True)
        if result.returncode == 0:
            return f"{dm}.service"
    return None


def find_input_devices():
    """Finds keyboard and mouse event devices for passthrough."""
    print_header("Input Device Selection")
    print_info("Please select the primary keyboard and mouse to pass to the VM.")
    print_warning("The selected devices will become unavailable to the host while the VM is running.")
    
    try:
        with open('/proc/bus/input/devices', 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print_error("Could not read /proc/bus/input/devices. Cannot select input devices.")
        return None

    devices = []
    for block in content.strip().split('\n\n'):
        name_line = re.search(r'N: Name="([^"]+)"', block)
        handlers_line = re.search(r'H: Handlers=([^\n]+)', block)
        if not name_line or not handlers_line:
            continue
        
        name = name_line.group(1)
        handlers = handlers_line.group(1).split()
        event_dev = next((h for h in handlers if h.startswith('event')), None)
        
        if event_dev:
            devices.append({"name": name, "event": event_dev, "path": f"/dev/input/{event_dev}"})

    keyboards = [d for d in devices if "keyboard" in d['name'].lower()]
    mice = [d for d in devices if "mouse" in d['name'].lower()]

    if not keyboards or not mice:
        print_error("Could not automatically identify a keyboard and mouse.")
        print_info("You may need to manually identify the /dev/input/eventX paths for your devices.")
        return None

    print_info("Available Keyboards:")
    selected_keyboard = select_from_list(keyboards, "Select a keyboard", display_key='name')
    
    print_info("\nAvailable Mice:")
    selected_mouse = select_from_list(mice, "Select a mouse", display_key='name')

    if selected_keyboard and selected_mouse:
        print_success(f"Selected Keyboard: {selected_keyboard['path']}")
        print_success(f"Selected Mouse: {selected_mouse['path']}")
        return {"keyboard": selected_keyboard['path'], "mouse": selected_mouse['path']}
    
    return None


def run_vm_with_live_passthrough():
    clear_screen()
    print_header("Run VM with Live Passthrough")

    if not _check_and_load_vfio_module():
        print_error("Launch aborted. Please reboot and try again after `vfio-pci` module is loaded.")
        return

    dm_service = _detect_display_manager()
    if dm_service is None and os.environ.get("DISPLAY"):
        print_error("Unsupported Host Configuration for Live Passthrough")
        print_warning("A graphical session (X11/Wayland) is running, but it was not started by a recognized display manager service (gdm, sddm, etc.).")
        print_info("This is common for minimalist window managers started with `startx`.")
        print_warning("\nThis script cannot safely stop your graphical session automatically.")
        print_info(f"To proceed, please do the following:\n  1. Log out of your graphical session.\n  2. Switch to a TTY (text console) using {Style.BOLD}Ctrl+Alt+F3{Style.ENDC}.\n  3. Log in there and run this script again.")
        return

    vm_name = select_vm("run with Live Passthrough")
    if not vm_name:
        return

    passthrough_devices = {}
    while True:
        print_header("Select Devices for Passthrough")
        print(f"Current devices: {list(d['display'] for d in passthrough_devices.values()) or 'None'}")
        choice = input(f"{Style.BOLD}Add device: [1] GPU, [2] USB Controller, [3] NVMe Drive, [4] Done: {Style.ENDC}").strip()
        if choice == '1':
            devices = _get_gpus()
            name = "GPU"
        elif choice == '2':
            devices = _get_usb_controllers()
            name = "USB Controller"
        elif choice == '3':
            devices = _get_nvme_drives()
            name = "NVMe Drive"
        elif choice == '4':
            break
        else:
            print_warning("Invalid choice.")
            continue

        if not devices:
            print_error(f"No {name} devices found.")
            continue
        devices = [d for d in devices if d['pci'] not in passthrough_devices]
        if not devices:
            print_error(f"All available {name}s already selected.")
            continue

        selected_dev = select_from_list(devices, f"Choose a {name} to pass through", 'display')
        passthrough_devices[selected_dev['pci']] = selected_dev

    if not passthrough_devices:
        print_info("No devices selected. Aborting.")
        return

    print_header("Gathering All VM Information")
    final_pci_ids_to_bind = set()
    final_vendor_ids_to_register = set()
    original_drivers = {}
    iommu_groups_out = _get_iommu_groups()

    for pci_id in passthrough_devices:
        _, group_pci_ids, group_vendor_ids = _get_full_iommu_group_devices(pci_id, iommu_groups_out)
        if not group_pci_ids:
            print_error(f"Could not find IOMMU group for {pci_id}. Aborting.")
            return

        for dev_id in group_pci_ids:
            if not re.match(r'^[\da-f:.]+
, dev_id):
                print_error(f"FATAL: Collected an invalid device ID '{dev_id}' for IOMMU group of {pci_id}. Aborting.")
                return
            original_drivers[dev_id] = _get_pci_device_driver(dev_id)

        print_info(f"Adding IOMMU group for {pci_id}: {', '.join(group_pci_ids)}")
        final_pci_ids_to_bind.update(group_pci_ids)
        final_vendor_ids_to_register.update(group_vendor_ids)

    input_devices = find_input_devices()
    if not input_devices:
        return
    vm_settings = get_vm_config({"VM_MEM": CONFIG['VM_MEM'], "VM_CPU": CONFIG['VM_CPU']})

    is_laptop = _check_system_type()

    print_header("Pre-Flight Checklist")
    print_info(f"VM Name: {vm_name}")
    print_info(f"Memory: {vm_settings['VM_MEM']}, CPU Cores: {vm_settings['VM_CPU']}")
    print_info(f"Passthrough Devices: {', '.join(sorted(list(final_pci_ids_to_bind)))}")

    if dm_service:
        print_warning("\nCRITICAL WARNING: This process will stop your graphical desktop session.")
        if is_laptop:
            print(f"{Style.FAIL}{Style.BOLD}Your built-in screen WILL go black. This is NORMAL.{Style.ENDC}")
            print(f"{Style.OKGREEN}To see the VM, you MUST connect an external monitor to your laptop's HDMI/DisplayPort.{Style.ENDC}")
        else:
            print(f"{Style.FAIL}{Style.BOLD}Your primary monitor WILL go black. This is NORMAL.{Style.ENDC}")
            print(f"{Style.OKGREEN}You must connect a second monitor to the passed-through GPU to see the VM.{Style.ENDC}")
        print(f"{Style.OKGREEN}Your desktop will automatically return when the VM shuts down.{Style.ENDC}")

    if input("\nProceed with launch? (y/N): ").strip().lower() != 'y':
        return

    script_path = f"/tmp/vm_passthrough_launcher_{os.getpid()}.sh"
    log_path = f"/tmp/vm_passthrough_launcher_{os.getpid()}.log"

    host_dns, ssh_port = find_host_dns(), find_unused_port()
    ids = {'uuid': str(uuid.uuid4()), 'mac': f"52:54:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"}
    vendor = "NVIDIA" if any(dev['ids'].startswith('10de') for dev in passthrough_devices.values()) else ""
    primary_gpu = next((d for d in passthrough_devices.values() if d['class_code'] == '0300'), None)
    passthrough_info = {
        "vga_pci": primary_gpu['pci'] if primary_gpu else list(final_pci_ids_to_bind)[0],
        "pci_ids": list(final_pci_ids_to_bind),
        "vendor": vendor,
        "devices": passthrough_devices
    }

    qemu_cmd_list = _get_qemu_command(vm_name, vm_settings, input_devices, ids, host_dns, ssh_port, passthrough_info)

    with open(script_path, 'w') as f:
        f.write("#!/bin/bash\n")
        f.write(f"# This script requires root. It will be executed with sudo.\n")
        f.write(f"exec &> {log_path}\n")
        f.write("set -x\n")

        post_cmds = []
        if dm_service:
            post_cmds.append(f"echo 'Restarting graphical session...' && systemctl start {dm_service}")
        for pci_id in reversed(sorted(list(final_pci_ids_to_bind))):
            original_driver = original_drivers.get(pci_id)
            if original_driver:
                post_cmds.insert(0, f"echo 'Rebinding {pci_id} to {original_driver}' && echo {pci_id} > /sys/bus/pci/drivers/{original_driver}/bind || true")
                post_cmds.insert(0, f"echo {pci_id} > /sys/bus/pci/drivers/vfio-pci/unbind || true")
        for vdid in final_vendor_ids_to_register:
            post_cmds.insert(0, f"echo {vdid.replace(':', ' ')} > /sys/bus/pci/drivers/vfio-pci/remove_id || true")

        f.write("function cleanup {\n")
        f.write("    echo '--- Running cleanup ---\n")
        for cmd in post_cmds:
            f.write(f"    {cmd}\n")
        f.write("    echo '--- Cleanup complete ---\n")
        f.write("}\n")
        f.write("trap cleanup EXIT\n\n")

        if dm_service:
            f.write(f"echo 'Stopping graphical session...' && systemctl stop {dm_service}\n")
            f.write("sleep 3\n")

        for vdid in final_vendor_ids_to_register:
            f.write(f"echo {vdid.replace(':', ' ')} > /sys/bus/pci/drivers/vfio-pci/new_id || true\n")
        for pci_id in final_pci_ids_to_bind:
            f.write(f"echo 'Unbinding {pci_id}' && echo {pci_id} > /sys/bus/pci/devices/{pci_id}/driver/unbind || true\n")
            f.write(f"echo 'Binding {pci_id} to vfio-pci' && echo {pci_id} > /sys/bus/pci/drivers/vfio-pci/bind\n")

        f.write("\n\necho '--- Launching QEMU ---\n")
        f.write(' '.join(shlex.quote(s) for s in qemu_cmd_list))
        f.write("\n\necho '--- QEMU process finished, exiting script. Cleanup trap will run. ---\n")

    os.chmod(script_path, 0o755)

    print_info(f"Handing off to independent launcher script: {script_path}")
    print_warning("This script will now exit. The background process is in control.")
    print_warning(f"Your screen should go black shortly. To debug, check the log file at: {log_path}")

    launch_cmd = ['nohup', 'sudo', 'bash', script_path]
    subprocess.Popen(launch_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
    sys.exit(0)


def revert_system_changes():
    clear_screen()
    print_header("Revert System to Pre-Passthrough State")
    files_to_revert = {
        "/etc/default/grub": "GRUB configuration",
        "/etc/modprobe.d/vfio.conf": "VFIO static binding",
        "/etc/modules-load.d/vfio-pci.conf": "VFIO module auto-load config"
    }
    backups_found = {}
    files_to_delete = []

    for f_path, desc in files_to_revert.items():
        backup_path = f"{f_path}.vm_manager.bak"
        if os.path.exists(backup_path):
            backups_found[backup_path] = f_path
        elif os.path.exists(f_path):
            files_to_delete.append((f_path, desc))

    if not backups_found and not files_to_delete:
        print_info("No backup or generated files found. System appears to be in a clean state.")
        return

    print_warning("The following changes can be reverted:")
    for backup, original in backups_found.items():
        print(f"  - Restore '{original}' from backup '{backup}'")
    for f_path, desc in files_to_delete:
        print(f"  - Delete generated file for '{desc}': {f_path}")

    if input("Are you sure you want to proceed? (y/N): ").strip().lower() != 'y':
        print_info("Operation cancelled.")
        return

    for backup, original in backups_found.items():
        if run_command_live(['mv', backup, original], as_root=True) is not None:
            print_success(f"Restored {original}")
        else:
            print_error(f"Failed to restore {original}")

    for f_path, _ in files_to_delete:
        remove_file(f_path, as_root=True)

    print_header("Revert Complete")
    distro = detect_distro()
    update_grub_cmd = DISTRO_INFO.get(distro, {}).get("grub_update", "sudo update-grub")
    update_initramfs_cmd = DISTRO_INFO.get(distro, {}).get("initramfs_update", "sudo update-initramfs -u")
    print_warning("ACTION REQUIRED: To finalize the revert, you may need to update system configs and reboot.")
    print_info(f"If GRUB or initramfs were affected, run these commands:\n  {Style.BOLD}{update_grub_cmd}\n  {update_initramfs_cmd}{Style.ENDC}")
    print_info(f"Then reboot with: {Style.BOLD}sudo reboot{Style.ENDC}")


def display_passthrough_guide():
    clear_screen()
    print_header("What to Expect & How to Use Passthrough")
    print(f"""
{Style.BOLD}Understanding the "Headless Host" Concept{Style.ENDC}
When you pass a GPU to a VM, your main operating system (the "host") can no longer use it. For this to work without crashing, we must completely stop the host's graphical desktop environment before the VM starts.

{Style.WARNING}This means your screen WILL go black and show a text cursor. This is normal!{Style.ENDC}

The host is now "headless" (it has no display). The VM, however, now has full control of the GPU.

{Style.BOLD}How Do I See the VM's Display?{Style.ENDC}
You need to connect a monitor to a port that is physically wired to the passed-through GPU.

  - {Style.OKCYAN}For Laptops:{Style.ENDC}
    This almost always means you {Style.BOLD}MUST connect an external monitor or TV{Style.ENDC} to your laptop's {Style.OKGREEN}HDMI or DisplayPort{Style.ENDC}.
    The VM will appear on the external monitor. Your built-in laptop screen will remain black.

  - {Style.OKCYAN}For Desktops:{Style.ENDC}
    You need two monitors. One connected to your host GPU, and a second one connected to the GPU you are passing to the VM.
    Your host monitor will go black, and the VM will appear on the second monitor.

{Style.BOLD}What Happens When I Shut Down the VM?{Style.ENDC}
The script will automatically perform a cleanup sequence:
1. It gives the GPU back to the host system.
2. It restarts your graphical desktop environment.
3. You will be returned to your normal login screen.

{Style.BOLD}Alternative: Remote Desktop{Style.ENDC}
If you do not have an external monitor, you can install remote desktop software (like VNC, XRDP, or NoMachine) inside your VM's operating system. You can then connect to the VM's desktop from another computer on your network.
    """)


def gpu_passthrough_menu():
    if not shutil.which("lspci"):
        print_error("`lspci` command not found. Please install `pciutils` for your distribution.")
        return
    while True:
        clear_screen()
        print(f"\n{Style.HEADER}{Style.BOLD}Passthrough & Performance (Advanced){Style.ENDC}\n───────────────────────────────────────────────")
        print(f"{Style.OKBLUE}1.{Style.ENDC} {Style.BOLD}Run VM with 'Live' Passthrough (GPU, USB, NVMe){Style.ENDC}")
        print(f"{Style.OKCYAN}2.{Style.ENDC} {Style.BOLD}Run System Compatibility Checklist{Style.ENDC}")
        print(f"{Style.OKGREEN}3.{Style.ENDC} {Style.BOLD}What to Expect & How to Use Passthrough{Style.ENDC}")
        print(f"{Style.FAIL}4.{Style.ENDC} {Style.BOLD}Revert ALL Passthrough-Related System Changes{Style.ENDC}")
        print(f"{Style.WARNING}5.{Style.ENDC} {Style.BOLD}Return to Linux VM Menu{Style.ENDC}")
        print("───────────────────────────────────────────────")
        choice = input(f"{Style.BOLD}Select an option [1-5]: {Style.ENDC}").strip()
        action_taken = True
        if choice == "1":
            run_vm_with_live_passthrough()
        elif choice == "2":
            run_gpu_passthrough_check()
        elif choice == "3":
            display_passthrough_guide()
        elif choice == "4":
            revert_system_changes()
        elif choice == "5":
            break
        else:
            print_warning("Invalid option.")
            action_taken = False
        if action_taken:
            input("\nPress Enter to return to the menu...")


def linux_vm_menu():
    os.makedirs(CONFIG['VMS_DIR_LINUX'], exist_ok=True)
    while True:
        cleanup_stale_sessions()
        clear_screen()
        print(f"\n{Style.HEADER}{Style.BOLD}Linux VM Management{Style.ENDC}\n───────────────────────────────────────────────")
        print(f"{Style.OKBLUE}1.{Style.ENDC} {Style.BOLD}Create New Linux VM{Style.ENDC}")
        print(f"{Style.OKCYAN}2.{Style.ENDC} {Style.BOLD}Run / Resume VM Session (Standard Graphics){Style.ENDC}")
        print(f"{Style.OKBLUE}3.{Style.ENDC} {Style.BOLD}Nuke & Boot a Fresh Session{Style.ENDC}")
        print(f"{Style.OKGREEN}4.{Style.ENDC} {Style.BOLD}Transfer Files to/from a Running VM{Style.ENDC}")
        print(f"{Style.OKCYAN}5.{Style.ENDC} {Style.BOLD}Passthrough & Performance (Advanced){Style.ENDC}")
        print(f"{Style.WARNING}6.{Style.ENDC} {Style.BOLD}Stop a Running VM{Style.ENDC}")
        print(f"{Style.FAIL}7.{Style.ENDC} {Style.BOLD}Nuke VM Completely{Style.ENDC}")
        print(f"{Style.OKBLUE}8.{Style.ENDC} {Style.BOLD}Return to Main Menu{Style.ENDC}")
        print("───────────────────────────────────────────────")
        try:
            choice = input(f"{Style.BOLD}Select an option [1-8]: {Style.ENDC}").strip()
            action_taken, vm_name = True, None
            if choice == "1":
                create_new_vm()
            elif choice == "2":
                vm_name = select_vm("Run / Resume")
                if vm_name:
                    run_or_nuke_vm(vm_name, is_fresh=False)
            elif choice == "3":
                vm_name = select_vm("Nuke & Boot")
                if vm_name:
                    run_or_nuke_vm(vm_name, is_fresh=True)
            elif choice == "4":
                transfer_files()
            elif choice == "5":
                gpu_passthrough_menu()
                action_taken = False
            elif choice == "6":
                stop_vm()
            elif choice == "7":
                nuke_vm_completely()
            elif choice == "8":
                break
            else:
                print_warning("Invalid option.")
                action_taken = False

            if action_taken:
                input("\nPress Enter to return to the menu...")
        except (KeyboardInterrupt, EOFError):
            break
        except RuntimeError as e:
            if "lost sys.stdin" in str(e):
                print_error("This script is interactive and cannot be run in this environment.")
                break
            else:
                raise e
