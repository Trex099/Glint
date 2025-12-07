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
import psutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
# from rich.text import Text
from config import CONFIG, DISTRO_INFO
from file_transfer import transfer_files_menu
from core_utils import (
    print_header, print_info, print_success, print_warning, print_error, clear_screen,
    run_command_live, select_from_list, launch_in_new_terminal_and_wait, remove_dir,
    detect_distro, get_cpu_vendor, get_host_ips, remove_file, identify_iso_type, find_first_existing_path,
    get_disk_size, get_host_gpus, is_vfio_module_loaded, is_iommu_active, is_monitor_connected, get_active_gpu_pci_address,
    get_iommu_group_devices, find_unused_port, get_pci_device_driver, bind_pci_device_to_driver,
    manage_firewall_rule, run_guestfs_command, is_apfs_support_enabled
)
console = Console()


MACOS_RECOMMENDED_MODELS = {
    "Sequoia (15)": "iMacPro1,1",
    "Sonoma (14)": "iMacPro1,1",
    "Ventura (13)": "MacPro7,1",
    "Monterey (12)": "MacBookPro16,1",
    "Big Sur (11)": "MacBookPro16,1",
    "Catalina (10.15)": "MacBookPro15,1",
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
        "session_info": os.path.join(vm_dir, "session.info"),
    }


def get_running_vm_info(vm_name):
    """Gets the PID and other info of a running VM by checking the pidfile."""
    paths = _get_vm_paths(vm_name)
    pid_file = paths.get('pid_file')
    if pid_file and os.path.exists(pid_file):
        try:
            with open(pid_file, 'r', encoding='utf-8') as f:
                pid = int(f.read().strip())
            # Check if the process is actually running
            if psutil.pid_exists(pid):
                return {'pid': pid}
        except (IOError, ValueError):
            # PID file is invalid or process is gone
            pass
    return None

def is_vm_running(vm_name):
    """Checks if a VM is running."""
    return get_running_vm_info(vm_name) is not None


def select_vm(action_text, running_only=False):
    """
    Prompts the user to select a VM from the list of available macOS VMs.
    """
    print_header(f"Select VM to {action_text}")
    vms_dir = CONFIG['VMS_DIR_MACOS']
    if not os.path.isdir(vms_dir) or not os.listdir(vms_dir):
        print_error("No macOS VMs found.")
        return None

    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])

    if running_only:
        vm_list = [vm for vm in vm_list if is_vm_running(vm)]
        if not vm_list:
            print_error("No running VMs found.")
            return None

    if not vm_list:
        print_error("No macOS VMs found.")
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
        time.sleep(1)
        paths = _get_vm_paths(vm_name)
        files_to_clean = [paths['pid_file']]
        if 'session_info' in paths and paths['session_info']:
            files_to_clean.append(paths['session_info'])
        for f in files_to_clean:
            if os.path.exists(f):
                remove_file(f)
    elif not force:
        print_error(f"Could not get running info for '{vm_name}'. It may not be running.")



def _get_macos_qemu_command(vm_name, vm_settings, mac_addr, ssh_port, installer_path=None, passthrough_devices=None, use_vnc=False, vnc_port=None, resolution=None):
    """
    Builds the QEMU command, supporting standard, passthrough, and VNC display modes with maximum compatibility.
    """
    paths = _get_vm_paths(vm_name)
    cores = vm_settings.get('cpu', '8')

    qemu_cmd = [
        "qemu-system-x86_64", "-enable-kvm", "-m", vm_settings['mem'],
        "-cpu", "Cascadelake-Server,-hle,-rtm,kvm=off",
        "-machine", "q35,accel=kvm",
        "-smp", f"{cores},sockets=1,cores={cores},threads=1",
        "-device", f"isa-applesmc,osk={CONFIG['OSK_KEY']}",
        "-smbios", "type=2",
        "-drive", f"if=pflash,format=raw,readonly=on,file={paths['uefi_code']}",
        "-drive", f"if=pflash,format=raw,file={paths['uefi_vars']}",
        "-device", "ich9-ahci,id=sata",
        "-device", "ide-hd,bus=sata.0,drive=opencore_disk,bootindex=1",
        "-drive", f"id=opencore_disk,if=none,format=qcow2,file={paths['opencore']}",
        "-drive", f"id=main_disk,if=none,format=qcow2,file={paths['main_disk']}",
        "-device", "virtio-blk-pci,drive=main_disk",
    ]

    if installer_path and os.path.exists(installer_path):
        if installer_path.lower().endswith('.iso'):
            qemu_cmd.extend(["-device", "ide-cd,bus=sata.2,id=install_cd", "-drive", f"id=install_cd,if=none,format=raw,media=cdrom,file={installer_path}"])
        else:
            qemu_cmd.extend(["-drive", f"id=install_disk,if=none,format=raw,file={installer_path}", "-device", "virtio-blk-pci,drive=install_disk"])

    net_config = f"user,id=net0,hostfwd=tcp::{ssh_port}-:22"
    qemu_cmd.extend(["-netdev", net_config, "-device", f"vmxnet3,netdev=net0,mac={mac_addr}"])

    # --- Display Logic: Final Version ---
    if passthrough_devices:
        print_info("Attaching physical PCI passthrough devices...")
        for addr in passthrough_devices:
            qemu_cmd.extend(["-device", f"vfio-pci,host={addr}"])
        
        if use_vnc and vnc_port:
            print_info("Creating a virtual display for VNC...")
            # We still need a device for VNC to bind to
            qemu_cmd.extend(["-device", "vmware-svga,vgamem_mb=256"])
            qemu_cmd.extend(["-vnc", f"0.0.0.0:{vnc_port - 5900}"])
        else:
            qemu_cmd.extend(["-display", "none"])
    else:
        # Standard virtual graphics. We must disable the default VGA device
        # to ensure macOS only sees our intended vmware-svga device.
        # Use the standard vmware-svga device, which is the most compatible.
        # The resolution is set inside the guest by OpenCore, not on the QEMU command line.
        qemu_cmd.extend(["-vga", "none"])
        qemu_cmd.extend(["-device", "vmware-svga,vgamem_mb=256"])
        qemu_cmd.extend(["-display", "gtk,gl=on,show-cursor=off"])


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
        rom_match = re.search(r"ROM:\s*(\S+)", output)

        smbios_data = {
            'type': type_match.group(1),
            'serial': serial_match.group(1),
            'mlb': mlb_match.group(1),
            'sm_uuid': uuid_match.group(1),
            'rom': rom_match.group(1) if rom_match else None # Add the ROM to our dictionary
        }

        # Print all 5 values
        print_success(f"  {'Type':<13}: {smbios_data['type']}")
        print_success(f"  {'Serial':<13}: {smbios_data['serial']}")
        print_success(f"  {'Mlb':<13}: {smbios_data['mlb']}")
        print_success(f"  {'Sm uuid':<13}: {smbios_data['sm_uuid']}")
        if smbios_data['rom']:
            print_success(f"  {'Apple ROM':<13}: {smbios_data['rom']}")
        
        # iServices verification reminder
        print_info("")
        print_warning("📱 iMESSAGE/FACETIME VERIFICATION:")
        print_info(f"  1. Go to: https://checkcoverage.apple.com/")
        print_info(f"  2. Enter serial: {smbios_data['serial']}")
        print_info(f"  3. Should show: 'Unable to check coverage' (not registered)")
        print_info(f"  4. If it shows a purchase date, regenerate SMBIOS!")
        print_info("")
        print_info("⚠️  iServices compatibility depends on Apple's servers.")
        print_info("     This configuration is optimized but NOT guaranteed to work.")
        
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


      
      
