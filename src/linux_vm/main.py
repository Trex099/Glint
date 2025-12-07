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
from datetime import datetime
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
    
    # Check for Tor (required for Privacy Mode)
    if not shutil.which('tor'):
        missing_pkgs.append(info['pkgs'].get('tor', 'tor'))

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
    Enhanced VM info retrieval using the new session manager.
    Maintains backward compatibility while providing better reliability.
    """
    try:
        from src.linux_vm.session_manager import get_session_manager
        session_manager = get_session_manager()
        
        session = session_manager.get_session_info(vm_name)
        if session:
            return {
                'pid': session.pid,
                'port': session.ssh_port,
                'uuid': session.uuid,
                'mac': session.mac_address,
                'start_time': session.start_time,
                'uptime': (datetime.now() - session.start_time).total_seconds() if session.start_time else 0
            }
        return None
        
    except ImportError:
        print_warning("Enhanced session manager not available, using fallback method.")
        # Fallback to original implementation
        return _get_running_vm_info_fallback(vm_name)
    except Exception as e:
        print_error(f"Error getting VM info: {e}")
        return _get_running_vm_info_fallback(vm_name)


def _get_running_vm_info_fallback(vm_name):
    """Fallback implementation for VM info retrieval"""
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
    """Enhanced VM running check using the new session manager."""
    try:
        from src.linux_vm.session_manager import get_session_manager
        session_manager = get_session_manager()
        return session_manager.is_vm_running(vm_name)
    except ImportError:
        # Fallback to original implementation
        return get_running_vm_info(vm_name) is not None
    except Exception as e:
        print_error(f"Error checking VM status: {e}")
        return get_running_vm_info(vm_name) is not None


def cleanup_stale_sessions():
    """Enhanced stale session cleanup using the new session manager."""
    try:
        from src.linux_vm.session_manager import get_session_manager
        session_manager = get_session_manager()
        cleaned_count = session_manager.cleanup_stale_sessions()
        if cleaned_count > 0:
            print_success(f"Cleaned up {cleaned_count} stale sessions")
        return cleaned_count
    except ImportError:
        print_warning("Enhanced session manager not available, using fallback cleanup.")
        return _cleanup_stale_sessions_fallback()
    except Exception as e:
        print_error(f"Error during session cleanup: {e}")
        return _cleanup_stale_sessions_fallback()


def _cleanup_stale_sessions_fallback():
    """Fallback implementation for stale session cleanup"""
    vms_dir = CONFIG['VMS_DIR_LINUX']
    if not os.path.isdir(vms_dir):
        return 0
    
    cleaned_count = 0
    for vm_name in os.listdir(vms_dir):
        if os.path.isdir(os.path.join(vms_dir, vm_name)):
            # This will trigger cleanup if the VM is not running
            if not get_running_vm_info(vm_name):
                cleaned_count += 1
    
    return cleaned_count


def stop_vm(vm_name=None, force=False):
    """
    Enhanced VM stopping with session manager integration
    """
    if not vm_name:
        vm_name = select_vm("Stop", running_only=True)
        if not vm_name:
            return
    
    try:
        from src.linux_vm.session_manager import get_session_manager
        session_manager = get_session_manager()
        
        if session_manager.stop_session(vm_name, force=force):
            print_success(f"Successfully stopped VM '{vm_name}'")
        else:
            print_error(f"Failed to stop VM '{vm_name}'")
            
    except ImportError:
        print_warning("Enhanced session manager not available, using fallback method.")
        _stop_vm_fallback(vm_name, force)
    except Exception as e:
        print_error(f"Error stopping VM '{vm_name}': {e}")
        _stop_vm_fallback(vm_name, force)


def _stop_vm_fallback(vm_name, force=False):
    """Fallback implementation for stopping VMs"""
    vm_info = get_running_vm_info(vm_name)
    if not vm_info:
        print_warning(f"VM '{vm_name}' is not running.")
        return
    
    pid = vm_info['pid']
    
    try:
        import signal
        
        if not force:
            # Try graceful shutdown first
            os.kill(pid, signal.SIGTERM)
            print_info(f"Sent SIGTERM to VM '{vm_name}' (PID: {pid})")
            
            # Wait up to 30 seconds for graceful shutdown
            for _ in range(30):
                try:
                    os.kill(pid, 0)  # Check if process still exists
                    time.sleep(1)
                except ProcessLookupError:
                    print_success(f"VM '{vm_name}' stopped gracefully")
                    return
            
            print_warning(f"VM '{vm_name}' did not respond to SIGTERM, using SIGKILL")
        
        # Force kill
        os.kill(pid, signal.SIGKILL)
        print_success(f"VM '{vm_name}' stopped forcefully")
        
    except ProcessLookupError:
        print_info(f"VM '{vm_name}' process was already terminated")
    except Exception as e:
        print_error(f"Error stopping VM '{vm_name}': {e}")
    finally:
        # Clean up session files
        paths = get_vm_paths(vm_name)
        for f in [paths['pid_file'], paths['session_info']]:
            if os.path.exists(f):
                remove_file(f)


def register_vm_session(vm_name, pid, ssh_port, uuid, mac_address, command_line=None):
    """
    Register a new VM session with the session manager
    """
    try:
        from src.linux_vm.session_manager import get_session_manager
        session_manager = get_session_manager()
        
        session = session_manager.create_session(
            vm_name=vm_name,
            pid=pid,
            ssh_port=ssh_port,
            uuid=uuid,
            mac_address=mac_address,
            command_line=command_line
        )
        
        print_success(f"Registered session for VM '{vm_name}' (PID: {pid})")
        return session
        
    except ImportError:
        print_warning("Enhanced session manager not available")
        return None
    except Exception as e:
        print_error(f"Failed to register session for VM '{vm_name}': {e}")
        return None


def get_vm_session_stats(vm_name):
    """
    Get detailed session statistics for a VM
    """
    try:
        from src.linux_vm.session_manager import get_session_manager
        session_manager = get_session_manager()
        
        stats = session_manager.get_session_stats(vm_name)
        return stats
        
    except ImportError:
        print_warning("Enhanced session manager not available")
        return None
    except Exception as e:
        print_error(f"Failed to get session stats for VM '{vm_name}': {e}")
        return None


def create_new_vm():
    """Enhanced VM creation with all advanced features."""
    clear_screen()
    print_header("Create New Linux VM - Enhanced")
    if not check_dependencies():
        return

    # Step 1: VM Name
    while True:
        result = questionary.text("Enter a short name for new VM (e.g., arch-kde):").ask()
        if result is None:
            print_info("VM creation cancelled.")
            return
        vm_name = result.strip()
        if not vm_name:
            continue
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

    print_info(f"Creating VM directory at: {paths['dir']}")
    os.makedirs(paths['shared_dir'], exist_ok=True)

    # Display IMPORTANT installation instructions EARLY so user knows what to expect
    from rich.panel import Panel
    
    instructions_text = (
        "[bold white]After you install your Linux and it prompts to restart:[/]\n"
        "   [bold cyan]→ Press Enter to remove installation media[/]\n"
        "   [bold green]→ The VM will SHUT DOWN[/] - [bold white]THIS IS EXPECTED![/]\n\n"
        "[dim]GLINT creates an overlay to enable Nuke & Reset.\n"
        "Just start the VM again from the menu after shutdown.[/]\n\n"
        "[bold magenta]💡 PRO TIP:[/] Anything installed BEFORE first shutdown\n"
        "goes into the base image and [bold white]survives Nuke & Reset![/]\n"
        "Use this to pre-install tools you always need.\n"
        "[dim](But be careful - unwanted stuff will persist too!)[/]"
    )
    
    console.print(Panel(
        instructions_text,
        title="[bold yellow]📋 IMPORTANT: Read Before Continuing[/]",
        border_style="yellow",
        expand=False
    ))
    console.print()

    # Step 2: Enhanced Storage Configuration
    print_header("Enhanced Storage Configuration")
    
    # Offer encryption option
    use_encryption = questionary.confirm(
        "🔐 Enable LUKS disk encryption? (Recommended for sensitive data)"
    ).ask()
    
    # Handle user cancellation
    if use_encryption is None:
        print_info("VM creation cancelled.")
        return
    
    encryption_config = None
    if use_encryption:
        try:
            from linux_vm.storage.encryption import EncryptionConfig
            
            passphrase = questionary.password("Enter encryption passphrase:").ask()
            if passphrase is None:
                print_info("VM creation cancelled.")
                return
            
            confirm_passphrase = questionary.password("Confirm passphrase:").ask()
            if confirm_passphrase is None:
                print_info("VM creation cancelled.")
                return
            
            if passphrase != confirm_passphrase:
                print_error("Passphrases don't match. Encryption disabled.")
                use_encryption = False
            else:
                encryption_config = EncryptionConfig(
                    passphrase=passphrase,
                    cipher="aes-xts-plain64",
                    key_size=512
                )
                print_success("✅ Encryption configured")
        except ImportError:
            print_warning("⚠️  LUKS encryption not available, continuing without encryption")
            use_encryption = False

    # Multi-disk configuration
    use_multi_disk = questionary.confirm(
        "💾 Configure additional disks? (For data separation or performance)"
    ).ask()
    
    # Handle user cancellation
    if use_multi_disk is None:
        print_info("VM creation cancelled.")
        return
    
    additional_disks = []
    if use_multi_disk:
        try:
            from linux_vm.storage.multi_disk import DiskConfig, DiskType
            
            while True:
                disk_name_result = questionary.text("Disk name (e.g., 'data', 'cache'):").ask()
                if disk_name_result is None:
                    print_info("VM creation cancelled.")
                    return
                disk_name = disk_name_result.strip()
                if not disk_name:
                    break
                    
                disk_size_result = questionary.text("Disk size (e.g., '50G', '100G'):").ask()
                if disk_size_result is None:
                    print_info("VM creation cancelled.")
                    return
                disk_size = disk_size_result.strip()
                if not disk_size:
                    disk_size = "20G"
                
                disk_type = questionary.select(
                    "Disk type:",
                    choices=[
                        questionary.Choice("Data (High capacity)", value=DiskType.DATA),
                        questionary.Choice("Cache (High performance)", value=DiskType.CACHE),
                        questionary.Choice("Backup (Reliable)", value=DiskType.BACKUP)
                    ]
                ).ask()
                
                disk_config = DiskConfig(
                    name=disk_name,
                    size=disk_size,
                    disk_type=disk_type,
                    encrypted=use_encryption
                )
                additional_disks.append(disk_config)
                
                if not questionary.confirm("Add another disk?").ask():
                    break
                    
            if additional_disks:
                print_success(f"✅ Configured {len(additional_disks)} additional disks")
        except ImportError:
            print_warning("⚠️  Multi-disk support not available")

    # Step 3: Basic VM Configuration
    disk = get_disk_size("Enter base disk size (GB)", CONFIG['BASE_DISK_SIZE'])
    if disk is None:
        print_info("VM creation cancelled.")
        return
    
    vm_settings = get_vm_config({"VM_MEM": CONFIG['VM_MEM'], "VM_CPU": CONFIG['VM_CPU']}, include_networking=True)
    if vm_settings is None:
        print_info("VM creation cancelled.")
        return
    
    # Add enhanced configuration
    vm_settings.update({
        'encryption_enabled': use_encryption,
        'multi_disk_enabled': len(additional_disks) > 0,
        'additional_disks': len(additional_disks),
        'created_with_enhancements': True
    })
    
    import json
    with open(paths['config'], 'w', encoding='utf-8') as f:
        json.dump(vm_settings, f, indent=4)
    print_success(f"✅ Saved enhanced configuration to {paths['config']}")
    
    # Show networking mode selection
    networking_mode = vm_settings.get('NETWORKING_MODE', 'nat')
    if networking_mode == 'bridged':
        print_info("🌐 Using bridged networking (direct network access)")
    else:
        print_info("🌐 Using NAT networking (isolated, with port forwarding)")
    
    # Privacy Mode option for VM creation
    enable_privacy_on_boot = False
    privacy_choice = questionary.confirm(
        "🔒 Enable Privacy Mode? (Routes all traffic through Tor)",
        default=False
    ).ask()
    
    if privacy_choice:
        try:
            from linux_vm.privacy_mode import check_tor_installed, show_privacy_mode_panel
            
            tor_installed, tor_msg = check_tor_installed()
            if not tor_installed:
                print_warning(f"⚠️  Privacy Mode requires Tor: {tor_msg}")
                print_info("Install Tor with: sudo apt install tor")
                print_info("Privacy Mode will be disabled for now, you can enable it later via Nuke & Boot.")
            else:
                show_privacy_mode_panel()
                confirm = questionary.confirm("Enable Privacy Mode for this VM?", default=False).ask()
                if confirm:
                    enable_privacy_on_boot = True
                    vm_settings['privacy_mode'] = True
                    # Update config with privacy mode
                    with open(paths['config'], 'w', encoding='utf-8') as f:
                        json.dump(vm_settings, f, indent=4)
                    print_success("✅ Privacy Mode will be enabled on boot")
                else:
                    print_info("Privacy Mode declined.")
        except ImportError as e:
            print_warning(f"Privacy Mode module not available: {e}")

    # Step 4: Generate Fresh System Identifiers
    print_header("Generating Unique System Identifiers")
    try:
        from linux_vm.uuid_manager import get_uuid_manager
        uuid_manager = get_uuid_manager()
        
        # Generate fresh identifiers for this VM
        identifiers = uuid_manager.generate_fresh_identifiers(vm_name, force_regenerate=True)
        
        # Reset UEFI variables for fresh boot environment
        uuid_manager.reset_uefi_variables(vm_name)
        
        # Create post-install script for setting identifiers inside VM
        uuid_manager.create_post_install_script(vm_name, identifiers)
        
        vm_ids = {'uuid': identifiers.vm_uuid, 'mac': identifiers.mac_address}
        
        print_success("✅ Generated unique system identifiers:")
        print_info(f"   VM UUID: {identifiers.vm_uuid}")
        print_info(f"   MAC Address: {identifiers.mac_address}")
        print_info(f"   Machine ID: {identifiers.machine_id}")
        print_info(f"   Disk UUID: {identifiers.disk_uuid}")
        
    except ImportError:
        print_warning("⚠️  Enhanced UUID manager not available, using basic generation")
        # Fallback to basic generation
        mac_addr = f"52:54:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"
        vm_ids = {'uuid': str(uuid.uuid4()), 'mac': mac_addr}
        identifiers = None

    ssh_port = find_unused_port()
    print_info(f"SSH will be available on host port {ssh_port}")
    with open(paths['session_info'], 'w', encoding='utf-8') as f:
        f.write(str(ssh_port))

    # Step 5: Create storage with enhancements
    commands_to_run = []
    
    # UEFI setup
    uefi_vars_path = find_first_existing_path(CONFIG['UEFI_VARS_PATHS'])
    if not uefi_vars_path:
        print_error("Could not find a valid UEFI VARS template file. Cannot proceed.")
        return
    
    commands_to_run.append(("Preparing UEFI seed", ["cp", uefi_vars_path, paths['seed']]))
    
    # Create base disk (with encryption if enabled)
    if use_encryption and encryption_config:
        # Create encrypted base disk using a temporary key file
        encrypted_path = paths['base'].replace('.qcow2', '_encrypted.qcow2')
        
        # Store the passphrase securely using SecurePassphraseManager
        try:
            from src.linux_vm.storage.secure_passphrase import get_passphrase_manager
            passphrase_manager = get_passphrase_manager(vm_name, paths['dir'])
            passphrase_manager.store_passphrase(encryption_config.passphrase)
            print_success("Passphrase stored securely")
        except Exception as e:
            print_warning(f"Could not store passphrase in secure storage: {e}")
            # Fallback will be handled by the manager on next retrieval
        
        # For LUKS encryption, we need to handle the interactive prompts properly
        print(f"▶️  Creating {disk} encrypted base image")
        
        # First, let's create a regular disk and then convert it to encrypted
        # This approach is more reliable than trying to handle interactive prompts
        temp_disk_path = paths['base'].replace('.qcow2', '_temp.qcow2')
        
        try:
            # Step 1: Create a regular qcow2 disk
            print(f"▶️  Creating temporary disk: {temp_disk_path}")
            result = subprocess.run([
                "qemu-img", "create", "-f", "qcow2", temp_disk_path, disk
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                raise Exception(f"Failed to create temporary disk: {result.stderr}")
            
            # Step 2: Convert to encrypted format using a password file
            print(f"▶️  Converting to encrypted format: {encrypted_path}")
            
            # Create a temporary password file
            temp_pass_file = os.path.join(paths['dir'], '.temp_pass')
            with open(temp_pass_file, 'w', encoding='utf-8') as f:
                f.write(encryption_config.passphrase)
            os.chmod(temp_pass_file, 0o600)
            
            # Use qemu-img convert with password file
            convert_cmd = [
                "qemu-img", "convert", "-f", "qcow2", "-O", "qcow2",
                "-o", "encrypt.format=luks,encrypt.key-secret=sec0",
                "--object", f"secret,id=sec0,file={temp_pass_file}",
                temp_disk_path, encrypted_path
            ]
            
            result = subprocess.run(convert_cmd, capture_output=True, text=True)
            
            # Clean up temporary files
            os.unlink(temp_pass_file)
            os.unlink(temp_disk_path)
            
            if result.returncode == 0:
                print(f"✅ Successfully created encrypted disk: {encrypted_path}")
            else:
                print("❌ Failed to convert to encrypted format")
                print(f"Error: {result.stderr}")
                # Fallback: use the temporary disk as unencrypted
                os.rename(temp_disk_path, paths['base'])
                print("⚠️  Using unencrypted disk as fallback")
                use_encryption = False
                encryption_config = None
                
        except Exception as e:
            print(f"❌ Exception creating encrypted disk: {e}")
            # Clean up any temporary files
            for temp_file in [temp_disk_path, os.path.join(paths['dir'], '.temp_pass')]:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            
            print("⚠️  Creating unencrypted disk as fallback")
            commands_to_run.append((
                f"Creating {disk} base image (unencrypted fallback)", 
                ["qemu-img", "create", "-f", "qcow2", paths['base'], disk]
            ))
            use_encryption = False
            encryption_config = None
        
        print_info("🔐 Base disk will be encrypted with LUKS")
    else:
        commands_to_run.append((
            f"Creating {disk} base image", 
            ["qemu-img", "create", "-f", "qcow2", paths['base'], disk]
        ))
    
    # Create additional disks
    if additional_disks:
        for i, disk_config in enumerate(additional_disks):
            disk_path = os.path.join(paths['dir'], f"{disk_config.name}.qcow2")
            if disk_config.encrypted and encryption_config:
                # Use same two-step approach as base disk for encryption
                temp_additional_path = os.path.join(paths['dir'], f"{disk_config.name}_temp.qcow2")
                encrypted_additional_path = disk_path
                
                print(f"▶️  Creating encrypted {disk_config.name} disk ({disk_config.size})")
                
                # Step 1: Create temporary unencrypted disk
                result = subprocess.run(
                    ["qemu-img", "create", "-f", "qcow2", temp_additional_path, disk_config.size],
                    capture_output=True, text=True
                )
                
                if result.returncode == 0:
                    # Step 2: Convert to encrypted with password file
                    pass_file_path = os.path.join(paths['dir'], '.temp_pass')
                    with open(pass_file_path, 'w') as pf:
                        pf.write(encryption_config.passphrase)
                    
                    result = subprocess.run([
                        "qemu-img", "convert",
                        "--object", f"secret,id=sec0,file={pass_file_path}",
                        "--image-opts", "-O", "qcow2",
                        "-o", "encrypt.format=luks,encrypt.key-secret=sec0",
                        f"driver=qcow2,file.driver=file,file.filename={temp_additional_path}",
                        encrypted_additional_path
                    ], capture_output=True, text=True)
                    
                    # Clean up temp file
                    if os.path.exists(temp_additional_path):
                        os.unlink(temp_additional_path)
                    if os.path.exists(pass_file_path):
                        os.unlink(pass_file_path)
                    
                    if result.returncode == 0:
                        print_success(f"✅ Created encrypted disk: {disk_config.name}")
                    else:
                        print_warning(f"⚠️  Failed to encrypt {disk_config.name}, creating unencrypted")
                        subprocess.run(["qemu-img", "create", "-f", "qcow2", disk_path, disk_config.size])
                else:
                    print_warning(f"⚠️  Failed to create {disk_config.name}")
            else:
                commands_to_run.append((
                    f"Creating {disk_config.name} disk ({disk_config.size})",
                    ["qemu-img", "create", "-f", "qcow2", disk_path, disk_config.size]
                ))

    # Step 6: Generate enhanced QEMU command
    qemu_cmd = _get_enhanced_qemu_command(vm_name, vm_settings, {}, vm_ids, find_host_dns(), ssh_port, 
                                        iso_path=iso_path, encryption_config=encryption_config, 
                                        additional_disks=additional_disks, identifiers=identifiers)
    
    commands_to_run.append(("Booting enhanced VM from ISO", qemu_cmd))

    # Step 7: Launch VM
    print_header("VM Launch Options")
    console.print("🚀 [bold green]Enhanced VM Ready![/bold green]")
    if use_encryption:
        console.print("🔐 [yellow]Encryption: Enabled[/yellow]")
    if additional_disks:
        console.print(f"💾 [blue]Additional Disks: {len(additional_disks)}[/blue]")
    if identifiers:
        console.print("🆔 [green]Unique System Identifiers: Generated[/green]")
    
    # Brief reminder (full instructions were shown earlier)
    console.print("\n[dim]📋 Remember: After installation, the VM will shut down to create the overlay.[/dim]")
    
    debug_mode = questionary.confirm("Launch in Debug Mode (to see QEMU errors in this terminal)?").ask()
    
    if debug_mode:
        console.print("\n[bold yellow]-- ENHANCED DEBUG MODE --[/]")
        for title, cmd_list in commands_to_run[:-1]:
            console.print(f"\n[blue]▶️  {title}[/]")
            if run_command_live(cmd_list, check=True) is None: 
                return
        
        title, qemu_cmd_list = commands_to_run[-1]
        full_command_str = ' '.join(qemu_cmd_list)
        console.print(f"\n[bold cyan]Enhanced QEMU Command:[/]\n[white on black]{full_command_str}[/]")
        
        # Start the VM process
        process = subprocess.Popen(qemu_cmd_list)
        
        # Register the session with enhanced identifiers
        if identifiers:
            register_vm_session(vm_name, process.pid, ssh_port, identifiers.vm_uuid, identifiers.mac_address, full_command_str)
        else:
            register_vm_session(vm_name, process.pid, ssh_port, vm_ids['uuid'], vm_ids['mac'], full_command_str)
        
        # Wait for process to complete
        process.wait()
    else:
        launch_in_new_terminal_and_wait(commands_to_run)
    
    # Step 8: Post-creation setup information
    print_success("🎉 Enhanced VM creation completed!")
    
    if identifiers:
        print_info("\n🤖 Automated Setup:")
        print_info("1. Complete the OS installation")
        print_info("2. The VM will automatically configure itself on first boot!")
        print_info("3. System identifiers, networking, and SSH keys will be set automatically")
        print_info("4. Manual setup instructions available in shared/SETUP_INSTRUCTIONS.md if needed")
    
    if use_encryption or additional_disks:
        print_info("💡 After OS installation, you can manage disks and encryption through the VM menu")


def _get_enhanced_qemu_command(vm_name, vm_settings, input_devices, ids, host_dns,
                             ssh_port, iso_path=None, encryption_config=None, 
                             additional_disks=None, passthrough_info=None, identifiers=None):
    """Enhanced QEMU command with all advanced features."""
    
    # Start with base command
    qemu_cmd = _build_qemu_base_cmd(vm_name, vm_settings, ids)
    if not qemu_cmd:
        return None
    
    # Add encryption secrets if needed
    if encryption_config:
        qemu_cmd.extend(["-object", f"secret,id=sec0,data={encryption_config.passphrase}"])
        if additional_disks:
            for i, disk in enumerate(additional_disks):
                if disk.encrypted:
                    qemu_cmd.extend(["-object", f"secret,id=sec{i+1},data={encryption_config.passphrase}"])
    
    # Add network configuration
    networking_mode = vm_settings.get('NETWORKING_MODE', 'nat')
    _add_network_args(qemu_cmd, ids, ssh_port, host_dns, networking_mode)
    
    # Add passthrough if configured
    if passthrough_info:
        _add_passthrough_args(qemu_cmd, passthrough_info, input_devices)
    else:
        # QXL with high VRAM - fast 2D performance without GL requirements
        qemu_cmd.extend(["-cpu", "host", "-device", "qxl-vga,vgamem_mb=256", "-display", "gtk,gl=off,window-close=on"])
    
    # Add storage devices
    paths = get_vm_paths(vm_name)
    
    # Base disk
    if encryption_config:
        encrypted_path = paths['base'].replace('.qcow2', '_encrypted.qcow2')
        qemu_cmd.extend(["-drive", f"file={encrypted_path},if=virtio,encrypt.key-secret=sec0"])
    else:
        qemu_cmd.extend(["-drive", f"file={paths['base']},if=virtio"])
    
    # Additional disks
    if additional_disks:
        for i, disk_config in enumerate(additional_disks):
            disk_path = os.path.join(paths['dir'], f"{disk_config.name}.qcow2")
            if disk_config.encrypted and encryption_config:
                qemu_cmd.extend(["-drive", f"file={disk_path},if=virtio,encrypt.key-secret=sec{i+1}"])
            else:
                qemu_cmd.extend(["-drive", f"file={disk_path},if=virtio"])
    
    # Add ISO
    if iso_path:
        qemu_cmd.extend(["-cdrom", iso_path])
    
    # Add shutdown action
    qemu_cmd.extend(["-action", "reboot=shutdown"])
    
    return qemu_cmd


      
def _build_qemu_base_cmd(vm_name, vm_settings, ids):
    """Builds the base QEMU command list with enhanced UUID management."""
    paths = get_vm_paths(vm_name)
    uefi_code_path = find_first_existing_path(CONFIG['UEFI_CODE_PATHS'])
    if not uefi_code_path:
        print_error("Could not find a valid UEFI firmware file. Cannot proceed.")
        return None

    qemu_cmd = [
        CONFIG["QEMU_BINARY"],
        "-enable-kvm",
        "-m", vm_settings["VM_MEM"],
        "-smp", vm_settings["VM_CPU"],
        "-uuid", ids['uuid'],
    ]

    # Apply enhanced system identifiers if available
    try:
        from linux_vm.uuid_manager import get_uuid_manager
        uuid_manager = get_uuid_manager()
        identifiers = uuid_manager.get_identifiers(vm_name)
        
        if identifiers:
            # Apply all system identifiers to QEMU command
            qemu_cmd = uuid_manager.apply_identifiers_to_qemu_command(qemu_cmd, identifiers)
            print_info(f"✅ Applied enhanced system identifiers to QEMU command")
        else:
            print_warning("⚠️  No enhanced identifiers found, using basic UUID only")
            
    except ImportError:
        print_warning("⚠️  Enhanced UUID manager not available")

    # UEFI firmware configuration - only add the code file here
    # The variables file will be added by the specific command functions
    qemu_cmd.extend(["-drive", f"if=pflash,format=raw,readonly=on,file={uefi_code_path}"])
    qemu_cmd.extend(["-fsdev", f"local,security_model=mapped-xattr,id=fsdev0,path={paths['shared_dir']}"])
    qemu_cmd.extend(["-device", f"virtio-9p-pci,fsdev=fsdev0,mount_tag={CONFIG['SHARED_DIR_MOUNT_TAG']}"])
    qemu_cmd.extend(["-pidfile", paths['pid_file']])

    return qemu_cmd

    


def _add_network_args(qemu_cmd, ids, ssh_port, host_dns, networking_mode='nat'):
    """Adds networking arguments to the QEMU command."""
    if networking_mode == 'bridged':
        # Bridge networking configuration with DNS support
        # Note: Bridge mode relies on external DHCP/DNS (dnsmasq, systemd-resolved, etc.)
        qemu_cmd.extend([
            "-netdev", "bridge,id=n1,br=br0",
            "-device", f"virtio-net-pci,netdev=n1,mac={ids['mac']}"
        ])
        print_info(f"Bridge networking configured - DNS will be provided by host network")
        print_info(f"Host DNS server: {host_dns}")
        
        # Always configure comprehensive bridge networking for perfect connectivity
        try:
            from linux_vm.networking.bridge_dns_fix import auto_fix_bridge_dns
            
            print_info("🌐 Ensuring comprehensive bridge networking...")
            dns_configured = auto_fix_bridge_dns("br0")
            
            if dns_configured:
                print_success("✅ Bridge networking configured with full internet connectivity")
            else:
                print_warning("⚠️  Comprehensive networking setup incomplete")
                print_info("VMs may need manual network configuration inside the guest OS")
                
        except Exception as e:
            print_warning(f"Comprehensive networking setup error: {e}")
            print_info("VMs may need manual network configuration")
    else:
        # NAT networking configuration (default)
        if ssh_port > 0:
            qemu_cmd.extend([
                "-netdev", f"user,id=n1,dns={host_dns},hostfwd=tcp::{ssh_port}-:22",
                "-device", f"virtio-net-pci,netdev=n1,mac={ids['mac']}"
            ])
        else:
            qemu_cmd.extend(["-netdev", "user,id=n1", "-device", f"virtio-net-pci,netdev=n1,mac={ids['mac']}"])

def _add_passthrough_args(qemu_cmd, passthrough_info, input_devices):
    """
    Enhanced PCI passthrough arguments with advanced cursor fix integration
    """
    try:
        # Import the enhanced cursor fix module
        from src.linux_vm.passthrough.cursor_fix import create_cursor_fix_manager
        cursor_fix = create_cursor_fix_manager()
        
        # Check for Ubuntu-specific USB mouse issues first
        if cursor_fix.detect_ubuntu_mouse_issue():
            from rich.console import Console
            from rich.panel import Panel
            import questionary
            
            console = Console()
            console.print(Panel(
                "[yellow]⚠️  Ubuntu USB Mouse Issue Detected[/]\n\n"
                "[white]You're running Ubuntu with USB passthrough. This commonly causes\n"
                "physical mouse issues where trackpad works but USB mouse doesn't.[/]\n\n"
                "[cyan]We can apply Ubuntu-specific fixes automatically.[/]",
                title="Ubuntu Mouse Fix Available",
                border_style="yellow"
            ))
            
            if questionary.confirm("Apply Ubuntu USB mouse fixes?").ask():
                has_risk = True
                risk_description = "Ubuntu USB mouse compatibility issue"
                fix_profile = "ubuntu_usb_fix"
            elif questionary.confirm("Run detailed USB mouse diagnostic?").ask():
                try:
                    from src.linux_vm.ubuntu_usb_mouse_fix import UbuntuUSBMouseFix
                    fix_utility = UbuntuUSBMouseFix()
                    diagnosis = fix_utility.diagnose_mouse_issue()
                    fix_utility.display_diagnosis_results(diagnosis)
                    
                    if diagnosis['issues'] and questionary.confirm("Apply automatic fixes?").ask():
                        fix_utility.apply_automatic_fixes(diagnosis)
                        # Still apply QEMU-level fixes
                        has_risk = True
                        risk_description = "Ubuntu USB mouse compatibility issue"
                        fix_profile = "ubuntu_usb_fix"
                except ImportError:
                    console.print("[red]USB mouse fix utility not available[/]")
        
        # Detect cursor issue risk if not already set
        if 'has_risk' not in locals():
            has_risk, risk_description = cursor_fix.detect_cursor_issue_risk(passthrough_info)
        
        if has_risk:
            # Get user preference for cursor fix if not already set
            if 'fix_profile' not in locals():
                fix_profile = cursor_fix.get_user_preference(risk_description)
            if fix_profile and fix_profile != "skip":
                # Apply the cursor fix to QEMU command
                qemu_cmd = cursor_fix.apply_cursor_fix(qemu_cmd, fix_profile, passthrough_info)
        
    except ImportError:
        print_warning("Enhanced cursor fix module not available, using fallback method.")
        # Fallback to original implementation
        _add_passthrough_args_fallback(qemu_cmd, passthrough_info, input_devices)
        return
    except Exception as e:
        print_error(f"Error in cursor fix module: {e}")
        _add_passthrough_args_fallback(qemu_cmd, passthrough_info, input_devices)
        return

    # Determine passthrough types
    is_gpu = any(d.get('class_code') == '0300' for d in passthrough_info['devices'].values())
    is_usb_passthrough = any(d.get('class_code') == '0c03' for d in passthrough_info['devices'].values())

    # Configure CPU arguments based on GPU passthrough
    if is_gpu:
        cpu_args = "host,kvm=off,hv_vendor_id=null" if passthrough_info.get('vendor') == "NVIDIA" else "host"
        qemu_cmd.extend(["-cpu", cpu_args])
        
        # For GPU passthrough, disable virtual display
        if "-nographic" not in qemu_cmd:
            qemu_cmd.append("-nographic")
        
        # Add evdev input if available and not conflicting with USB passthrough
        if input_devices and not is_usb_passthrough:
            qemu_cmd.extend([
                "-object", f"input-linux,id=mouse,evdev={input_devices['mouse']}",
                "-object", f"input-linux,id=kbd,evdev={input_devices['keyboard']},grab_all=on,repeat=on"
            ])
        elif is_usb_passthrough:
            qemu_cmd.append("-nodefaults")
    else:
        # Non-GPU passthrough
        qemu_cmd.extend(["-cpu", "host"])
        
        # Add evdev input for non-USB passthrough scenarios
        if input_devices and not is_usb_passthrough:
            print_info("Adding evdev passthrough for seamless keyboard/mouse input.")
            qemu_cmd.extend([
                "-object", f"input-linux,id=kbd,evdev={input_devices['keyboard']},grab_all=on,repeat=on",
                "-object", f"input-linux,id=mouse,evdev={input_devices['mouse']}"
            ])

    # Add all PCI devices to passthrough
    primary_gpu_pci = passthrough_info.get('vga_pci')
    is_vga_set = False
    for pci_id in passthrough_info['pci_ids']:
        device_args = ["-device", f"vfio-pci,host={pci_id}"]
        if is_gpu and primary_gpu_pci == pci_id and not is_vga_set:
            device_args[1] += ",x-vga=on,rombar=0"
            is_vga_set = True
        qemu_cmd.extend(device_args)


def _add_passthrough_args_fallback(qemu_cmd, passthrough_info, input_devices):
    """
    Fallback implementation for passthrough arguments (original logic)
    """
    is_gpu = any(d.get('class_code') == '0300' for d in passthrough_info['devices'].values())
    is_usb_passthrough = any(d.get('class_code') == '0c03' for d in passthrough_info['devices'].values())

    if is_gpu:
        # Full GPU passthrough - no virtual display is needed.
        cpu_args = "host,kvm=off,hv_vendor_id=null" if passthrough_info.get('vendor') == "NVIDIA" else "host"
        qemu_cmd.extend(["-cpu", cpu_args, "-nographic"])
        if input_devices and not is_usb_passthrough:
             qemu_cmd.extend([
                "-object", f"input-linux,id=mouse,evdev={input_devices['mouse']}",
                "-object", f"input-linux,id=kbd,evdev={input_devices['keyboard']},grab_all=on,repeat=on"
            ])
        elif is_usb_passthrough:
            qemu_cmd.append("-nodefaults")
    else:
        # This is for non-GPU passthrough (e.g., USB controller).
        qemu_cmd.extend(["-cpu", "host"])
        graphics_args = []

        if is_usb_passthrough:
            print_warning("USB controller passthrough detected. You may experience an invisible mouse cursor.")
            
            # Simple fallback cursor fix options
            render_choice = questionary.select(
                "To fix a potential invisible cursor, choose a rendering strategy:",
                choices=[
                    questionary.Choice("1. Use SDL Display (Recommended)", value="sdl"),
                    questionary.Choice("2. Use Standard VGA (Safe Mode)", value="std"),
                    questionary.Choice("3. Keep Current Settings", value="current")
                ],
                use_indicator=True
            ).ask()

            if render_choice == "sdl":
                print_info("Using SDL display backend with QXL graphics (128MB VRAM).")
                graphics_args = ["-device", "qxl-vga,vgamem_mb=128", "-display", "sdl"]
            elif render_choice == "std":
                print_info("Using Standard VGA with GTK display backend.")
                graphics_args = ["-vga", "std", "-display", "gtk,gl=off"]
            else:
                print_info("Using QXL graphics with GTK display backend (128MB VRAM).")
                graphics_args = ["-device", "qxl-vga,vgamem_mb=128", "-display", "gtk,gl=off"]

            qemu_cmd.append("-nodefaults")
            qemu_cmd.extend(["-device", "virtio-keyboard-pci", "-device", "virtio-mouse-pci"])

        elif input_devices:
            print_info("Adding evdev passthrough for seamless keyboard/mouse input.")
            qemu_cmd.extend([
                "-object", f"input-linux,id=kbd,evdev={input_devices['keyboard']},grab_all=on,repeat=on",
                "-object", f"input-linux,id=mouse,evdev={input_devices['mouse']}"
            ])
            graphics_args = ["-device", "qxl-vga,vgamem_mb=128", "-display", "gtk,gl=off"]

        qemu_cmd.extend(graphics_args)

    # Add all PCI devices
    primary_gpu_pci = passthrough_info.get('vga_pci')
    is_vga_set = False
    for pci_id in passthrough_info['pci_ids']:
        device_args = ["-device", f"vfio-pci,host={pci_id}"]
        if is_gpu and primary_gpu_pci == pci_id and not is_vga_set:
            device_args[1] += ",x-vga=on,rombar=0"
            is_vga_set = True
        qemu_cmd.extend(device_args)
      
def _get_qemu_command(vm_name, vm_settings, input_devices, ids, host_dns,
                      ssh_port, passthrough_info=None, iso_path=None):
    """
    Constructs the full QEMU command list, now using a robust SATA controller
    for the disk in passthrough mode to guarantee boot.
    
    If iso_path is provided, it will be attached as an installer ISO using
    the new InstallerISOManager if available.
    """
    # Try to use the new InstallerISOManager for ISO attachment
    if iso_path:
        try:
            from src.linux_vm.storage.integration import attach_installer_iso
            # Attach the ISO using the new manager
            if attach_installer_iso(vm_name, iso_path):
                # Set iso_path to None so we don't add it again in the legacy code
                iso_path = None
                print_info("Using enhanced installer ISO management")
        except ImportError:
            # Fall back to legacy ISO attachment
            print_warning("Enhanced installer ISO manager not available, using fallback method.")
        except Exception as e:
            print_error(f"Failed to attach installer ISO using enhanced manager: {e}")
            print_warning("Falling back to legacy ISO attachment method.")
            iso_path = None
    """
    Constructs the full QEMU command list, now using a robust SATA controller
    for the disk in passthrough mode to guarantee boot.
    """
    paths = get_vm_paths(vm_name)
    qemu_cmd = _build_qemu_base_cmd(vm_name, vm_settings, ids)
    
    # Check if this VM uses encryption
    encrypted_disk_path = paths['base'].replace('.qcow2', '_encrypted.qcow2')
    is_encrypted = os.path.exists(encrypted_disk_path)
    
    # Add encryption secret if needed
    if is_encrypted:
        # Retrieve passphrase securely using SecurePassphraseManager
        try:
            from src.linux_vm.storage.secure_passphrase import get_passphrase_manager
            passphrase_manager = get_passphrase_manager(vm_name, paths['dir'])
            passphrase = passphrase_manager.get_passphrase()
            if passphrase:
                # Use a temporary file for qemu-img (more secure than command line)
                import tempfile
                temp_pass_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.key')
                temp_pass_file.write(passphrase)
                temp_pass_file.close()
                os.chmod(temp_pass_file.name, 0o600)
                qemu_cmd.extend(["-object", f"secret,id=sec0,file={temp_pass_file.name}"])
                # Note: temp file should be cleaned up after VM starts
        except Exception as e:
            print_warning(f"Could not retrieve passphrase: {e}")

    uefi_vars_path = paths['seed'] if iso_path else paths['instance']
    qemu_cmd.extend(["-drive", f"if=pflash,format=raw,file={uefi_vars_path}"])

    networking_mode = vm_settings.get('NETWORKING_MODE', 'nat')
    _add_network_args(qemu_cmd, ids, ssh_port, host_dns, networking_mode)
    stable_graphics_args = ["-device", "qxl-vga,vgamem_mb=256", "-display", "gtk,gl=off,window-close=on"]

    if passthrough_info:
        # --- THE DEFINITIVE FIX ---
        # Passthrough mode now uses a standard SATA controller for the disk.
        # This is the most compatible method and avoids all PCI-related boot issues.
        _add_passthrough_args(qemu_cmd, passthrough_info, input_devices)
        print_info("Attaching disk via virtual SATA controller for maximum compatibility.")
        qemu_cmd.extend(["-device", "ahci,id=sata"])
        qemu_cmd.extend(["-drive", f"id=disk,file={paths['overlay']},if=none,format=qcow2,cache=writeback"])
        qemu_cmd.extend(["-device", "ide-hd,bus=sata.0,drive=disk"])

    elif iso_path:
        # Check if this is a new VM (using base disk) or an existing VM (using overlay)
        if os.path.exists(paths['overlay']):
            disk_path = paths['overlay']
        elif is_encrypted:
            disk_path = encrypted_disk_path
        else:
            disk_path = paths['base']
        
        qemu_cmd.extend(["-cpu", "host"])
        qemu_cmd.extend(stable_graphics_args)
        if is_encrypted:
            qemu_cmd.extend(["-drive", f"file={disk_path},if=virtio,encrypt.key-secret=sec0", "-cdrom", iso_path])
        else:
            qemu_cmd.extend(["-drive", f"file={disk_path},if=virtio", "-cdrom", iso_path])
        qemu_cmd.extend(["-action", "reboot=shutdown"])
    else:
        # Normal, non-passthrough boot uses virtio-blk for speed.
        qemu_cmd.extend(["-cpu", "host"])
        qemu_cmd.extend(stable_graphics_args)
        if is_encrypted:
            qemu_cmd.extend(["-drive", f"file={paths['overlay']},if=virtio,cache=writeback,encrypt.key-secret=sec0"])
        else:
            qemu_cmd.extend(["-drive", f"file={paths['overlay']},if=virtio,cache=writeback"])

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
        # Check if we have an encrypted base disk
        encrypted_disk_path = paths['base'].replace('.qcow2', '_encrypted.qcow2')
        if os.path.exists(encrypted_disk_path):
            # Create overlay for encrypted disk
            run_command_live(["qemu-img", "create", "-f", "qcow2", "-b", encrypted_disk_path, "-F", "qcow2", paths['overlay']], check=True)
        else:
            # Create overlay for regular disk
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
    result = questionary.text(f"To confirm, please type the name of the VM ({vm_name}):").ask()
    if result is None:
        print_info("Deletion cancelled.")
        return
    confirm = result.strip()
    if confirm == vm_name:
        remove_dir(get_vm_paths(vm_name)['dir'])
        print_success(f"VM '{vm_name}' has been successfully deleted.")
    else:
        print_error("Confirmation failed. Aborting.")    


def _generate_run_dashboard_linux(vm_name, mem, cpu, iso_path=None):
    """Generates a rich Panel that displays the current VM run settings."""
    from rich.panel import Panel
    from rich.table import Table

    table = Table(box=None, expand=True, show_header=False)
    table.add_column("Setting", justify="right", style="cyan")
    table.add_column("Value", justify="left")

    table.add_row("Memory:", f"[bold white]{mem}[/]")
    table.add_row("CPU Cores:", f"[bold white]{cpu}[/]")
    
    if iso_path:
        # Display the ISO path if one is selected
        iso_name = os.path.basename(iso_path)
        table.add_row("Installer ISO:", f"[bold yellow]{iso_name}[/]")

    return Panel(table, title=f"[bold purple]Pre-Launch Dashboard for '{vm_name}'[/]", border_style="purple")

def run_existing_vm():
    """Lists and runs an existing Linux VM with an interactive pre-launch dashboard."""
    clear_screen()
    vm_name = select_vm("Run / Resume")
    if not vm_name: return

    if is_vm_running(vm_name):
        print_error(f"VM '{vm_name}' is already running.")
        return

    paths = get_vm_paths(vm_name)
    
    # Check for both regular and encrypted base disks
    # base_disk_path = paths['base']  # Unused variable
    encrypted_disk_path = paths['base'].replace('.qcow2', '_encrypted.qcow2')
    
    if os.path.exists(encrypted_disk_path):
        # Use encrypted disk if it exists
        pass  # Commented out: base_disk_path = encrypted_disk_path
    elif not os.path.exists(paths['base']):
        print_error(f"Base disk for '{vm_name}' not found. Cannot run.")
        return

    import json
    vm_config = {}
    if os.path.exists(paths['config']):
        with open(paths['config'], 'r', encoding='utf-8') as f:
            vm_config = json.load(f)
    
    mem = vm_config.get('VM_MEM', CONFIG.get('VM_MEM', '4096M'))
    cpu = vm_config.get('VM_CPU', CONFIG.get('VM_CPU', '2'))
    # ISO should not be permanently stored - only temporarily attached when requested
    iso_path = None

    while True:
        clear_screen()
        console.print(_generate_run_dashboard_linux(vm_name, mem, cpu, iso_path))

        choices = [
            questionary.Choice(f"1. Change Memory ({mem})", value="mem"),
            questionary.Choice(f"2. Change CPU Cores ({cpu})", value="cpu"),
            questionary.Separator(),
            questionary.Choice("✅ Launch VM", value="launch"),
            questionary.Choice("📀 Attach Installer ISO", value="attach_iso"),
            questionary.Choice("❌ Cancel Launch", value="cancel")
        ]

        choice = questionary.select(
            "Modify settings or launch the VM:",
            choices=choices,
            use_indicator=True
        ).ask()

        if choice is None or choice == "cancel":
            print_info("VM launch cancelled."); return
        if choice == "launch":
            break
        elif choice == "mem":
            new_mem = questionary.text(f"Enter Memory [current: {mem}]:").ask().strip().upper()
            if new_mem: mem = new_mem
        elif choice == "cpu":
            new_cpu = questionary.text(f"Enter CPU cores [current: {cpu}]:").ask().strip()
            if new_cpu and new_cpu.isdigit(): cpu = new_cpu
        elif choice == "attach_iso":
            # Use the same ISO detection as in create_vm
            iso_path = find_iso_path()
            # Don't save ISO path to config - it should only be temporarily attached
    
    # ISO should not be permanently attached - only when explicitly requested above
    # iso_path is already set if user chose to attach it in this session
    
    final_settings = {'VM_MEM': mem, 'VM_CPU': cpu}
    # Don't save ISO path to config - it should only be temporarily attached
        
    with open(paths['config'], 'w', encoding='utf-8') as f:
        json.dump(final_settings, f, indent=4)
    print_success(f"Configuration saved for '{vm_name}'.")
    
    _, ids = _prepare_vm_session(vm_name, is_fresh=False)
    if not ids: return

    host_dns = find_host_dns()
    ssh_port = find_unused_port()
    print_info(f"SSH will be available on host port {ssh_port}")
    with open(paths['session_info'], 'w', encoding='utf-8') as f:
        f.write(str(ssh_port))

    # Pass the ISO path to the QEMU command if it was selected
    qemu_cmd = _get_qemu_command(vm_name, final_settings, {}, ids, host_dns, ssh_port, iso_path=iso_path)
    
    debug_mode = questionary.confirm("Launch in Debug Mode (to see QEMU errors in this terminal)?").ask()
    if debug_mode:
        import shlex
        full_command_str = ' '.join(shlex.quote(s) for s in qemu_cmd)
        
        console.print("\n[bold yellow]-- DEBUG MODE: Running Command Directly in This Terminal --[/]")
        console.print(f"\n[bold cyan]Full QEMU Command:[/]\n[white on black]{full_command_str}[/]")
        console.print("[bold yellow]--------------------------------------------------------[/]\n")
        console.print("[bold yellow]QEMU output will appear below:[/]")

        subprocess.run(qemu_cmd, check=False)
        print_info("Debug command execution finished.")
    else:
        launch_in_new_terminal_and_wait([("Booting VM", qemu_cmd)])

def nuke_and_boot_fresh():
    """Nukes the session and boots the VM with its last saved configuration."""
    clear_screen()
    vm_name = select_vm("Nuke & Boot a Fresh Session")
    if not vm_name: return

    if is_vm_running(vm_name):
        print_error(f"Cannot nuke '{vm_name}' while it is running. Please stop it first.")
        return

    print_header(f"Nuke & Boot: '{vm_name}'")
    
    # Ask about Privacy Mode
    enable_privacy = False
    privacy_mode_choice = questionary.select(
        "🔒 Select nuke type:",
        choices=[
            questionary.Choice("Standard Nuke (Fresh overlay, keep IP)", value="standard"),
            questionary.Choice("Privacy Nuke (Fresh overlay + Tor routing)", value="privacy"),
            questionary.Choice("Cancel", value="cancel")
        ]
    ).ask()
    
    if privacy_mode_choice is None or privacy_mode_choice == "cancel":
        print_info("Operation cancelled.")
        return
    
    if privacy_mode_choice == "privacy":
        try:
            from linux_vm.privacy_mode import (
                show_privacy_mode_panel, 
                check_tor_installed,
                enable_privacy_mode
            )
            
            # Check if Tor is available
            tor_installed, tor_msg = check_tor_installed()
            if not tor_installed:
                print_error(f"Privacy Mode requires Tor: {tor_msg}")
                print_info("Install Tor with: sudo apt install tor")
                if not questionary.confirm("Continue with Standard Nuke instead?").ask():
                    return
            else:
                # Show pros/cons/disclaimer
                show_privacy_mode_panel()
                
                confirm = questionary.confirm("Enable Privacy Mode for this session?", default=False).ask()
                if confirm:
                    enable_privacy = True
                    print_success("✅ Privacy Mode will be enabled after nuke")
                else:
                    print_info("Privacy Mode declined. Proceeding with Standard Nuke.")
        except ImportError as e:
            print_warning(f"Privacy Mode module not available: {e}")
            print_info("Proceeding with Standard Nuke.")
    
    paths, ids = _prepare_vm_session(vm_name, is_fresh=True)
    if not paths: return

    import json
    vm_config = {}
    if os.path.exists(paths['config']):
        with open(paths['config'], 'r', encoding='utf-8') as f:
            vm_config = json.load(f)
    
    final_settings = {
        'VM_MEM': vm_config.get('VM_MEM', CONFIG.get('VM_MEM', '4096M')),
        'VM_CPU': vm_config.get('VM_CPU', CONFIG.get('VM_CPU', '2')),
    }
    print_info(f"Using saved config: {final_settings['VM_MEM']} RAM, {final_settings['VM_CPU']} Cores.")

    host_dns = find_host_dns()
    ssh_port = find_unused_port()
    print_info(f"SSH will be available on host port {ssh_port}")
    with open(paths['session_info'], 'w', encoding='utf-8') as f:
        f.write(str(ssh_port))

    # Apply privacy mode if enabled
    if enable_privacy:
        try:
            from linux_vm.privacy_mode import enable_privacy_mode
            success, msg = enable_privacy_mode()
            if success:
                print_success(f"🔒 {msg}")
                # Save privacy mode to config
                vm_config['privacy_mode'] = True
                with open(paths['config'], 'w', encoding='utf-8') as f:
                    json.dump(vm_config, f, indent=2)
            else:
                print_warning(f"Privacy Mode setup failed: {msg}")
                if not questionary.confirm("Continue without Privacy Mode?").ask():
                    return
        except Exception as e:
            print_warning(f"Privacy Mode error: {e}")

    qemu_cmd = _get_qemu_command(vm_name, final_settings, {}, ids, host_dns, ssh_port)
    
    # --- ADDED DEBUG LOGIC ---
    debug_mode = questionary.confirm("Launch in Debug Mode (to see QEMU errors in this terminal)?").ask()
    if debug_mode:
        import shlex
        full_command_str = ' '.join(shlex.quote(s) for s in qemu_cmd)
        
        console.print("\n[bold yellow]-- DEBUG MODE: Running Command Directly in This Terminal --[/]")
        console.print(f"\n[bold cyan]Full QEMU Command:[/]\n[white on black]{full_command_str}[/]")
        console.print("[bold yellow]--------------------------------------------------------[/]\n")
        console.print("[bold yellow]QEMU output will appear below:[/]")

        subprocess.run(qemu_cmd, check=False)
        print_info("Debug command execution finished.")
        
        # Clean up privacy mode if enabled
        if enable_privacy:
            try:
                from linux_vm.privacy_mode import disable_privacy_mode
                disable_privacy_mode()
                print_info("Privacy Mode disabled after VM shutdown.")
            except Exception:
                pass
    else:
        launch_in_new_terminal_and_wait([("Booting Fresh VM Session", qemu_cmd)])





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


      
      
      
      
def _check_and_restore_vfio_devices():
    """
    Checks for devices actively bound to vfio-pci from a previous session and
    offers to restore them to their original host drivers.
    This function now correctly ignores devices that are normally driverless (N/A).
    """
    clear_screen()
    print_header("Passthrough & Performance (Linux)")
    print_info("Performing pre-flight check of PCI device states...")

    all_devices = _get_gpus() + _get_usb_controllers() + _get_nvme_drives() + _get_serial_controllers() + _get_memory_controllers()
    # THE CORE FIX: We only care about devices actively stuck on vfio-pci. 'N/A' is considered normal.
    devices_to_restore = [dev for dev in all_devices if dev['driver'] == "vfio-pci"]

    if not devices_to_restore:
        print_success("System state is clean. No devices are stuck on the vfio-pci driver.")
        time.sleep(2)
        return True

    print_warning("The following devices are still bound to the 'vfio-pci' driver from a previous session:")
    for dev in devices_to_restore:
        potential_drivers = [mod for mod in dev.get('modules', []) if mod != 'vfio-pci']
        message = f"  - [bold yellow]{dev['pci']}[/] ({dev['name']})"
        if potential_drivers:
            message += f" (Should be on [cyan]{', '.join(potential_drivers)}[/])"
        console.print(message)

    print_info("\nThis is likely from a previous session that did not exit cleanly.")
    if not questionary.confirm("Attempt to restore these devices to their host drivers?").ask():
        print_error("Aborted by user. A reboot is the most reliable way to fix this state.")
        return False

    # Use the most powerful restoration method: a full PCI bus rescan.
    print_info("Triggering PCI bus rescan to restore all host drivers...")
    rescan_cmd = ["bash", "-c", "echo 1 > /sys/bus/pci/rescan"]
    run_command_live(rescan_cmd, as_root=True, quiet=True, check=False)
    print_info("Waiting for kernel to re-probe devices...")
    time.sleep(3)

    # --- Final Verification ---
    all_devices_after_rescan = _get_gpus() + _get_usb_controllers() + _get_nvme_drives() + _get_serial_controllers() + _get_memory_controllers()
    still_stuck = False
    for dev_to_check in devices_to_restore:
        restored_dev_info = next((d for d in all_devices_after_rescan if d['pci'] == dev_to_check['pci']), None)
        if restored_dev_info and restored_dev_info.get('driver') == 'vfio-pci':
            print_error(f"  - Restoration failed for {dev_to_check['pci']}. It is still on driver 'vfio-pci'.")
            still_stuck = True

    if still_stuck:
        print_error("\nAutomatic restoration failed. A system reboot is required.")
        return False

    print_success("\nAll devices successfully restored to their host drivers.")
    time.sleep(2)
    return True

def gpu_passthrough_menu():
    """Menu for GPU passthrough on Linux VMs."""
    clear_screen()
    print_header("Passthrough & Performance (Linux)")
    
    if not _check_and_restore_vfio_devices():
        questionary.text("Press Enter to return to the main menu...").ask()
        return

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

def _get_serial_controllers():
    """Gets a list of Serial Bus Controllers (e.g., I2C, SPI) often found in IOMMU groups."""
    return _find_pci_devices_by_class("0c80")

def _get_memory_controllers():
    """Gets a list of Memory controllers (e.g., SRAM) often found in IOMMU groups."""
    return _find_pci_devices_by_class("0500")

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

def _provide_bootloader_instructions(param_to_add):
    """
    Advises the user on how to manually add a kernel parameter to their bootloader.
    """
    distro = detect_distro()
    
    # Instructions for GRUB
    grub_file = "/etc/default/grub"
    update_cmd = DISTRO_INFO.get(distro, {}).get("grub_update", "sudo update-grub")
    
    # Instructions for systemd-boot (used by Pop!_OS and others)
    esp_path = "/boot/efi"
    if distro == "pop":
        esp_path = "/boot/efi" # Pop!_OS specific path
    
    print_warning("ACTION REQUIRED: Manual kernel parameter update needed.")
    print_info(f"To enable IOMMU, you need to add '{param_to_add}' to your kernel boot parameters.")
    
    # Create a choice for the user
    bootloader_choice = questionary.select(
        "Which bootloader are you using?",
        choices=["GRUB (most systems)", "systemd-boot (Pop!_OS, etc.)", "Other/Unsure"]
    ).ask()

    if bootloader_choice == "GRUB (most systems)":
        console.print(f"""
  [bold]GRUB Instructions:[/bold]
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
    elif bootloader_choice == "systemd-boot (Pop!_OS, etc.)":
        console.print(f"""
  [bold]systemd-boot Instructions:[/bold]
  1. Find your EFI System Partition (ESP). It's usually mounted at [cyan]{esp_path}[/].
  2. Edit the boot entry configuration file. For Pop!_OS, this is often at:
     [bold]sudo nano {esp_path}/loader/entries/Pop_OS-current.conf[/]
     For other systems, you may need to find the correct `.conf` file in `{esp_path}/loader/entries/`.
  3. Find the line starting with [cyan]options[/].
  4. Add [bold]{param_to_add}[/] to the end of that line.
  5. Save the file and exit the editor.
  6. Reboot your system for the changes to take effect:
     [bold]sudo reboot[/]
  
  [dim]Note: Unlike GRUB, systemd-boot does not require a separate update command.[/dim]
        """)
    else:
        print_info("Please consult your distribution's documentation on how to add kernel parameters.")
        print_info(f"The parameter you need to add is: [bold]{param_to_add}[/]")


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
    if questionary.confirm(f"Would you like instructions on how to add the '{param}' kernel parameter to your bootloader?").ask():
        _provide_bootloader_instructions(param)
    
    return False


