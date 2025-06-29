# pylint: disable=too-many-lines,too-many-arguments,too-many-locals
# pylint: disable=too-many-return-statements,too-many-branches,too-many-statements
"""
This module handles all Windows VM management functionality.
"""
import os
import sys
import re
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG
from core_utils import (
    Style, print_header, print_info, print_warning, print_error, clear_screen,
    run_command_live, launch_in_new_terminal_and_wait, select_from_list,
    remove_dir, print_success
)


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
    }


def find_iso_path():
    """
    Finds the path to the installation ISO.
    """
    print_header("Select Installation ISO")
    isos = [f for f in os.listdir('.') if f.endswith('.iso')]
    if not isos:
        print_error("No .iso file found in the current directory.")
        return None
    iso_path = select_from_list(isos, "Choose an ISO") if len(isos) > 1 else isos[0]
    iso_abs_path = os.path.abspath(iso_path)
    print_info(f"Using ISO: {iso_abs_path}")
    return iso_abs_path


def get_vm_config(defaults):
    """
    Prompts the user to configure the VM.
    """
    config = {}
    print_header("Configure Virtual Machine")
    while True:
        mem = input(f"{Style.BOLD}Enter Memory (e.g., 4G) "
                    f"[default: {defaults['VM_MEM']}]: {Style.ENDC}").strip().upper() \
              or defaults['VM_MEM']
        if re.match(r"^\d+[MG]$", mem):
            config['VM_MEM'] = mem
            break
        print_warning("Invalid format. Use a number followed by 'M' or 'G'.")
    while True:
        cpu = input(f"{Style.BOLD}Enter CPU cores "
                    f"[default: {defaults['VM_CPU']}]: {Style.ENDC}").strip() \
              or defaults['VM_CPU']
        if cpu.isdigit() and int(cpu) > 0:
            config['VM_CPU'] = cpu
            break
        print_warning("Invalid input.")
    return config


def create_new_windows_vm():
    """
    Creates a new Windows VM.
    """
    clear_screen()
    print_header("Create New Windows VM")

    while True:
        vm_name = input(f"{Style.BOLD}Enter a short name for new VM (e.g., win11): {Style.ENDC}").strip()
        if not re.match(r"^[a-zA-Z0-9_-]+$", vm_name):
            print_warning("Invalid name.")
        elif os.path.exists(os.path.join(CONFIG['VMS_DIR_WINDOWS'], vm_name)):
            print_warning("A VM with this name already exists.")
        else:
            break

    paths = get_vm_paths(vm_name)
    iso_path = find_iso_path()
    if not iso_path:
        return

    virtio_path = find_iso_path()
    if not virtio_path:
        print_warning("VirtIO drivers not found. You may need to manually install them.")

    while True:
        disk = input(f"{Style.BOLD}Enter base disk size (GB) [default: 64]: {Style.ENDC}").strip() or "64"
        if disk.isdigit() and int(disk) > 0:
            break
        else:
            print_warning("Invalid input.")

    vm_settings = get_vm_config({"VM_MEM": CONFIG['VM_MEM'], "VM_CPU": CONFIG['VM_CPU']})
    qemu_cmd = _get_qemu_command(vm_name, vm_settings, {'uuid': str(uuid.uuid4()), 'mac': ''}, iso_path=iso_path, virtio_path=virtio_path)

    commands_to_run = [
        ("Creating directory structure", ["mkdir", "-p", paths['dir']]),
        ("Creating UEFI variable store", ["cp", CONFIG['UEFI_VARS_TEMPLATE'], paths['uefi_vars']]),
        (f"Creating {disk}G base image", ["qemu-img", "create", "-f", "qcow2", paths['base'], f"{disk}G"]),
        ("Booting from ISO (Install your OS, then simply close this terminal window)", qemu_cmd)
    ]
    launch_in_new_terminal_and_wait(commands_to_run)



def _get_qemu_command(vm_name, vm_settings, ids, iso_path=None, virtio_path=None):
    """
    Builds the QEMU command for a Windows VM.
    """
    paths = get_vm_paths(vm_name)
    qemu_cmd = [
        CONFIG["QEMU_BINARY"],
        "-enable-kvm",
        "-m", vm_settings["VM_MEM"],
        "-smp", vm_settings["VM_CPU"],
        "-uuid", ids['uuid'],
        "-drive", f"if=pflash,format=raw,readonly=on,file={CONFIG['UEFI_CODE']}",
        "-drive", f"if=pflash,format=raw,file={paths['uefi_vars']}",
        "-drive", f"file={paths['base']},if=virtio",
        "-netdev", "user,id=n1",
        "-device", "virtio-net-pci,netdev=n1",
        "-vga", "virtio",
        "-device", "usb-tablet",
        *CONFIG["QEMU_DISPLAY"]
    ]

    if iso_path:
        qemu_cmd.extend(["-cdrom", iso_path])
    if virtio_path:
        qemu_cmd.extend(["-drive", f"file={virtio_path},media=cdrom"])

    return qemu_cmd


