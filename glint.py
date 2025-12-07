# Made by trex099
# https://github.com/Trex099/Glint
"""
Main entry point for the Universal VM Manager.
"""
import sys
import os
import subprocess
import importlib.util
import time
import shutil
import json
import pexpect
import getpass

            
def run_aur_install(package_name, console, live_updater):
    """
    Installs an AUR package using pexpect, correctly handling sudo and reinstall prompts.
    
    Args:
        package_name (str): The name of the AUR package to install.
        console (rich.console.Console): The console object for printing.
        live_updater (function): A function to call to refresh the live display.
    """
    original_user = os.environ.get('SUDO_USER')
    command = f"yay -S --noconfirm {package_name}"
    
    if os.geteuid() == 0 and original_user:
        console.print(f"[yellow]Running as root. Dropping privileges to user '{original_user}' for yay...[/]")
        command = f"sudo -u {original_user} {command}"
    elif os.geteuid() == 0:
        console.print("[red]Running as root, but could not determine original user (SUDO_USER not set).[/]")
        return False
        
    try:
        child = pexpect.spawn(command, timeout=600, encoding='utf-8')
        sudo_password = None

        while True:
            # Add the "Proceed with installation?" prompt to our list of expected patterns
            index = child.expect([
                r"\[sudo\] password for .*: ",      # 0: Sudo password prompt
                r"==> Packages to cleanBuild\?",   # 1: Clean build prompt
                r"==> Diffs to show\?",            # 2: Diffs prompt
                r":: Proceed with installation\? \[Y/n\]", # 3: NEW - Reinstall prompt
                pexpect.EOF,                       # 4: End of command
                pexpect.TIMEOUT                    # 5: Timeout
            ])

            live_updater()

            if index == 0:
                console.print("[yellow]Sudo password required for yay to continue...[/]")
                if sudo_password is None:
                    prompt = f"Password for {original_user}: " if original_user else "Password: "
                    sudo_password = getpass.getpass(prompt)
                child.sendline(sudo_password)
            elif index == 1:
                child.sendline("N") # Answer "None" to cleanBuild
            elif index == 2:
                child.sendline("N") # Answer "None" to diffs
            elif index == 3:
                child.sendline("y") # Answer "Yes" to proceed with installation
            elif index == 4: # EOF
                child.close()
                # Security: clear password from memory as soon as possible
                sudo_password = None
                return child.exitstatus == 0
            elif index == 5: # Timeout
                console.print(f"[red]Timeout: yay took too long to install {package_name}.[/]")
                # Security: clear password from memory
                sudo_password = None
                return False

    except pexpect.exceptions.ExceptionPexpect as e:
        console.print(f"[red]An unexpected pexpect error occurred: {e}[/]")
        return False
    except Exception as e:
        console.print(f"[red]A general error occurred during AUR installation: {e}[/]")
        return False

    
    