def _surgical_rebuild_config(smbios_data, mac_addr, custom_config_path, output_path):
    """
    Takes a config.plist and injects ONLY the SMBIOS and ROM data,
    leaving all other values untouched.
    Also adds DeviceProperties for en0 built-in (required for iMessage).
    """
    print_info("Surgically patching config.plist...")
    try:
        with open(custom_config_path, 'rb') as f:
            config_data = plistlib.load(f)

        # Inject SMBIOS and ROM
        if "PlatformInfo" in config_data and "Generic" in config_data["PlatformInfo"]:
            generic_section = config_data["PlatformInfo"]["Generic"]
            generic_section["SystemProductName"] = smbios_data['type']
            generic_section["SystemSerialNumber"] = smbios_data['serial']
            generic_section["MLB"] = smbios_data['mlb']
            generic_section["SystemUUID"] = smbios_data['sm_uuid']
            generic_section["ROM"] = binascii.unhexlify(mac_addr.replace(":", ""))
            print_info("  - SMBIOS and ROM injected.")
        else:
            print_error("  - ERROR: Could not find PlatformInfo -> Generic section!")
            return False

        # Add DeviceProperties for en0 built-in (iMessage compatibility)
        # This marks the primary network interface as "built-in" which is
        # required for Apple iServices (iMessage, FaceTime) to work properly.
        if "DeviceProperties" not in config_data:
            config_data["DeviceProperties"] = {}
        if "Add" not in config_data["DeviceProperties"]:
            config_data["DeviceProperties"]["Add"] = {}
        
        # Standard QEMU virtio-net PCI path
        # This may need adjustment based on VM configuration
        en0_pci_paths = [
            "PciRoot(0x0)/Pci(0x2,0x0)",  # Common QEMU path
            "PciRoot(0x0)/Pci(0x1,0x0)",  # Alternative path
        ]
        
        for pci_path in en0_pci_paths:
            if pci_path not in config_data["DeviceProperties"]["Add"]:
                config_data["DeviceProperties"]["Add"][pci_path] = {}
            # built-in = 0x01 (true) as Data type
            config_data["DeviceProperties"]["Add"][pci_path]["built-in"] = b'\x01'
        
        print_info("  - DeviceProperties for en0 built-in added (iServices compatibility).")

        with open(output_path, 'wb') as f:
            plistlib.dump(config_data, f)

        print_success("config.plist patched successfully.")
        return True
    except (IOError, plistlib.InvalidFileException, KeyError, TypeError) as e:
        print_error(f"Failed during config rebuild: {e}")
        import traceback
        traceback.print_exc()
        return False
 
      
