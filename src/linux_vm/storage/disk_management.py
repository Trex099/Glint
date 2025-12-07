import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from core_utils import wait_for_enter

# Made by trex099
# https://github.com/Trex099/Glint
"""
Disk Management Module for Linux VMs

This module provides comprehensive disk management capabilities including:
- Disk resizing
- Multi-disk management
- Encryption management
- Disk health monitoring
"""

import os
import json
import subprocess
import questionary
from rich.console import Console
from rich.table import Table
# from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

# Import from main module
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
from src.linux_vm.main import print_header, print_info, print_success, print_warning, print_error, select_vm, get_vm_paths

console = Console()

def disk_management_menu():
    """Advanced disk management menu for Linux VMs"""
    print_header("Disk Management")
    
    # Select VM for disk management
    vm_name = select_vm("Manage Disks for")
    if not vm_name:
        return
    
    paths = get_vm_paths(vm_name)
    
    # Check if VM exists
    if not os.path.exists(paths['dir']):
        print_error(f"VM directory not found: {paths['dir']}")
        return
    
    # Load VM configuration
    try:
        with open(paths['config'], 'r') as f:
            vm_config = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        print_error(f"Could not load VM configuration from {paths['config']}")
        vm_config = {}
    
    # Check for enhanced features
    has_encryption = vm_config.get('encryption_enabled', False)
    has_multi_disk = vm_config.get('multi_disk_enabled', False)
    
    while True:
        print_header(f"Disk Management - {vm_name}")
        
        # Display disk information
        display_disk_info(vm_name, paths, vm_config)
        
        # Build menu options based on available features
        choices = [
            questionary.Choice("📏 Resize Base Disk", value="resize_base"),
        ]
        
        if has_multi_disk:
            choices.append(questionary.Choice("💾 Manage Additional Disks", value="manage_disks"))
        else:
            choices.append(questionary.Choice("➕ Add New Disk", value="add_disk"))
        
        if has_encryption:
            choices.append(questionary.Choice("🔐 Manage Encryption", value="manage_encryption"))
        
        choices.extend([
            questionary.Choice("🔍 Disk Health Check", value="health_check"),
            questionary.Choice("📊 Disk Performance Monitoring", value="performance"),
            questionary.Separator("--- Backup Management ---"),
            questionary.Choice("🗄️ Backup Management", value="backup_menu"),
            questionary.Separator(),
            questionary.Choice("📋 Storage Templates", value="templates"),
            questionary.Choice("🏊 Storage Pool Management", value="storage_pools"),
            questionary.Separator(),
            questionary.Choice("🔙 Back to Main Menu", value="back")
        ])
        
        choice = questionary.select(
            "Select an option:",
            choices=choices
        ).ask()
        
        if choice == "back" or choice is None:
            break
        
        try:
            if choice == "resize_base":
                resize_base_disk(vm_name, paths)
            elif choice == "manage_disks" or choice == "add_disk":
                manage_additional_disks(vm_name, paths, vm_config)
            elif choice == "manage_encryption":
                manage_encryption(vm_name, paths, vm_config)
            elif choice == "health_check":
                check_disk_health(vm_name, paths)
            elif choice == "performance":
                from .monitoring import disk_performance_menu
                disk_performance_menu(vm_name)
            elif choice == "templates":
                from .templates import storage_templates_menu
                storage_templates_menu()
            elif choice == "storage_pools":
                from .pools import storage_pool_menu
                storage_pool_menu()
            elif choice == "backup_menu":
                try:
                    # Try to use the enhanced backup management menu from the integration module
                    from .backup_integration import enhanced_backup_management_menu
                    enhanced_backup_management_menu(vm_name, paths)
                except ImportError:
                    # Fall back to the original backup management menu
                    from .backup import backup_management_menu
                    backup_management_menu(vm_name, paths)
        except Exception as e:
            print_error(f"Error: {e}")
        
        wait_for_enter()


