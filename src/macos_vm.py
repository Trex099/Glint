import os
import sys
import shutil
import subprocess
import re
import uuid
import plistlib
import time
import random
import binascii

from config import CONFIG, DISTRO_INFO
from core_utils import (
    Style, print_header, print_info, print_success, print_warning, print_error, clear_screen,
    run_command_live, select_from_list, launch_in_new_terminal_and_wait, remove_dir, detect_distro,
    find_host_dns, setup_bridge_network, remove_file
)

MACOS_RECOMMENDED_MODELS = {
    "Sonoma (14)": "iMacPro1,1",
    "Ventura (13)": "MacPro7,1",
    "Monterey (12)": "iMac20,1",
    "Big Sur (11)": "iMac20,1",
    "Catalina (10.15)": "iMac19,1",
}


def _get_vm_paths(vm_name):
    vm_dir = os.path.abspath(os.path.join(CONFIG['VMS_DIR_MACOS'], vm_name))
    return {
        "dir": vm_dir,
        "opencore": os.path.join(vm_dir, "OpenCore.qcow2"),
        "uefi_code": os.path.join(vm_dir, "OVMF_CODE.fd"),
        "uefi_vars": os.path.join(vm_dir, "OVMF_VARS.fd"),
        "main_disk": os.path.join(vm_dir, "macOS.qcow2"),
        "smbios_info": os.path.join(vm_dir, "smbios.info"),
        "efi_dir": os.path.join(vm_dir, "EFI"),
        "shared_dir": os.path.join(vm_dir, "Shared"),
    }


def _get_macos_qemu_command(vm_name, vm_settings, mac_addr, passthrough_info=None, installer_path=None):
    """
    Builds the QEMU command for a macOS VM.
    """
    paths = _get_vm_paths(vm_name)
    cores = vm_settings.get('cpu', '8')
    
    qemu_cmd = [
        "qemu-system-x86_64", "-enable-kvm", "-m", vm_settings['mem'],
        "-cpu", "Skylake-Client,-hle,-rtm,kvm=off",
        "-machine", "q35,accel=kvm",
        "-smp", f"{cores},sockets=1,cores={cores},threads=1",
        "-device", f"isa-applesmc,osk={CONFIG['OSK_KEY']}",
        "-smbios", "type=2",
        "-drive", f"if=pflash,format=raw,readonly=on,file={paths['uefi_code']}",
        "-drive", f"if=pflash,format=raw,file={paths['uefi_vars']}",
        "-device", "ich9-ahci,id=sata",
        "-device", "ide-hd,bus=sata.0,drive=opencore_disk",
        "-drive", f"id=opencore_disk,if=none,format=qcow2,file={paths['opencore']}",
        "-drive", f"id=main_disk,if=none,format=qcow2,file={paths['main_disk']}",
        "-device", "virtio-blk-pci,drive=main_disk",
    ]

    if installer_path and os.path.exists(installer_path):
        qemu_cmd.extend([
            "-drive", f"id=install_disk,if=none,format=raw,file={installer_path}",
            "-device", "virtio-blk-pci,drive=install_disk",
        ])
    elif installer_path:
        print_warning(f"Installer path '{installer_path}' not found, installer will not be attached.")

    net_config = setup_bridge_network()
    qemu_cmd.extend(["-netdev", net_config, "-device", f"vmxnet3,netdev=net0,mac={mac_addr}"])

    qemu_cmd.extend([
        "-device", "vmware-svga,vgamem_mb=128",
        "-display", "gtk,gl=on,show-cursor=on",
        "-device", "qemu-xhci,id=xhci",
        "-device", "usb-kbd,bus=xhci.0",
        "-device", "usb-tablet,bus=xhci.0",
        "-fsdev", f"local,security_model=passthrough,id=fsdev0,path={paths['shared_dir']}",
        "-device", "virtio-9p-pci,id=fs0,fsdev=fsdev0,mount_tag=host_share"
    ])
        
    return qemu_cmd


