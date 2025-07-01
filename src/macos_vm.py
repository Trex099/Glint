# Made by trex099
# https://github.com/Trex099/Glint
# pylint: disable=too-many-branches,too-many-statements
"""
This module handles all macOS VM management functionality.
"""
import os
import sys
import shutil
import subprocess
import re
import plistlib
import time
import random
import binascii
import tempfile
import json
import questionary

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rich.console import Console
from rich.panel import Panel
from config import CONFIG, DISTRO_INFO
from file_transfer import transfer_files_menu
from core_utils import (
    print_header, print_info, print_success, print_warning, print_error, clear_screen,
    run_command_live, select_from_list, launch_in_new_terminal_and_wait, remove_dir,
    detect_distro, remove_file, identify_iso_type, find_first_existing_path,
    get_disk_size, get_host_gpus, is_vfio_module_loaded, get_active_gpu_pci_address,
    get_iommu_group_devices, find_unused_port
)

console = Console()


MACOS_RECOMMENDED_MODELS = {
    "Sonoma (14)": "iMacPro1,1",
    "Ventura (13)": "MacPro7,1",
    "Monterey (12)": "iMac20,1",
    "Big Sur (11)": "iMac20,1",
    "Catalina (10.15)": "iMac19,1",
}


def _get_vm_paths(vm_name):
    """
    Returns a dictionary of paths for a given VM name.
    """
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
        "pid_file": os.path.join(vm_dir, "qemu.pid"),
        "config": os.path.join(vm_dir, "config.json"),
    }