def _build_and_patch_opencore_image(vm_name, smbios_data, vm_settings, igpu_patch_properties=None):
    """
    Builds a new OpenCore image, reading resolution from the VM's config if it exists.
    It now also generates and saves the permanent MAC address to the vm_settings dict.
    """
    print_header(f"Building OpenCore Image for '{vm_name}'")
    paths = _get_vm_paths(vm_name)
    build_dir = f"/tmp/opencore_build_{os.getpid()}"
    temp_mount_point = f"/tmp/opencore_mount_{os.getpid()}"
    
    # --- FIX STARTS HERE: Read resolution directly from the passed vm_settings ---
    # resolution = vm_settings.get('resolution')  # Unused variable
    # --- FIX ENDS HERE ---

    try:
        shutil.copytree("assets/EFI", build_dir, dirs_exist_ok=True)
        print_info("Temporary EFI structure created.")

        
        # Get the ROM from the SMBIOS data and convert it to a MAC address for the config.
        generated_rom = smbios_data.get('rom') # <-- THIS IS THE MISSING LINE
        
        if not generated_rom:
            raise RuntimeError("Failed to get a ROM from GenSMBIOS. Cannot proceed.")

        # Convert the 12-char ROM string to a standard MAC address with colons.
        mac_addr = ":".join(generated_rom[i:i+2] for i in range(0, len(generated_rom), 2))
        vm_settings['mac_addr'] = mac_addr
        print_info(f"Using ROM-derived MAC Address: {mac_addr}")
        
        temp_config_path = os.path.join(build_dir, "OC", "config.plist")

        if not os.path.exists(temp_config_path):
             print_error("FATAL: Template 'config.plist' not found in 'assets/EFI/OC/'")
             return False

              
        if not _surgical_rebuild_config(
            smbios_data, mac_addr, temp_config_path, temp_config_path
        ):
            raise RuntimeError("Failed to patch config.plist in temporary directory.")

    

        print_info("Setting up shell-based boot for reliability...")
        boot_dir = os.path.join(build_dir, "BOOT")
        shell_path = os.path.join(build_dir, "OC", "Tools", "OpenShell.efi")
        bootx64_path = os.path.join(boot_dir, "BOOTx64.efi")
        os.makedirs(boot_dir, exist_ok=True)
        shutil.copy(shell_path, bootx64_path)

        nsh_path = os.path.join(build_dir, "startup.nsh")
        with open(nsh_path, 'w', encoding='utf-8') as f:
            f.write(r"fs0:\EFI\OC\OpenCore.efi")
        print_info("  - startup.nsh created to launch OpenCore.")

        # If OpenCore disk exists, remove it before creating a new one
        if os.path.exists(paths['opencore']):
            remove_file(paths['opencore'], as_root=True)

        run_command_live(["qemu-img", "create", "-f", "qcow2", paths['opencore'], "512M"], quiet=True)
        
        guestfish_cmd = ["guestfish", "--rw", "-a", paths['opencore']]
        commands_to_pipe = "run\npart-init /dev/sda mbr\npart-add /dev/sda primary 2048 -1\npart-set-bootable /dev/sda 1 on\nmkfs vfat /dev/sda1\n"
        if os.geteuid() != 0: guestfish_cmd.insert(0, "sudo")
        subprocess.run(guestfish_cmd, input=commands_to_pipe, capture_output=True, text=True, check=True, encoding='utf-8')
            
        os.makedirs(temp_mount_point, exist_ok=True)
        guestmount_cmd = ["guestmount", "-a", paths['opencore'], "-m", "/dev/sda1", temp_mount_point]
        if run_command_live(guestmount_cmd, as_root=True, check=True) is None: return False
        
        if run_command_live(["cp", "-r", f"{build_dir}/.", temp_mount_point], as_root=True, check=True) is None: return False
        
        print_success("OpenCore image built and patched successfully.")
        return True

    except Exception as e:
        print_error(f"An unexpected error occurred during OpenCore image construction: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        run_command_live(["guestunmount", temp_mount_point], as_root=True, check=False, quiet=True)
        if os.path.exists(build_dir): shutil.rmtree(build_dir)
        if os.path.exists(temp_mount_point): shutil.rmtree(temp_mount_point, ignore_errors=True)
            
    return False

    

    

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
        
        # Use run_command_live and check its return value.
        # It returns None ONLY on failure. It returns an empty string "" on silent success.
        result = run_command_live(convert_cmd, check=True)
        if result is not None:
            print_success("Conversion successful.")
            return img_path
        else:
            print_error("Conversion failed. Please check the output above.")
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
            # We use subprocess.run directly here to let the interactive script
            # control the terminal, which is necessary for its menu and progress bar.
            subprocess.run([sys.executable, CONFIG['FETCHMACOS_SCRIPT']], check=False)
            # Use an absolute path to be consistent with the other logic paths.
            basesystem_path = os.path.abspath("BaseSystem.dmg")
            if os.path.exists(basesystem_path):
                print_success(f"Download script finished. Using '{os.path.basename(basesystem_path)}'.")
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
        model = questionary.text("Enter Mac model (Recommended, iMacPro1,1 or MacPro7,1):").ask().strip()
        if model:
            return model
        print_warning("Model cannot be empty.")


KVM_IGPU_PATCHES = {
    "Intel HD 530 (Skylake)": {
        "AAPL,ig-platform-id": binascii.unhexlify("00001219"),
        "device-id": binascii.unhexlify("12190000"),
    },
    "Intel UHD 630 (Coffee Lake)": {
        "AAPL,ig-platform-id": binascii.unhexlify("07009B3E"),
        "device-id": binascii.unhexlify("9B3E0000"),
    },
    "Intel UHD 770 (Alder/Raptor Lake)": {
        "AAPL,ig-platform-id": binascii.unhexlify("0600A780"),
        "device-id": binascii.unhexlify("A7800000"),
    },
    "Intel Iris Xe (Rocket Lake)": {
        "AAPL,ig-platform-id": binascii.unhexlify("0A00C09A"),
        "device-id": binascii.unhexlify("C09A0000"),
    },
}

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
        result = questionary.text("Enter a short name for the new macOS VM (e.g., Sequoia):").ask()
        if result is None:
            print_info("VM creation cancelled.")
            return
        vm_name = result.strip()
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
    
    mem_result = questionary.text("Enter Memory (e.g., 8G) [default: 4096M]:").ask()
    if mem_result is None:
        print_info("VM creation cancelled.")
        return
    mem = mem_result.strip() or "4096M"
    
    cpu_result = questionary.text("Enter CPU cores to assign (e.g., 6):").ask()
    if cpu_result is None:
        print_info("VM creation cancelled.")
        return
    cpu = cpu_result.strip() or "2"
    
    vm_settings = {'mem': mem, 'cpu': cpu}
    from core_utils import get_host_screen_resolution
    native_res = get_host_screen_resolution()
    res_confirm = questionary.confirm(f"Use native host resolution ({native_res})? (Recommended for HiDPI/Retina)").ask() if native_res else None
    if res_confirm is None:
        print_info("VM creation cancelled.")
        return
    if native_res and res_confirm:
        vm_settings['resolution'] = native_res

    disk_size = get_disk_size("Enter main disk size (GB)", "100G")
    if disk_size is None:
        print_info("VM creation cancelled.")
        return

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

    if not _build_and_patch_opencore_image(vm_name, smbios_data, vm_settings):
        print_error("Failed to build the OpenCore image. Aborting.")
        return

    qemu_img_cmd = ["qemu-img", "create", "-f", "qcow2"]
    if preallocate:
        qemu_img_cmd.extend(["-o", "preallocation=full"])
    qemu_img_cmd.extend([paths['main_disk'], disk_size])
    run_command_live(qemu_img_cmd, check=True)
    print_success(f"Created {disk_size} main disk at {paths['main_disk']}.")

    print_header("Launching VM for Installation")

    # The vm_settings dict was modified in-place by _build_and_patch_opencore_image
    # Now we save it to the config file so the MAC is persistent.
    with open(paths['config'], 'w', encoding='utf-8') as f:
        json.dump(vm_settings, f, indent=4)

    # Now read the persistent MAC from the dictionary for the launch command
    mac_addr = vm_settings.get('mac_addr')
    if not mac_addr:
        print_error("FATAL: MAC Address was not saved to config.json. Cannot launch.")
        return

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

def _generate_run_dashboard(vm_name, mem, cpu, installer_path, passthrough_devices):
    """Generates a rich Panel that displays the current VM run settings."""
    
    table = Table(box=None, expand=True, show_header=False)
    table.add_column("Setting", justify="right", style="cyan")
    table.add_column("Value", justify="left")

    table.add_row("Memory:", f"[bold white]{mem}[/]")
    table.add_row("CPU Cores:", f"[bold white]{cpu}[/]")
    
    installer_display = os.path.basename(installer_path) if installer_path else "[dim]None[/]"
    table.add_row("Installer Image:", f"[bold white]{installer_display}[/]")
    
    if passthrough_devices:
        gpu_text = "\n".join(f"  - {addr}" for addr in passthrough_devices)
        status_text = f"[bold yellow]Active[/]\n{gpu_text}"
    else:
        status_text = "[bold green]Standard Virtual Graphics[/]"
    table.add_row("Graphics:", status_text)

    return Panel(table, title=f"[bold purple]Pre-Launch Dashboard for '{vm_name}'[/]", border_style="purple")

def run_macos_vm():
    """Lists and runs an existing macOS VM with an interactive pre-launch dashboard."""
    clear_screen()
    vm_name = select_vm("Run / Resume")
    if not vm_name: return

    if is_vm_running(vm_name):
        print_error(f"VM '{vm_name}' is already running.")
        return

    paths = _get_vm_paths(vm_name)
    os.makedirs(paths['shared_dir'], exist_ok=True)
    if not os.path.exists(paths['main_disk']):
        print_error(f"Main disk for '{vm_name}' not found. Cannot run.")
        return

    vm_config = {}
    if os.path.exists(paths['config']):
        with open(paths['config'], 'r', encoding='utf-8') as f: vm_config = json.load(f)

    # --- Initialize settings from config or defaults ---
    mem = vm_config.get('mem', '4096M')
    cpu = vm_config.get('cpu', '2')
    passthrough_devices = vm_config.get('passthrough_devices', [])
    installer_path = None
    use_vnc = False
    vnc_port = None
    firewall_rule_managed = False
    bound_devices = {}

    # --- Interactive Dashboard Loop ---
    while True:
        clear_screen()
        console.print(_generate_run_dashboard(vm_name, mem, cpu, installer_path, passthrough_devices))

        installer_action = "Change/Remove Installer" if installer_path else "Attach Installer Image"
        
        choice = questionary.select(
            "Modify settings or launch the VM:",
            choices=[
                questionary.Choice(f"1. Change Memory ({mem})", value="mem"),
                questionary.Choice(f"2. Change CPU Cores ({cpu})", value="cpu"),
                questionary.Choice(f"3. {installer_action}", value="installer"),
                questionary.Separator(),
                questionary.Choice("✅ Launch VM in Window", value="launch"),
                questionary.Choice("🚀 Launch VM in Fullscreen", value="fullscreen"),
                questionary.Choice("❌ Cancel Launch", value="cancel")
            ],
            use_indicator=True
        ).ask()

        if choice is None or choice == "cancel":
            print_info("VM launch cancelled.")
            return
        elif choice in ["launch", "fullscreen"]:
            break # Exit loop to proceed with launch
        elif choice == "mem":
            new_mem = questionary.text(f"Enter Memory [current: {mem}]:").ask().strip().upper()
            if new_mem: mem = new_mem
        elif choice == "cpu":
            new_cpu = questionary.text(f"Enter CPU cores [current: {cpu}]:").ask().strip()
            if new_cpu and new_cpu.isdigit(): cpu = new_cpu
        elif choice == "installer":
            if installer_path:
                if questionary.confirm("Do you want to remove the currently attached installer?").ask():
                    installer_path = None
            else:
                new_installer_path = _get_installer_path()
                if new_installer_path: installer_path = new_installer_path
    
    # --- Final Launch Sequence ---
    try:
        if passthrough_devices:
            print_header("Passthrough Display Configuration")
            display_choice = select_from_list(["On a physical monitor", "Remotely via VNC"], "How do you want to view this VM?")
            if display_choice is None: raise KeyboardInterrupt("VM launch cancelled.")
            
            if "physical monitor" in display_choice.lower():
                gpu_pci_addr = passthrough_devices[0]
                if not is_monitor_connected(gpu_pci_addr):
                    print_error(f"No monitor detected on the selected GPU ({gpu_pci_addr}).")
                    if not questionary.confirm("Continue anyway? (May require VNC later)").ask():
                        raise KeyboardInterrupt("Launch aborted by user.")
                else:
                    print_success(f"Monitor detected on GPU {gpu_pci_addr}. Proceeding with physical display mode.")
            
            if "VNC" in display_choice:
                use_vnc = True
                vnc_port = find_unused_port()

        # --- Point of No Return ---
        mac_addr = vm_config.get('mac_addr')
        if not mac_addr:
            print_warning("No persistent MAC address found in config.json.")
            print_error("iServices will likely fail. To fix this, use the 'Nuke & Recreate VM Identity' option from the menu.")
            # Generate a temporary one for this session only
            mac_addr = f"52:54:00:{random.randint(0,255):02x}:{random.randint(0,255):02x}:{random.randint(0,255):02x}"

        ssh_port = find_unused_port()
        vm_settings = {'mem': mem, 'cpu': cpu} # Use the final settings from the dashboard

        resolution = vm_config.get('resolution')

        qemu_cmd = _get_macos_qemu_command(
            vm_name, vm_settings, mac_addr, ssh_port, 
            installer_path, passthrough_devices, use_vnc, vnc_port, resolution # Pass resolution here
        )
        print_success("QEMU command and all file paths validated.")
        
        if choice == "fullscreen":
            qemu_cmd.append("-full-screen")

        if passthrough_devices:
            if use_vnc:
                if questionary.confirm(f"A firewall may block VNC. Allow Glint to manage port {vnc_port} temporarily?").ask():
                    if manage_firewall_rule(vnc_port, action='add'): firewall_rule_managed = True
                    else: raise RuntimeError("Failed to open firewall port.")
                host_ips = get_host_ips()
                vnc_instructions = f"Connect with a VNC client to any of these IPs:\n[bold cyan]{', '.join(host_ips)}[/] on port [bold cyan]{vnc_port}[/]"
                console.print(Panel(vnc_instructions, title="VNC Mode Enabled", border_style="cyan"))
            else:
                console.print(Panel("[bold red]FINAL WARNING: HOST SCREEN WILL GO BLACK[/]", title="PHYSICAL MONITOR MODE", border_style="red"))

            print_header("Preparing Passthrough Devices")
            for device_addr in passthrough_devices:
                current_driver = get_pci_device_driver(device_addr)
                if current_driver != 'vfio-pci':
                    if not questionary.confirm(f"Unbind device {device_addr} from '{current_driver}' and bind to vfio-pci? This is the final step.").ask():
                        raise KeyboardInterrupt("Passthrough declined by user.")
                    if bind_pci_device_to_driver(device_addr, 'vfio-pci'):
                        bound_devices[device_addr] = current_driver
                    else:
                        raise RuntimeError(f"Failed to bind device {device_addr} to vfio-pci.")

        # --- Execution Stage ---
        print_header("Launching VM")
        with open(paths['session_info'], 'w') as f: f.write(str(ssh_port))
        debug_mode = True if passthrough_devices else questionary.confirm("Launch in Debug Mode?").ask()

        if debug_mode:
            print_info("Running QEMU command in this terminal. Press Ctrl+C to exit.")
            console.print(f"\n[blue]▶️  Executing: {' '.join(qemu_cmd)}[/]\n")
            subprocess.run(qemu_cmd, check=False)
        else:
            launch_in_new_terminal_and_wait([("Run macOS VM", qemu_cmd)])

    except (KeyboardInterrupt, RuntimeError) as e:
        if isinstance(e, RuntimeError): print_error(f"ERROR: {e}")
        print_info("\nVM launch aborted.")
    finally:
        # --- Automated Cleanup Stage ---
        if firewall_rule_managed:
            manage_firewall_rule(vnc_port, action='remove')
        if bound_devices:
            print_header("VM Session Ended: Reverting Passthrough Devices")
            for addr, original_driver in bound_devices.items():
                if questionary.confirm(f"Return device {addr} to its original driver '{original_driver}'?").ask():
                    bind_pci_device_to_driver(addr, original_driver)
                else:
                    print_info(f"Device {addr} will remain bound to 'vfio-pci'.")

    
def nuke_and_recreate_macos_vm():
    """
    Provides options to reset a VM's identity or perform a factory reset of the macOS installation.
    """
    clear_screen()
    print_header("Nuke / Reset VM")
    vm_name = select_vm("nuke or reset")
    if not vm_name:
        return

    if is_vm_running(vm_name):
        print_error(f"VM '{vm_name}' is currently running.")
        print_warning("This operation cannot be performed on a running VM because it will cause a QEMU process conflict.")
        print_info("Please stop the VM first and then run this option again.")
        return # Stop execution immediately    

    # --- Step 1: Ask the user what level of "nuke" they want ---
    clear_screen()
    print_header(f"Nuke Options for '{vm_name}'")

    nuke_choice = questionary.select(
        "What do you want to do?",
        choices=[
            questionary.Choice(
                title="1. Regenerate Identity Only (Safe, for iServices)",
                value="identity"
            ),
            questionary.Choice(
                title="2. Factory Reset macOS (Deletes users & data, keeps OS)",
                value="factory_reset"
            ),
            questionary.Separator(),
            questionary.Choice("Cancel", value="cancel")
        ],
        use_indicator=True
    ).ask()

    if nuke_choice is None or nuke_choice == "cancel":
        print_info("Operation cancelled.")
        return

    paths = _get_vm_paths(vm_name)
    
    # --- Step 2: Handle the chosen action ---
    if nuke_choice == "identity":
        console.print(
            Panel(
                "[bold]This will perform the following actions:[/]\n\n"
                "1. [red]DELETE[/] the current `OpenCore.qcow2` bootloader image.\n"
                "2. [cyan]GENERATE[/] a new, unique SMBIOS identity (Serial, UUID, etc.).\n"
                "3. [green]CREATE[/] a new `OpenCore.qcow2` with the new identity.\n\n"
                "[bold yellow]Your main `macOS.qcow2` disk (your macOS installation, files, and apps) WILL NOT BE DELETED.[/]",
                title="[bold yellow]⚠️ Confirm: Regenerate Identity Only[/]",
                border_style="yellow"
            )
        )
        if not questionary.confirm("This is useful for iMessage/FaceTime issues. Do you want to proceed?").ask():
            print_info("Operation cancelled.")
            return

        if os.path.exists(paths['opencore']):
            if not remove_file(paths['opencore'], as_root=True): return
        
        smbios_model = _get_smbios_model_choice()
        if not smbios_model: return
        smbios_data = _generate_smbios(smbios_model)
        if not smbios_data: return
        
        vm_config = {}
        if os.path.exists(paths['config']):
            try:
                with open(paths['config'], 'r', encoding='utf-8') as f:
                    vm_config = json.load(f)
            except (json.JSONDecodeError, IOError):
                print_error("Could not load existing config.json, will create a new one.")

        if _build_and_patch_opencore_image(vm_name, smbios_data, vm_config):
            # Save the updated config which now contains the new mac_addr
            with open(paths['config'], 'w', encoding='utf-8') as f:
                json.dump(vm_config, f, indent=4)
            print_success(f"\n✅ Identity for '{vm_name}' has been successfully recreated.")
        else:
            print_error("Failed to rebuild OpenCore. The VM may be unbootable.")

    elif nuke_choice == "factory_reset":
        console.print(
            Panel(
                "[bold red]!!! DATA LOSS WARNING !!![/]\n\n"
                "This will mount the `macOS.qcow2` disk and [red]DELETE[/] all user accounts and their home folders (`/Users/*`).\n\n"
                "✅ The core macOS installation and system applications will be preserved.\n"
                "❌ All personal files, documents, downloads, and installed user apps will be [bold]PERMANENTLY DELETED[/].\n\n"
                "The next time you boot the VM, you will be greeted by the macOS Setup Assistant to create a new user.",
                title="[bold red]🔥 Confirm: Factory Reset macOS 🔥[/]",
                border_style="red"
            )
        )
        if not questionary.confirm("Are you absolutely sure you want to proceed?").ask():
            print_info("Operation cancelled.")
            return

        # --- This is the simple, direct logic ---
        if not is_apfs_support_enabled():
            print_error("APFS support is not available or libguestfs is not configured correctly.")
            print_error("Please ensure you have run 'sudo guestfish -a /dev/null' at least once after installing/reinstalling guestfs-tools.")
            return

        temp_mount_point = tempfile.mkdtemp(prefix=f"glint_{vm_name}_reset_")
        try:
            print_header("Performing Factory Reset")
            
            print_info("Inspecting VM disk for the macOS data partition...")
            fs_list_output = run_command_live(
                ['sudo', 'virt-filesystems', '--long', '-a', paths['main_disk']],
                quiet=True
            )
            if fs_list_output is None:
                raise RuntimeError("Failed to inspect filesystems on the VM disk.")

            data_partition = next((line.split()[0] for line in fs_list_output.strip().splitlines() if 'apfs' in line), None)

            if not data_partition:
                raise RuntimeError("Could not find any APFS partitions on the disk.")
            
            print_success(f"Found macOS data partition: [cyan]{data_partition}[/]")
            
            print_info(f"Mounting '{data_partition}' from the VM disk at '{temp_mount_point}'...")
            # Simple, automatic guestmount call. We add --backend=appliance as a failsafe.
            guestmount_cmd = ["guestmount", "--backend=appliance", "-a", paths['main_disk'], "-m", data_partition, temp_mount_point]
            if run_command_live(guestmount_cmd, as_root=True, check=True) is None:
                raise RuntimeError("Failed to mount the VM disk partition automatically.")

            # --- The Surgical Deletion ---
            print_info("Deleting user accounts and data...")
            
            users_dir = os.path.join(temp_mount_point, "Users")
            if os.path.isdir(users_dir):
                for item in os.listdir(users_dir):
                    if item not in ["Shared", ".localized"]:
                        item_path = os.path.join(users_dir, item)
                        print_info(f"  - Removing: {item_path}")
                        if run_command_live(['rm', '-rf', item_path], as_root=True, check=True, quiet=True) is None:
                            raise RuntimeError(f"Failed to remove {item}.")
            
            db_file_path = os.path.join(temp_mount_point, "private", "var", "db", ".AppleSetupDone")
            if os.path.exists(db_file_path):
                print_info("  - Removing '.AppleSetupDone' flag to trigger Setup Assistant.")
                if run_command_live(['rm', '-f', db_file_path], as_root=True, check=True, quiet=True) is None:
                     raise RuntimeError("Failed to remove the setup flag.")

            print_success("\n✅ Factory Reset Complete.")
            print_info("The VM will now run the Setup Assistant on next boot.")

        except Exception as e:
            print_error(f"An error occurred during the factory reset: {e}")
        finally:
            # --- Unmount and Cleanup ---
            print_info("Unmounting disk and cleaning up...")
            run_guestfs_command(["guestunmount", temp_mount_point], check=False, quiet=True)
            if os.path.exists(temp_mount_point):
                shutil.rmtree(temp_mount_point, ignore_errors=True)


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
    result = questionary.text(f"To confirm, please type the name of the VM ({vm_name}):").ask()
    if result is None:
        print_info("Deletion cancelled.")
        return
    confirm = result.strip()
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

    # --- Automated NBD Module Handling ---
    print_info("Ensuring NBD kernel module is loaded...")
    try:
        # First, try to load the module automatically.
        result = subprocess.run(['sudo', 'modprobe', 'nbd'], capture_output=True, text=True, check=False)
        
        if result.returncode != 0:
            stderr = result.stderr.lower()
            if 'module nbd not found' in stderr:
                print_error("FATAL: The 'nbd' kernel module is not installed for your running kernel.")
                print_info("This is the root cause. To fix this, your system needs a full update and a reboot.")
                print_warning("Recommended Action: Close Glint, then run these two commands in your terminal:")
                console.print("  [bold]1. sudo pacman -Syu[/]")
                console.print("  [bold]2. sudo reboot[/]")
                return
            else:
                print_error("Failed to load the 'nbd' kernel module for an unknown reason.")
                print_error(result.stderr)
                return

        print_success("NBD module is loaded.")
        
    except FileNotFoundError:
        print_error("The 'modprobe' command was not found. Please ensure kmod/systemd is installed correctly.")
        return

    # Now that we are sure the module is loaded, we can look for a device.
    nbd_device = _find_available_nbd()
    if not nbd_device:
        print_error("NBD module is loaded, but no available /dev/nbdX device was found.")
        print_info("This is unusual. A reboot after running 'sudo pacman -Syu' may be required.")
        return
    # --- END OF NBD HANDLING ---

    #
    # --- THIS BLOCK IS NOW CORRECTLY INDENTED ---
    #
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
        error_message = f"An error occurred during the mounting process: {str(e)}"
        print_error(error_message)
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

def configure_display_resolution():
    """Allows the user to set or remove a custom display resolution for a VM."""
    clear_screen()
    print_header("Configure VM Display Resolution")
    vm_name = select_vm("configure resolution for")
    if not vm_name:
        return

    paths = _get_vm_paths(vm_name)
    config_path = paths['config']
    vm_config = {}
    current_res = "Default"
    
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            vm_config = json.load(f)
        current_res = vm_config.get('resolution', 'Default')
    
    print_info(f"Current resolution for '{vm_name}' is set to: [bold cyan]{current_res}[/]")

    from core_utils import get_host_screen_resolution
    native_res = get_host_screen_resolution()
    
    choices = []
    if native_res:
        choices.append(f"Use Host Native Resolution ({native_res})")
    choices.extend([
        "Enter Custom Resolution (e.g., 1920x1080)",
        "Remove Custom Resolution (Revert to Default)",
        "Cancel"
    ])
    
    choice = select_from_list(choices, "Select an option")
    
    new_res = None
    if choice is None or choice == "Cancel":
        print_info("Operation cancelled.")
        return
    elif "Host Native" in choice:
        new_res = native_res
    elif "Custom" in choice:
        new_res = questionary.text("Enter resolution (format: WIDTHxHEIGHT):").ask()
    elif "Remove" in choice:
        vm_config.pop('resolution', None)
        new_res = None # Explicitly set to None to trigger rebuild
        print_info("Removing custom resolution setting.")

    if new_res:
        if not re.match(r'^\d+x\d+$', new_res):
            print_error("Invalid format. Please use WIDTHxHEIGHT (e.g., 2560x1440).")
            return
        vm_config['resolution'] = new_res
        print_success(f"Set resolution to {new_res}.")
        
    # Save the config file
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(vm_config, f, indent=4)
    print_success("Saved configuration.")
    
    # Rebuild OpenCore to apply the changes
    print_header("Rebuilding OpenCore Image to Apply Resolution")
    print_info("A new SMBIOS is required for the OpenCore rebuild.")
    smbios_model = _get_smbios_model_choice()
    if not smbios_model: return
    smbios_data = _generate_smbios(smbios_model)
    if not smbios_data: return
    
    if _build_and_patch_opencore_image(vm_name, smbios_data, vm_config):
        # Save the updated config which now contains the new mac_addr from the rebuild
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(vm_config, f, indent=4)
        print_success("OpenCore image has been updated with the new resolution settings.")
    else:
        print_error("Failed to rebuild OpenCore image.")

def run_host_setup_wizard():
    """
    An intelligent, automated wizard to help users configure their host for IOMMU passthrough.
    It incorporates robust parsing, module automation, bootloader detection, and safe recovery options.
    """
    clear_screen()
    print_header("Host Passthrough Setup Wizard")
    
    console.print(Panel(
        "[bold red]!!! WARNING !!![/]\n\n"
        "This wizard will attempt to modify critical system files related to booting. "
        "An incorrect modification can potentially make your system unbootable.\n\n"
        "A backup will be created, but it is [bold]STRONGLY RECOMMENDED[/] that you have a bootable USB drive or other recovery media available.",
        title="[bold yellow]CRITICAL: READ BEFORE PROCEEDING[/]", border_style="red"
    ))

    if not questionary.confirm("Do you understand the risks and wish to proceed?").ask():
        print_info("Setup cancelled by user.")
        return

    # --- Step 1: Intelligent System Analysis ---
    print_header("1. Analyzing Host System")
    
    # Check IOMMU (VT-d/AMD-Vi) status first
    iommu_enabled = is_iommu_active()
    if iommu_enabled:
        print_success("IOMMU (VT-d / AMD-Vi) is already active on your system.")
    else:
        print_warning("IOMMU (VT-d / AMD-Vi) is not detected. This must be enabled in your BIOS/UEFI.")

    # Check for bootloader type and CPU
    cpu_vendor = get_cpu_vendor()
    iommu_param = "intel_iommu=on" if cpu_vendor == "Intel" else "amd_iommu=on"
    grub_cfg_path = "/etc/default/grub"
    
    if not os.path.exists(grub_cfg_path):
        # Handle non-GRUB systems gracefully
        print_warning("GRUB bootloader not found. This wizard can only automate GRUB-based systems.")
        if os.path.exists("/boot/loader/loader.conf"):
            print_info("Detected 'systemd-boot'. To enable IOMMU, you must manually add "
                       f"`{iommu_param}` to the 'options' line in your boot entry file.")
        return

    # --- Step 2: Propose Comprehensive, Context-Aware Changes ---
    print_header("2. Reviewing Proposed Changes")
    
    changes_needed = []
    # Only propose GRUB changes if IOMMU is NOT already enabled
    if not iommu_enabled:
        changes_needed.append(f"Add `[bold]{iommu_param}[/]` to the kernel boot options in `[bold]{grub_cfg_path}[/]`.")
    
    vfio_conf_path = "/etc/modules-load.d/glint-vfio.conf"
    if not os.path.exists(vfio_conf_path):
        changes_needed.append("Configure VFIO modules to load automatically on boot.")
    
    if not changes_needed:
        print_success("No configuration changes needed. Your system appears to be ready.")
        return

    for change in changes_needed:
        print_info(f"  - {change}")

    if not questionary.confirm("Are you ready to apply these changes to your system?").ask():
        print_info("Setup cancelled by user.")
        return

    # --- Step 3: Execute Changes with Enhanced Safety and Error Handling ---
    print_header("3. Applying Configuration")
    backup_path = f"{grub_cfg_path}.glint.bak.{int(time.time())}"
    original_grub_content = None
    
    try:
        if not iommu_enabled:
            print_info(f"Backing up and modifying {grub_cfg_path}...")
            original_grub_content = run_command_live(['cat', grub_cfg_path], as_root=True, quiet=True)
            if run_command_live(['cp', grub_cfg_path, backup_path], as_root=True, check=True, quiet=True) is None:
                raise RuntimeError("Failed to create GRUB config backup.")

            grub_content = original_grub_content
            pattern = re.compile(r'^(GRUB_CMDLINE_LINUX_DEFAULT=(["\']))(.*?)\2', re.MULTILINE)
            match = pattern.search(grub_content)
            if not match:
                raise ValueError("Could not find a valid GRUB_CMDLINE_LINUX_DEFAULT line to modify.")
            
            new_grub_content = pattern.sub(rf'\1\3 {iommu_param}\2', grub_content)
            
            temp_grub_path = f"/tmp/grub_temp_{os.getpid()}"
            with open(temp_grub_path, 'w', encoding='utf-8') as f: f.write(new_grub_content)
            if run_command_live(['mv', temp_grub_path, grub_cfg_path], as_root=True, check=True, quiet=True) is None:
                raise RuntimeError("Failed to write updated GRUB configuration.")
            print_success(f"Successfully updated '{grub_cfg_path}'.")

        if not os.path.exists(vfio_conf_path):
            print_info(f"Creating VFIO module configuration at {vfio_conf_path}...")
            vfio_modules = "vfio\nvfio_iommu_type1\nvfio_pci\n"
            temp_vfio_path = f"/tmp/vfio_temp_{os.getpid()}"
            with open(temp_vfio_path, 'w', encoding='utf-8') as f: f.write(vfio_modules)
            if run_command_live(['mv', temp_vfio_path, vfio_conf_path], as_root=True, check=True, quiet=True) is None:
                raise RuntimeError("Failed to create VFIO module configuration file.")
            print_success("VFIO modules configured to load on boot.")

        distro = detect_distro()
        if distro in ["ubuntu", "debian", "pop"]:
            if run_command_live(["update-grub"], as_root=True, check=True) is None:
                raise RuntimeError("The 'update-grub' command failed.")
            if run_command_live(["update-initramfs", "-u"], as_root=True, check=True) is None:
                raise RuntimeError("The 'update-initramfs' command failed.")
        elif distro in ["arch", "manjaro", "endeavouros"]:
            if run_command_live(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"], as_root=True, check=True) is None:
                raise RuntimeError("The 'grub-mkconfig' command failed.")
            if shutil.which("mkinitcpio") and run_command_live(["mkinitcpio", "-P"], as_root=True, check=True) is None:
                 raise RuntimeError("The 'mkinitcpio' command failed.")
        else:
            print_warning("Unsupported distro. Please run `update-grub` and/or `update-initramfs` manually.")

    except Exception as e:
        print_error(f"An unexpected error occurred: {e}")
        print_warning(f"Configuration failed. A backup was made at {backup_path}")
        if original_grub_content and questionary.confirm("Would you like to restore the GRUB config from backup now?").ask():
            try:
                temp_restore_path = f"/tmp/grub_restore_{os.getpid()}"
                with open(temp_restore_path, 'w', encoding='utf-8') as f: f.write(original_grub_content)
                if run_command_live(['mv', temp_restore_path, grub_cfg_path], as_root=True, check=True, quiet=True) is not None:
                    print_success("Successfully restored GRUB configuration.")
                else:
                    print_error(f"Failed to restore automatically. Please restore from {backup_path} manually.")
            except Exception as restore_e:
                print_error(f"Failed to restore backup: {restore_e}")
        return

    # --- Step 4: Final Dynamic Instructions ---
    print_header("✅ Host Configuration Complete!")
    if not iommu_enabled:
        console.print(Panel(
            "1. [bold]REBOOT YOUR COMPUTER.[/] The changes will only apply after a full reboot.\n\n"
            "2. [bold]ENTER YOUR BIOS/UEFI SETUP.[/] Find and [bold]ENABLE[/] the IOMMU setting:\n"
            "   - For Intel: [bold]VT-d[/] or [bold]Intel (R) Virtualization Technology for Directed I/O[/]\n"
            "   - For AMD: [bold]AMD-Vi[/] or [bold]AMD I/O Virtualization Technology[/]\n\n"
            "3. [bold]RERUN GLINT.[/] After rebooting, the Passthrough menu check should pass.",
            title="[bold green]CRITICAL: Final Manual Steps[/]", border_style="green"
        ))
    else:
        print_info("Your system appears ready for passthrough. You may need to reboot for all changes to take effect.")

def _revert_passthrough_to_standard():
    """Reverts a VM's configuration from GPU passthrough back to standard virtual graphics."""
    clear_screen()
    print_header("Revert Passthrough to Standard Graphics")
    
    vm_name = select_vm("revert from passthrough", running_only=False)
    if not vm_name:
        return

    paths = _get_vm_paths(vm_name)
    config_path = paths['config']
    
    if not os.path.exists(config_path):
        print_error(f"No configuration file found for VM '{vm_name}'. Cannot revert.")
        return

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            vm_config = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print_error(f"Could not read config file for '{vm_name}': {e}")
        return

    if 'passthrough_devices' not in vm_config or not vm_config['passthrough_devices']:
        print_info(f"VM '{vm_name}' is not currently configured for passthrough. Nothing to do.")
        return

    print_warning(f"This will remove the GPU passthrough configuration for '{vm_name}' and restore it to use standard virtual graphics.")
    if not questionary.confirm("Are you sure you want to proceed?").ask():
        print_info("Revert operation cancelled.")
        return

    # Remove the passthrough-specific keys from the configuration
    vm_config.pop('passthrough_devices', None)
    vm_config.pop('use_vnc', None)
    vm_config.pop('vnc_port', None)
    
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(vm_config, f, indent=4)
        print_success("Removed passthrough configuration from config.json.")
    except IOError as e:
        print_error(f"Failed to save updated configuration: {e}")
        return

    # Offer to rebuild the OpenCore image, which is highly recommended
    if questionary.confirm(
        "Rebuilding the OpenCore image is recommended to ensure compatibility with standard graphics. Rebuild now?"
    ).ask():
        print_info("To rebuild OpenCore, we need to regenerate the SMBIOS data.")
        smbios_model = _get_smbios_model_choice()
        if not smbios_model:
            print_warning("SMBIOS selection cancelled. OpenCore image was not rebuilt.")
            return

        smbios_data = _generate_smbios(smbios_model)
        if not smbios_data:
            print_error("Failed to generate SMBIOS data. Cannot rebuild OpenCore.")
            return

        # Rebuild the image WITHOUT any iGPU patches
        if _build_and_patch_opencore_image(vm_name, smbios_data, igpu_patch_properties=None):
            print_success("OpenCore image successfully rebuilt for standard graphics.")
        else:
            print_error("Failed to rebuild OpenCore image. The VM might not boot correctly.")

    print_success(f"\nVM '{vm_name}' has been successfully reverted to standard graphics mode.")
    print_info("You can now run the VM normally.")

def passthrough_menu():
    """Menu for GPU passthrough and performance settings with enhanced safety checks."""
    clear_screen()
    print_header("Passthrough & Performance")

    # --- Host Readiness Check ---
    if not is_vfio_module_loaded():
        # Proactively try to load the module. This will succeed if IOMMU is already enabled.
        if run_command_live(['modprobe', 'vfio-pci'], as_root=True, check=False, quiet=True) is None:
            # If modprobe fails, it's a real configuration issue.
            print_warning("The 'vfio-pci' kernel module could not be loaded.")
            print_info("This is a strong sign that IOMMU (VT-d/AMD-Vi) is not enabled on your system.")
            if questionary.confirm("Run the Host Setup Wizard to attempt to fix this?").ask():
                run_host_setup_wizard()
            return
        else:
            print_success("Successfully loaded 'vfio-pci' module for this session.")
    
    while True:
        clear_screen()
        print_header("Passthrough & Performance Menu")
        choice = questionary.select(
            "Select an action:",
            choices=[
                "1. Configure a VM for GPU Passthrough",
                "2. Revert a VM from Passthrough to Standard Graphics",
                "3. Run Host Setup Wizard (for first-time setup)",
                "4. Return to macOS Menu"
            ]
        ).ask()

        if choice is None or choice.startswith("4."):
            break
        
        action_taken = True
        if choice.startswith("1."):
            _configure_passthrough_for_vm()
        elif choice.startswith("2."):
            _revert_passthrough_to_standard()
        elif choice.startswith("3."):
            run_host_setup_wizard()
        else:
            action_taken = False

        if action_taken:
            questionary.text("\nPress Enter to return to the passthrough menu...").ask()

def _configure_passthrough_for_vm():
    """Menu for GPU passthrough and performance settings with enhanced safety checks."""
    
    # --- Main Configuration Logic ---
    print_header("⚠️ IMPORTANT: PLEASE READ CAREFULLY ⚠️")
    warning_text = """
[bold]1. Potential for Instability:[/bold]
   Incorrectly passing through a device (especially one your host is actively using) can lead to system instability, a black screen on your host, or a forced hard reboot.

[bold]2. Primary GPU Warning:[/bold]
   Passing through your primary/boot GPU is an advanced procedure. If you do this without a secondary GPU for your host, you will lose display output on the host.
"""
    console.print(warning_text)
    
    confirmation = questionary.text(
        "This is an advanced feature. Type 'understand the risks' to continue:"
    ).ask()
    if confirmation != "understand the risks":
        print_error("Confirmation failed. Aborting.")
        return

    vms_dir = CONFIG['VMS_DIR_MACOS']
    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])
    if not vm_list:
        print_error("No macOS VMs found.")
        return

    vm_name = select_from_list(vm_list, "Choose a VM to configure")
    if not vm_name: return

    paths = _get_vm_paths(vm_name)
    print_header(f"Select GPU for '{vm_name}'")
    gpus = get_host_gpus()
    if not gpus:
        print_error("No GPUs found on the host system."); return

    active_gpu_pci = get_active_gpu_pci_address()
    if active_gpu_pci:
        print_info(f"Detected active host GPU: {active_gpu_pci}. It will be marked.")
        for gpu in gpus:
            if gpu['pci_address'] == active_gpu_pci:
                gpu['display_name'] += " [bold yellow](Active Host GPU)[/bold yellow]"

    selected_gpu = select_from_list(gpus, "Select a GPU to pass through", display_key='display_name')
    if not selected_gpu: return

    # --- Hybrid Laptop Safety Check ---
    is_hybrid = any(gpu['type'] == 'iGPU' for gpu in gpus) and any(gpu['type'] == 'dGPU' for gpu in gpus)
    use_vnc = False
    vnc_port = None
    
    if is_hybrid:
        print_warning("Hybrid laptop graphics detected (e.g., NVIDIA Optimus / AMD SmartShift).")
        print_info("On most laptops, only the dGPU can be passed through safely.")
    
    if is_hybrid and selected_gpu['type'] == 'iGPU' and selected_gpu['pci_address'] == active_gpu_pci:
        print_error("\nCRITICAL: You have selected the active iGPU on a hybrid laptop.")
        print_error("This action is nearly guaranteed to crash your host's display server.")
        
        vnc_choice = select_from_list([
            "Enable VNC to access the VM remotely (Recommended)",
            "Abort passthrough configuration"
        ], "How would you like to proceed?")

        if vnc_choice is None or "Abort" in vnc_choice:
            print_error("Passthrough configuration aborted for safety.")
            return
        
        use_vnc = True
        vnc_port = find_unused_port()
        print_success(f"VNC access will be enabled on host port {vnc_port}.")

    # --- macOS GPU Compatibility Vetting ---
    description = selected_gpu['description'].lower()
    if 'nvidia' in description:
        print_error("\nUnsupported GPU for macOS")
        console.print(Panel(
            "You have selected an [bold]NVIDIA GPU[/].\n\n"
            "macOS does not have drivers for modern NVIDIA GPUs (Maxwell/GTX 9xx series and newer). "
            "Attempting to pass this through will result in a black screen or no graphics acceleration inside the VM.",
            title="[bold red]Compatibility Error[/]", border_style="red"
        ))
        print_info("Please choose a supported AMD GPU or an Intel Integrated GPU.")
        return
    
    elif 'amd' in description or 'advanced micro devices' in description:
        print_success("Selected AMD GPU is compatible with macOS.")
    elif 'intel' in description:
        print_success("Selected Intel iGPU is compatible. Framebuffer patching will be required.")
    
    devices_to_pass = [selected_gpu['pci_address']]
    print_info("Checking for associated devices in the same IOMMU group...")
    other_devices = get_iommu_group_devices(selected_gpu['pci_address'])

    if other_devices:
        print_warning("The selected GPU is in an IOMMU group with other devices.")
        for addr in other_devices: console.print(f"  - {addr}")
        print_info("To ensure stability (e.g., for HDMI audio), all devices in the group should be passed through together.")
        if questionary.confirm("Add all associated devices to the passthrough list? (Recommended)").ask():
            devices_to_pass.extend(other_devices)
            print_success("All group devices will be passed to the VM.")
    else:
        print_info("No other devices found in the IOMMU group.")

    # --- iGPU Patching Workflow ---
    igpu_patch_properties = None
    if selected_gpu['type'] == 'iGPU':
        print_header("iGPU Framebuffer Patching")
        print_info("To enable graphics acceleration, we must apply a patch to make your iGPU appear as a compatible model.")
        
        profile_choice = select_from_list(list(KVM_IGPU_PATCHES.keys()), "Choose a compatible profile to apply")
        if not profile_choice:
            print_error("Profile selection cancelled. Aborting.")
            return
        
        igpu_patch_properties = {"PciRoot(0x0)/Pci(0x2,0x0)": KVM_IGPU_PATCHES[profile_choice]}
        
        print_success(f"Selected profile '{profile_choice}'. The iGPU will be patched accordingly.")
        if not questionary.confirm("This will rebuild the OpenCore image with these patches. Continue?").ask():
            return
    
    # --- Save Final Configuration ---
    vm_config = {}
    if os.path.exists(paths['config']):
        with open(paths['config'], 'r', encoding='utf-8') as f:
            vm_config = json.load(f)
            
    vm_config['passthrough_devices'] = devices_to_pass
    vm_config['use_vnc'] = use_vnc
    vm_config['vnc_port'] = vnc_port

    try:
        with open(paths['config'], 'w', encoding='utf-8') as f:
            json.dump(vm_config, f, indent=4)
        print_success(f"Saved passthrough configuration to {vm_name}'s config.")
    except (IOError, json.JSONDecodeError) as e:
        print_error(f"Could not update VM config: {e}")
        return

    if igpu_patch_properties:
        print_header("Rebuilding OpenCore for iGPU Passthrough")
        smbios_model = "iMac20,1" 
        print_info(f"Using SMBIOS model '{smbios_model}' which is known to be compatible with iGPU passthrough.")
        smbios_data = _generate_smbios(smbios_model)
        if not smbios_data:
            print_error("Failed to generate SMBIOS. Aborting.")
            return
        
        if _build_and_patch_opencore_image(vm_name, smbios_data, vm_config, igpu_patch_properties=igpu_patch_properties):
            # Save the updated config which now contains the new mac_addr
            with open(paths['config'], 'w', encoding='utf-8') as f:
                json.dump(vm_config, f, indent=4)
            print_success("OpenCore image rebuilt successfully for iGPU passthrough.")
        else:
            print_error("Failed to rebuild OpenCore image.")

    print_success(f"\nPassthrough has been successfully configured for '{vm_name}'.")
    print_info("You can now run the VM. The script will handle the GPU automatically at launch.")



