import os
import sys
import pexpect
import questionary
from rich.console import Console

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core_utils import (
    print_header, print_info, print_success, print_warning, print_error
)

console = Console()

def _get_vm_ip(vm_type):
    """
    Returns the default IP address for a given VM type.
    """
    return "10.0.2.15"

def _get_vm_ssh_port(vm_dir):
    """
    Retrieves the SSH port for a running VM from its session file.
    """
    session_info_file = os.path.join(vm_dir, 'session.info')
    if not os.path.exists(session_info_file):
        return None
    
    try:
        with open(session_info_file, 'r', encoding='utf-8') as f:
            return int(f.read().strip())
    except (IOError, ValueError):
        return None

def _install_ssh_server_instructions(vm_type):
    """
    Provides instructions for enabling the SSH server on the guest.
    """
    if vm_type == "macos":
        print_warning("SSH Server (Remote Login) may not be enabled on the macOS guest.")
        print_info("To enable it, please run this command inside your macOS VM's Terminal:")
        console.print("  [bold]sudo systemsetup -setremotelogin on[/]", highlight=False)
    elif vm_type == "linux":
        print_warning("SSH server may not be running or installed on the Linux guest.")
        print_info("You may need to install 'openssh-server' and ensure the 'sshd' service is running.")
        console.print("Example for Debian/Ubuntu: [bold]sudo apt update && sudo apt install openssh-server[/]", highlight=False)
        console.print("Example for Arch Linux: [bold]sudo pacman -S openssh[/]", highlight=False)
    elif vm_type == "windows":
        print_warning("OpenSSH Server may not be enabled on the Windows guest.")
        print_info("To enable it, open PowerShell as an Administrator inside the VM and run:")
        console.print("  [bold]Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0[/]", highlight=False)
        console.print("  [bold]Start-Service sshd[/]", highlight=False)

def transfer_files_menu(vm_name, vm_type, vm_dir):
    """
    Main menu for handling file transfers.
    """
    print_header(f"File Transfer for '{vm_name}' ({vm_type.capitalize()})")

    vm_info = None
    if vm_type == "linux":
        from linux_vm import get_running_vm_info
        vm_info = get_running_vm_info(vm_name)
    elif vm_type == "macos":
        from macos_vm import get_running_vm_info
        vm_info = get_running_vm_info(vm_name)
    elif vm_type == "windows":
        from windows_vm import get_running_vm_info
        vm_info = get_running_vm_info(vm_name)

    if not vm_info or not vm_info.get('port'):
        print_error("Could not determine the SSH port for the running VM.")
        print_info("Please ensure the VM was started with Glint and is currently running.")
        return

    ssh_port = vm_info['port']
    
    print_info(f"This utility uses SFTP (SSH File Transfer Protocol) via port {ssh_port}.")
    _install_ssh_server_instructions(vm_type)
    
    vm_user = questionary.text("Please enter your username inside the VM:").ask()
    if not vm_user:
        print_error("Username cannot be empty.")
        return

    vm_password = questionary.password("Please enter your password for the VM:").ask()

    direction = questionary.select(
        "What would you like to do?",
        choices=["Copy files FROM your computer TO the VM", "Copy files FROM the VM TO your computer"]
    ).ask()
    if not direction:
        return

    local_path = questionary.text("Enter the path on your LOCAL computer:").ask()
    if not os.path.exists(local_path):
        print_error(f"Local path not found: {local_path}")
        return

    remote_path = questionary.text("Enter the path in the VM (e.g., 'Desktop' or '~/Documents'):").ask()

    if "TO the VM" in direction:
        src = local_path
        dest = f"{vm_user}@localhost:{remote_path}"
    else:
        src = f"{vm_user}@localhost:{remote_path}"
        dest = local_path

    scp_cmd = f"scp -r -P {ssh_port} '{src}' '{dest}'"
    
    try:
        print_info("Starting file transfer...")
        child = pexpect.spawn(scp_cmd, timeout=None) # No timeout for large files
        
        # Handle password prompt and host key checking
        index = child.expect(['(yes/no)', 'password:', pexpect.EOF, pexpect.TIMEOUT], timeout=15)

        if index == 0: # Host key check
            child.sendline('yes')
            child.expect('password:')
            child.sendline(vm_password)
        elif index == 1: # Password prompt
            child.sendline(vm_password)
        elif index == 2: # EOF
            print_error("Connection failed before password prompt. Is the SSH server running?")
            print_info(f"Debug output:\n{child.before.decode()}")
            return
        else: # Timeout
            print_error("Connection timed out.")
            return

        child.logfile_read = sys.stdout.buffer
        child.expect(pexpect.EOF)
        child.close()
        
        if child.exitstatus == 0:
            print_success("File transfer completed successfully.")
        else:
            print_error(f"File transfer failed with exit code {child.exitstatus}.")
            print_info(f"Debug output:\n{child.before.decode()}")

    except pexpect.exceptions.ExceptionPexpect as e:
        print_error(f"An error occurred during the file transfer: {e}")