def _get_macos_qemu_command(vm_name, vm_settings, mac_addr, ssh_port, installer_path=None, passthrough_pci_address=None):
    """
    Builds the QEMU command for a macOS VM, handling different installer types and SSH port forwarding.
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
        if installer_path.lower().endswith('.iso'):
            print_info("Attaching installer ISO as a SATA CD-ROM.")
            qemu_cmd.extend([
                "-device", "ide-cd,bus=sata.2,id=install_cd",
                "-drive", f"id=install_cd,if=none,format=raw,media=cdrom,file={installer_path}",
            ])
        else: # .dmg, .img
            print_info("Attaching installer image as a virtio block device.")
            qemu_cmd.extend([
                "-drive", f"id=install_disk,if=none,format=raw,file={installer_path}",
                "-device", "virtio-blk-pci,drive=install_disk",
            ])
    elif installer_path:
        print_warning(f"Installer path '{installer_path}' not found, installer will not be attached.")

    net_config = f"user,id=net0,hostfwd=tcp::{ssh_port}-:22"
    qemu_cmd.extend(["-netdev", net_config, "-device", f"vmxnet3,netdev=net0,mac={mac_addr}"])

    if passthrough_pci_address:
        print_info(f"Attaching VFIO PCI device: {passthrough_pci_address}")
        qemu_cmd.extend(["-device", f"vfio-pci,host={passthrough_pci_address}"])
    else:
        qemu_cmd.extend([
            "-device", "vmware-svga,vgamem_mb=128",
            "-display", "gtk,gl=on,show-cursor=on",
        ])

    qemu_cmd.extend([
        "-device", "qemu-xhci,id=xhci",
        "-device", "usb-kbd,bus=xhci.0",
        "-device", "usb-tablet,bus=xhci.0",
        "-fsdev", f"local,security_model=passthrough,id=fsdev0,path={paths['shared_dir']}",
        "-device", "virtio-9p-pci,id=fs0,fsdev=fsdev0,mount_tag=host_share",
        "-pidfile", paths['pid_file']
    ])

    return qemu_cmd


def _generate_smbios(model):
    """Generates a complete SMBIOS data set for a given model."""
    print_header("Generating SMBIOS...")
    cmd = [sys.executable, CONFIG['GENSMBIOS_SCRIPT'], "--model", model, "--count", "1"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                check=True, timeout=60, encoding='utf-8')
        output = result.stdout
        type_match, serial_match, mlb_match, uuid_match = (re.search(p, output) for p in [
            r"Type:\s*(\S+)", r"Serial:\s*(\S+)",
            r"Board Serial:\s*(\S+)", r"SmUUID:\s*(\S+)"
        ])
        if not all([type_match, serial_match, mlb_match, uuid_match]):
            print_error("Failed to parse SMBIOS from GenSMBIOS output for model "
                        f"'{model}'.")
            return None
        smbios_data = {'type': type_match.group(1), 'serial': serial_match.group(1),
                       'mlb': mlb_match.group(1), 'sm_uuid': uuid_match.group(1)}
        for key, value in smbios_data.items():
            print_success(f"  {key.replace('_', ' ').capitalize():<13}: {value}")
        return smbios_data
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        print_error(f"GenSMBIOS script failed: {e}")
        return None


def _find_available_nbd():
    """Finds the first available /dev/nbd device."""
    for i in range(16):  # Check nbd0 through nbd15
        device = f"/dev/nbd{i}"
        try:
            size = subprocess.check_output(['sudo', 'blockdev', '--getsize64', device],
                                           text=True).strip()
            if size == '0':
                return device
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


def _surgical_rebuild_config(smbios_data, mac_addr, custom_config_path, output_path, igpu_patch_properties=None):
    """
    Takes a known-good config.plist and injects SMBIOS, MAC address, and optional iGPU properties.
    """
    print_info("Injecting SMBIOS and MAC Address ROM into known-good config.plist...")
    try:
        with open(custom_config_path, 'rb') as f:
            config_data = plistlib.load(f)

        # Inject SMBIOS and ROM
        generic_section = config_data["PlatformInfo"]["Generic"]
        generic_section["SystemProductName"] = smbios_data['type']
        generic_section["SystemSerialNumber"] = smbios_data['serial']
        generic_section["MLB"] = smbios_data['mlb']
        generic_section["SystemUUID"] = smbios_data['sm_uuid']
        generic_section["ROM"] = binascii.unhexlify(mac_addr.replace(":", ""))

        # Inject iGPU patch if provided
        if igpu_patch_properties:
            print_info("Injecting iGPU device properties...")
            device_properties = config_data.setdefault("DeviceProperties", {}).setdefault("Add", {})
            device_properties.update(igpu_patch_properties)
            print_success("iGPU properties injected.")

        with open(output_path, 'wb') as f:
            plistlib.dump(config_data, f)

        print_success("config.plist patched successfully.")
        return True
    except (IOError, plistlib.InvalidFileException, KeyError) as e:
        print_error(f"Failed during config rebuild: {e}")
        return False


def _build_and_patch_opencore_image(vm_name, smbios_data, igpu_patch_properties=None):
    """
    Builds a new OpenCore image using guestmount for a safer and more reliable
    way to manipulate the disk image.
    """
    print_header(f"Building OpenCore Image for '{vm_name}'")
    paths = _get_vm_paths(vm_name)
    build_dir = f"/tmp/opencore_build_{os.getpid()}"
    temp_mount_point = f"/tmp/opencore_mount_{os.getpid()}"
    
    try:
        # --- 1. Prepare local EFI structure ---
        os.makedirs(build_dir, exist_ok=True)
        shutil.copytree("assets/EFI", os.path.join(build_dir, "EFI"), dirs_exist_ok=True)

        boot_dir = os.path.join(build_dir, "EFI", "BOOT")
        os.makedirs(boot_dir, exist_ok=True)
        shutil.copy(os.path.join("assets", "EFI", "OC", "Tools", "OpenShell.efi"), os.path.join(boot_dir, "BOOTx64.efi"))
        
        nsh_path = os.path.join(build_dir, "startup.nsh")
        with open(nsh_path, 'w', encoding='utf-8') as f:
            f.write(r"fs0:\EFI\OC\OpenCore.efi")

        mac_addr = f"52:54:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"
        if not _surgical_rebuild_config(
            smbios_data,
            mac_addr,
            "assets/EFI/config.plist",
            os.path.join(build_dir, "EFI", "OC", "config.plist"),
            igpu_patch_properties=igpu_patch_properties
        ):
            raise RuntimeError("Failed to patch config.plist locally.")

        # --- 2. Create and Format the Disk Image ---
        run_command_live(["qemu-img", "create", "-f", "qcow2", paths['opencore'], "512M"], quiet=True)
        
        # Use a reliable, non-interactive guestfish command sequence
        format_cmd = [
            "guestfish", "--rw", "-a", paths['opencore'],
            "run",
            "part-init", "/dev/sda", "mbr",
            "part-add", "/dev/sda", "primary", "2048", "-1",
            "part-set-bootable", "/dev/sda", "1", "true",
            "mkfs", "vfat", "/dev/sda1"
        ]
        if run_command_live(format_cmd, as_root=True, quiet=True) is None:
            print_error("Failed to format the OpenCore disk image using guestfish.")
            return False

        # --- 3. Mount and Copy Files ---
        os.makedirs(temp_mount_point, exist_ok=True)
        guestmount_cmd = [
            "guestmount",
            "-a", paths['opencore'],
            "-m", "/dev/sda1", # Mount the partition, not the whole disk
            temp_mount_point
        ]
        if run_command_live(guestmount_cmd, as_root=True, check=True) is None:
            print_error("Failed to mount the OpenCore disk image using guestmount.")
            return False

        if run_command_live(["cp", "-r", os.path.join(build_dir, "EFI"), temp_mount_point], as_root=True, check=True) is None:
            print_error("Failed to copy EFI files to the OpenCore image.")
            return False
        if run_command_live(["cp", nsh_path, temp_mount_point], as_root=True, check=True) is None:
            print_error("Failed to copy startup.nsh to the OpenCore image.")
            return False
        
        print_success("OpenCore image built and patched successfully.")
        return True

    except Exception as e:
        print_error(f"An unexpected error occurred during OpenCore image construction: {e}")
        return False
    finally:
        # --- 4. Robust Cleanup ---
        run_command_live(["guestunmount", temp_mount_point], as_root=True, check=False, quiet=True)
        if os.path.exists(build_dir):
            shutil.rmtree(build_dir)
        if os.path.exists(temp_mount_point):
            # Use rmtree for non-empty directories
            shutil.rmtree(temp_mount_point, ignore_errors=True)
            
    return False # Should not be reached, but as a fallback


def _find_installers():
    """
    Scans for local macOS installers, including .dmg, .img, and .iso files.
    """
    installers = []
    search_dirs = ['.', CONFIG['ASSETS_DIR']]
    
    print_info("Scanning for macOS installers (.dmg, .img, .iso)...")
    for directory in search_dirs:
        if not os.path.isdir(directory):
            continue
        for f in os.listdir(directory):
            full_path = os.path.abspath(os.path.join(directory, f))
            if full_path in installers:
                continue

            if f.lower().endswith(('.dmg', '.img')):
                installers.append(full_path)
            elif f.lower().endswith('.iso'):
                iso_type = identify_iso_type(full_path)
                if iso_type == 'macos':
                    installers.append(full_path)
                else:
                    print_warning(f"Ignoring non-macOS ISO: {f} (type: {iso_type})")
                    
    return installers


def _handle_dmg_conversion(dmg_path):
    """
    Handles the conversion of a .dmg file to a .img file.
    """
    print_header("DMG File Selected")
    console.print(
        Panel(
            "[bold]Why is conversion needed?[/bold]\n\n"
            "Most `.dmg` files are compressed or contain license agreements that prevent QEMU from booting them directly. "
            "Converting the `.dmg` to a raw `.img` file creates a simple, uncompressed, bit-for-bit disk image that QEMU can treat like a real hard drive, making it bootable.",
            title="[bold yellow]Action Required[/]",
            border_style="yellow",
            expand=False
        )
    )
    
    img_path = os.path.splitext(dmg_path)[0] + ".img"
    
    if questionary.confirm(f"Do you want to convert '{os.path.basename(dmg_path)}' to '{os.path.basename(img_path)}'?").ask():
        if os.path.exists(img_path):
            print_warning(f"'{os.path.basename(img_path)}' already exists.")
            if not questionary.confirm("Do you want to overwrite it?").ask():
                print_info("Conversion cancelled.")
                return None
        
        print_info(f"Converting '{os.path.basename(dmg_path)}' to '.img' format. This may take a moment...")
        convert_cmd = ["qemu-img", "convert", "-O", "raw", dmg_path, img_path]
        
        # Use run_command_live to show progress
        if run_command_live(convert_cmd, check=True):
            print_success("Conversion successful.")
            return img_path
        else:
            print_error("Conversion failed. Please check the output above.")
            return None
    else:
        print_info("Conversion declined. You cannot proceed with a .dmg file.")
        return None

def _get_installer_path():
    """Guides the user to select, download, or specify a path for the macOS installer."""
    print_header("Select macOS Installer")
    local_installers = _find_installers()
    options = []
    if local_installers:
        options.extend(local_installers)
    
    options.extend([
        questionary.Separator(),
        "Download using FetchMacOS.py script",
        "Enter path to installer manually",
        "Cancel"
    ])

    while True:
        selected_option = select_from_list(options, "Choose an installer or an option")

        if selected_option is None or selected_option == "Cancel":
            return None

        if os.path.exists(selected_option):
            if selected_option.lower().endswith('.dmg'):
                # Handle DMG conversion
                converted_path = _handle_dmg_conversion(selected_option)
                if converted_path:
                    return converted_path
                else:
                    # If conversion fails or is declined, re-prompt
                    continue
            else:
                # It's an ISO or IMG, which are fine
                return selected_option

        elif selected_option.startswith("Download"):
            run_command_live([sys.executable, CONFIG['FETCHMACOS_SCRIPT']], check=False)
            basesystem_path = "BaseSystem.dmg"
            if os.path.exists(basesystem_path):
                print_success(f"Download script finished. Using '{basesystem_path}'.")
                # Now handle the downloaded DMG
                converted_path = _handle_dmg_conversion(basesystem_path)
                if converted_path:
                    return converted_path
            else:
                print_error(f"Download script did not produce '{basesystem_path}'.")
            # Refresh installer list after download attempt
            local_installers = _find_installers()
            options = local_installers + [
                questionary.Separator(),
                "Download using FetchMacOS.py script",
                "Enter path to installer manually",
                "Cancel"
            ]
            continue

        elif selected_option.startswith("Enter path"):
            manual_path = questionary.text("Enter the absolute path to your installer file:").ask().strip()
            if os.path.exists(manual_path):
                if manual_path.lower().endswith('.dmg'):
                    converted_path = _handle_dmg_conversion(manual_path)
                    if converted_path:
                        return converted_path
                    else:
                        continue
                else:
                    return manual_path
            else:
                print_error(f"Path not found: {manual_path}")
        else:
            print_error("Invalid selection.")



def _get_smbios_model_choice():
    """Presents the user with options for SMBIOS model generation."""
    print_header("SMBIOS Model Selection")
    print_info("Select how to determine the Mac model for SMBIOS generation.")
    menu_items = ["Choose a model based on the macOS version (Recommended)",
                  "Enter a model identifier manually (Advanced)"]
    choice = select_from_list(menu_items, "Select an option")
    if not choice:
        return None
    if "Recommended" in choice:
        print_header("Select macOS Version")
        os_choice = select_from_list(list(MACOS_RECOMMENDED_MODELS.keys()),
                                     "Select the macOS version you are installing")
        return MACOS_RECOMMENDED_MODELS.get(os_choice) if os_choice else None
    while True:
        model = questionary.text("Enter Mac model (e.g., iMacPro1,1):").ask().strip()
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
    }
    for name, path in required_assets.items():
        if not os.path.exists(path):
            print_error(f"Asset '{name}' not found at: {path}")
            assets_ok = False

    found_code_path = find_first_existing_path(CONFIG['UEFI_CODE_PATHS'])
    found_vars_path = find_first_existing_path(CONFIG['UEFI_VARS_PATHS'])

    if found_code_path:
        print_success(f"Found UEFI Firmware: {found_code_path}")
    else:
        print_error("UEFI Firmware (OVMF_CODE.fd) not found.")
        assets_ok = False
        
    if found_vars_path:
        print_success(f"Found UEFI Vars Template: {found_vars_path}")
    else:
        print_error("UEFI Vars Template (OVMF_VARS.fd) not found.")
        assets_ok = False

    if not assets_ok:
        distro = detect_distro()
        distro_config = DISTRO_INFO.get(distro)
        if distro_config and distro_config['pkgs'].get('ovmf'):
            ovmf_pkg = distro_config['pkgs']['ovmf']
            print_error("One or more required UEFI firmware files are missing.")
            install_cmd = f"sudo {distro_config['cmd']} {ovmf_pkg}"
            if questionary.confirm(f"Attempt to install '{ovmf_pkg}' now with command:   [bold]{install_cmd}[/]").ask():
                run_command_live(distro_config['cmd'].split() + [ovmf_pkg], as_root=True)
                return check_macos_assets()

    if not shutil.which("qemu-nbd"):
        print_error("Command 'qemu-nbd' not found. Please install 'qemu-utils'.")
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
        vm_name = questionary.text("Enter a short name for the new macOS VM (e.g., Sequoia):").ask().strip()
        if not vm_name:
            continue
        if os.path.exists(os.path.join(CONFIG['VMS_DIR_MACOS'], vm_name)):
            print_warning("A VM with this name already exists.")
            continue
        break
    installer_path = _get_installer_path()
    if not installer_path:
        print_info("VM creation cancelled.")
        return
    print_header("Configure Virtual Machine")
    mem = questionary.text("Enter Memory (e.g., 8G) [default: 4096M]:").ask().strip() or "4096M"
    cpu = questionary.text("Enter CPU cores to assign (e.g., 6):").ask().strip() or "2"
    vm_settings = {'mem': mem, 'cpu': cpu}

    disk_size = get_disk_size("Enter main disk size (GB)", "100G")

    smbios_model = _get_smbios_model_choice()
    if not smbios_model:
        print_info("SMBIOS model selection cancelled. Aborting VM creation.")
        return

    preallocate = questionary.confirm("Enable disk pre-allocation for better performance? (This is slower to create)").ask()

    print_header("Pre-Flight Checklist")
    console.print(f"VM Name: {vm_name}\nInstaller: {os.path.basename(installer_path)}\n"
          f"Memory: {mem}, CPU Cores: {cpu}\nDisk Size: {disk_size}\n"
          f"SMBIOS Model: {smbios_model}\nPre-allocation: {'Yes' if preallocate else 'No'}")
    if not questionary.confirm("Proceed with VM creation?").ask():
        print_info("VM creation cancelled.")
        return

    print_header(f"Creating macOS VM: {vm_name}")
    paths = _get_vm_paths(vm_name)
    os.makedirs(paths['shared_dir'], exist_ok=True)
    with open(paths['config'], 'w', encoding='utf-8') as f:
        json.dump(vm_settings, f, indent=4)
    print_success(f"VM directory created at: {paths['dir']}")

    uefi_code_path = find_first_existing_path(CONFIG['UEFI_CODE_PATHS'])
    uefi_vars_path = find_first_existing_path(CONFIG['UEFI_VARS_PATHS'])
    if not uefi_code_path or not uefi_vars_path:
        print_error("Could not find required UEFI firmware files. Aborting.")
        return
        
    shutil.copy(uefi_code_path, paths['uefi_code'])
    shutil.copy(uefi_vars_path, paths['uefi_vars'])
    print_success("Copied UEFI assets.")

    smbios_data = _generate_smbios(smbios_model)
    if not smbios_data:
        return

    if not _build_and_patch_opencore_image(vm_name, smbios_data):
        print_error("Failed to build the OpenCore image. Aborting.")
        return

    qemu_img_cmd = ["qemu-img", "create", "-f", "qcow2"]
    if preallocate:
        qemu_img_cmd.extend(["-o", "preallocation=full"])
    qemu_img_cmd.extend([paths['main_disk'], disk_size])
    run_command_live(qemu_img_cmd, check=True)
    print_success(f"Created {disk_size} main disk at {paths['main_disk']}.")

    print_header("Launching VM for Installation")
    mac_addr = (f"52:54:00:{random.randint(0, 255):02x}:" 
               f"{random.randint(0, 255):02x}:{random.randint(0, 255):02x}")
    ssh_port = find_unused_port()
    print_info(f"SSH will be available on host port {ssh_port}")
    qemu_cmd = _get_macos_qemu_command(vm_name, vm_settings,
                                       mac_addr, ssh_port, installer_path=installer_path)
    debug_mode = questionary.confirm("Launch in Debug Mode (to see QEMU errors in this terminal)?").ask()
    if debug_mode:
        print_info("Running QEMU command in current terminal. Press Ctrl+C to exit.")
        print(f"\n[blue]▶️  Executing: {' '.join(qemu_cmd)}[/]\n")
        subprocess.run(qemu_cmd, check=False)
    else:
        launch_in_new_terminal_and_wait([("macOS Installer", qemu_cmd)])


def run_macos_vm():
    """Lists and runs an existing macOS VM."""
    clear_screen()
    print_header("Run Existing macOS VM")
    vms_dir = CONFIG['VMS_DIR_MACOS']
    vm_list = sorted([d for d in os.listdir(vms_dir)
                      if os.path.isdir(os.path.join(vms_dir, d))])
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

    defaults = {"mem": "4096M", "cpu": "2"}
    passthrough_pci_address = None
    if os.path.exists(paths['config']):
        with open(paths['config'], 'r', encoding='utf-8') as f:
            saved_config = json.load(f)
        defaults['mem'] = saved_config.get('mem', defaults['mem'])
        defaults['cpu'] = saved_config.get('cpu', defaults['cpu'])
        passthrough_pci_address = saved_config.get('passthrough_pci_address')

    print_header(f"Configure Run Settings for {vm_name}")
    mem = questionary.text(f"Enter Memory (e.g., 8G) [default: {defaults['mem']}]:").ask().strip() or defaults['mem']
    cpu = questionary.text(f"Enter CPU cores to assign (e.g., 6) [default: {defaults['cpu']}]:").ask().strip() or defaults['cpu']
    vm_settings = {'mem': mem, 'cpu': cpu}

    if passthrough_pci_address:
        print_info(f"Using saved passthrough device: {passthrough_pci_address}")

    installer_path = None
    if questionary.confirm("Attach an installer image?").ask():
        installer_path = _get_installer_path()
        if installer_path:
            print_info(f"Attaching installer: {os.path.basename(installer_path)}")

    mac_addr = (f"52:54:00:{random.randint(0, 255):02x}:"
               f"{random.randint(0, 255):02x}:{random.randint(0, 255):02x}")
    
    ssh_port = find_unused_port()
    print_info(f"SSH will be available on host port {ssh_port}")
    
    qemu_cmd = _get_macos_qemu_command(vm_name, vm_settings,
                                       mac_addr, ssh_port, installer_path=installer_path,
                                       passthrough_pci_address=passthrough_pci_address)
    debug_mode = questionary.confirm("Launch in Debug Mode (to see QEMU errors in this terminal)?").ask()
    if debug_mode:
        print_info("Running QEMU command in current terminal. Press Ctrl+C to exit.")
        console.print(f"\n[blue]▶️  Executing: {' '.join(qemu_cmd)}[/]\n")
        subprocess.run(qemu_cmd, check=False)
    else:
        launch_in_new_terminal_and_wait([("Run macOS VM", qemu_cmd)])


def nuke_and_recreate_macos_vm():
    """Nukes the identity (SMBIOS) of a VM and re-patches OpenCore."""
    clear_screen()
    print_header("Nuke & Recreate VM Identity")
    vms_dir = CONFIG['VMS_DIR_MACOS']
    vm_list = sorted([d for d in os.listdir(vms_dir)
                      if os.path.isdir(os.path.join(vms_dir, d))])
    if not vm_list:
        print_error("No macOS VMs found.")
        return
    vm_name = select_from_list(vm_list, "Choose a VM to nuke")
    if not vm_name:
        return
    print_warning(f"This will generate a new Serial, MLB, and SmUUID for '{vm_name}'. "
                  "This can be useful for iMessage/FaceTime activation issues.")
    if not questionary.confirm("Are you sure you want to proceed?").ask():
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
    print_success(f"Identity for '{vm_name}' has been successfully nuked and "
                  f"recreated with model {smbios_model}.")


def delete_macos_vm():
    """Completely deletes a macOS VM directory."""
    clear_screen()
    print_header("Delete macOS VM Completely")
    vms_dir = CONFIG['VMS_DIR_MACOS']
    vm_list = sorted([d for d in os.listdir(vms_dir)
                      if os.path.isdir(os.path.join(vms_dir, d))])
    if not vm_list:
        print_error("No macOS VMs found.")
        return
    vm_name = select_from_list(vm_list, "Choose a VM to delete")
    if not vm_name:
        return
    print_warning(f"This will permanently delete the entire VM '{vm_name}', "
                  "including its virtual disk.\nThis action CANNOT be undone.")
    confirm = questionary.text(f"To confirm, please type the name of the VM ({vm_name}):").ask().strip()
    if confirm == vm_name:
        remove_dir(_get_vm_paths(vm_name)['dir'])
        print_success(f"VM '{vm_name}' has been deleted.")
    else:
        print_error("Confirmation failed. Aborting.")


def mount_efi_partition():
    """Mounts the OpenCore EFI partition for a selected VM."""
    clear_screen()
    print_header("Mount EFI Partition (Advanced)")

    vms_dir = CONFIG['VMS_DIR_MACOS']
    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])
    if not vm_list:
        print_error("No macOS VMs found.")
        return

    vm_name = select_from_list(vm_list, "Choose a VM whose EFI you want to mount")
    if not vm_name:
        return

    paths = _get_vm_paths(vm_name)
    opencore_img = paths['opencore']
    if not os.path.exists(opencore_img):
        print_error(f"OpenCore image not found for VM '{vm_name}'.")
        return

    nbd_device = _find_available_nbd()
    if not nbd_device:
        print_error("No available NBD device found. Please ensure 'nbd' module is loaded.")
        return

    temp_mount_point = tempfile.mkdtemp(prefix=f"glint_{vm_name}_efi_")
    print_info(f"Using NBD device: {nbd_device}")
    print_info(f"Using mount point: {temp_mount_point}")

    try:
        run_command_live(["qemu-nbd", "--connect", nbd_device, opencore_img], as_root=True, check=True)
        time.sleep(1)

        run_command_live(["mount", f"{nbd_device}p1", temp_mount_point], as_root=True, check=True)

        print_success(f"\nEFI Partition for '{vm_name}' successfully mounted at:")
        console.print(f"[bold]{temp_mount_point}[/]")
        print_warning("Make your changes in another terminal. Press Enter here when you are done to unmount.")
        questionary.text("").ask()

    except Exception as e:
        print_error(f"An error occurred during the mounting process: {e}")
    finally:
        print_info("\nCleaning up resources...")
        try:
            run_command_live(["umount", temp_mount_point], as_root=True, check=False, quiet=True)
        except Exception:
            pass

        try:
            run_command_live(["qemu-nbd", "--disconnect", nbd_device], as_root=True, check=False, quiet=True)
        except Exception:
            pass

        try:
            os.rmdir(temp_mount_point)
        except OSError:
            pass

        print_success("Cleanup complete.")


def passthrough_menu():
    """Menu for GPU passthrough and performance settings with enhanced safety checks."""
    clear_screen()
    print_header("Passthrough & Performance")

    # 1. VFIO Module Check
    if not is_vfio_module_loaded():
        print_warning("The 'vfio-pci' kernel module is not loaded.")
        print_info("This is a strong indication that your host system is not configured for PCI passthrough.")
        if not questionary.confirm("Continue anyway? (Not Recommended)").ask():
            return

    # 2. Enhanced User Warnings
    print_header("⚠️ IMPORTANT: PLEASE READ CAREFULLY ⚠️")
    warning_text = """