def macos_vm_menu():
    """Main menu for macOS VM management."""
    if not check_macos_assets():
        questionary.text("Press Enter to return to the main menu...").ask()
        return
    while True:
        clear_screen()
        console.print("[bold]macOS VM Management[/]")
        console.rule(style="dim")
        choice = questionary.select(
            "Select an option",
            choices=[
                "1. Create New macOS VM",
                "2. Run Existing macOS VM",
                "3. Stop a Running VM",
                "4. Nuke & Recreate VM Identity",
                "5. Configure Display Resolution",
                "6. Mount EFI Partition (Advanced)",
                "7. Passthrough & Performance",
                "8. Transfer Files (SFTP)",
                "9. Delete macOS VM Completely",
                "10. Return to Main Menu",
            ]
        ).ask()
        action_taken = True
        if choice == "1. Create New macOS VM":
            create_new_macos_vm()
        elif choice == "2. Run Existing macOS VM":
            run_macos_vm()
        elif choice == "3. Stop a Running VM":
            stop_vm()
        elif choice == "4. Nuke & Recreate VM Identity":
            nuke_and_recreate_macos_vm()
        elif choice == "5. Configure Display Resolution":
            configure_display_resolution()
        elif choice == "6. Mount EFI Partition (Advanced)":
            mount_efi_partition()
        elif choice == "7. Passthrough & Performance":
            passthrough_menu()
        elif choice == "8. Transfer Files (SFTP)":
            vm_name = select_vm("Transfer Files with", running_only=True)
            if vm_name:
                vm_dir = _get_vm_paths(vm_name)['dir']
                transfer_files_menu(vm_name, "macos", vm_dir)
        elif choice == "9. Delete macOS VM Completely":
            delete_macos_vm()
        elif choice == "10. Return to Main Menu":
            break
        else:
            print_warning("Invalid option.")
            action_taken = False
        if action_taken and choice != "10. Return to Main Menu":
            questionary.text("\nPress Enter to return to the menu...").ask()