def _generate_smbios(model):
    """Generates a complete SMBIOS data set for a given model."""
    print_header("Generating SMBIOS...")
    cmd = [sys.executable, CONFIG['GENSMBIOS_SCRIPT'], "--model", model, "--count", "1"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        output = result.stdout
        type_match = re.search(r"Type:\s*(\S+)", output)
        serial_match = re.search(r"Serial:\s*(\S+)", output)
        mlb_match = re.search(r"Board Serial:\s*(\S+)", output)
        uuid_match = re.search(r"SmUUID:\s*(\S+)", output)
        
        if not all([type_match, serial_match, mlb_match, uuid_match]):
            print_error(f"Failed to parse SMBIOS from GenSMBIOS output for model '{model}'.")
            return None
            
        smbios_data = {
            'type': type_match.group(1),
            'serial': serial_match.group(1),
            'mlb': mlb_match.group(1),
            'sm_uuid': uuid_match.group(1)
        }
        for key, value in smbios_data.items():
            print_success(f"  {key.replace('_', ' ').capitalize():<13}: {value}")
        return smbios_data
    except Exception as e:
        print_error(f"GenSMBIOS script failed: {e}")
        return None


def _find_available_nbd():
    """Finds the first available /dev/nbd device."""
    for i in range(16):
        device = f"/dev/nbd{i}"
        try:
            size = subprocess.check_output(['sudo', 'blockdev', '--getsize64', device]).strip()
            if size == b'0':
                return device
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


def _surgical_rebuild_config(smbios_data, mac_addr, custom_config_path, output_path):
    """
    Takes a known-good config.plist and injects the generated SMBIOS and MAC address data into it.
    """
    print_info("Injecting SMBIOS and MAC Address ROM into known-good config.plist...")
    try:
        with open(custom_config_path, 'rb') as f:
            config_data = plistlib.load(f)

        generic_section = config_data["PlatformInfo"]["Generic"]
        generic_section["SystemProductName"] = smbios_data['type']
        generic_section["SystemSerialNumber"] = smbios_data['serial']
        generic_section["MLB"] = smbios_data['mlb']
        generic_section["SystemUUID"] = smbios_data['sm_uuid']
        generic_section["ROM"] = binascii.unhexlify(mac_addr.replace(":", ""))
        
        with open(output_path, 'wb') as f:
            plistlib.dump(config_data, f)
            
        print_success("config.plist patched successfully with new SMBIOS and ROM.")
        return True
    except Exception as e:
        print_error(f"Failed during config rebuild: {e}")
        return False


def _build_and_patch_opencore_image(vm_name, smbios_data):
    """
    Builds a new OpenCore image for a specific VM, including verification.
    """
    print_header(f"Building OpenCore Image for '{vm_name}'")
    paths = _get_vm_paths(vm_name)
    
    build_dir = f"/tmp/opencore_build_{os.getpid()}"
    os.makedirs(build_dir, exist_ok=True)
    
    shutil.copytree("assets/EFI", os.path.join(build_dir, "EFI"), dirs_exist_ok=True)
    
    boot_dir = os.path.join(build_dir, "EFI", "BOOT")
    os.makedirs(boot_dir, exist_ok=True)
    shutil.copy(os.path.join("assets", "EFI", "OC", "Tools", "OpenShell.efi"), os.path.join(boot_dir, "BOOTx64.efi"))
    print_success("Set OpenShell.efi as the default bootloader.")

    nsh_content = r"fs0:\EFI\OC\OpenCore.efi"
    nsh_path = os.path.join(build_dir, "startup.nsh")
    with open(nsh_path, 'w') as f:
        f.write(nsh_content)
    print_success("Created automatic startup.nsh script to launch OpenCore.")

    custom_config_path = os.path.join(CONFIG['ASSETS_DIR'], "EFI", "config.plist")
    final_config_path = os.path.join(build_dir, "EFI", "OC", "config.plist")
    mac_addr = f"52:54:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"
    if not _surgical_rebuild_config(smbios_data, mac_addr, custom_config_path, final_config_path):
        return False

    nbd_device = None
    temp_mount_point = f"/tmp/opencore_mount_{os.getpid()}"
    success = False
    try:
        run_command_live(["qemu-img", "create", "-f", "qcow2", paths['opencore'], "512M"], check=True, quiet=True)
        run_command_live(["modprobe", "nbd"], as_root=True, check=True, quiet=True)
        nbd_device = _find_available_nbd()
        if not nbd_device:
            print_error("No available NBD device found.")
            return False
        
        run_command_live(["qemu-nbd", "--connect", nbd_device, paths['opencore']], as_root=True, check=True, quiet=True)
        time.sleep(1)
        run_command_live(["mkfs.vfat", "-F", "32", nbd_device], as_root=True, check=True, quiet=True)
        
        os.makedirs(temp_mount_point, exist_ok=True)
        run_command_live(["mount", nbd_device, temp_mount_point], as_root=True, check=True, quiet=True)
        
        run_command_live(["cp", "-r", os.path.join(build_dir, "EFI"), temp_mount_point], as_root=True, check=True, quiet=True)
        run_command_live(["cp", nsh_path, temp_mount_point], as_root=True, check=True, quiet=True)
        
        run_command_live(["sync"], as_root=True, quiet=True)
        run_command_live(["umount", temp_mount_point], as_root=True, check=True, quiet=True)
        
        print_info("Verifying created OpenCore image...")
        run_command_live(["mount", nbd_device, temp_mount_point], as_root=True, check=True, quiet=True)
        try:
            with open(os.path.join(temp_mount_point, "EFI", "OC", "config.plist"), 'rb') as f:
                plistlib.load(f)
            if not os.path.exists(os.path.join(temp_mount_point, "startup.nsh")):
                raise FileNotFoundError("startup.nsh missing from final image")
            print_success("Verification successful: config.plist and startup.nsh are valid.")
            success = True
        except Exception as e:
            print_error(f"Verification failed: {e}")
            success = False
            
    finally:
        if os.path.ismount(temp_mount_point):
            run_command_live(["umount", "-l", temp_mount_point], as_root=True, check=False, quiet=True)
        if nbd_device:
            run_command_live(["qemu-nbd", "--disconnect", nbd_device], as_root=True, check=False, quiet=True)
        if os.path.exists(temp_mount_point):
            os.rmdir(temp_mount_point)
        if os.path.exists(build_dir):
            shutil.rmtree(build_dir)
        
    return success


def _find_installers():
    """Scans for local .img, .dmg or .iso installers."""
    installers = []
    search_dirs = ['.', CONFIG['ASSETS_DIR']]
    for directory in search_dirs:
        if not os.path.isdir(directory):
            continue
        for f in os.listdir(directory):
            if f.endswith(('.img', '.dmg', '.iso')):
                full_path = os.path.abspath(os.path.join(directory, f))
                if full_path not in installers:
                    installers.append(full_path)
    return installers


def _get_installer_path():
    """Guides the user to select, download, or specify a path for the macOS installer."""
    print_header("Select macOS Installer")
    local_installers = _find_installers()
    options = []
    if local_installers:
        print_info("Found local installers:")
        options.extend(local_installers)
    options.extend(["Download using FetchMacOS.py script", "Enter path to installer manually", "Cancel"])
    
    while True:
        for i, opt in enumerate(options, 1):
            display_text = os.path.basename(opt) if os.path.exists(opt) else opt
            print(f"  {Style.OKBLUE}{i}.{Style.ENDC} {display_text}")
            
        choice_str = input(f"{Style.BOLD}Choose an option: {Style.ENDC}").strip()
        try:
            choice_idx = int(choice_str) - 1
            if not 0 <= choice_idx < len(options):
                raise ValueError
                
            selected_option = options[choice_idx]
            if os.path.exists(selected_option):
                return selected_option
            elif selected_option.startswith("Download"):
                run_command_live([sys.executable, CONFIG['FETCHMACOS_SCRIPT']], check=False)
                basesystem_path = "BaseSystem.dmg"
                if os.path.exists(basesystem_path):
                    print_success(f"Download script finished. Using '{basesystem_path}'.")
                    return basesystem_path
                else:
                    print_error(f"Download script did not produce '{basesystem_path}'. Please choose another option.")
                    local_installers = _find_installers()
                    options = []
                    if local_installers:
                        options.extend(local_installers)
                    options.extend(["Download using FetchMacOS.py script", "Enter path to installer manually", "Cancel"])
                    continue
            elif selected_option.startswith("Enter path"):
                manual_path = input("Enter the absolute path to your .dmg or .iso file: ").strip()
                if os.path.exists(manual_path):
                    return manual_path
                else:
                    print_error(f"Path not found: {manual_path}")
            elif selected_option == "Cancel":
                return None
        except ValueError:
            print_warning("Invalid selection.")


def _get_smbios_model_choice():
    """Presents the user with options for SMBIOS model generation."""
    print_header("SMBIOS Model Selection")
    print_info("Select how to determine the Mac model for SMBIOS generation.")
    menu_items = ["Choose a model based on the macOS version (Recommended)", "Enter a model identifier manually (Advanced)"]
    choice = select_from_list(menu_items, "Select an option")
    
    if "Recommended" in choice:
        print_header("Select macOS Version")
        os_choice = select_from_list(list(MACOS_RECOMMENDED_MODELS.keys()), "Select the macOS version you are installing")
        return MACOS_RECOMMENDED_MODELS[os_choice]
    else:
        while True:
            model = input(f"{Style.BOLD}Enter Mac model (e.g., iMacPro1,1): {Style.ENDC}").strip()
            if model:
                return model
            print_warning("Model cannot be empty.")


def check_macos_assets():
    """Checks for assets and offers to install missing system dependencies."""
    print_header("Checking macOS Assets")
    assets_ok = True
    
    required_assets = {
        "GenSMBIOS Script": CONFIG['GENSMBIOS_SCRIPT'],
        "FetchMacOS Script": CONFIG['FETCHMACOS_SCRIPT'],
        "OpenCore EFI Source": "assets/EFI",
        "Sample.plist Template": os.path.join(CONFIG['ASSETS_DIR'], "EFI", "Sample.plist"),
    }
    for name, path in required_assets.items():
        if not os.path.exists(path):
            print_error(f"Asset '{name}' not found at: {path}")
            assets_ok = False

    ovmf_code_paths = ["/usr/share/edk2/x64/OVMF_CODE.4m.fd", "/usr/share/OVMF/OVMF_CODE.fd"]
    ovmf_vars_paths = ["/usr/share/edk2/x64/OVMF_VARS.4m.fd", "/usr/share/OVMF/OVMF_VARS.fd"]
    found_code_path = next((path for path in ovmf_code_paths if os.path.exists(path)), None)
    found_vars_path = next((path for path in ovmf_vars_paths if os.path.exists(path)), None)
    
    if not found_code_path or not found_vars_path:
        distro = detect_distro()
        distro_config = DISTRO_INFO.get(distro)
        if distro_config and distro_config['pkgs'].get('ovmf'):
            ovmf_pkg = distro_config['pkgs']['ovmf']
            print_error("Required UEFI firmware (OVMF) not found.")
            install_cmd = f"sudo {distro_config['cmd']} {ovmf_pkg}"
            if input(f"Attempt to install '{ovmf_pkg}' now with command:\n  {Style.BOLD}{install_cmd}{Style.ENDC}\n(y/N): ").strip().lower() == 'y':
                run_command_live(distro_config['cmd'].split() + [ovmf_pkg], as_root=True)
                found_code_path = next((path for path in ovmf_code_paths if os.path.exists(path)), None)
                found_vars_path = next((path for path in ovmf_vars_paths if os.path.exists(path)), None)
    
    if found_code_path:
        CONFIG['MACOS_UEFI_CODE'] = found_code_path
        print_success(f"Found UEFI Firmware: {found_code_path}")
    else:
        print_error("UEFI Firmware (OVMF_CODE.fd) still not found.")
        assets_ok = False
        
    if found_vars_path:
        CONFIG['MACOS_UEFI_VARS'] = found_vars_path
        print_success(f"Found UEFI Vars Template: {found_vars_path}")
    else:
        print_error("UEFI Vars Template (OVMF_VARS.fd) still not found.")
        assets_ok = False

    if not shutil.which("qemu-nbd"):
        print_error("Command 'qemu-nbd' not found. Please install 'qemu-utils'.")
        assets_ok = False
    if not shutil.which("mcopy"):
        distro = detect_distro()
        mtools_pkg = DISTRO_INFO.get(distro, {}).get("pkgs", {}).get("mtools", "mtools")
        print_error(f"Command 'mcopy' not found. Please install '{mtools_pkg}'.")
        assets_ok = False

    if not assets_ok:
        print_warning("\nPlease resolve the missing assets/packages before proceeding.")
        return False

    print_success("All required assets and tools are present.")
    return True


def create_new_macos_vm():
    """The main workflow for creating a new macOS VM."""
    clear_screen()
    print_header("Create New macOS VM")
    
    while True:
        vm_name = input(f"{Style.BOLD}Enter a short name for the new macOS VM (e.g., Sequoia): {Style.ENDC}").strip()
        if not vm_name:
            continue
        if os.path.exists(os.path.join(CONFIG['VMS_DIR_MACOS'], vm_name)):
            print_warning("A VM with this name already exists.")
            continue
        else:
            break
            
    installer_path = _get_installer_path()
    if not installer_path:
        print_info("VM creation cancelled.")
        return
        
    print_header("Configure Virtual Machine")
    mem = input(f"{Style.BOLD}Enter Memory (e.g., 8G) [default: 4096M]: {Style.ENDC}").strip() or "4096M"
    cpu = input(f"{Style.BOLD}Enter CPU cores to assign (e.g., 6): {Style.ENDC}").strip() or "2"
    vm_settings = {'mem': mem, 'cpu': cpu}
    
    disk_size_input = input(f"{Style.BOLD}Enter main disk size (GB) [default: 100G]: {Style.ENDC}").strip().upper() or "100G"
    if disk_size_input.isalpha():
        disk_size = "100G"
    elif not disk_size_input.endswith(('G', 'M', 'T')):
        disk_size = f"{re.sub(r'[^0-9]', '', disk_size_input)}G"
    else:
        disk_size = disk_size_input
    
    smbios_model = _get_smbios_model_choice()
    if not smbios_model:
        print_info("SMBIOS model selection cancelled. Aborting VM creation.")
        return
    
    print_header("Pre-Flight Checklist")
    print(f"VM Name: {vm_name}\nInstaller: {os.path.basename(installer_path)}\nMemory: {mem}, CPU Cores: {cpu}\nDisk Size: {disk_size}\nSMBIOS Model: {smbios_model}")
    if input("\nProceed with VM creation? (Y/n): ").strip().lower() == 'n':
        print_info("VM creation cancelled.")
        return

    print_header(f"Creating macOS VM: {vm_name}")
    paths = _get_vm_paths(vm_name)
    os.makedirs(paths['shared_dir'], exist_ok=True)
    print_success(f"VM directory created at: {paths['dir']}")

    shutil.copy(CONFIG['MACOS_UEFI_CODE'], paths['uefi_code'])
    shutil.copy(CONFIG['MACOS_UEFI_VARS'], paths['uefi_vars'])
    print_success("Copied UEFI assets.")

    smbios_data = _generate_smbios(smbios_model)
    if not smbios_data:
        return
    
    if not _build_and_patch_opencore_image(vm_name, smbios_data):
        print_error("Failed to build the OpenCore image. Aborting.")
        return
        
    run_command_live(["qemu-img", "create", "-f", "qcow2", paths['main_disk'], disk_size], check=True)
    print_success(f"Created {disk_size} main disk at {paths['main_disk']}.")

    print_header("Launching VM for Installation")
    qemu_cmd = _get_macos_qemu_command(vm_name, vm_settings, installer_path=installer_path)
    debug_mode = input("Launch in Debug Mode (to see QEMU errors in this terminal)? (y/N): ").strip().lower() == 'y'
    if debug_mode:
        print_info("Running QEMU command in current terminal. Press Ctrl+C to exit.")
        print(f"\n{Style.OKBLUE}▶️  Executing: {' '.join(qemu_cmd)}{Style.ENDC}\n")
        subprocess.run(qemu_cmd)
    else:
        launch_in_new_terminal_and_wait([("macOS Installer", qemu_cmd)])


def run_macos_vm():
    """Lists and runs an existing macOS VM."""
    clear_screen()
    print_header("Run Existing macOS VM")
    vms_dir = CONFIG['VMS_DIR_MACOS']
    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])
    if not vm_list:
        print_error("No macOS VMs found.")
        return
        
    vm_name = select_from_list(vm_list, "Choose a VM to run")
    if not vm_name:
        return
        
    paths = _get_vm_paths(vm_name)
    os.makedirs(paths['shared_dir'], exist_ok=True)
    if not os.path.exists(paths['main_disk']):
        print_error(f"Main disk for '{vm_name}' not found. Cannot run.")
        return

    print_header(f"Configure Run Settings for {vm_name}")
    mem = input(f"{Style.BOLD}Enter Memory (e.g., 8G) [default: 4096M]: {Style.ENDC}").strip() or "4096M"
    cpu = input(f"{Style.BOLD}Enter CPU cores to assign (e.g., 6): {Style.ENDC}").strip() or "2"
    vm_settings = {'mem': mem, 'cpu': cpu}

    installer_path = None
    if input(f"{Style.BOLD}Attach an installer image? (y/N): {Style.ENDC}").strip().lower() == 'y':
        installer_path = _get_installer_path()
        if installer_path:
            print_info(f"Attaching installer: {os.path.basename(installer_path)}")

    mac_addr = f"52:54:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"
    qemu_cmd = _get_macos_qemu_command(vm_name, vm_settings, mac_addr, installer_path=installer_path)
    debug_mode = input("Launch in Debug Mode (to see QEMU errors in this terminal)? (y/N): ").strip().lower() == 'y'
    if debug_mode:
        print_info("Running QEMU command in current terminal. Press Ctrl+C to exit.")
        print(f"\n{Style.OKBLUE}▶️  Executing: {' '.join(qemu_cmd)}{Style.ENDC}\n")
        subprocess.run(qemu_cmd)
    else:
        launch_in_new_terminal_and_wait([("Run macOS VM", qemu_cmd)])