[bold]1. Host System Prerequisite:[/bold]
   This tool only configures the VM. Your host system [bold]must[/] already be configured for IOMMU/VFIO passthrough (e.g., kernel parameters, BIOS/UEFI settings).

[bold]2. Potential for Instability:[/bold]
   Incorrectly passing through a device (especially one your host is actively using) can lead to system instability, a black screen on your host, or a forced hard reboot.

[bold]3. Primary GPU Warning:[/bold]
   Passing through your primary/boot GPU is an advanced procedure. If you do this without a secondary GPU for your host, you will lose display output on the host.
"""
    console.print(warning_text)
    
    confirmation = questionary.text(
        "This is an advanced feature. Type 'understand the risks' to continue:"
    ).ask()
    if confirmation != "understand the risks":
        print_error("Confirmation failed. Aborting.")
        return

    # --- VM and GPU Selection ---
    vms_dir = CONFIG['VMS_DIR_MACOS']
    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])
    if not vm_list:
        print_error("No macOS VMs found.")
        return

    vm_name = select_from_list(vm_list, "Choose a VM to configure")
    if not vm_name:
        return

    paths = _get_vm_paths(vm_name)
    print_header(f"Select GPU for '{vm_name}'")
    gpus = get_host_gpus()
    if not gpus:
        print_error("No GPUs found on the host system.")
        return

    active_gpu_pci = get_active_gpu_pci_address()
    if active_gpu_pci:
        print_info(f"Detected active host GPU: {active_gpu_pci}. It will be marked.")
        for gpu in gpus:
            if gpu['pci_address'] == active_gpu_pci:
                gpu['display_name'] += " [bold yellow](Active Host GPU)[/bold yellow]"

    selected_gpu = select_from_list(gpus, "Select a GPU to pass through", display_key='display_name')
    if not selected_gpu:
        return

    # --- Final Safety Checks for Selected GPU ---
    pci_address = selected_gpu['pci_address']
    
    # 4. Primary GPU Warning
    if pci_address == active_gpu_pci:
        print_warning("You have selected the active host GPU.")
        print_info("This will likely cause your host display to go black. Only proceed if you have a secondary GPU or another way to access your host.")
        if not questionary.confirm("Are you absolutely sure you want to proceed?").ask():
            return

    # 5. IOMMU Group Check
    other_devices = get_iommu_group_devices(pci_address)
    if other_devices:
        print_warning(f"The selected GPU is in an IOMMU group with other devices:")
        for device in other_devices:
            console.print(f"  - {device}")
        print_info("Passing this GPU will pass through all these devices. This is usually not recommended unless the devices are part of the GPU (e.g., HDMI Audio).")
        if not questionary.confirm("Proceed with passing through the entire group?").ask():
            return

    print_info(f"Proceeding with configuration for: {selected_gpu['description']}")

    # --- Configuration and Saving ---
    igpu_patch_properties = None
    if selected_gpu['type'] == 'iGPU':
        print_info("iGPU selected. Preparing necessary OpenCore patch.")
        igpu_patch_properties = {
            "PciRoot(0x0)/Pci(0x2,0x0)": {
                "AAPL,ig-platform-id": binascii.unhexlify("00001659"),
                "device-id": binascii.unhexlify("16590000"),
            }
        }
        if not questionary.confirm("This will rebuild the OpenCore image with iGPU patches. Continue?").ask():
            return
    
    try:
        with open(paths['config'], 'r+') as f:
            vm_config = json.load(f)
            vm_config['passthrough_pci_address'] = pci_address
            f.seek(0)
            json.dump(vm_config, f, indent=4)
            f.truncate()
        print_success(f"Saved passthrough device {pci_address} to {vm_name}'s config.")
    except (IOError, json.JSONDecodeError) as e:
        print_error(f"Could not update VM config: {e}")
        return

    if igpu_patch_properties:
        print_header("Rebuilding OpenCore for iGPU Passthrough")
        smbios_model = _get_smbios_model_choice()
        if not smbios_model:
            print_error("SMBIOS model is required to rebuild OpenCore. Aborting.")
            return
        smbios_data = _generate_smbios(smbios_model)
        if not smbios_data:
            print_error("Failed to generate SMBIOS. Aborting.")
            return
        
        if _build_and_patch_opencore_image(vm_name, smbios_data, igpu_patch_properties=igpu_patch_properties):
            print_success("OpenCore image rebuilt successfully for iGPU passthrough.")
        else:
            print_error("Failed to rebuild OpenCore image.")





def macos_vm_menu():
    """Main menu for macOS VM management."""
    if not check_macos_assets():
        questionary.text("Press Enter to return to the main menu...").ask()
        return
    while True:
        clear_screen()
        console.print("[bold]macOS VM Management[/]")
        console.print("───────────────────────────────────────────────")
        choice = questionary.select(
            "Select an option",
            choices=[
                "1. Create New macOS VM",
                "2. Run Existing macOS VM",
                "3. Nuke & Recreate VM Identity",
                "4. Mount EFI Partition (Advanced)",
                "5. Passthrough & Performance",
                "6. Transfer Files (SFTP)",
                "7. Delete macOS VM Completely",
                "8. Return to Main Menu",
            ]
        ).ask()
        action_taken = True
        if choice == "1. Create New macOS VM":
            create_new_macos_vm()
        elif choice == "2. Run Existing macOS VM":
            run_macos_vm()
        elif choice == "3. Nuke & Recreate VM Identity":
            nuke_and_recreate_macos_vm()
        elif choice == "4. Mount EFI Partition (Advanced)":
            mount_efi_partition()
        elif choice == "5. Passthrough & Performance":
            passthrough_menu()
        elif choice == "6. Transfer Files (SFTP)":
            vm_name = select_from_list([d for d in os.listdir(CONFIG['VMS_DIR_MACOS']) if os.path.isdir(os.path.join(CONFIG['VMS_DIR_MACOS'], d))], "Choose a VM")
            if vm_name:
                vm_dir = _get_vm_paths(vm_name)['dir']
                transfer_files_menu(vm_name, "macos", vm_dir)
        elif choice == "7. Delete macOS VM Completely":
            delete_macos_vm()
        elif choice == "8. Return to Main Menu":
            break
        else:
            print_warning("Invalid option.")
            action_taken = False
        if action_taken:
            questionary.text("\nPress Enter to return to the menu...").ask()
