# Made by trex099
# https://github.com/Trex099/Glint
"""
Core utility functions for the Universal VM Manager.

This module provides a collection of helper functions for command execution,
file operations, user interaction, and network configuration.
"""

import os
import subprocess
import shutil
import random
import socket
import shlex
import re
import questionary
from rich.console import Console
from rich.panel import Panel

console = Console()
# Create a dedicated console for printing errors to stderr
error_console = Console(stderr=True, style="bold red")

# --- Text and Styling ---

def print_header(text):
    """Prints a styled header to the console."""
    console.print(Panel(f"[bold cyan]{text}[/]", expand=False, border_style="blue"))

def print_info(text):
    """Prints an informational message to the console."""
    console.print(f"[cyan]ℹ️  {text}[/]")

def print_success(text):
    """Prints a success message to the console."""
    console.print(f"[green]✅ {text}[/]")

def print_warning(text):
    """Prints a warning message to the console."""
    console.print(f"[yellow]⚠️  {text}[/]")

def print_error(text):
    """Prints an error message to the stderr console."""
    error_console.print(f"❌ {text}")

def clear_screen():
    """Clears the console screen."""
    os.system('cls' if os.name == 'nt' else 'clear')

# --- Command Execution ---

def run_command_live(cmd_list, as_root=False, check=True, quiet=False):
    """
    Runs a command and prints its output live, with improved error handling.
    Returns the command's output as a string if successful, otherwise None.
    """
    if as_root and os.geteuid() != 0:
        cmd_list.insert(0, "sudo")

    cmd_str = ' '.join(shlex.quote(s) for s in cmd_list)
    if not quiet:
        console.print(f"\n[blue]▶️  Executing: {cmd_str}[/]")

    try:
        process = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if quiet else subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding='utf-8'
        )

        output_lines = []
        with process.stdout:
            for line in iter(process.stdout.readline, ''):
                if not quiet:
                    console.print(f"  {line.strip()}", highlight=False)
                output_lines.append(line)
        
        return_code = process.wait()

        if check and return_code != 0:
            stderr_output = process.stderr.read() if quiet else "".join(output_lines)
            raise subprocess.CalledProcessError(
                return_code, cmd_list, output="".join(output_lines), stderr=stderr_output
            )
        
        return "".join(output_lines)

    except FileNotFoundError:
        print_error(f"Command not found: '{cmd_list[0]}'. Please ensure it is installed and in your PATH.")
        return None
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed with exit code {e.returncode}: {e.cmd}")
        if not quiet:
            # Output was already printed live
            pass
        elif e.stderr:
            print_error(f"Stderr:\n{e.stderr.strip()}")
        elif e.output:
            print_error(f"Output:\n{e.output.strip()}")
        return None
    except Exception as e:
        print_error(f"An unexpected error occurred while running command: {e}")
        return None


def _run_command(cmd, as_root=False):
    """
    Runs a command and returns its stripped output.
    Raises exceptions on failure for the caller to handle.
    """
    if as_root and os.geteuid() != 0:
        cmd.insert(0, "sudo")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8'
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        # Re-raise the exception to be handled by the caller
        raise e


def _create_launcher_script(script_path, commands, as_root=False):
    """
    Dynamically creates a shell script to run a series of commands in a new terminal.
    """
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write("#!/bin/bash\nset -e\n")
        
        if 'XDG_RUNTIME_DIR' in os.environ:
            f.write(f"export XDG_RUNTIME_DIR={os.environ['XDG_RUNTIME_DIR']}\n")

        f.write("echo '--- VM LAUNCHER (This terminal will close when the VM shuts down) ---\n\n'")
        
        for i, (title, cmd_list) in enumerate(commands):
            # The last command should use 'exec' to replace the shell process
            final_cmd = "exec " if i == len(commands) - 1 else ""
            
            # Sudo should be applied to the command itself, not the launcher script
            if as_root and os.geteuid() != 0:
                cmd_list.insert(0, "sudo")
                
            quoted_cmd = ' '.join(shlex.quote(s) for s in cmd_list)
            f.write(f"echo '▶️  {title}...'\\n"
                    f"{final_cmd}{quoted_cmd}\\n\\n")
            
    os.chmod(script_path, 0o755)


def get_terminal_command(shell_script_path):
    """
    Returns the full command list to launch a script in a new terminal.
    """
    terminals = {'konsole': '-e', 'gnome-terminal': '--', 'xfce4-terminal': '-x', 'xterm': '-e'}
    for term, arg in terminals.items():
        if shutil.which(term):
            return [term, arg, 'bash', shell_script_path]
    return None