def initial_dependency_check():
    """
    Checks and installs core dependencies with a rich TUI, with improved error handling and clearer messaging.
    """
    try:
        from rich.console import Console
        from rich.live import Live
        from rich.progress import Progress, BarColumn, TextColumn
        from rich.table import Table
        from rich.text import Text
    except ImportError:
        print("Bootstrapping: 'rich' library not found. Attempting to install...")
        try:
            if os.path.exists("/usr/bin/pacman"):
                print("Bootstrapping: Synchronizing pacman databases (sudo pacman -Sy)...")
                subprocess.run(["sudo", "pacman", "-Sy", "--noconfirm"], check=True)
                subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "python-rich"], check=True)
            elif os.path.exists("/usr/bin/apt"):
                subprocess.run(["sudo", "apt", "update"], check=True)
                subprocess.run(["sudo", "apt", "install", "-y", "python3-rich"], check=True)
            else:
                print("Error: Could not find 'pacman' or 'apt'. Please install 'rich' manually: pip3 install rich")
                sys.exit(1)
            # Verify the install actually worked before asking user to re-run
            try:
                import rich as _test_rich
                del _test_rich
                print("Successfully installed 'rich'. Please re-run the script.")
                sys.exit(0)
            except ImportError:
                print("ERROR: 'rich' installation appeared to succeed but import still fails.")
                print("Please install manually: pip3 install rich")
                sys.exit(1)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("Error during 'rich' bootstrap installation.")
            print("Please install manually: pip3 install rich")
            sys.exit(1)

    console = Console()
    distro_id = "unknown"
    try:
        with open("/etc/os-release", "r", encoding='utf-8') as f:
            for line in f:
                if line.startswith("ID="):
                    distro_id = line.strip().split("=")[1].lower().strip('"')
    except FileNotFoundError:
        pass

    # Enhanced OVMF check for multiple Ubuntu paths
    def check_ovmf():
        ovmf_paths = [
            "/usr/share/OVMF/OVMF_CODE.fd",
            "/usr/share/edk2/ovmf/OVMF_CODE.fd", 
            "/usr/share/edk2/x64/OVMF_CODE.4m.fd",
            "/usr/share/ovmf/OVMF_CODE.fd",
            "/usr/share/qemu/OVMF_CODE.fd"
        ]
        return any(os.path.exists(path) for path in ovmf_paths)

    tasks = {
        "QEMU": {"status": "⚪ Pending", "check": lambda: shutil.which("qemu-system-x86_64"), "arch": "qemu-desktop", "debian": "qemu-system-x86", "fedora": "qemu-system-x86"},
        "OVMF/EDK2": {"status": "⚪ Pending", "check": check_ovmf, "arch": "edk2-ovmf", "debian": "ovmf", "fedora": "edk2-ovmf"},
        "Python Rich": {"status": "⚪ Pending", "check": lambda: importlib.util.find_spec("rich"), "arch": "python-rich", "debian": "python3-rich", "fedora": "python3-rich"},
        "Zenity": {"status": "⚪ Pending", "check": lambda: shutil.which("zenity"), "arch": "zenity", "debian": "zenity", "fedora": "zenity"},
        "Python Pexpect": {"status": "⚪ Pending", "check": lambda: importlib.util.find_spec("pexpect"), "arch": "python-pexpect", "debian": "python3-pexpect", "fedora": "python3-pexpect"},
        "Python Questionary": {"status": "⚪ Pending", "check": lambda: importlib.util.find_spec("questionary"), "arch": "AUR:python-questionary", "debian": "python3-questionary", "fedora": "python3-questionary"},
        "Python Requests": {"status": "⚪ Pending", "check": lambda: importlib.util.find_spec("requests"), "arch": "python-requests", "debian": "python3-requests", "fedora": "python3-requests"},
        "Python TQDM": {"status": "⚪ Pending", "check": lambda: importlib.util.find_spec("tqdm"), "arch": "python-tqdm", "debian": "python3-tqdm", "fedora": "python3-tqdm"},
        "ISO Info Tool": {"status": "⚪ Pending", "check": lambda: shutil.which("isoinfo"), "arch": "cdrkit", "debian": "genisoimage", "fedora": "genisoimage"},
        "GuestFS Tools": {"status": "⚪ Pending", "check": lambda: shutil.which("guestmount"), "arch": "guestfs-tools", "debian": "guestfs-tools", "fedora": "libguestfs-tools-c"},
        # APFS Support - needed for macOS VM support. On Fedora, only apfs-fuse is available (libfsapfs-utils doesn't exist)
        # We check for either apfs-fuse OR fsck.apfs since either is sufficient for basic macOS support
        "APFS Support": {"status": "⚪ Pending", "check": lambda: shutil.which("apfs-fuse") or os.path.exists("/usr/bin/fsck.apfs"), "arch": "AUR:apfs-fuse-git", "debian": "apfs-fuse", "fedora": "fuse-apfs", "optional": True}
    }

    progress = Progress(
        TextColumn("[bold blue]Glint Status[/bold blue]"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    )
    progress_task = progress.add_task("Verifying...", total=len(tasks))
    
    action_message = "Glint is verifying your system's dependencies."

    def generate_ui():
        grid = Table.grid(expand=True)
        grid.add_column()
        grid.add_row(Text("Glint Dependency Manager", style="bold cyan"))
        grid.add_row(action_message)
        grid.add_row("─" * 50)
        
        table = Table.grid()
        for task, details in tasks.items():
            table.add_row(Text(task), Text(details['status'], style="yellow" if "ing" in details['status'] else "green" if "Found" in details['status'] else "red" if "Error" in details['status'] else "dim"))
        grid.add_row(table)
        grid.add_row("─" * 50)
        grid.add_row(progress)
        return grid

    with Live(generate_ui(), console=console, screen=False, auto_refresh=False) as live:
        apt_updated = False
        pacman_synced = False
        for task, details in tasks.items():
            live.update(generate_ui(), refresh=True)
            time.sleep(0.2)

            if details["check"]():
                tasks[task]['status'] = "✅ Found"
                progress.update(progress_task, advance=1)
                live.update(generate_ui(), refresh=True)
                continue # Skip to the next task if already found

            # --- Installation Logic Starts Here ---
            tasks[task]['status'] = "🟡 Installing..."
            live.update(generate_ui(), refresh=True)
            
            install_cmd = []
            installation_succeeded = False

            # --- Arch Linux Logic ---
            if distro_id in ["arch", "manjaro", "endeavouros"]:
                if not pacman_synced:
                    action_message = "Synchronizing pacman databases..."
                    live.update(generate_ui(), refresh=True)
                    try:
                        subprocess.run(["sudo", "pacman", "-Sy", "--noconfirm"], check=True, capture_output=True, text=True)
                        pacman_synced = True
                        # Note: -Sy without -u is a partial upgrade - warn user
                        console.print("[yellow]⚠️  Note: For a full system upgrade, run 'sudo pacman -Syu' separately[/]")
                    except subprocess.CalledProcessError:
                        tasks[task]['status'] = "🔴 Error: 'pacman -Sy' failed."
                        live.update(generate_ui(), refresh=True)
                        time.sleep(4)
                        sys.exit(1)
                
                pkg_name = details.get("arch")
                if pkg_name.startswith("AUR:"):
                    aur_pkg_name = pkg_name.split(":", 1)[1]
                    action_message = f"Installing {aur_pkg_name} from the AUR with yay..."
                    live.update(generate_ui(), refresh=True)

                    if not shutil.which("yay"):
                        tasks[task]['status'] = "🔴 Error: 'yay' not found. See instructions above."
                        console.print("\n[yellow]To install yay (AUR helper):[/]")
                        console.print("[cyan]  git clone https://aur.archlinux.org/yay.git[/]")
                        console.print("[cyan]  cd yay && makepkg -si[/]")
                        console.print("[dim]Or use paru/pikaur as an alternative.[/]\n")
                        live.update(generate_ui(), refresh=True)
                        time.sleep(6)
                        sys.exit(1)
                    
                    installation_succeeded = run_aur_install(aur_pkg_name, console, lambda: live.update(generate_ui(), refresh=True))
                
                else: # It's an official repository package
                    action_message = f"Installing {pkg_name} with pacman..."
                    live.update(generate_ui(), refresh=True)
                    install_cmd = ["sudo", "pacman", "-S", "--noconfirm", pkg_name]
                    try:
                        subprocess.run(install_cmd, check=True, capture_output=True, text=True)
                        installation_succeeded = True
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        installation_succeeded = False

            # --- Debian/Ubuntu Logic ---
            elif distro_id in ["debian", "ubuntu", "pop", "linuxmint", "elementary", "zorin", "kubuntu", "xubuntu", "lubuntu", "ubuntu-mate", "ubuntu-budgie", "neon"]:
                pkg_name = details.get("debian")
                
                # Enhanced Ubuntu support
                if distro_id in ["ubuntu", "pop", "linuxmint", "elementary", "zorin", "kubuntu", "xubuntu", "lubuntu", "ubuntu-mate", "ubuntu-budgie", "neon"]:
                    try:
                        # Import Ubuntu compatibility module
                        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
                        from linux_vm.ubuntu_compatibility import get_ubuntu_package_info, install_ubuntu_package
                        
                        # Get Ubuntu-specific package info
                        ubuntu_pkg_info = get_ubuntu_package_info(task)
                        if ubuntu_pkg_info:
                            pkg_name = ubuntu_pkg_info.get("primary", pkg_name)
                            alternatives = ubuntu_pkg_info.get("alternatives", [])
                            pip_fallback = ubuntu_pkg_info.get("pip_fallback")
                            ppa = ubuntu_pkg_info.get("ppa")
                        else:
                            alternatives = []
                            pip_fallback = None
                            ppa = None
                    except ImportError:
                        # Fallback to standard behavior if Ubuntu module not available
                        alternatives = []
                        pip_fallback = None
                        ppa = None
                
                if not apt_updated:
                    action_message = "Updating package lists (apt update)..."
                    live.update(generate_ui(), refresh=True)
                    try:
                        subprocess.run(["sudo", "apt", "update"], check=True, capture_output=True, text=True)
                        apt_updated = True
                    except subprocess.CalledProcessError as e:
                        tasks[task]['status'] = f"🔴 Error: 'apt update' failed: {str(e)[:50]}..."
                        live.update(generate_ui(), refresh=True)
                        time.sleep(4)
                        sys.exit(1)
                
                action_message = f"Installing {pkg_name} with apt..."
                live.update(generate_ui(), refresh=True)
                
                # Use enhanced Ubuntu installation if available
                if distro_id in ["ubuntu", "pop", "linuxmint", "elementary", "zorin", "kubuntu", "xubuntu", "lubuntu", "ubuntu-mate", "ubuntu-budgie", "neon"] and 'alternatives' in locals():
                    try:
                        installation_succeeded = install_ubuntu_package(pkg_name, alternatives, pip_fallback, ppa)
                    except Exception as e:
                        # Fallback to standard apt install (log the error for debugging)
                        # Note: bare except replaced with Exception to avoid catching KeyboardInterrupt
                        install_cmd = ["sudo", "apt", "install", "-y", pkg_name]
                        try:
                            subprocess.run(install_cmd, check=True, capture_output=True, text=True)
                            installation_succeeded = True
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            installation_succeeded = False
                else:
                    # Standard Debian/Ubuntu installation
                    install_cmd = ["sudo", "apt", "install", "-y", pkg_name]
                    try:
                        subprocess.run(install_cmd, check=True, capture_output=True, text=True)
                        installation_succeeded = True
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        installation_succeeded = False
            
            # --- Fedora Logic ---
            elif distro_id == "fedora":
                pkg_name = details.get("fedora")
                action_message = f"Installing {pkg_name} with dnf..."
                live.update(generate_ui(), refresh=True)
                install_cmd = ["sudo", "dnf", "install", "-y", pkg_name]
                try:
                    subprocess.run(install_cmd, check=True, capture_output=True, text=True)
                    installation_succeeded = True
                except (subprocess.CalledProcessError, FileNotFoundError):
                    installation_succeeded = False
            
            # --- CentOS/RHEL Logic ---
            elif distro_id in ["centos", "rhel", "rocky", "almalinux"]:
                pkg_name = details.get("fedora")  # CentOS/RHEL use similar package names
                action_message = f"Installing {pkg_name} with yum..."
                live.update(generate_ui(), refresh=True)
                install_cmd = ["sudo", "yum", "install", "-y", pkg_name]
                try:
                    subprocess.run(install_cmd, check=True, capture_output=True, text=True)
                    installation_succeeded = True
                except (subprocess.CalledProcessError, FileNotFoundError):
                    installation_succeeded = False
            
            # --- openSUSE Logic ---
            elif distro_id in ["opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles"]:
                pkg_name = details.get("fedora")  # openSUSE uses similar package names
                action_message = f"Installing {pkg_name} with zypper..."
                live.update(generate_ui(), refresh=True)
                install_cmd = ["sudo", "zypper", "install", "-y", pkg_name]
                try:
                    subprocess.run(install_cmd, check=True, capture_output=True, text=True)
                    installation_succeeded = True
                except (subprocess.CalledProcessError, FileNotFoundError):
                    installation_succeeded = False
            
            # --- Gentoo Logic (requires manual intervention) ---
            elif distro_id == "gentoo":
                pkg_name = details.get("fedora")  # Gentoo package names differ significantly
                console.print(f"\n[yellow]⚠️  Gentoo detected. Package '{pkg_name}' may need manual installation.[/]")
                console.print("[cyan]  Example: sudo emerge --ask app-emulation/qemu[/]")
                console.print("[dim]  Check the Gentoo wiki for exact package names.[/]\n")
                # Try emerge anyway with common naming
                action_message = f"Attempting to install {pkg_name} with emerge..."
                live.update(generate_ui(), refresh=True)
                install_cmd = ["sudo", "emerge", "--ask=n", pkg_name]
                try:
                    subprocess.run(install_cmd, check=True, capture_output=True, text=True, timeout=300)
                    installation_succeeded = True
                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                    installation_succeeded = False
            
            else:
                tasks[task]['status'] = f"🔴 Error: Unsupported distro '{distro_id}'."
                console.print(f"\n[red]Your distro '{distro_id}' is not yet supported.[/]")
                console.print("[yellow]Please install dependencies manually:[/]")
                console.print("[cyan]  - QEMU (qemu-system-x86_64)[/]")
                console.print("[cyan]  - OVMF/EDK2 (UEFI firmware)[/]")
                console.print("[cyan]  - Python packages: rich, questionary, pexpect, requests, tqdm[/]")
                live.update(generate_ui(), refresh=True)
                time.sleep(6)
                sys.exit(1)

            # --- Final check after installation attempt ---
            action_message = "Glint is verifying your system's dependencies."
            if installation_succeeded and details["check"]():
                tasks[task]['status'] = "✅ Installed"
            else:
                # Check if this is an optional dependency
                if details.get("optional", False):
                    tasks[task]['status'] = f"⚠️ Skipped (optional)"
                    # Don't exit - just continue with the next dependency
                else:
                    tasks[task]['status'] = f"🔴 Error: Failed to install {task}."
                    live.update(generate_ui(), refresh=True)
                    time.sleep(4)
                    sys.exit(1)

            progress.update(progress_task, advance=1)
            live.update(generate_ui(), refresh=True)
        
        progress.update(progress_task, description="All dependencies satisfied.")
        live.update(generate_ui(), refresh=True)
        time.sleep(1)


def setup_directories():
    """
    Ensures that all necessary VM storage directories exist.
    """
    from config import CONFIG
    from core_utils import print_info

    print_info("Verifying storage directories...")
    required_dirs = [
        CONFIG['VMS_DIR_LINUX'],
        CONFIG['VMS_DIR_MACOS'],
        CONFIG['VMS_DIR_WINDOWS'],
        # You could also add CONFIG['ASSETS_DIR'] here if needed
    ]
    for vm_dir in required_dirs:
        try:
            os.makedirs(vm_dir, exist_ok=True)
        except OSError as e:
            # This is a critical error, the program can't run without storage
            print(f"FATAL: Could not create required directory {vm_dir}: {e}")
            sys.exit(1)        

# --- Main Execution Logic ---

# These functions are defined here because they are part of the main script's flow
# and depend on imports that are checked/loaded after the initial dependency check.

def display_help_menu():
    """
    Displays an interactive, menu-driven help system.
    """
    from rich.console import Console
    from rich.panel import Panel
    import questionary
    from core_utils import clear_screen

    console = Console()
    
    help_topics = {
        "About Glint": """
[bold cyan]About Glint VM Manager[/bold cyan]
Glint is a command-line tool designed to simplify the creation and management of QEMU virtual machines for Linux, Windows, and macOS.
It automates dependency checking, disk creation, and configuration to get you up and running quickly.
        """,
        "First-Time Setup (Crucial!)": """
[bold cyan]First-Time Setup[/bold cyan]
For the 'Create VM' options to work, you [bold]must[/] place your operating system installer files in the same directory where you run `glint.py`.

- For [bold]Linux[/] and [bold]Windows[/], this should be an `.iso` file.
- For [bold]macOS[/], this should be a `.dmg` or `.img` file (e.g., `BaseSystem.dmg`).
- For [bold]Windows[/], it is also highly recommended to have a `virtio-win-*.iso` file for necessary drivers.
        """,
        "Understanding VM Sessions": """
[bold cyan]Core Features Explained[/bold cyan]
- [bold]Create VM:[/bold] A one-time process that creates a 'base' disk image for your VM. This is the clean, original installation.
- [bold]Run / Resume VM:[/bold] This loads the VM using an 'overlay' disk. Changes you make inside the VM are saved to this overlay, leaving the base image untouched. It's like a persistent snapshot.
- [bold]Nuke & Boot a Fresh Session:[/bold] This deletes [underline]only the overlay disk[/] and starts a new, clean session from the original base image. This is useful for reverting to a clean state without reinstalling the OS.
- [bold]Nuke VM Completely:[/bold] [bold red]IRREVERSIBLE.[/] This deletes the entire VM directory, including the base image and all overlays.
        """,
        "PCI Passthrough (Advanced)": """
[bold cyan]Passthrough & Performance (Advanced)[/bold cyan]
This feature allows you to give a virtual machine direct control over a physical piece of hardware, like a GPU, USB controller, or NVMe drive.
This can provide near-native performance, which is especially useful for gaming or other intensive tasks.

[bold yellow]WARNING:[/bold yellow] This is an advanced feature that directly modifies your host system's driver bindings and can have significant consequences if configured incorrectly, potentially requiring a hard reboot. 
For more details, please use the dedicated guide inside the 'Passthrough & Performance' menu in the Linux VM section.
        """,
        "File Locations": """
[bold cyan]File Locations[/bold cyan]
Your virtual machines are stored in subdirectories within the Glint folder:
- `vms_linux/`
- `vms_macos/`
- `vms_windows/`

Each VM folder contains the base disk, overlay disks, and configuration files for that specific VM.
        """
    }

    while True:
        clear_screen()
        console.print(Panel("Select a topic to learn more, or exit to return to the main menu.", title="[bold cyan]Interactive Help[/]", border_style="cyan"))
        
        choices = list(help_topics.keys())
        choices.append(questionary.Separator())
        choices.append("Return to Main Menu")

        selection = questionary.select(
            "Choose a help topic:",
            choices=choices,
            use_indicator=True
        ).ask()

        if selection is None or selection == "Return to Main Menu":
            break
        
        clear_screen()
        console.print(Panel(help_topics[selection].strip(), title=f"[bold cyan]Help: {selection}[/]", border_style="cyan", expand=False))
        questionary.text("Press Enter to return to the help menu...").ask()

def main_menu():
    """
    Displays the main menu and handles user navigation.
    """
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    import questionary
    from core_utils import clear_screen, print_info
    from linux_vm import linux_vm_menu, get_running_vm_info as get_linux_vm_status
    from macos_vm import macos_vm_menu, get_running_vm_info as get_macos_vm_status
    from windows_vm import windows_vm_menu, get_running_vm_info as get_windows_vm_status

    console = Console()

    def generate_dashboard():
        """
        Generates the main dashboard panel showing the status of all VMs.
        """
        from config import CONFIG, DISTRO_INFO
        from rich.text import Text
        from rich.columns import Columns
        
        # --- Host System Info ---
        def get_host_info():
            """Get information about the host system."""
            # Detect distro
            distro_id = "unknown"
            distro_name = "Unknown"
            try:
                with open("/etc/os-release", "r", encoding='utf-8') as f:
                    for line in f:
                        if line.startswith("ID="):
                            distro_id = line.strip().split("=")[1].lower().strip('"')
                        elif line.startswith("PRETTY_NAME="):
                            distro_name = line.strip().split("=", 1)[1].strip('"')
            except FileNotFoundError:
                pass
            
            # Check if running in a VM
            is_vm = False
            vm_type = ""
            try:
                import subprocess
                result = subprocess.run(['systemd-detect-virt'], capture_output=True, text=True, timeout=2)
                if result.returncode == 0 and result.stdout.strip() != 'none':
                    is_vm = True
                    vm_type = result.stdout.strip()
            except Exception:
                pass
            
            # Get kernel version
            kernel = ""
            try:
                with open("/proc/version", "r") as f:
                    kernel_line = f.read()
                    # Extract just the version number (e.g., "6.1.0-arch1-1")
                    import re
                    match = re.search(r'Linux version (\S+)', kernel_line)
                    if match:
                        kernel = match.group(1)
            except Exception:
                pass
            
            return distro_id, distro_name, is_vm, vm_type, kernel
        
        distro_id, distro_name, is_vm, vm_type, kernel = get_host_info()
        
        # Build host info string
        if is_vm:
            host_status = f"[cyan]🖥️  Host:[/] [bold]{distro_name}[/] [dim]({kernel})[/] [yellow]⚡ Running in VM ({vm_type})[/]"
        else:
            host_status = f"[cyan]🖥️  Host:[/] [bold]{distro_name}[/] [dim]({kernel})[/] [green]✓ Bare Metal[/]"
        
        all_vms = []
        vm_types = {
            "🐧 Linux": CONFIG['VMS_DIR_LINUX'],
            "🍎 macOS": CONFIG['VMS_DIR_MACOS'],
            "🪟 Windows": CONFIG['VMS_DIR_WINDOWS'],
        }
        for os_type, vms_dir in vm_types.items():
            if not os.path.isdir(vms_dir):
                continue
            for vm_name in sorted(os.listdir(vms_dir)):
                vm_dir = os.path.join(vms_dir, vm_name)
                if not os.path.isdir(vm_dir):
                    continue
                
                vm_status_func = None
                if os_type == "🐧 Linux":
                    vm_status_func = get_linux_vm_status
                elif os_type == "🍎 macOS":
                    vm_status_func = get_macos_vm_status
                elif os_type == "🪟 Windows":
                    vm_status_func = get_windows_vm_status

                vm_info = vm_status_func(vm_name) # Pass vm_name, not vm_dir
                is_running = vm_info is not None
                pid = vm_info.get('pid') if is_running else 'N/A'
                status = f"[green]● Running[/] [dim](PID: {pid})[/]" if is_running else "[red]● Stopped[/]"
                
                config_path = os.path.join(vm_dir, "config.json")
                cpu_mem = "N/A"
                if os.path.exists(config_path):
                    try:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            vm_config = json.load(f)
                        cpu = vm_config.get('VM_CPU') or vm_config.get('cpu', '?')
                        mem = vm_config.get('VM_MEM') or vm_config.get('mem', '?')
                        cpu_mem = f"{cpu} / {mem}"
                    except (json.JSONDecodeError, IOError):
                        cpu_mem = "[red]Invalid[/]"
                
                all_vms.append({
                    "status": status,
                    "name": vm_name,
                    "os": os_type,
                    "cpu_mem": cpu_mem
                })
        
        table = Table(box=None, expand=True, show_header=False)
        table.add_column("Status", justify="left", style="bold", width=20)
        table.add_column("Name", justify="left")
        table.add_column("OS", justify="left")
        table.add_column("CPU / Mem", justify="left")
        table.add_row("[bold]Status[/]", "[bold]Name[/]", "[bold]OS[/]", "[bold]CPU / Mem[/]")
        table.add_row("─" * 20, "─" * 20, "─" * 10, "─" * 15)
        for vm in all_vms:
            table.add_row(vm['status'], vm['name'], vm['os'], vm['cpu_mem'])
        
        # Combine host info + VM table into panel
        from rich.console import Group
        dashboard_content = Group(
            Text.from_markup(host_status),
            Text(""),  # Spacer
            table
        )
        return Panel(dashboard_content, title="[bold purple]VM Dashboard[/]", border_style="purple", expand=True)

    

    custom_style = questionary.Style([
        ('selected', 'fg:#673ab7 bold'),
        ('highlighted', 'fg:#673ab7 bold'),
        ('pointer', 'fg:#673ab7 bold'),
    ])
    while True:
        clear_screen()
        console.print(generate_dashboard())
        try:
            choice = questionary.select(
                "What would you like to do?",
                choices=[
                    questionary.Choice("🐧 Linux VM Management", value="1"),
                    questionary.Choice("🍎 macOS VM Management", value="2"),
                    questionary.Choice("🪟 Windows VM Management", value="3"),
                    questionary.Separator(),
                    questionary.Choice("Exit", value="4"),
                    questionary.Choice("❔ Help", value="5")
                ],
                use_indicator=True,
                style=custom_style
            ).ask()

            if choice == "1":
                linux_vm_menu()
            elif choice == "2":
                macos_vm_menu()
            elif choice == "3":
                windows_vm_menu()
            elif choice == "4" or choice is None:
                print_info("Exiting. Goodbye! 👋")
                break
            elif choice == "5":
                display_help_menu()
                questionary.text("\nPress Enter to return to the main menu...").ask()

        except (KeyboardInterrupt, EOFError):
            print_info("\nExiting. Goodbye! 👋")
            break

      
if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath('src'))
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # Run the initial dependency check
    initial_dependency_check()
    
    # Ensure all required directories exist before starting the menu
    setup_directories()
    
    # Now that dependencies are met, start the main application
    main_menu()

    