def nuke_and_recreate_macos_vm():
    """Nukes the identity (SMBIOS) of a VM and re-patches OpenCore."""
    clear_screen()
    print_header("Nuke & Recreate VM Identity")
    vms_dir = CONFIG['VMS_DIR_MACOS']
    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])
    if not vm_list:
        print_error("No macOS VMs found.")
        return
        
    vm_name = select_from_list(vm_list, "Choose a VM to nuke")
    if not vm_name:
        return
        
    print_warning(f"This will generate a new Serial, MLB, and SmUUID for '{vm_name}'.\nThis can be useful for iMessage/FaceTime activation issues.")
    if input("Are you sure you want to proceed? (y/N): ").strip().lower() != 'y':
        print_info("Operation cancelled.")
        return
        
    paths = _get_vm_paths(vm_name)
    
    if os.path.exists(paths['opencore']):
        remove_file(paths['opencore'], as_root=True)
        print_info("Forcibly removed old OpenCore image.")

    smbios_model = _get_smbios_model_choice()
    if not smbios_model:
        print_info("SMBIOS model selection cancelled. Aborting nuke.")
        return
        
    smbios_data = _generate_smbios(smbios_model)
    if not smbios_data:
        return
        
    if not _build_and_patch_opencore_image(vm_name, smbios_data):
        print_error("Failed to build the new OpenCore image. Aborting.")
        return
        
    print_success(f"Identity for '{vm_name}' has been successfully nuked and recreated with model {smbios_model}.")