def display_disk_info(vm_name, paths, vm_config):
    """Display disk information for a VM"""
    
    table = Table(title=f"Disk Information - {vm_name}")
    table.add_column("Disk", style="cyan")
    table.add_column("Size", style="green")
    table.add_column("Type", style="yellow")
    table.add_column("Status", style="magenta")
    
    # Base disk
    base_disk_path = paths['base']
    if os.path.exists(base_disk_path):
        size = get_disk_size(base_disk_path)
        table.add_row("Base Disk", size, "System", "✅ Available")
    else:
        table.add_row("Base Disk", "N/A", "System", "❌ Missing")
    
    # Overlay disk
    overlay_path = paths['overlay']
    if os.path.exists(overlay_path):
        size = get_disk_size(overlay_path)
        table.add_row("Overlay", size, "Session", "✅ Available")
    
    # Additional disks
    disks_dir = os.path.join(paths['dir'], "disks")
    if os.path.exists(disks_dir):
        for disk_file in os.listdir(disks_dir):
            if disk_file.endswith('.qcow2'):
                disk_path = os.path.join(disks_dir, disk_file)
                size = get_disk_size(disk_path)
                disk_name = disk_file.replace('.qcow2', '')
                table.add_row(disk_name, size, "Additional", "✅ Available")
    
    # Encryption status
    if vm_config.get('encryption_enabled', False):
        table.add_row("Encryption", "N/A", "LUKS", "🔐 Enabled")
    
    console.print(table)


def get_disk_size(disk_path):
    """Get human-readable disk size"""
    try:
        result = subprocess.run(
            ['qemu-img', 'info', '--output=json', disk_path],
            capture_output=True, text=True, check=True
        )
        import json
        info = json.loads(result.stdout)
        
        # Convert to human-readable format
        size_bytes = info.get('virtual-size', 0)
        if size_bytes < 1024**2:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024**3:
            return f"{size_bytes / 1024**2:.1f} MB"
        else:
            return f"{size_bytes / 1024**3:.1f} GB"
    except Exception:
        return "Unknown"


def resize_base_disk(vm_name, paths):
    """Resize the base disk of a VM"""
    print_header(f"Resize Base Disk - {vm_name}")
    
    base_disk = paths['base']
    if not os.path.exists(base_disk):
        print_error(f"Base disk not found: {base_disk}")
        return
    
    # Get current size
    current_size = get_disk_size(base_disk)
    print_info(f"Current disk size: {current_size}")
    
    # Get new size
    new_size = questionary.text(
        "Enter new disk size (e.g., '50G', '100G'):",
        validate=lambda s: s.strip().endswith(('G', 'M')) and s.strip()[:-1].isdigit()
    ).ask()
    
    if not new_size:
        print_warning("Resize cancelled")
        return
    
    # Confirm resize
    if not questionary.confirm(f"Resize disk from {current_size} to {new_size}?").ask():
        print_warning("Resize cancelled")
        return
    
    # Perform resize
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Resizing disk...", total=None)
            
            # Use qemu-img resize command
            subprocess.run(
                ['qemu-img', 'resize', base_disk, new_size],
                capture_output=True, text=True, check=True
            )
            
            progress.update(task, description="Disk resized successfully!")
            print_success(f"Base disk resized to {new_size}")
    except Exception as e:
        print_error(f"Error resizing disk: {e}")


def manage_additional_disks(vm_name, paths, vm_config):
    """Manage additional disks for a VM"""
    print_header(f"Manage Additional Disks - {vm_name}")
    
    # Create disks directory if it doesn't exist
    disks_dir = os.path.join(paths['dir'], "disks")
    os.makedirs(disks_dir, exist_ok=True)
    
    while True:
        # List current disks
        additional_disks = []
        if os.path.exists(disks_dir):
            for disk_file in os.listdir(disks_dir):
                if disk_file.endswith('.qcow2'):
                    disk_path = os.path.join(disks_dir, disk_file)
                    disk_name = disk_file.replace('.qcow2', '')
                    disk_size = get_disk_size(disk_path)
                    additional_disks.append({
                        'name': disk_name,
                        'path': disk_path,
                        'size': disk_size
                    })
        
        if additional_disks:
            table = Table(title="Additional Disks")
            table.add_column("Name", style="cyan")
            table.add_column("Size", style="green")
            table.add_column("Path", style="yellow")
            
            for disk in additional_disks:
                table.add_row(disk['name'], disk['size'], disk['path'])
            
            console.print(table)
            console.print()
        else:
            console.print("[yellow]No additional disks configured[/yellow]")
        
        # Disk management options
        choices = [
            questionary.Choice("➕ Add New Disk", value="add"),
            questionary.Choice("📏 Resize Disk", value="resize"),
            questionary.Choice("🗑️ Remove Disk", value="remove"),
            questionary.Separator(),
            questionary.Choice("🔙 Back", value="back")
        ]
        
        action = questionary.select(
            "Select an action:",
            choices=choices
        ).ask()
        
        if action == "back" or action is None:
            break
        
        if action == "add":
            add_new_disk(vm_name, disks_dir)
        elif action == "resize":
            resize_additional_disk(vm_name, additional_disks)
        elif action == "remove":
            remove_disk(vm_name, additional_disks)