def _find_pci_devices_by_class(class_code):
    """
    Finds PCI devices by their class code, using a robust regex that correctly
    parses multi-line module information.
    """
    try:
        # Use lspci -k to ensure kernel driver/module info is present
        lspci_out = _run_command(["lspci", "-k", "-nn"])
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_error("`lspci` command failed. Is `pciutils` installed?")
        return []

    devices = []
    # This regex is designed to find a device block and then look within it.
    device_block_regex = re.compile(
        r"^([\da-f:.]+)\s"       # Group 1: PCI Address
        r".*?\[" + class_code + r"\]:\s" # Match the specific class code
        r"(.*?)\s"               # Group 2: Device Name
        r"\[([\da-f]{4}:[\da-f]{4})\]" # Group 3: Vendor:Device ID
        r"((?:.|\n)*?)"          # Group 4: The rest of the block for this device
        r"(?=\n\S|\Z)",          # Positive lookahead for the next device or end of string
        re.MULTILINE
    )
    
    # Regex to find specific lines within the captured device block
    driver_regex = re.compile(r"Kernel driver in use:\s+(\S+)")
    modules_regex = re.compile(r"Kernel modules:\s+(.*)")

    for block_match in device_block_regex.finditer(lspci_out):
        pci, name, vdid, rest_of_block = block_match.groups()
        
        # Now search for driver and modules within the isolated block
        driver_match = driver_regex.search(rest_of_block)
        modules_match = modules_regex.search(rest_of_block)
        
        driver = driver_match.group(1) if driver_match else "N/A"
        modules_str = modules_match.group(1) if modules_match else ""
        
        mod_list = [m.strip() for m in modules_str.split(',')] if modules_str else []

        devices.append({
            "pci": pci.strip(),
            "name": name.strip(),
            "ids": vdid.strip(),
            "driver": driver,
            "modules": mod_list,
            "class_code": class_code,
            "display": f"[{pci.strip()}] {name.strip()} (driver: {driver})"
        })
    return devices

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
    Manages the entire lifecycle of a passthrough VM, attempting a forceful live
    binding and providing a complete, robust state restoration using explicit
    rebinding followed by a PCI bus rescan.
    """
    dm_service = _detect_display_manager()
    original_drivers = {}
    vfio_rules_created = set()
    devices_successfully_bound = set()

    try:
        # --- PRE-LAUNCH: Prepare Host ---
        print_header("Preparing Host for Passthrough")
        if dm_service and passthrough_info.get('is_primary_gpu'):
            print_info(f"Primary GPU passthrough detected. Stopping display manager ({dm_service})...")
            if run_command_live(["systemctl", "stop", dm_service], as_root=True) is None:
                raise RuntimeError(f"Failed to stop display manager {dm_service}.")
            print_success("Display manager stopped.")
            time.sleep(3)

        # Store the original drivers BEFORE any changes are made.
        for pci_id, device in passthrough_info['devices'].items():
            original_drivers[pci_id] = device['driver']

        # Unbind all devices from their host drivers.
        for pci_id, driver in original_drivers.items():
            if driver and driver not in ["vfio-pci", "N/A"]:
                print_info(f"Unbinding {pci_id} from host driver '{driver}'...")
                unbind_cmd = ["bash", "-c", f"echo {pci_id} > /sys/bus/pci/devices/{pci_id}/driver/unbind"]
                run_command_live(unbind_cmd, as_root=True, quiet=True)
                time.sleep(0.2)
        
        # Bind all necessary devices to vfio-pci.
        for pci_id, device in passthrough_info['devices'].items():
            if _get_pci_device_driver(pci_id) == "vfio-pci":
                print_success(f"Verified: {pci_id} is already on vfio-pci.")
                devices_successfully_bound.add(pci_id)
                continue
            
            vendor_device_id = device['ids']
            if vendor_device_id not in vfio_rules_created:
                print_info(f"Creating vfio-pci rule for new ID {vendor_device_id}...")
                vendor, dev_id = vendor_device_id.split(':')
                bind_cmd = ["bash", "-c", f"echo {vendor} {dev_id} > /sys/bus/pci/drivers/vfio-pci/new_id"]
                run_command_live(bind_cmd, as_root=True, quiet=True, check=False)
                vfio_rules_created.add(vendor_device_id)
                time.sleep(0.5)
            
            new_driver = _get_pci_device_driver(pci_id)
            if new_driver == "vfio-pci":
                print_success(f"Verified: {pci_id} is now bound to vfio-pci.")
                devices_successfully_bound.add(pci_id)
            else:
                 raise RuntimeError(f"Verification failed: {pci_id} is bound to '{new_driver or 'None'}' instead of 'vfio-pci'.")

        print_success("Host prepared. Launching VM...")

        # --- LAUNCH: Run QEMU ---
        # The session was already prepared in the calling function.
        _, ids = _prepare_vm_session(vm_name, is_fresh=False)
        if not ids: raise RuntimeError("Failed to get session IDs for QEMU launch.")

        qemu_cmd = _get_qemu_command(vm_name, vm_settings, input_devices, ids, find_host_dns(), 0, passthrough_info)
        if qemu_cmd is None: raise RuntimeError("Failed to construct QEMU command.")
        
        run_command_live(qemu_cmd, as_root=False) # check_vfio_permissions handles sudo now.

    except Exception as e:
        print_error(f"An error occurred during passthrough lifecycle: {e}")
        print_warning("Attempting to restore host state...")
    finally:
        # --- POST-LAUNCH: Complete and GUARANTEED State Restoration ---
        print_header("Restoring Host State")
        
        # Release devices from vfio-pci
        for pci_id in devices_successfully_bound:
            run_command_live(["bash", "-c", f"echo {pci_id} > /sys/bus/pci/drivers/vfio-pci/unbind"], as_root=True, quiet=True, check=False)

        # Remove the vfio override rules
        for vendor_device_id in vfio_rules_created:
            vendor, dev_id = vendor_device_id.split(':')
            remove_cmd = ["bash", "-c", f"echo {vendor} {dev_id} > /sys/bus/pci/drivers/vfio-pci/remove_id"]
            run_command_live(remove_cmd, as_root=True, quiet=True, check=False)
        
        # --- THE DEFINITIVE RESTORATION LOGIC ---
        # 1. Explicitly re-bind the original drivers. This is the most critical step.
        print_info("Explicitly re-binding devices to their original host drivers...")
        for pci_id, driver in original_drivers.items():
            # Only try to re-bind if there was a driver in the first place.
            if driver and driver != "N/A":
                print_info(f"  - Attempting to re-bind {pci_id} to '{driver}'...")
                bind_cmd = ["bash", "-c", f"echo {pci_id} > /sys/bus/pci/drivers/{driver}/bind"]
                # We don't check for errors here; the rescan is the final safety net.
                run_command_live(bind_cmd, as_root=True, quiet=True, check=False)

        # 2. As a final catch-all, trigger a PCI bus rescan.
        print_info("Triggering PCI bus rescan to ensure system consistency...")
        run_command_live(["bash", "-c", "echo 1 > /sys/bus/pci/rescan"], as_root=True, quiet=True, check=False)
        time.sleep(3) 

        if dm_service and passthrough_info.get('is_primary_gpu'):
            try:
                print_info(f"Restarting display manager ({dm_service})...")
                run_command_live(["systemctl", "start", dm_service], as_root=True)
            except Exception as e:
                print_error(f"Failed to restart display manager: {e}")
            
        print_success("Host state restoration complete. The system should be back to normal.")


def run_vm_with_live_passthrough():
    """
    Guides the user through a categorized, multi-level menu to select devices
    for a live passthrough session, with full safety checks.
    """
    clear_screen()
    print_header("Run VM with Live Passthrough")

    if not _check_and_load_vfio_module(): return
    if not _check_vfio_permissions(): return

    vm_name = select_vm("run with Passthrough")
    if not vm_name: return

    # Prepare the session to ensure an overlay disk exists for passthrough.
    paths, ids = _prepare_vm_session(vm_name, is_fresh=False)
    if not ids:
        print_error("Failed to prepare VM session. Cannot proceed."); return

    from core_utils import get_active_gpu_pci_address
    active_gpu_pci = get_active_gpu_pci_address()
    selected_devices = {}

    while True:
        # --- Main Selection Dashboard ---
        clear_screen(); print_header("Passthrough Device Selection")
        if selected_devices:
            console.print("[bold]Selected Devices for Passthrough:[/]")
            for dev in selected_devices.values():
                console.print(f"  - {dev['display']}")
            console.print("")
        else:
            console.print("[dim]No devices selected yet.[/]\n")

        # --- Top-Level Menu (Device Category) ---
        category_choice = questionary.select(
            "What type of device would you like to add?",
            choices=[
                questionary.Choice("1. GPU", value="gpu"),
                questionary.Choice("2. USB Controller", value="usb"),
                questionary.Choice("3. NVMe Drive", value="nvme"),
                questionary.Separator(),
                questionary.Choice("✅ Done Selecting & Continue", value="done", disabled=not selected_devices),
                questionary.Choice("❌ Cancel Passthrough", value="cancel"),
            ],
            use_indicator=True
        ).ask()

        if category_choice is None or category_choice == "cancel":
            print_info("Passthrough cancelled."); return
        if category_choice == "done":
            break

        # --- Sub-Menu (Specific Device) ---
        device_map = {
            "gpu": ("GPU", _get_gpus),
            "usb": ("USB Controller", _get_usb_controllers),
            "nvme": ("NVMe Drive", _get_nvme_drives),
        }
        device_type_name, device_func = device_map[category_choice]
        all_of_type = device_func()
        
        # Filter out devices that have already been selected
        available_for_type = [dev for dev in all_of_type if dev['pci'] not in selected_devices]

        if not available_for_type:
            print_warning(f"No unselected {device_type_name}s found.")
            time.sleep(2)
            continue

        device_choices = []
        for dev in available_for_type:
            is_active = dev['pci'] == active_gpu_pci
            title = f"{dev['display']}"
            if is_active:
                title += " [bold yellow]⚠️ ACTIVE HOST GPU[/]"
            device_choices.append(questionary.Choice(title=title, value=dev['pci']))

        device_choices.extend([questionary.Separator(), "Back to Main Selection"])

        sub_selection = questionary.select(
            f"Select a {device_type_name} to add:",
            choices=device_choices
        ).ask()

        if sub_selection and sub_selection != "Back to Main Selection":
            # If user selects the active GPU, show a final warning.
            if sub_selection == active_gpu_pci:
                if not questionary.confirm(
                    "This will STOP your graphical session to proceed. Are you sure?"
                ).ask():
                    continue # Go back to the main selection without adding it.
            
            # Add the selected device to our dictionary
            selected_devices[sub_selection] = next(dev for dev in all_of_type if dev['pci'] == sub_selection)

    if not selected_devices:
        print_info("No devices selected. Exiting."); return

    # --- Gather Full Device Info for Lifecycle Manager ---
    print_header("Gathering Full Passthrough Device List")
    passthrough_info = {'pci_ids': set(), 'devices': {}, 'is_primary_gpu': False}
    iommu_groups = _get_iommu_groups()
    all_scannable_devs = _get_gpus() + _get_usb_controllers() + _get_nvme_drives() + _get_serial_controllers() + _get_memory_controllers()

    for pci_id in selected_devices:
        group, devices_in_group, _ = _get_full_iommu_group_devices(pci_id, iommu_groups)
        if not group:
            print_error(f"Could not find IOMMU group for {pci_id}. Aborting."); return
        print_info(f"Selected device {pci_id} is in IOMMU Group {group}. Adding all co-located devices.")
        passthrough_info['pci_ids'].update(devices_in_group)

    for pci_id in passthrough_info['pci_ids']:
        device_info = next((d for d in all_scannable_devs if d['pci'] == pci_id), None)
        if not device_info:
            print_error(f"Could not get details for required IOMMU group member {pci_id}."); return
        passthrough_info['devices'][pci_id] = device_info
        if device_info.get('pci') == active_gpu_pci:
            passthrough_info['is_primary_gpu'] = True
        if device_info['class_code'] == '0300' and not passthrough_info.get('vga_pci'):
            passthrough_info['vga_pci'] = pci_id
            passthrough_info['vendor'] = 'NVIDIA' if device_info['ids'].startswith('10de') else 'Other'

    console.print("\n[bold]Final list of devices to be passed to the VM:[/]")
    for pci_id in sorted(list(passthrough_info['pci_ids'])):
        dev = passthrough_info['devices'][pci_id]
        console.print(f"  - {dev['display']}")

    if not questionary.confirm("Proceed with VM launch?").ask(): return

    input_devices = find_input_devices()
    vm_settings = get_vm_config({"VM_MEM": CONFIG['VM_MEM'], "VM_CPU": CONFIG['VM_CPU']})
    _execute_passthrough_lifecycle(vm_name, passthrough_info, vm_settings, input_devices)

def snapshot_management_menu():
    """Advanced snapshot management menu for Linux VMs."""
    clear_screen()
    print_header("Snapshot Management")
    
    # Select VM for snapshot management
    vm_name = select_vm("Manage Snapshots for")
    if not vm_name:
        return
    
    try:
        # Import the snapshot integration module
        from linux_vm.storage.integration import handle_snapshot_menu
        
        # Launch the comprehensive snapshot management interface
        handle_snapshot_menu(vm_name)
        
    except ImportError as e:
        print_error("Advanced Snapshot System not available.")
        print_info("The snapshot management system requires additional components.")
        print_info("Please ensure all storage modules are properly installed.")
        console.print(f"[dim]Error details: {e}[/dim]")
    except Exception as e:
        print_error(f"Error launching snapshot management: {e}")
        print_info("Please check the VM exists and try again.")


def linux_vm_menu():
    """Main menu for Linux VM management."""
    os.makedirs(CONFIG['VMS_DIR_LINUX'], exist_ok=True)
    while True:
        cleanup_stale_sessions()
        clear_screen()
        console.print("[bold]Linux VM Management[/]")
        console.rule(style="dim")
        try:
            choice = questionary.select(
                "Select an option",
                choices=[
                    "1. Create New Linux VM",
                    "2. Run / Resume VM Session (Standard Graphics)",
                    "3. Nuke & Boot a Fresh Session",
                    "4. Transfer Files (SFTP)",
                    "5. Passthrough & Performance (Advanced)",
                    "6. Snapshot Management (Advanced)",
                    "7. Disk Management (Advanced)",
                    "8. Bridge Networking (Advanced)",
                    "9. UUID & Identifier Management (Advanced)",
                    "10. Stop a Running VM",
                    "11. Nuke VM Completely",
                    "12. Return to Main Menu",
                ]
            ).ask()
            action_taken = True
            if choice == "1. Create New Linux VM": create_new_vm()
            elif choice == "2. Run / Resume VM Session (Standard Graphics)":
                run_existing_vm()
            elif choice == "3. Nuke & Boot a Fresh Session":
                nuke_and_boot_fresh()
            elif choice == "4. Transfer Files (SFTP)":
                vm_name = select_vm("Transfer Files with", running_only=True)
                if vm_name:
                    vm_dir = get_vm_paths(vm_name)['dir']
                    transfer_files_menu(vm_name, "linux", vm_dir)
            elif choice == "5. Passthrough & Performance (Advanced)": gpu_passthrough_menu()
            elif choice == "6. Snapshot Management (Advanced)": snapshot_management_menu()
            elif choice == "7. Disk Management (Advanced)":
                try:
                    from src.linux_vm.storage.disk_management import disk_management_menu
                    disk_management_menu()
                except ImportError as e:
                    print_error("Disk management functionality not available")
                    print_info("Please ensure all storage modules are properly installed")
                    console.print(f"[dim]Error details: {e}[/dim]")
            elif choice == "8. Bridge Networking (Advanced)":
                try:
                    from src.linux_vm.networking.bridge_ui import show_bridge_menu
                    show_bridge_menu()
                except ImportError as e:
                    print_error("Bridge networking functionality not available")
                    print_info("Please ensure all networking modules are properly installed")
                    console.print(f"[dim]Error details: {e}[/dim]")
            elif choice == "9. UUID & Identifier Management (Advanced)": uuid_management_menu()
            elif choice == "10. Stop a Running VM": stop_vm()
            elif choice == "11. Nuke VM Completely": nuke_vm_completely()
            elif choice == "12. Return to Main Menu": break
            else:
                print_warning("Invalid option.")
                action_taken = False

            if action_taken and choice != "12. Return to Main Menu":
                questionary.text("\nPress Enter to return to the menu...").ask()
        except (KeyboardInterrupt, EOFError):
            break
        except RuntimeError as e:
            if "lost sys.stdin" in str(e):
                print_error("This script is interactive and cannot be run in this environment.")
                break
            raise e


def nuke_vm_session():
    """
    Nuclear option: Completely regenerate all identifiers and reset VM to fresh state
    
    This function:
    1. Stops the VM if running
    2. Regenerates ALL system identifiers
    3. Resets UEFI variables
    4. Creates fresh overlay (if exists)
    5. Provides post-install script for setting identifiers
    """
    clear_screen()
    print_header("🔥 NUKE VM Session - Complete Fresh Start")
    
    vm_name = select_vm("Nuke (Complete Reset)")
    if not vm_name:
        return
    
    # Confirm the nuclear option
    print_warning("⚠️  This will completely reset ALL system identifiers for the VM!")
    print_info("This includes:")
    print_info("  • VM UUID and MAC address")
    print_info("  • Machine ID and hardware serials")
    print_info("  • Disk and partition UUIDs")
    print_info("  • UEFI/TPM/Secure Boot variables")
    print_info("  • Fresh overlay disk (if exists)")
    
    if not questionary.confirm("🔥 Are you sure you want to NUKE this VM session?").ask():
        print_info("Operation cancelled.")
        return
    
    # Stop VM if running
    if is_vm_running(vm_name):
        print_info(f"Stopping VM '{vm_name}' before reset...")
        stop_vm(vm_name, force=True)
        time.sleep(2)  # Give it a moment to fully stop
    
    try:
        from linux_vm.uuid_manager import get_uuid_manager
        uuid_manager = get_uuid_manager()
        
        # Nuclear regeneration of all identifiers
        identifiers = uuid_manager.nuke_and_regenerate_all(vm_name)
        
        # Regenerate overlay if it exists
        paths = get_vm_paths(vm_name)
        if os.path.exists(paths['overlay']):
            print_info("🔄 Regenerating overlay disk with fresh identifiers...")
            
            # Remove old overlay
            os.remove(paths['overlay'])
            
            # Create fresh overlay from base
            overlay_cmd = [
                "qemu-img", "create", "-f", "qcow2", 
                "-b", paths['base'], 
                "-F", "qcow2", 
                paths['overlay']
            ]
            
            if run_command_live(overlay_cmd, check=True):
                print_success("✅ Created fresh overlay disk")
            else:
                print_error("❌ Failed to create fresh overlay disk")
                return
        
        print_success("🔥 NUKE COMPLETE!")
        print_info("New system identifiers:")
        print_info(f"  VM UUID: {identifiers.vm_uuid}")
        print_info(f"  MAC Address: {identifiers.mac_address}")
        print_info(f"  Machine ID: {identifiers.machine_id}")
        
        print_info("\n🤖 Next steps:")
        print_info("1. Boot the VM normally")
        print_info("2. The VM will automatically configure itself on first boot!")
        print_info("3. Manual setup available in shared/SETUP_INSTRUCTIONS.md if needed")
        
    except ImportError:
        print_error("❌ Enhanced UUID manager not available")
        print_info("Manual steps required:")
        print_info("1. Delete overlay.qcow2 if it exists")
        print_info("2. Delete uefi-instance.fd and uefi-seed.fd")
        print_info("3. Recreate overlay and UEFI files manually")
    except Exception as e:
        print_error(f"❌ Error during NUKE operation: {e}")


def regenerate_overlay_with_fresh_identifiers():
    """
    Regenerate overlay disk with fresh disk identifiers
    
    This is useful when you want to create a fresh overlay while keeping
    the same base image but with different disk UUIDs.
    """
    clear_screen()
    print_header("🔄 Regenerate Overlay with Fresh Identifiers")
    
    vm_name = select_vm("Regenerate Overlay")
    if not vm_name:
        return
    
    paths = get_vm_paths(vm_name)
    
    # Check if overlay exists
    if not os.path.exists(paths['overlay']):
        print_error(f"No overlay disk found for VM '{vm_name}'")
        print_info("This function is only for VMs that use overlay disks.")
        return
    
    # Stop VM if running
    if is_vm_running(vm_name):
        print_info(f"Stopping VM '{vm_name}' before regenerating overlay...")
        stop_vm(vm_name, force=True)
        time.sleep(2)
    
    print_warning("⚠️  This will destroy the current overlay and create a fresh one!")
    print_info("All changes in the current overlay will be lost.")
    print_info("The base image will remain unchanged.")
    
    if not questionary.confirm("Continue with overlay regeneration?").ask():
        print_info("Operation cancelled.")
        return
    
    try:
        from linux_vm.uuid_manager import get_uuid_manager
        uuid_manager = get_uuid_manager()
        
        # Regenerate disk-specific identifiers
        identifiers = uuid_manager.regenerate_disk_identifiers(vm_name)
        
        # Reset UEFI variables
        uuid_manager.reset_uefi_variables(vm_name)
        
        # Remove old overlay
        print_info("🗑️  Removing old overlay...")
        os.remove(paths['overlay'])
        
        # Create fresh overlay
        print_info("🔄 Creating fresh overlay...")
        overlay_cmd = [
            "qemu-img", "create", "-f", "qcow2",
            "-b", paths['base'],
            "-F", "qcow2",
            paths['overlay']
        ]
        
        if run_command_live(overlay_cmd, check=True):
            print_success("✅ Successfully regenerated overlay with fresh identifiers")
            print_info("New disk identifiers:")
            print_info(f"  Disk UUID: {identifiers.disk_uuid}")
            print_info(f"  Partition UUID: {identifiers.partition_uuid}")
            print_info(f"  Filesystem UUID: {identifiers.filesystem_uuid}")
        else:
            print_error("❌ Failed to create fresh overlay")
            
    except ImportError:
        print_error("❌ Enhanced UUID manager not available")
        print_info("Manual overlay regeneration:")
        print_info(f"1. rm {paths['overlay']}")
        print_info(f"2. qemu-img create -f qcow2 -b {paths['base']} -F qcow2 {paths['overlay']}")
    except Exception as e:
        print_error(f"❌ Error during overlay regeneration: {e}")


def show_vm_identifiers():
    """
    Display system identifiers for VMs
    """
    clear_screen()
    print_header("🆔 VM System Identifiers")
    
    try:
        from linux_vm.uuid_manager import get_uuid_manager
        uuid_manager = get_uuid_manager()
        
        # Option to show specific VM or all VMs
        choice = questionary.select(
            "What would you like to view?",
            choices=[
                "All VMs",
                "Specific VM"
            ]
        ).ask()
        
        if choice == "Specific VM":
            vm_name = select_vm("View Identifiers")
            if not vm_name:
                return
            identifiers_dict = uuid_manager.list_vm_identifiers(vm_name)
        else:
            identifiers_dict = uuid_manager.list_vm_identifiers()
        
        if not identifiers_dict:
            print_warning("No VM identifiers found.")
            return
        
        # Display identifiers
        for vm_name, identifiers in identifiers_dict.items():
            print_header(f"VM: {vm_name}")
            print_info(f"Created: {identifiers.created_at}")
            print_info(f"VM UUID: {identifiers.vm_uuid}")
            print_info(f"MAC Address: {identifiers.mac_address}")
            print_info(f"Machine ID: {identifiers.machine_id}")
            print_info(f"Disk UUID: {identifiers.disk_uuid}")
            print_info(f"Partition UUID: {identifiers.partition_uuid}")
            print_info(f"Filesystem UUID: {identifiers.filesystem_uuid}")
            print_info(f"Boot UUID: {identifiers.boot_uuid}")
            print_info(f"Swap UUID: {identifiers.swap_uuid}")
            print_info(f"SMBIOS UUID: {identifiers.smbios_uuid}")
            print_info(f"CPU Serial: {identifiers.cpu_serial}")
            print_info(f"Motherboard Serial: {identifiers.motherboard_serial}")
            print("")
            
    except ImportError:
        print_error("❌ Enhanced UUID manager not available")
    except Exception as e:
        print_error(f"❌ Error displaying identifiers: {e}")


def regenerate_base_image_identifiers():
    """
    Regenerate identifiers when creating a new base image
    
    This should be called when creating a completely new base image
    to ensure it has unique identifiers.
    """
    clear_screen()
    print_header("🔄 Regenerate Base Image Identifiers")
    
    vm_name = select_vm("Regenerate Base Identifiers")
    if not vm_name:
        return
    
    # Stop VM if running
    if is_vm_running(vm_name):
        print_info(f"Stopping VM '{vm_name}' before regenerating base identifiers...")
        stop_vm(vm_name, force=True)
        time.sleep(2)
    
    print_warning("⚠️  This will regenerate identifiers for the base image!")
    print_info("Use this when:")
    print_info("  • Creating a new base image from scratch")
    print_info("  • Cloning a base image from another VM")
    print_info("  • After major system changes")
    
    if not questionary.confirm("Continue with base image identifier regeneration?").ask():
        print_info("Operation cancelled.")
        return
    
    try:
        from linux_vm.uuid_manager import get_uuid_manager
        uuid_manager = get_uuid_manager()
        
        # Generate completely fresh identifiers
        identifiers = uuid_manager.generate_fresh_identifiers(vm_name, force_regenerate=True)
        
        # Reset UEFI variables
        uuid_manager.reset_uefi_variables(vm_name)
        
        # Create post-install script
        uuid_manager.create_post_install_script(vm_name, identifiers)
        
        print_success("✅ Successfully regenerated base image identifiers")
        print_info("New identifiers:")
        print_info(f"  VM UUID: {identifiers.vm_uuid}")
        print_info(f"  MAC Address: {identifiers.mac_address}")
        print_info(f"  Machine ID: {identifiers.machine_id}")
        
        print_info("\n🤖 Next steps:")
        print_info("1. Boot the VM")
        print_info("2. The VM will automatically configure itself on first boot!")
        print_info("3. Manual setup available in shared/SETUP_INSTRUCTIONS.md if needed")
        print_info("4. Create overlay if needed")
        
    except ImportError:
        print_error("❌ Enhanced UUID manager not available")
    except Exception as e:
        print_error(f"❌ Error regenerating base identifiers: {e}")

def uuid_management_menu():
    """
    UUID and System Identifier Management Menu
    
    Provides options for managing VM system identifiers including:
    - Viewing current identifiers
    - Regenerating identifiers
    - Nuclear reset (NUKE)
    - Overlay regeneration
    """
    while True:
        clear_screen()
        print_header("🆔 UUID & System Identifier Management")
        console.rule(style="dim")
        console.print("[yellow]Manage unique system identifiers for Linux VMs[/yellow]")
        console.print("")
        
        try:
            choice = questionary.select(
                "Select an option:",
                choices=[
                    "1. View VM Identifiers",
                    "2. Regenerate Overlay with Fresh Identifiers",
                    "3. Regenerate Base Image Identifiers",
                    "4. 🔥 NUKE VM Session (Complete Reset)",
                    "5. Return to Linux VM Menu"
                ]
            ).ask()
            
            if choice == "1. View VM Identifiers":
                show_vm_identifiers()
            elif choice == "2. Regenerate Overlay with Fresh Identifiers":
                regenerate_overlay_with_fresh_identifiers()
            elif choice == "3. Regenerate Base Image Identifiers":
                regenerate_base_image_identifiers()
            elif choice == "4. 🔥 NUKE VM Session (Complete Reset)":
                nuke_vm_session()
            elif choice == "5. Return to Linux VM Menu":
                break
            else:
                print_warning("Invalid option.")
                continue
                
            if choice != "5. Return to Linux VM Menu":
                questionary.text("\nPress Enter to return to the menu...").ask()
                
        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            print_error(f"Error in UUID management menu: {e}")
            questionary.text("\nPress Enter to continue...").ask()