def launch_in_new_terminal_and_wait(commands, as_root_script=False):
    """
    Generates and executes a launcher script in a new terminal, waiting for it to complete.
    Ensures robust cleanup of the temporary script.
    """
    script_path = f"/tmp/vm_launcher_{os.getpid()}_{random.randint(1000, 9999)}.sh"
    
    try:
        _create_launcher_script(script_path, commands, as_root=as_root_script)
        terminal_cmd = get_terminal_command(script_path)

        if not terminal_cmd:
            print_error("No supported terminal found (konsole, gnome-terminal, etc.).")
            print_info(f"Launcher script created at: {script_path}")
            print_warning("Please run the script manually from the launcher file.")
            return False

        print_info("Launching VM in a new terminal window... The script will wait for it to close.")
        
        # Use Popen to wait for the terminal process to complete
        process = subprocess.Popen(terminal_cmd)
        process.wait()
        
        print_info("VM process has terminated.")
        return True

    finally:
        # Robustly remove the script file
        try:
            if os.path.exists(script_path):
                os.remove(script_path)
        except OSError as e:
            print_warning(f"Could not remove temporary launcher script {script_path}: {e}")


# --- File and Directory Operations ---

def remove_file(path, as_root=False):
    """Removes a file, handling permissions."""
    try:
        if as_root:
            run_command_live(['rm', '-f', path], as_root=True, check=True, quiet=True)
        else:
            os.remove(path)
        print_success(f"Removed: {path}")
        return True
    except (OSError, subprocess.CalledProcessError) as e:
        print_error(f"Could not remove file {path}: {e}")
        return False


def remove_dir(path):
    """Removes a directory and its contents."""
    try:
        shutil.rmtree(path)
        print_success(f"Deleted directory: {os.path.basename(path)}")
        return True
    except OSError as e:
        print_error(f"Could not delete directory {path}: {e}")
        return False

# --- User Interaction ---

def get_disk_size(prompt, default_size):
    """
    Prompts the user for a disk size and validates the input.
    Accepts formats like '80G', '80g', '80GB', or just a number (assumes GB).
    """
    while True:
        disk_size_input = questionary.text(f"{prompt} [default: {default_size}]:").ask().strip().upper() or default_size
        
        # Remove GB, G, etc. and check if the rest is a digit
        size_val = re.sub(r'(G|GB|M|MB|T|TB)', '', disk_size_input)
        
        if size_val.isdigit():
            # If only a number was entered, append 'G'
            if disk_size_input.isdigit():
                return f"{disk_size_input}G"
            # Otherwise, return the value as is (e.g., '80G')
            return disk_size_input
        
        print_warning("Invalid format. Please enter a number, optionally followed by G, GB, M, etc. (e.g., 80G, 512M).")


def get_vm_config(defaults):
    """
    Prompts the user to configure the VM's memory and CPU cores.
    """
    config = {}
    print_header("Configure Virtual Machine")
    
    while True:
        mem_prompt = f"Enter Memory (e.g., 8G) [default: {defaults['VM_MEM']}]: "
        mem = questionary.text(mem_prompt).ask().strip().upper() or defaults['VM_MEM']
        if re.match(r"^\d+[MG]$", mem):
            config['VM_MEM'] = mem
            break
        print_warning("Invalid format. Use a number followed by 'M' or 'G' (e.g., 8G, 4096M).")
        
    while True:
        cpu_prompt = f"Enter CPU cores [default: {defaults['VM_CPU']}]: "
        cpu = questionary.text(cpu_prompt).ask().strip() or defaults['VM_CPU']
        if cpu.isdigit() and int(cpu) > 0:
            config['VM_CPU'] = cpu
            break
        print_warning("Invalid input. Please enter a positive number.")
        
    return config

def find_iso_path(prompt_text="Select Installation ISO"):
    """
    Finds and allows selection of an installation ISO from the current directory.
    """
    print_header(prompt_text)
    try:
        isos = [f for f in os.listdir('.') if f.endswith('.iso')]
        if not isos:
            print_error("No .iso file found in the current directory.")
            return None
        
        if len(isos) > 1:
            iso_path = select_from_list(isos, "Choose an ISO")
        else:
            iso_path = isos[0]
            
        if iso_path:
            iso_abs_path = os.path.abspath(iso_path)
            print_info(f"Using ISO: {iso_abs_path}")
            return iso_abs_path
    except OSError as e:
        print_error(f"Error reading current directory: {e}")
    return None