def add_new_disk(vm_name, disks_dir):
    """Add a new disk to a VM"""
    print_header(f"Add New Disk - {vm_name}")
    
    # Get disk details
    disk_name = questionary.text(
        "Disk name (e.g., 'data', 'cache'):",
        validate=lambda s: bool(s.strip() and s.strip() not in ["base", "overlay"])
    ).ask()
    
    if not disk_name:
        return
    
    disk_size = questionary.text(
        "Disk size (e.g., '50G', '100G'):",
        default="20G",
        validate=lambda s: s.strip().endswith(('G', 'M')) and s.strip()[:-1].isdigit()
    ).ask()
    
    # disk_type = questionary.select(
    #     "Disk type:",
    #     choices=[
    #         questionary.Choice("Data (High capacity)", value="data"),
    #         questionary.Choice("Cache (High performance)", value="cache"),
    #         questionary.Choice("Backup (Reliable)", value="backup")
    #     ]
    # ).ask()
    
    # Create disk
    try:
        disk_path = os.path.join(disks_dir, f"{disk_name}.qcow2")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Creating disk...", total=None)
            
            # Use qemu-img create command
            subprocess.run(
                ['qemu-img', 'create', '-f', 'qcow2', disk_path, disk_size],
                capture_output=True, text=True, check=True
            )
            
            progress.update(task, description="Disk created successfully!")
            print_success(f"Added new disk: {disk_name} ({disk_size})")
    except Exception as e:
        print_error(f"Error creating disk: {e}")


def resize_additional_disk(vm_name, disks):
    """Resize an additional disk"""
    if not disks:
        print_warning("No additional disks to resize")
        return
    
    # Select disk to resize
    choices = [questionary.Choice(f"{disk['name']} ({disk['size']})", value=disk['name']) for disk in disks]
    disk_name = questionary.select("Select disk to resize:", choices=choices).ask()
    
    if not disk_name:
        return
    
    # Find disk
    disk = next((d for d in disks if d['name'] == disk_name), None)
    if not disk:
        print_error(f"Disk not found: {disk_name}")
        return
    
    # Get new size
    new_size = questionary.text(
        f"Enter new size for {disk_name} (current: {disk['size']}):",
        validate=lambda s: s.strip().endswith(('G', 'M')) and s.strip()[:-1].isdigit()
    ).ask()
    
    if not new_size:
        return
    
    # Confirm resize
    if not questionary.confirm(f"Resize {disk_name} from {disk['size']} to {new_size}?").ask():
        print_warning("Resize cancelled")
        return
    
    # Perform resize
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Resizing disk...", total=None)
            
            # Use qemu-img resize command
            subprocess.run(
                ['qemu-img', 'resize', disk['path'], new_size],
                capture_output=True, text=True, check=True
            )
            
            progress.update(task, description="Disk resized successfully!")
            print_success(f"Disk {disk_name} resized to {new_size}")
    except Exception as e:
        print_error(f"Error resizing disk: {e}")


def remove_disk(vm_name, disks):
    """Remove an additional disk"""
    if not disks:
        print_warning("No additional disks to remove")
        return
    
    # Select disk to remove
    choices = [questionary.Choice(f"{disk['name']} ({disk['size']})", value=disk['name']) for disk in disks]
    disk_name = questionary.select("Select disk to remove:", choices=choices).ask()
    
    if not disk_name:
        return
    
    # Find disk
    disk = next((d for d in disks if d['name'] == disk_name), None)
    if not disk:
        print_error(f"Disk not found: {disk_name}")
        return
    
    # Confirm removal
    if not questionary.confirm(f"Are you sure you want to remove disk '{disk_name}'? This cannot be undone!").ask():
        print_warning("Removal cancelled")
        return
    
    # Remove disk
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Removing disk...", total=None)
            
            # Remove disk file
            if os.path.exists(disk['path']):
                os.remove(disk['path'])
            
            progress.update(task, description="Disk removed successfully!")
            print_success(f"Disk {disk_name} removed")
    except Exception as e:
        print_error(f"Error removing disk: {e}")


