# Made by trex099
# https://github.com/Trex099/Glint
"""
Core utility functions for the Universal VM Manager.

This module provides a collection of helper functions for command execution,
file operations, user interaction, and network configuration.
"""
import tempfile
import os
import subprocess
import shutil
import random
import socket
import shlex
import re
import time
import questionary
# from rich.markup import escape
from rich.console import Console
from rich.panel import Panel
import sys

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
    """
    DIAGNOSTIC MODE: Prints raw, unformatted text to stderr to avoid all
    rich markup errors and guarantee the error message is visible.
    """
    # We use a standard print to the system's stderr stream.
    # This completely bypasses the rich library and its formatting.
    print(f"❌ {text}", file=sys.stderr)

def clear_screen():
    """Clears the console screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def wait_for_enter(message="Press Enter to continue..."):
    """
    Unified utility to wait for user to press Enter.
    
    Handles ESC and Ctrl+C gracefully (just returns, doesn't crash).
    Uses questionary for consistent styling across the app.
    """
    try:
        questionary.text(f"\n{message}").ask()
    except (KeyboardInterrupt, EOFError):
        # User pressed ESC or Ctrl+C - just return without crashing
        pass


class UserCancelled(Exception):
    """Exception raised when user cancels an operation via ESC or Ctrl+C."""
    pass


def safe_ask(prompt_result):
    """
    Safely handle questionary .ask() result.
    
    If user pressed ESC/Ctrl+C (returns None), raises UserCancelled.
    Otherwise returns the result.
    
    Usage:
        result = safe_ask(questionary.text("Name:").ask())
        # If user cancels, UserCancelled is raised
        # Otherwise result contains the user's input
    """
    if prompt_result is None:
        raise UserCancelled("Operation cancelled by user")
    return prompt_result


def safe_text_ask(prompt, default="", allow_empty=False):
    """
    Safely ask for text input with proper cancellation handling.
    
    Args:
        prompt: The prompt to display
        default: Default value if user enters empty string
        allow_empty: If True, empty input returns empty string; if False, returns default
    
    Returns:
        User input (stripped) or default value
        
    Raises:
        UserCancelled if user presses ESC/Ctrl+C
    """
    result = questionary.text(prompt).ask()
    if result is None:
        raise UserCancelled("Operation cancelled by user")
    
    stripped = result.strip()
    if not stripped and not allow_empty:
        return default
    return stripped

# --- Command Execution --

      
def get_host_screen_resolution():
    """
    Tries to get the primary monitor's screen resolution using tkinter.
    Returns a string 'WIDTHxHEIGHT' or None if it fails.
    """
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw() # Hide the main window
        width = root.winfo_screenwidth()
        height = root.winfo_screenheight()
        root.destroy()
        return f"{width}x{height}"
    except Exception:
        # This can fail on systems without a running X server (headless)
        return None

      
      
      
def run_command_live(cmd_list, as_root=False, check=True, quiet=False):
    """
    Runs a command and prints its output live, with improved error handling.
    Returns the command's output as a string if successful, otherwise None.
    """
    # Make a copy to avoid mutating the original list (security/correctness fix)
    cmd_list = list(cmd_list)
    
    if as_root and os.geteuid() != 0:
        cmd_list.insert(0, "sudo")

    cmd_str = ' '.join(shlex.quote(s) for s in cmd_list)
    if not quiet:
        console.print(f"\n[blue]▶️  Executing: {cmd_str}[/]")

    try:
        process = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            # Use errors='ignore' to prevent crashes on weird characters from subprocesses
            encoding='utf-8',
            errors='ignore'
        )

        output_lines = []
        # Do NOT use a 'with' block on process.stdout, as it closes the stream.
        # We iterate over the output line by line until the process ends.
        for line in iter(process.stdout.readline, ''):
            if not quiet:
                console.print(f"  {line.strip()}", highlight=False)
            output_lines.append(line)

        # Wait for the process to terminate and get the return code and stderr
        return_code = process.wait()
        stderr_output = process.stderr.read()

        # Join the captured lines to form the full stdout
        stdout_output = "".join(output_lines)

        if check and return_code != 0:
            # Raise an error, making sure to include the captured stderr
            raise subprocess.CalledProcessError(
                return_code, cmd_list, output=stdout_output, stderr=stderr_output
            )
        
        return stdout_output

    except FileNotFoundError:
        print_error(f"Command not found: '{cmd_list[0]}'. Please ensure it is installed and in your PATH.")
        return None
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed with exit code {e.returncode}: {e.cmd}")
        # ALWAYS print stderr if it exists, as it's the most likely source of the error
        if e.stderr:
            error_console.print(f"[bold red]Error Details (stderr):[/]\n{e.stderr.strip()}")
        elif e.output and not quiet:
            # If no stderr, but there was output, show that.
            print_error(f"Output:\n{e.output.strip()}")
        return None
    except Exception as e:
        print_error(f"An unexpected error occurred while running command: {e}")
        return None

      

def run_guestfs_command(cmd_list, as_root=True, check=True, quiet=False):
    """
    Runs a libguestfs command. This assumes the system's libguestfs
    is correctly configured to use the appliance backend for APFS.
    """
    if not quiet:
        console.print(f"\n[blue]▶️  Executing GuestFS Command: {' '.join(shlex.quote(s) for s in cmd_list)}[/]")
    
    # We pass no special environment, relying on the system's default
    # (which should be the appliance backend after a proper install).
    return run_command_live(cmd_list, as_root=as_root, check=check, quiet=quiet)
    

def get_vm_status(vm_dir):
    """
    Safely checks if a VM process is running by checking its PID file
    and retrieves session information like SSH port if available.
    """
    pid_file = os.path.join(vm_dir, "qemu.pid")
    session_info_file = os.path.join(vm_dir, "session.info")

    if not os.path.exists(pid_file):
        return None, None

    try:
        with open(pid_file, 'r', encoding='utf-8') as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # Check if process exists

        session_info = None
        if os.path.exists(session_info_file):
            with open(session_info_file, 'r', encoding='utf-8') as f:
                # Attempt to read as simple port, fallback to key-value
                content = f.read().strip()
                if content.isdigit():
                    session_info = {'port': int(content)}
                else:
                    # Simple key-value parser
                    info = {}
                    for line in content.splitlines():
                        if '=' in line:
                            key, value = line.split('=', 1)
                            info[key.strip()] = value.strip()
                    session_info = info

        return pid, session_info
    except (IOError, ValueError, ProcessLookupError, OSError):
        # Cleanup stale files if process is not running
        files_to_clean = [pid_file, session_info_file]
        for f in files_to_clean:
            if os.path.exists(f):
                remove_file(f, quiet=True) # Assuming remove_file can be quiet
        return None, None


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
            f.write(f"echo '▶️  {title}...\n")
            f.write(f"{final_cmd}{quoted_cmd}\n\n")
            
    os.chmod(script_path, 0o755)


def get_terminal_command(shell_script_path):
    """
    Returns the full command list to launch a script in a new terminal.
    """
    terminals = {
        'konsole': ['-e'],
        'gnome-terminal': ['--'],
        'xfce4-terminal': ['-x'],
        'alacritty': ['-e'],
        'kitty': ['--'],
        'xterm': ['-e']
    }
    for term, args in terminals.items():
        if shutil.which(term):
            return [term] + args + ['bash', shell_script_path]
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
    
    Returns:
        Disk size string (e.g., '80G') or None if user cancelled
    """
    while True:
        result = questionary.text(f"{prompt} [default: {default_size}]:").ask()
        
        # Handle user cancellation (ESC/Ctrl+C)
        if result is None:
            return None
        
        disk_size_input = result.strip().upper() or default_size
        
        # Remove GB, G, etc. and check if the rest is a digit
        size_val = re.sub(r'(G|GB|M|MB|T|TB)', '', disk_size_input)
        
        if size_val.isdigit():
            # If only a number was entered, append 'G'
            if disk_size_input.isdigit():
                return f"{disk_size_input}G"
            # Otherwise, return the value as is (e.g., '80G')
            return disk_size_input
        
        print_warning("Invalid format. Please enter a number, optionally followed by G, GB, M, etc. (e.g., 80G, 512M).")


def get_vm_config(defaults, header_text="Configure Virtual Machine", include_networking=False):
    """
    Prompts the user to configure the VM's memory, CPU cores, and optionally networking.
    
    Returns:
        Config dictionary or None if user cancelled
    """
    config = {}
    print_header(header_text)
    
    while True:
        mem_prompt = f"Enter Memory (e.g., 8G) [default: {defaults['VM_MEM']}]: "
        result = questionary.text(mem_prompt).ask()
        if result is None:
            return None  # User cancelled
        mem = result.strip().upper() or defaults['VM_MEM']
        if re.match(r"^\d+[MG]$", mem):
            config['VM_MEM'] = mem
            break
        print_warning("Invalid format. Use a number followed by 'M' or 'G' (e.g., 8G, 4096M).")
        
    while True:
        cpu_prompt = f"Enter CPU cores [default: {defaults['VM_CPU']}]: "
        result = questionary.text(cpu_prompt).ask()
        if result is None:
            return None  # User cancelled
        cpu = result.strip() or defaults['VM_CPU']
        if cpu.isdigit() and int(cpu) > 0:
            config['VM_CPU'] = cpu
            break
        print_warning("Invalid input. Please enter a positive number.")
    
    # Add networking choice if requested
    if include_networking:
        networking_choice = questionary.select(
            "🌐 Select networking mode:",
            choices=[
                questionary.Choice("NAT (faster, isolated)", value="nat"),
                questionary.Choice("Bridged (slower, direct network access)", value="bridged")
            ],
            use_indicator=True
        ).ask()
        
        if networking_choice == 'bridged':
            # Setup bridge networking using existing implementation
            try:
                from linux_vm.networking.bridge import get_bridge_manager
                bridge_manager = get_bridge_manager()
                
                # Check if default bridge exists, create if not
                bridges = bridge_manager.list_bridges()
                if 'br0' not in bridges:
                    print_info("🔧 Setting up bridge networking...")
                    success = bridge_manager.create_bridge(
                        name='br0',
                        description='Default VM bridge for Glint'
                    )
                    if success:
                        print_success("✅ Bridge networking ready")
                    else:
                        print_warning("⚠️  Bridge setup failed, falling back to NAT")
                        networking_choice = 'nat'
                else:
                    print_success("✅ Using existing bridge br0")
                    
            except Exception as e:
                print_warning(f"⚠️  Bridge setup failed: {e}")
                print_info("Falling back to NAT networking")
                networking_choice = 'nat'
        
        config['NETWORKING_MODE'] = networking_choice or 'nat'
        
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
        if isinstance(item, questionary.Separator):
            choices.append(item)
            continue
            
        display_text = item.get(display_key) if display_key and isinstance(item, dict) else os.path.basename(str(item))
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

def manage_firewall_rule(port, action='add'):
    """
    Intelligently adds or removes a firewall rule for a given port, supporting ufw and firewalld.
    Returns True on success or if no action is needed, False on failure.
    """
    fw_manager = None
    if shutil.which("ufw"):
        fw_manager = "ufw"
    elif shutil.which("firewall-cmd"):
        fw_manager = "firewalld"
    else:
        return True # No supported firewall, so we can't fail.

    # --- Intelligent State Check ---
    is_active = False
    if fw_manager == "ufw":
        status_output = run_command_live(['ufw', 'status'], as_root=True, check=False, quiet=True)
        if status_output and "active" in status_output.lower():
            is_active = True
    elif fw_manager == "firewalld":
        status_output = run_command_live(['firewall-cmd', '--state'], as_root=True, check=False, quiet=True)
        if status_output and "running" in status_output.lower():
            is_active = True

    if not is_active:
        print_success(f"Firewall ({fw_manager}) is not active. No rule needed.")
        return True # Success, because no rule is required.

    action_text = "Opening" if action == 'add' else "Closing"
    print_info(f"{action_text} port {port} on the host firewall ({fw_manager})...")

    cmd = []
    if fw_manager == "ufw":
        if action == 'add':
            cmd = ['ufw', 'allow', str(port), '/tcp', 'comment', 'Glint-VNC-Rule']
        else: # 'remove'
            cmd = ['ufw', 'delete', 'allow', str(port), '/tcp']
    elif fw_manager == "firewalld":
        if action == 'add':
            cmd = ['firewall-cmd', f'--add-port={port}/tcp']
        else: # 'remove'
            cmd = ['firewall-cmd', f'--remove-port={port}/tcp']

    # Use check=True to ensure we fail if the command doesn't work.
    if run_command_live(cmd, as_root=True, check=True):
        print_success(f"Port {port} has been successfully {'opened' if action == 'add' else 'closed'}.")
        return True
    else:
        print_error(f"Failed to {'open' if action == 'add' else 'close'} port {port}. Please check permissions.")
        return False
    
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
    
def get_host_ips():
    """
    Finds all non-local IPv4 addresses for the host machine.
    """
    ips = []
    try:
        # Using `ip addr` is the most reliable method on modern Linux
        result = subprocess.run(['ip', '-4', 'addr'], capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if 'inet' in line and 'global' in line:
                # Example: "    inet 192.168.1.50/24 brd 192.168.1.255 scope global dynamic noprefixroute wlan0"
                ip = line.strip().split()[1].split('/')[0]
                ips.append(ip)
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Fallback for systems without `ip` or if it fails
        try:
            hostname = socket.gethostname()
            # This can sometimes return 127.0.0.1, so it's a fallback
            ip = socket.gethostbyname(hostname)
            if not ip.startswith("127."):
                ips.append(ip)
        except socket.gaierror:
            pass # Could not resolve hostname
    
    if not ips:
        # If all else fails, inform the user
        return ["<COULD_NOT_DETECT_IP>"]
        
    return ips    


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
    Uses guestfish as a robust fallback for complex ISOs like UDF.
    """
    if not os.path.exists(iso_path) or not iso_path.lower().endswith('.iso'):
        return 'unknown'

    files_in_iso = set()
    try:
        # First, try isoinfo, which is fast and common
        result = subprocess.run(
            ["isoinfo", "-f", "-i", iso_path],
            capture_output=True, text=True, check=True,
            encoding='utf-8', errors='ignore'
        )
        files_in_iso = {path.strip().lower().lstrip('/') for path in result.stdout.splitlines()}
        
        # If isoinfo returns a tiny file list, it's likely an image it can't read.
        # Fallback to guestfish, which is more powerful.
        if len(files_in_iso) < 10 and shutil.which("guestfish"):
            print_info(f"ISO '{os.path.basename(iso_path)}' requires deep inspection. Using guestfish...")
            # This more complex command sequence can handle non-standard bootable ISOs
            # that don't have a standard partition table.
            try:
                guestfish_cmd = ["guestfish", "--ro", "-a", iso_path]
                commands = "run\nmount /dev/sda /\nfind /\n"
                result = subprocess.run(
                    guestfish_cmd,
                    input=commands,
                    capture_output=True, text=True, check=True,
                    encoding='utf-8', errors='ignore'
                )
                files_in_iso = {path.strip().lower().lstrip('/') for path in result.stdout.splitlines()}
            except (subprocess.CalledProcessError, FileNotFoundError):
                # This can happen if the ISO is truly unreadable.
                pass # We'll just use the (likely empty) files_in_iso set from isoinfo

    except (subprocess.CalledProcessError, FileNotFoundError):
        # If all methods fail, we can't know the type.
        return 'unknown'

    # --- OS Identification Logic ---
    try:
        # macOS check (high priority)
        if any(f.startswith('install macos') and f.endswith('.app/contents/sharedsupport/basesystem.dmg') for f in files_in_iso) or \
           any('install macos' in f and 'basesystem.dmg' in f for f in files_in_iso) or \
           'applications/install macos' in ''.join(files_in_iso):
            return 'macos'

        # VirtIO check
        if any('viostor/' in path for path in files_in_iso):
            return 'virtio'

        # Windows check
        has_boot_wim = 'sources/boot.wim' in files_in_iso
        has_boot_sdi = 'boot/boot.sdi' in files_in_iso
        has_setup_exe = any(f.endswith('/setup.exe') or f == 'setup.exe' for f in files_in_iso)

        if has_boot_wim or has_boot_sdi or has_setup_exe:
            return 'windows'
            
        # Linux check
        if any(path.startswith(('isolinux/', 'boot/syslinux/', 'boot/grub/')) or 'vmlinuz' in path or 'vmlinux' in path for path in files_in_iso):
            return 'linux'

    except (subprocess.CalledProcessError, FileNotFoundError):
        return 'unknown'
        
    return 'unknown'


def get_host_gpus():
    """
    Scans and identifies host GPUs using lspci and their PCI class codes for reliability.
    Returns a list of dictionaries, each representing a GPU component.
    """
    gpus = []
    try:
        # Use lspci with the '-D' flag to show domain numbers (for full addresses)
        # and '-n' to get numeric class codes.
        lspci_output = subprocess.check_output(
            ["lspci", "-Dn"],
            text=True,
            stderr=subprocess.PIPE
        ).strip()

        # The PCI class code for anything display-related starts with "03".
        # 0300: VGA-compatible controller
        # 0301: XGA controller
        # 0302: 3D controller
        # 0380: Other display controller
        # This regex is now much simpler and more reliable.
        # It captures the full PCI address, the class code, and the vendor/device ID.
        gpu_pattern = re.compile(
            r"^([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)\s"  # Full PCI Address (e.g., 0000:01:00.0)
            r"03[0-9a-fA-F]{2}:\s"                                  # Class Code (must start with 03)
            r"([0-9a-fA-F]{4}:[0-9a-fA-F]{4})",                     # Vendor:Device ID
            re.MULTILINE
        )

        for match in gpu_pattern.finditer(lspci_output):
            pci_address, vendor_device = match.groups()
            
            # Now, get the human-readable description for this specific address
            try:
                description_output = subprocess.check_output(
                    ["lspci", "-s", pci_address, "-v"],
                    text=True,
                    stderr=subprocess.PIPE
                ).strip()
                # A simple regex to grab the main description line
                description_match = re.search(r":\s(.*?)(?:\s\(rev.*\))?$", description_output.splitlines()[0])
                description = description_match.group(1).strip() if description_match else "Unknown GPU"
            except (subprocess.CalledProcessError, IndexError):
                description = "Unknown GPU"

            # Shorten the PCI address for display if it starts with 0000:
            display_pci_address = pci_address.replace("0000:", "")

            gpu_type = "iGPU" if "intel" in description.lower() else "dGPU"

            gpus.append({
                "pci_address": display_pci_address,
                "description": description,
                "vendor_device": vendor_device,
                "type": gpu_type,
                "display_name": f"{gpu_type} - {description} ({display_pci_address})"
            })
        
        if not gpus:
            print_warning("No devices with display controller class '03xx' found by lspci.")
            print_info("This might mean your user doesn't have permission, or pciutils is not installed correctly.")

    except FileNotFoundError:
        print_error("`lspci` command not found. Please install the 'pciutils' package.")
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

def get_cpu_vendor():
    """
    Identifies the CPU vendor (Intel/AMD) from /proc/cpuinfo.
    """
    try:
        with open('/proc/cpuinfo', 'r', encoding='utf-8') as f:
            cpu_info = f.read()
        if "GenuineIntel" in cpu_info:
            return "Intel"
        if "AuthenticAMD" in cpu_info:
            return "AMD"
    except IOError:
        return "Unknown"
    return "Unknown"
         
      

def is_apfs_support_enabled():
    """
    The definitive check for APFS support. This function creates an isolated
    bash script to run guestfish, completely avoiding the Python script's
    complex TTY environment that was causing guestfish to hang.
    """
    if os.geteuid() != 0:
        print_error("This function must be run as root. Please restart Glint with 'sudo ./glint.py'")
        return False

    # Define the content of the robust shell script.
    # It uses a "here document" (<<EOF) to reliably pass commands.
    script_content = """#!/bin/bash
set -e
unset LIBGUESTFS_BACKEND

guestfish --listen --ro -a /dev/null <<'EOF'
run
list-filesystems
EOF
"""

    try:
        # Create a temporary file to hold our script.
        # 'delete=False' is important so we can execute it by name.
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.sh') as tmp_script:
            tmp_script_path = tmp_script.name
            tmp_script.write(script_content)
            os.chmod(tmp_script_path, 0o755)

        # Execute the isolation script with sudo.
        # This is the most reliable way to run our command.
        cmd = ['sudo', 'bash', tmp_script_path]
        
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=120
        )

        # The check is the same: look for 'apfs' in the output.
        return 'apfs' in proc.stdout

    except subprocess.TimeoutExpired:
        print_error("Guestfish timed out even when run from an isolated script. This is a severe appliance issue.")
        return False
    except subprocess.CalledProcessError as e:
        print_error("The isolated guestfish script failed to run.")
        error_console.print("\n--- GUESTFISH SCRIPT ERROR ---\n" + e.stderr.strip() + "\n----------------------------\n")
        return False
    finally:
        # Clean up the temporary script file.
        if 'tmp_script_path' in locals() and os.path.exists(tmp_script_path):
            os.remove(tmp_script_path)
            
# --- Passthrough Safety Checks ---

def is_monitor_connected(pci_address):
    """
    Checks if a monitor is connected to any output of a given GPU.
    Returns True if a connected monitor is found, False otherwise.
    """
    drm_path = "/sys/class/drm/"
    full_pci_address = f"0000:{pci_address}"

    try:
        # Find the cardX directory that corresponds to the PCI device
        for card_dir in os.listdir(drm_path):
            if not card_dir.startswith("card"):
                continue
            
            device_link = os.path.join(drm_path, card_dir, "device")
            if os.path.islink(device_link):
                # The target is a relative path to the devices directory
                target_pci_path = os.path.realpath(device_link)
                if full_pci_address in target_pci_path:
                    # We found the right card. Now check its connectors.
                    for conn_dir in os.listdir(os.path.join(drm_path, card_dir)):
                        if conn_dir.startswith(card_dir + "-"):
                            status_path = os.path.join(drm_path, card_dir, conn_dir, "status")
                            if os.path.exists(status_path):
                                with open(status_path, 'r', encoding='utf-8') as f:
                                    if f.read().strip() == "connected":
                                        return True # Found a connected monitor
                    # If we checked all connectors for this card and found none
                    return False
    except (FileNotFoundError, PermissionError):
        # If we can't check, assume it might be connected to be safe.
        print_warning("Could not reliably check monitor connection status.")
        return True
        
    # If we loop through all cards and don't find the PCI address
    return False

def is_iommu_active():
    """
    Checks if IOMMU is active by looking for populated IOMMU group directories.
    """
    iommu_path = "/sys/kernel/iommu_groups/"
    if not os.path.isdir(iommu_path):
        return False
    # If the directory exists and contains any entries, IOMMU is active.
    return any(os.scandir(iommu_path))

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
        
        boot_vga_pattern = re.compile(r"^([0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)\sVGA compatible controller.*\s\[boot\]", re.MULTILINE)
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
    Returns a list of PCI addresses for all other devices in the group.
    """
    other_devices = []
    try:
        # We need the full 0000:xx:xx.x address for sysfs
        full_pci_address = f"0000:{pci_address}"

        device_path = f"/sys/bus/pci/devices/{full_pci_address}"
        if not os.path.exists(device_path):
            return [] # Device not found

        iommu_group_path = os.path.realpath(os.path.join(device_path, "iommu_group", "devices"))
        
        if not os.path.isdir(iommu_group_path):
            return []

        for device_link in os.listdir(iommu_group_path):
            # device_link is the full address, e.g., '0000:01:00.1'
            # We want the short version for QEMU, e.g., '01:00.1'
            short_addr = device_link.replace("0000:", "")
            
            # Don't add the original GPU to the list of "other" devices
            if short_addr != pci_address:
                other_devices.append(short_addr)
                    
    except (FileNotFoundError, NotADirectoryError):
        return []
        
    return other_devices


def get_pci_device_driver(pci_address):
    """
    Checks the current kernel driver in use for a given PCI device.
    Returns the driver name as a string (e.g., 'i915', 'vfio-pci') or None.
    """
    # Note: We use 0000: prefix for sysfs path but not for display.
    driver_path = f"/sys/bus/pci/devices/0000:{pci_address}/driver"
    try:
        if os.path.islink(driver_path):
            # The driver is a symlink, its name is the basename of the target
            return os.path.basename(os.readlink(driver_path))
    except (FileNotFoundError, OSError):
        # No driver directory or link means no driver is bound
        return None
    return None


def bind_pci_device_to_driver(pci_address, driver):
    """
    Binds a PCI device to a specified driver using the sysfs interface.
    This requires sudo privileges. Returns True on success, False on failure.
    """
    print_info(f"Attempting to bind device {pci_address} to driver '{driver}'...")

    # First, unbind from any current driver
    unbind_path = f"/sys/bus/pci/devices/0000:{pci_address}/driver/unbind"
    if os.path.exists(unbind_path):
        # We run this quietly and with check=False, as it's okay if it fails
        # (e.g., if no driver was bound to begin with).
        cmd_unbind = ['sh', '-c', f'echo "0000:{pci_address}" > {unbind_path}']
        run_command_live(cmd_unbind, as_root=True, check=False, quiet=True)

    # Second, bind to the new driver
    bind_path = f"/sys/bus/pci/drivers/{driver}/bind"
    if not os.path.exists(bind_path):
        print_error(f"Driver '{driver}' does not have a 'bind' interface. Is it loaded?")
        return False

    cmd_bind = ['sh', '-c', f'echo "0000:{pci_address}" > {bind_path}']
    if run_command_live(cmd_bind, as_root=True, check=True, quiet=True) is not None:
        # Give sysfs a moment to update itself before we check the result
        time.sleep(1)
        new_driver = get_pci_device_driver(pci_address)
        if new_driver == driver:
            print_success(f"Successfully bound {pci_address} to {driver}.")
            return True
        else:
            print_error(f"Command succeeded, but device is now bound to '{new_driver}' instead of '{driver}'.")
            return False
    else:
        print_error(f"Failed to execute bind command for {pci_address} to {driver}.")
        return False