def run_windows_vm():
    """
    Runs an existing Windows VM.
    """
    clear_screen()
    print_header("Run Existing Windows VM")

    vms_dir = CONFIG['VMS_DIR_WINDOWS']
    if not os.path.isdir(vms_dir) or not os.listdir(vms_dir):
        print_error("No Windows VMs found to list.")
        return

    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])
    if not vm_list:
        print_error("No Windows VMs found.")
        return

    vm_name = select_from_list(vm_list, "Choose a VM to run")
    if not vm_name:
        return

    paths = get_vm_paths(vm_name)
    if not os.path.exists(paths['base']):
        print_error(f"Base disk for '{vm_name}' not found. Cannot run.")
        return

    vm_settings = get_vm_config({"VM_MEM": CONFIG['VM_MEM'], "VM_CPU": CONFIG['VM_CPU']})
    qemu_cmd = _get_qemu_command(vm_name, vm_settings, {'uuid': str(uuid.uuid4()), 'mac': ''})
    launch_in_new_terminal_and_wait([("Booting VM", qemu_cmd)])


def nuke_and_recreate_windows_vm():
    """
    Nukes the identity of a VM and re-patches OpenCore.
    """
    clear_screen()
    print_header("Nuke & Boot a Fresh Session")

    vms_dir = CONFIG['VMS_DIR_WINDOWS']
    if not os.path.isdir(vms_dir) or not os.listdir(vms_dir):
        print_error("No Windows VMs found to list.")
        return

    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])
    if not vm_list:
        print_error("No Windows VMs found.")
        return

    vm_name = select_from_list(vm_list, "Choose a VM to nuke")
    if not vm_name:
        return

    paths = get_vm_paths(vm_name)
    if not os.path.exists(paths['base']):
        print_error(f"Base disk for '{vm_name}' not found. Cannot nuke.")
        return

    if os.path.exists(paths['overlay']):
        print_warning(f"You are about to permanently delete the current session for '{vm_name}'.")
        if input("Are you sure? (y/N): ").strip().lower() != 'y':
            print_info("Operation cancelled.")
            return
        os.remove(paths['overlay'])

    run_command_live(["qemu-img", "create", "-f", "qcow2", "-b", paths['base'], "-F", "qcow2", paths['overlay']], as_root=False, check=True)

    vm_settings = get_vm_config({"VM_MEM": CONFIG['VM_MEM'], "VM_CPU": CONFIG['VM_CPU']})
    qemu_cmd = _get_qemu_command(vm_name, vm_settings, {'uuid': str(uuid.uuid4()), 'mac': ''})
    launch_in_new_terminal_and_wait([("Booting VM", qemu_cmd)])


def delete_windows_vm():
    """
    Completely deletes a Windows VM directory.
    """
    clear_screen()
    print_header("Delete Windows VM Completely")

    vms_dir = CONFIG['VMS_DIR_WINDOWS']
    if not os.path.isdir(vms_dir) or not os.listdir(vms_dir):
        print_error("No Windows VMs found to list.")
        return

    vm_list = sorted([d for d in os.listdir(vms_dir) if os.path.isdir(os.path.join(vms_dir, d))])
    if not vm_list:
        print_error("No Windows VMs found.")
        return

    vm_name = select_from_list(vm_list, "Choose a VM to delete")
    if not vm_name:
        return

    print_warning(f"This will permanently delete the entire VM '{vm_name}', "
                  "including its virtual disk.\nThis action CANNOT be undone.")
    confirm = input(f"To confirm, please type the name of the VM ({vm_name}): ").strip()
    if confirm == vm_name:
        remove_dir(get_vm_paths(vm_name)['dir'])
    else:
        print_error("Confirmation failed. Aborting.")


def windows_vm_menu():
    """
    Displays the Windows VM menu.
    """
    os.makedirs(CONFIG['VMS_DIR_WINDOWS'], exist_ok=True)
    while True:
        clear_screen()
        print(f"\n{Style.HEADER}{Style.BOLD}Windows VM Management{Style.ENDC}\n"
              "───────────────────────────────────────────────")
        print(f"{Style.OKBLUE}1.{Style.ENDC} {Style.BOLD}Create New Windows VM{Style.ENDC}")
        print(f"{Style.OKCYAN}2.{Style.ENDC} {Style.BOLD}Run Existing Windows VM{Style.ENDC}")
        print(f"{Style.OKGREEN}3.{Style.ENDC} {Style.BOLD}Nuke & Boot a Fresh Session{Style.ENDC}")
        print(f"{Style.FAIL}4.{Style.ENDC} {Style.BOLD}Delete Windows VM Completely{Style.ENDC}")
        print(f"{Style.WARNING}5.{Style.ENDC} {Style.BOLD}Return to Main Menu{Style.ENDC}")
        print("───────────────────────────────────────────────")
        choice = input(f"{Style.BOLD}Select an option [1-5]: {Style.ENDC}").strip()
        action_taken = True
        if choice == "1":
            create_new_windows_vm()
        elif choice == "2":
            run_windows_vm()
        elif choice == "3":
            nuke_and_recreate_windows_vm()
        elif choice == "4":
            delete_windows_vm()
        elif choice == "5":
            break
        else:
            print_warning("Invalid option.")
            action_taken = False
        if action_taken:
            input("\nPress Enter to return to the menu...")