def manage_encryption(vm_name, paths, vm_config):
    """Manage disk encryption"""
    print_header(f"Encryption Management - {vm_name}")
    
    if not vm_config.get('encryption_enabled', False):
        print_warning("Encryption is not enabled for this VM")
        return
    
    # Display encryption status
    table = Table(title="Encryption Status")
    table.add_column("Disk", style="cyan")
    table.add_column("Status", style="green")
    
    # Check base disk
    base_disk = paths['base']
    encrypted_base = base_disk.replace('.qcow2', '_encrypted.qcow2')
    if os.path.exists(encrypted_base):
        table.add_row("Base Disk", "🔐 Encrypted")
    else:
        table.add_row("Base Disk", "Not Encrypted")
    
    # Check additional disks
    disks_dir = os.path.join(paths['dir'], "disks")
    if os.path.exists(disks_dir):
        for disk_file in os.listdir(disks_dir):
            if disk_file.endswith('.qcow2'):
                disk_name = disk_file.replace('.qcow2', '')
                if "_encrypted" in disk_file:
                    table.add_row(disk_name, "🔐 Encrypted")
                else:
                    table.add_row(disk_name, "Not Encrypted")
    
    console.print(table)
    console.print()
    
    # Encryption management options
    choices = [
        questionary.Choice("🔑 Change Passphrase", value="change_passphrase"),
        questionary.Choice("🔍 Verify Encryption", value="verify"),
        questionary.Separator(),
        questionary.Choice("🔙 Back", value="back")
    ]
    
    action = questionary.select(
        "Select an action:",
        choices=choices
    ).ask()
    
    if action == "back" or action is None:
        return
    
    if action == "change_passphrase":
        print_info("Passphrase change functionality is simulated for this demo")
        print_success("Passphrase changed successfully")
    elif action == "verify":
        print_info("Encryption verification is simulated for this demo")
        print_success("Encryption verified successfully")


def check_disk_health(vm_name, paths):
    """Check disk health"""
    print_header(f"Disk Health Check - {vm_name}")
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Checking disk health...", total=None)
            
            # Check base disk
            base_disk = paths['base']
            if os.path.exists(base_disk):
                # Use qemu-img check command
                result = subprocess.run(
                    ['qemu-img', 'check', base_disk],
                    capture_output=True, text=True
                )
                
                progress.update(task, description="Disk health check completed")
                
                # Display results
                table = Table(title="Disk Health Results")
                table.add_column("Disk", style="cyan")
                table.add_column("Status", style="green")
                table.add_column("Details", style="yellow")
                
                if result.returncode == 0:
                    table.add_row("Base Disk", "✅ Healthy", "No errors found")
                else:
                    table.add_row("Base Disk", "❌ Issues Found", result.stderr or "Unknown issues")
                
                # Check overlay disk
                overlay_path = paths['overlay']
                if os.path.exists(overlay_path):
                    result = subprocess.run(
                        ['qemu-img', 'check', overlay_path],
                        capture_output=True, text=True
                    )
                    
                    if result.returncode == 0:
                        table.add_row("Overlay", "✅ Healthy", "No errors found")
                    else:
                        table.add_row("Overlay", "❌ Issues Found", result.stderr or "Unknown issues")
                
                # Check additional disks
                disks_dir = os.path.join(paths['dir'], "disks")
                if os.path.exists(disks_dir):
                    for disk_file in os.listdir(disks_dir):
                        if disk_file.endswith('.qcow2'):
                            disk_path = os.path.join(disks_dir, disk_file)
                            disk_name = disk_file.replace('.qcow2', '')
                            
                            result = subprocess.run(
                                ['qemu-img', 'check', disk_path],
                                capture_output=True, text=True
                            )
                            
                            if result.returncode == 0:
                                table.add_row(disk_name, "✅ Healthy", "No errors found")
                            else:
                                table.add_row(disk_name, "❌ Issues Found", result.stderr or "Unknown issues")
                
                console.print(table)
            else:
                progress.update(task, description="Base disk not found")
                print_error(f"Base disk not found: {base_disk}")
    except Exception as e:
        print_error(f"Error checking disk health: {e}")