def delete_macos_vm():
    """Completely deletes a macOS VM directory."""
    clear_screen()
    print_header("Delete macOS VM Completely")
    vms_dir = CONFIG['VMS_DIR_MACOS']
    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])
    if not vm_list:
        print_error("No macOS VMs found.")
        return
        
    vm_name = select_from_list(vm_list, "Choose a VM to delete")
    if not vm_name:
        return
        
    print_warning(f"This will permanently delete the entire VM '{vm_name}', including its virtual disk.\nThis action CANNOT be undone.")
    confirm = input(f"To confirm, please type the name of the VM ({vm_name}): ").strip()
    if confirm == vm_name:
        remove_dir(_get_vm_paths(vm_name)['dir'])
        print_success(f"VM '{vm_name}' has been deleted.")
    else:
        print_error("Confirmation failed. Aborting.")


def macos_vm_menu():
    """Main menu for macOS VM management."""
    os.makedirs(CONFIG['VMS_DIR_MACOS'], exist_ok=True)
    if not check_macos_assets():
        input("Press Enter to return to the main menu...")
        return
        
    while True:
        clear_screen()
        print(f"\n{Style.HEADER}{Style.BOLD}macOS VM Management{Style.ENDC}\n───────────────────────────────────────────────")
        print(f"{Style.OKBLUE}1.{Style.ENDC} {Style.BOLD}Create New macOS VM{Style.ENDC}")
        print(f"{Style.OKCYAN}2.{Style.ENDC} {Style.BOLD}Run Existing macOS VM{Style.ENDC}")
        print(f"{Style.OKGREEN}3.{Style.ENDC} {Style.BOLD}Nuke & Recreate VM Identity{Style.ENDC}")
        print(f"{Style.FAIL}4.{Style.ENDC} {Style.BOLD}Delete macOS VM Completely{Style.ENDC}")
        print(f"{Style.WARNING}5.{Style.ENDC} {Style.BOLD}Return to Main Menu{Style.ENDC}")
        print("───────────────────────────────────────────────")
        choice = input(f"{Style.BOLD}Select an option [1-5]: {Style.ENDC}").strip()
        action_taken = True
        if choice == "1":
            create_new_macos_vm()
        elif choice == "2":
            run_macos_vm()
        elif choice == "3":
            nuke_and_recreate_macos_vm()
        elif choice == "4":
            delete_macos_vm()
        elif choice == "5":
            break
        else:
            print_warning("Invalid option.")
            action_taken = False
        if action_taken:
            input("\nPress Enter to return to the menu...")