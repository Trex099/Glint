# Made by trex099
# https://github.com/Trex099/Glint
"""
UUID and System Identifier Operations Module

Provides UUID and identifier management for Linux VMs:
- nuke_vm_session: Complete reset with new identifiers
- regenerate_overlay_with_fresh_identifiers: Fresh overlay disk
- show_vm_identifiers: Display VM identifiers
- regenerate_base_image_identifiers: New base image IDs
- uuid_management_menu: UUID management UI
"""

import os
import sys
import time
import questionary
from rich.console import Console

# Use same import pattern as main.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG
from core_utils import (
    print_header, print_info, print_warning, print_error, print_success,
    clear_screen, run_command_live
)

# Import from refactored modules
from linux_vm.vm_paths import get_vm_paths, select_vm
from linux_vm.vm_session import is_vm_running

console = Console()


def nuke_vm_session():
    """
    Nuclear option: Completely regenerate all identifiers and reset VM to fresh state
    
    This function:
    1. Stops the VM if running
    2. Regenerates ALL system identifiers
    3. Resets UEFI variables
    4. Creates fresh overlay (if exists)
    5. Optionally enables Privacy Mode (Tor routing)
    """
    clear_screen()
    print_header("🔥 NUKE VM Session - Complete Fresh Start")
    
    vm_name = select_vm("Nuke (Complete Reset)")
    if not vm_name:
        return
    
    # Ask user which type of nuke
    nuke_type = questionary.select(
        "Select Nuke Type:",
        choices=[
            questionary.Choice(
                title="🔄 Standard Nuke & Boot (Fresh overlay, same IP)",
                value="standard"
            ),
            questionary.Choice(
                title="🔒 Privacy Nuke & Boot (Fresh overlay + Tor IP)",
                value="privacy"
            ),
            questionary.Separator(),
            questionary.Choice("❌ Cancel", value="cancel")
        ],
        use_indicator=True
    ).ask()
    
    if nuke_type is None or nuke_type == "cancel":
        print_info("Operation cancelled.")
        return
    
    # Handle Privacy Mode
    enable_privacy = False
    if nuke_type == "privacy":
        # Import and show privacy panel
        try:
            from linux_vm.privacy_mode import (
                show_privacy_mode_panel, 
                is_privacy_mode_available,
                check_tor_installed
            )
            
            # Check if Tor is available
            tor_installed, tor_msg = check_tor_installed()
            if not tor_installed:
                print_error(f"Privacy Mode requires Tor: {tor_msg}")
                print_info("Install Tor with: sudo apt install tor")
                if not questionary.confirm("Continue with Standard Nuke instead?").ask():
                    return
                nuke_type = "standard"
            else:
                # Show pros/cons/disclaimer
                show_privacy_mode_panel()
                
                if questionary.confirm("Enable Privacy Mode for this session?", default=False).ask():
                    enable_privacy = True
                    print_success("✅ Privacy Mode will be enabled after nuke")
                else:
                    print_info("Privacy Mode declined. Proceeding with Standard Nuke.")
        except ImportError:
            print_warning("Privacy Mode module not available.")
            print_info("Proceeding with Standard Nuke.")
    
    # Confirm the nuclear option
    print_warning("⚠️  This will completely reset ALL system identifiers for the VM!")
    print_info("This includes:")
    print_info("  • VM UUID and MAC address")
    print_info("  • Machine ID and hardware serials")
    print_info("  • Disk and partition UUIDs")
    print_info("  • UEFI/TPM/Secure Boot variables")
    print_info("  • Fresh overlay disk (if exists)")
    if enable_privacy:
        print_info("  • 🔒 Privacy Mode (Tor routing) enabled")
    
    if not questionary.confirm("🔥 Are you sure you want to NUKE this VM session?").ask():
        print_info("Operation cancelled.")
        return
    
    # Stop VM if running
    if is_vm_running(vm_name):
        print_info(f"Stopping VM '{vm_name}' before reset...")
        # Lazy import to avoid circular dependency
        from linux_vm.main import stop_vm
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
        
        # Save privacy mode setting to config
        if enable_privacy:
            import json
            config_path = paths.get('config', os.path.join(paths['dir'], 'config.json'))
            vm_config = {}
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r') as f:
                        vm_config = json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass
            
            vm_config['privacy_mode'] = True
            with open(config_path, 'w') as f:
                json.dump(vm_config, f, indent=4)
            
            print_success("🔒 Privacy Mode saved to VM config!")
            print_info("Next boot will use Tor routing for network traffic.")
        
        print_info("\n🤖 Next steps:")
        print_info("1. Boot the VM normally")
        if enable_privacy:
            print_info("   → Privacy Mode will be automatically enabled")
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
        from linux_vm.main import stop_vm
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
        from linux_vm.main import stop_vm
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
