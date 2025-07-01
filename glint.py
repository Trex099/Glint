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
                subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "python-rich"], check=True)
            elif os.path.exists("/usr/bin/apt"):
                subprocess.run(["sudo", "apt", "update"], check=True)
                subprocess.run(["sudo", "apt", "install", "-y", "python3-rich"], check=True)
            else:
                print("Error: Could not find 'pacman' or 'apt'. Please install 'rich' manually.")
                sys.exit(1)
            print("Successfully installed 'rich'. Please re-run the script.")
            sys.exit(0)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("Error during 'rich' bootstrap installation.")
            sys.exit(1)
            print("Error during 'rich' bootstrap installation.")
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

    tasks = {
        "QEMU": {"status": "⚪ Pending", "check": lambda: shutil.which("qemu-system-x86_64"), "arch": "qemu-desktop", "debian": "qemu-system-x86"},
        "OVMF/EDK2": {"status": "⚪ Pending", "check": lambda: os.path.exists("/usr/share/edk2/x64/OVMF_CODE.4m.fd") or os.path.exists("/usr/share/OVMF/OVMF_CODE.fd"), "arch": "edk2-ovmf", "debian": "ovmf"},
        "Python Rich": {"status": "⚪ Pending", "check": lambda: importlib.util.find_spec("rich"), "arch": "python-rich", "debian": "python3-rich"},
        "Zenity": {"status": "⚪ Pending", "check": lambda: shutil.which("zenity"), "arch": "zenity", "debian": "zenity"},
        "Python Pexpect": {"status": "⚪ Pending", "check": lambda: importlib.util.find_spec("pexpect"), "arch": "python-pexpect", "debian": "python3-pexpect"},
        "Python Questionary": {"status": "⚪ Pending", "check": lambda: importlib.util.find_spec("questionary"), "arch": "AUR", "debian": "python3-questionary"},
        "ISO Info Tool": {"status": "⚪ Pending", "check": lambda: shutil.which("isoinfo"), "arch": "cdrkit", "debian": "genisoimage"},
        "GuestFS Tools": {"status": "⚪ Pending", "check": lambda: shutil.which("guestmount"), "arch": "guestfs-tools", "debian": "guestfs-tools"}
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
        for task, details in tasks.items():
            live.update(generate_ui(), refresh=True)
            time.sleep(0.2)

            if details["check"]():
                tasks[task]['status'] = "✅ Found"
            else:
                tasks[task]['status'] = "🟡 Installing..."
                live.update(generate_ui(), refresh=True)
                
                install_cmd = []
                if distro_id in ["arch", "manjaro"]:
                    pkg_name = details.get("arch")
                    if pkg_name == "AUR":
                        if not shutil.which("yay"):
                            tasks[task]['status'] = "🔴 Error: 'yay' not found."
                            live.update(generate_ui(), refresh=True)
                            time.sleep(4)
                            sys.exit(1)
                        install_cmd = ["yay", "-S", "--noconfirm", "python-questionary"]
                    else:
                        install_cmd = ["sudo", "pacman", "-S", "--noconfirm", pkg_name]
                elif distro_id in ["debian", "ubuntu", "pop"]:
                    pkg_name = details.get("debian")
                    install_cmd = ["sudo", "apt", "install", "-y", pkg_name]
                    if not apt_updated:
                        action_message = "Updating package lists (e.g., apt update)..."
                        live.update(generate_ui(), refresh=True)
                        try:
                            subprocess.run(["sudo", "apt", "update"], check=True, capture_output=True, text=True)
                            apt_updated = True
                            action_message = "Glint is verifying your system's dependencies."
                        except subprocess.CalledProcessError:
                            tasks[task]['status'] = "🔴 Error: 'apt update' failed."
                            live.update(generate_ui(), refresh=True)
                            time.sleep(4)
                            sys.exit(1)
                else:
                    tasks[task]['status'] = f"🔴 Error: Unsupported distro '{distro_id}'."
                    live.update(generate_ui(), refresh=True)
                    time.sleep(4)
                    sys.exit(1)

                try:
                    subprocess.run(install_cmd, check=True, capture_output=True, text=True)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    tasks[task]['status'] = f"🔴 Error: Failed to install {task}."
                    live.update(generate_ui(), refresh=True)
                    time.sleep(4)
                    sys.exit(1)

                if not details["check"]():
                    tasks[task]['status'] = f"🔴 Error: Install OK, but check failed."
                    live.update(generate_ui(), refresh=True)
                    time.sleep(4)
                    sys.exit(1)
                
                tasks[task]['status'] = "✅ Installed"

            progress.update(progress_task, advance=1)
            live.update(generate_ui(), refresh=True)
        
        progress.update(progress_task, description="All dependencies satisfied.")
        live.update(generate_ui(), refresh=True)
        time.sleep(1)

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
    from linux_vm import linux_vm_menu
    from macos_vm import macos_vm_menu
    from windows_vm import windows_vm_menu

    console = Console()

    def generate_dashboard():
        """
        Generates the main dashboard panel showing the status of all VMs.
        """
        from config import CONFIG
        
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
                
                is_running, pid = get_vm_status(vm_dir)
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
        return Panel(table, title="[bold purple]VM Dashboard[/]", border_style="purple", expand=True)

    def get_vm_status(vm_dir):
        """
        Safely checks if a VM process is running by checking its PID file.
        """
        pid_file = os.path.join(vm_dir, "qemu.pid")
        if not os.path.exists(pid_file):
            return False, None
        try:
            with open(pid_file, 'r', encoding='utf-8') as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True, pid
        except (IOError, ValueError, ProcessLookupError, OSError):
            if os.path.exists(pid_file):
                os.remove(pid_file)
            return False, None

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
    
    # Run the initial dependency check first
    initial_dependency_check()
    
    # Now that dependencies are met, start the main application
    main_menu()