def select_from_list(items, prompt, display_key=None):
    """
    Prompts the user to select an item from a list with robust error handling.
    """
    if not items:
        print_warning("No items to select from.")
        return None

    choices = []
    for item in items:
        display_text = item.get(display_key) if display_key and isinstance(item, dict) else os.path.basename(item)
        choices.append(questionary.Choice(title=display_text, value=item))

    try:
        # Define a consistent style for the prompt
        custom_style = questionary.Style([
            ('selected', 'fg:#673ab7 bold'),
            ('highlighted', 'fg:#673ab7 bold'),
            ('pointer', 'fg:#673ab7 bold'),
        ])
        
        selection = questionary.select(
            message=prompt,
            choices=choices,
            use_indicator=True,
            style=custom_style
        ).ask()
        
        # .ask() returns None if the user cancels (e.g., with Ctrl+C or Esc)
        return selection
        
    except (KeyboardInterrupt):
        # Explicitly handle KeyboardInterrupt to prevent crash
        print_info("\nSelection cancelled by user.")
        return None
    except Exception as e:
        # Catch any other unexpected errors from questionary
        print_error(f"An unexpected error occurred during selection: {e}")
        return None


# --- Network Utilities ---

def find_host_dns():
    """
    Finds the best DNS server from the host's resolv.conf.
    Skips local addresses and falls back to a public DNS.
    """
    try:
        with open("/etc/resolv.conf", "r", encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith("nameserver"):
                    dns_server = line.strip().split()[1]
                    if not dns_server.startswith("127."):
                        print_info(f"Found non-local DNS server: {dns_server}")
                        return dns_server
    except FileNotFoundError:
        pass
    print_warning("No non-local DNS server found, falling back to 8.8.8.8.")
    return "8.8.8.8"


def find_unused_port():
    """Finds an unused TCP port on the host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def setup_bridge_network():
    """
    Returns a reliable 'user' network configuration for QEMU.
    """
    print_header("Network Configuration")
    print_info("Using reliable 'user' networking mode for maximum compatibility.")
    dns_server = find_host_dns()
    return f"user,id=net0,dns={dns_server}"

# --- File Downloads ---

import requests
from tqdm import tqdm

def download_file(url, destination):
    """
    Downloads a file from a URL to a destination, with a progress bar.
    """
    try:
        with requests.get(url, stream=True, timeout=10) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            with open(destination, 'wb') as f, tqdm(
                total=total_size, unit='B', unit_scale=True, desc=os.path.basename(destination)
            ) as pbar:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    pbar.update(len(chunk))
        print_success(f"Downloaded '{os.path.basename(destination)}' successfully.")
        return True
    except requests.exceptions.RequestException as e:
        print_error(f"Failed to download {url}: {e}")
        return False
    except KeyboardInterrupt:
        print_error("\nDownload cancelled by user.")
        if os.path.exists(destination):
            os.remove(destination)
        return False

# --- System Information ---

def find_first_existing_path(path_list):
    """
    Finds the first path in a list that exists on the filesystem.
    Returns the path as a string, or None if no path is found.
    """
    for path in path_list:
        if os.path.exists(path):
            return path
    return None

def identify_iso_type(iso_path):
    """
    Identifies the type of OS in an ISO file by checking for characteristic files.
    Returns 'windows', 'linux', 'macos', 'virtio', or 'unknown'.
    """
    if not os.path.exists(iso_path) or not iso_path.lower().endswith('.iso'):
        return 'unknown'

    try:
        result = subprocess.run(
            ["isoinfo", "-f", "-i", iso_path],
            capture_output=True, text=True, check=True,
            encoding='utf-8', errors='ignore'
        )
        files_in_iso = {path.strip().lower().lstrip('/') for path in result.stdout.splitlines()}

        # macOS check (high priority)
        # Look for the app bundle or the BaseSystem.dmg within an 'Install' directory
        if any(f.startswith('install macos') and f.endswith('.app/contents/sharedsupport/basesystem.dmg') for f in files_in_iso) or \
           any('install macos' in f and 'basesystem.dmg' in f for f in files_in_iso) or \
           'applications/install macos' in ''.join(files_in_iso):
            return 'macos'

        # VirtIO check
        if any('viostor/' in path for path in files_in_iso):
            return 'virtio'

        # Windows check
        if 'sources/boot.wim' in files_in_iso or 'boot/boot.sdi' in files_in_iso:
            return 'windows'
            
        # Linux check
        if any(path.startswith(('isolinux/', 'boot/syslinux/', 'boot/grub/')) or 'vmlinuz' in path or 'vmlinux' in path for path in files_in_iso):
            return 'linux'

    except (subprocess.CalledProcessError, FileNotFoundError):
        return 'unknown'
        
    return 'unknown'

def get_host_gpus():
    """
    Scans and identifies host GPUs using lspci.
    Returns a list of dictionaries, each representing a GPU.
    """
    gpus = []
    try:
        # Execute lspci and capture output
        lspci_output = subprocess.check_output(
            ["lspci", "-nn"],
            text=True,
            stderr=subprocess.PIPE
        ).strip()

        # Regex to find VGA compatible controllers and 3D controllers
        gpu_pattern = re.compile(
            r"^([0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)\s"  # PCI Address (e.g., 01:00.0)
            r"(VGA compatible controller|3D controller)\s"          # Device Type
            r":\s(.+)\s"                              # Description (e.g., NVIDIA Corporation...)
            r"\[([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\]"     # Vendor:Device ID (e.g., [10de:1f08])
            r"(?:\s\(rev\s([a-zA-Z0-9]{2})\))?",       # Revision (optional)
            re.MULTILINE
        )

        for match in gpu_pattern.finditer(lspci_output):
            pci_address, _, description, vendor_device, _ = match.groups()
            
            # Determine if it's an iGPU (typically Intel) or dGPU
            gpu_type = "iGPU" if "intel" in description.lower() else "dGPU"

            gpus.append({
                "pci_address": pci_address,
                "description": description.strip(),
                "vendor_device": vendor_device,
                "type": gpu_type,
                "display_name": f"{gpu_type} - {description.strip()} ({pci_address})"
            })
        
        if not gpus:
            print_warning("No GPUs found via lspci. Passthrough may not be possible.")

    except FileNotFoundError:
        print_error("`lspci` command not found. Please install pciutils.")
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to run lspci: {e.stderr}")
    
    return gpus


def detect_distro():
    """
    Detects the Linux distribution from /etc/os-release.
    """
    try:
        with open("/etc/os-release", "r", encoding='utf-8') as f:
            for line in f:
                if line.startswith("ID="):
                    return line.strip().split("=")[1].lower().strip('"')
    except FileNotFoundError:
        return None
    return None

# --- Passthrough Safety Checks ---

def is_vfio_module_loaded():
    """Checks if the vfio-pci kernel module is loaded."""
    try:
        result = subprocess.run(['lsmod'], capture_output=True, text=True, check=True)
        return 'vfio_pci' in result.stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

def get_active_gpu_pci_address():
    """
    Identifies the PCI address of the GPU currently driving the display.
    Returns the PCI address string or None if it can't be determined.
    """
    try:
        # This command finds the boot VGA controller, which is a reliable way
        # to identify the primary GPU handling the initial display.
        lspci_output = subprocess.check_output(
            ["lspci", "-nn"],
            text=True,
            stderr=subprocess.PIPE
        ).strip()
        
        boot_vga_pattern = re.compile(r"^([0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)\sVGA compatible controller.*\[boot\]", re.MULTILINE)
        match = boot_vga_pattern.search(lspci_output)
        
        if match:
            return match.group(1)

        # Fallback for systems that don't use the [boot] flag clearly
        # Check for the driver in use by the DRM subsystem
        drm_path = "/sys/class/drm/"
        for card in os.listdir(drm_path):
            if card.startswith("card"):
                device_path = os.path.join(drm_path, card, "device")
                if os.path.islink(device_path):
                    # The target of the symlink is the PCI device path
                    pci_path = os.readlink(device_path)
                    return os.path.basename(pci_path) # e.g., 0000:01:00.0 -> 01:00.0
                    
    except (FileNotFoundError, subprocess.CalledProcessError, NotADirectoryError):
        return None
    return None


def get_iommu_group_devices(pci_address):
    """
    Finds all devices in the same IOMMU group as the given PCI device.
    Returns a list of device descriptions.
    """
    iommu_devices = []
    try:
        # Construct the path to the IOMMU group for the given device
        device_path = f"/sys/bus/pci/devices/0000:{pci_address}"
        if not os.path.exists(device_path):
            return [] # Device not found

        iommu_group_path = os.path.realpath(os.path.join(device_path, "iommu_group", "devices"))
        
        if not os.path.isdir(iommu_group_path):
            return []

        # Get lspci output to map PCI addresses to names
        lspci_output = subprocess.check_output(["lspci"], text=True).strip()
        
        for device_link in os.listdir(iommu_group_path):
            # device_link is like '0000:01:00.0'
            # We need to match this with the lspci output
            device_pci_addr = device_link.split(":")[-1] # e.g., 01:00.0
            
            for line in lspci_output.splitlines():
                if line.startswith(device_pci_addr):
                    # Don't add the original GPU to the list of "other" devices
                    if device_pci_addr != pci_address:
                        iommu_devices.append(line)
                    break
                    
    except (FileNotFoundError, subprocess.CalledProcessError, NotADirectoryError):
        return []
        
    return iommu_devices
