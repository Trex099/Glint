# Made by trex099
# https://github.com/Trex099/Glint
"""
VFIO Manager for Automated Permission and Device Management

This module provides comprehensive VFIO permission automation, including:
- Automatic /dev/vfio/vfio permission configuration
- Udev rules automation for persistent VFIO permissions
- User group management for KVM access
- Permission validation and troubleshooting guidance
"""

import os
import sys
# import subprocess
import pwd
import grp
import logging
import tempfile
from typing import Dict, List, Tuple

# Add parent directories to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core_utils import (
    print_header, print_info, print_success, print_warning, print_error,
    run_command_live
)

logger = logging.getLogger(__name__)


# Import the new error handling system
from ..error_handling import (
    GlintError, ErrorSeverity, ErrorCategory
)

class VFIOError(GlintError):
    """Custom exception for VFIO-related errors"""
    def __init__(self, message: str, error_code: str = None, suggestions: List[str] = None, **kwargs):
        kwargs.setdefault('category', ErrorCategory.HARDWARE)
        kwargs.setdefault('severity', ErrorSeverity.ERROR)
        kwargs.setdefault('code', error_code or 'GLINT-E410')
        kwargs.setdefault('suggestions', suggestions or [])
        super().__init__(message, **kwargs)


class VFIOManager:
    """
    Comprehensive VFIO Permission and Device Management System
    
    This class handles all aspects of VFIO setup including permissions,
    udev rules, user groups, and device binding.
    """
    
    def __init__(self):
        """Initialize the VFIO Manager"""
        self.logger = logging.getLogger('glint.vfio_manager')
        self.vfio_device_path = "/dev/vfio/vfio"
        self.kvm_device_path = "/dev/kvm"
        self.udev_rules_dir = "/etc/udev/rules.d"
        self.vfio_udev_rule_file = "10-glint-vfio.rules"
        self.kvm_group = "kvm"
        self.current_user = self._get_current_user()
        
        self.logger.info("VFIOManager initialized")
    
    def _get_current_user(self) -> str:
        """Get the current username safely"""
        try:
            return pwd.getpwuid(os.getuid()).pw_name
        except KeyError:
            # Fallback methods
            try:
                return os.getlogin()
            except OSError:
                return os.environ.get('USER', os.environ.get('USERNAME', 'unknown'))
    
    def check_vfio_permissions(self) -> Tuple[bool, Dict[str, any]]:
        """
        Comprehensive VFIO permission check with detailed status information
        
        Returns:
            Tuple[bool, Dict]: (success, status_info)
        """
        status_info = {
            'vfio_device_exists': False,
            'vfio_permissions_ok': False,
            'kvm_device_exists': False,
            'kvm_permissions_ok': False,
            'user_in_kvm_group': False,
            'vfio_module_loaded': False,
            'udev_rule_exists': False,
            'issues': [],
            'suggestions': []
        }
        
        try:
            # Check if VFIO device exists
            if os.path.exists(self.vfio_device_path):
                status_info['vfio_device_exists'] = True
                # Check VFIO permissions
                if os.access(self.vfio_device_path, os.R_OK | os.W_OK):
                    status_info['vfio_permissions_ok'] = True
                else:
                    status_info['issues'].append("No read/write access to /dev/vfio/vfio")
            else:
                status_info['issues'].append("/dev/vfio/vfio device does not exist")
            
            # Check if KVM device exists and permissions
            if os.path.exists(self.kvm_device_path):
                status_info['kvm_device_exists'] = True
                if os.access(self.kvm_device_path, os.R_OK | os.W_OK):
                    status_info['kvm_permissions_ok'] = True
                else:
                    status_info['issues'].append("No read/write access to /dev/kvm")
            else:
                status_info['issues'].append("/dev/kvm device does not exist")
            
            # Check if user is in KVM group
            try:
                kvm_group_info = grp.getgrnam(self.kvm_group)
                if self.current_user in kvm_group_info.gr_mem:
                    status_info['user_in_kvm_group'] = True
                else:
                    # Check if KVM is the user's primary group
                    user_info = pwd.getpwnam(self.current_user)
                    if user_info.pw_gid == kvm_group_info.gr_gid:
                        status_info['user_in_kvm_group'] = True
                    else:
                        status_info['issues'].append(f"User '{self.current_user}' is not in the 'kvm' group")
            except KeyError:
                status_info['issues'].append("KVM group does not exist")
            
            # Check if VFIO module is loaded
            try:
                with open('/proc/modules', 'r') as f:
                    modules = f.read()
                    if 'vfio_pci' in modules:
                        status_info['vfio_module_loaded'] = True
                    else:
                        status_info['issues'].append("vfio-pci kernel module is not loaded")
            except FileNotFoundError:
                status_info['issues'].append("Cannot check loaded kernel modules")
            
            # Check if udev rule exists
            udev_rule_path = os.path.join(self.udev_rules_dir, self.vfio_udev_rule_file)
            if os.path.exists(udev_rule_path):
                status_info['udev_rule_exists'] = True
            
            # Generate suggestions based on issues
            self._generate_suggestions(status_info)
            
            # Overall success if VFIO permissions are OK
            success = status_info['vfio_permissions_ok'] and status_info['kvm_permissions_ok']
            
            self.logger.debug(f"VFIO permission check completed. Success: {success}")
            return success, status_info
            
        except Exception as e:
            self.logger.error(f"Error during VFIO permission check: {e}")
            status_info['issues'].append(f"Permission check failed: {str(e)}")
            return False, status_info
    
    def _generate_suggestions(self, status_info: Dict[str, any]):
        """Generate actionable suggestions based on detected issues"""
        suggestions = []
        
        if not status_info['user_in_kvm_group']:
            suggestions.append(f"Add user '{self.current_user}' to the 'kvm' group")
        
        if not status_info['vfio_module_loaded']:
            suggestions.append("Load the vfio-pci kernel module")
        
        if not status_info['udev_rule_exists']:
            suggestions.append("Create udev rules for persistent VFIO permissions")
        
        if not status_info['vfio_permissions_ok'] and status_info['vfio_device_exists']:
            suggestions.append("Fix VFIO device permissions")
        
        if not status_info['kvm_permissions_ok'] and status_info['kvm_device_exists']:
            suggestions.append("Fix KVM device permissions")
        
        status_info['suggestions'] = suggestions
    
    def setup_vfio_permissions_automatically(self) -> bool:
        """
        Automatically configure VFIO permissions with minimal user interaction
        
        Returns:
            bool: True if setup was successful
        """
        print_header("Automatic VFIO Permission Setup")
        
        try:
            # Check current status
            success, status_info = self.check_vfio_permissions()
            
            if success:
                print_success("VFIO permissions are already configured correctly!")
                return True
            
            print_info("Configuring VFIO permissions automatically...")
            
            # Step 1: Add user to KVM group if needed
            if not status_info['user_in_kvm_group']:
                if not self._add_user_to_kvm_group():
                    return False
            
            # Step 2: Load VFIO module if needed
            if not status_info['vfio_module_loaded']:
                if not self._load_vfio_module():
                    return False
            
            # Step 3: Create udev rules for persistent permissions
            if not self._create_vfio_udev_rules():
                return False
            
            # Step 4: Apply udev rules and set temporary permissions
            if not self._apply_udev_rules_and_permissions():
                return False
            
            # Final verification
            success, final_status = self.check_vfio_permissions()
            
            if success:
                print_success("✅ VFIO permissions configured successfully!")
                print_info("Changes will persist across reboots.")
                return True
            else:
                print_warning("⚠️  Some issues remain after automatic setup:")
                self._display_status_info(final_status)
                return False
                
        except Exception as e:
            self.logger.error(f"Error during automatic VFIO setup: {e}")
            print_error(f"Automatic setup failed: {str(e)}")
            return False
    
    def _add_user_to_kvm_group(self) -> bool:
        """Add the current user to the KVM group"""
        print_info(f"Adding user '{self.current_user}' to the 'kvm' group...")
        
        try:
            # Check if KVM group exists, create if it doesn't
            try:
                grp.getgrnam(self.kvm_group)
            except KeyError:
                print_info("Creating 'kvm' group...")
                result = run_command_live(["groupadd", self.kvm_group], as_root=True)
                if result is None:
                    print_error("Failed to create 'kvm' group")
                    return False
            
            # Add user to KVM group
            result = run_command_live(
                ["usermod", "-aG", self.kvm_group, self.current_user], 
                as_root=True
            )
            
            if result is not None:
                print_success(f"✅ User '{self.current_user}' added to 'kvm' group")
                print_warning("Note: You may need to log out and back in for group changes to take effect")
                return True
            else:
                print_error("Failed to add user to 'kvm' group")
                return False
                
        except Exception as e:
            self.logger.error(f"Error adding user to KVM group: {e}")
            print_error(f"Failed to add user to KVM group: {str(e)}")
            return False
    
    def _load_vfio_module(self) -> bool:
        """Load the VFIO-PCI kernel module"""
        print_info("Loading vfio-pci kernel module...")
        
        try:
            result = run_command_live(["modprobe", "vfio-pci"], as_root=True)
            
            if result is not None:
                print_success("✅ vfio-pci module loaded successfully")
                
                # Also ensure it loads on boot
                self._ensure_vfio_module_on_boot()
                return True
            else:
                print_error("Failed to load vfio-pci module")
                return False
                
        except Exception as e:
            self.logger.error(f"Error loading VFIO module: {e}")
            print_error(f"Failed to load VFIO module: {str(e)}")
            return False
    
    def _ensure_vfio_module_on_boot(self):
        """Ensure VFIO module loads on boot"""
        try:
            modules_load_file = "/etc/modules-load.d/vfio.conf"
            
            # Check if already configured
            if os.path.exists(modules_load_file):
                with open(modules_load_file, 'r') as f:
                    content = f.read()
                    if 'vfio-pci' in content:
                        return  # Already configured
            
            # Create the configuration
            print_info("Configuring vfio-pci to load on boot...")
            
            # Create temporary file with the module configuration
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
                temp_file.write("# VFIO modules for GPU passthrough\n")
                temp_file.write("vfio\n")
                temp_file.write("vfio_iommu_type1\n")
                temp_file.write("vfio-pci\n")
                temp_file_path = temp_file.name
            
            # Copy to system location with sudo
            result = run_command_live([
                "cp", temp_file_path, modules_load_file
            ], as_root=True)
            
            # Clean up temp file
            os.unlink(temp_file_path)
            
            if result is not None:
                print_success("✅ VFIO modules configured to load on boot")
            
        except Exception as e:
            self.logger.warning(f"Could not configure VFIO module for boot: {e}")
            print_warning("Could not configure VFIO module to load on boot")
    
    def _create_vfio_udev_rules(self) -> bool:
        """Create udev rules for persistent VFIO permissions"""
        print_info("Creating udev rules for persistent VFIO permissions...")
        
        try:
            udev_rule_path = os.path.join(self.udev_rules_dir, self.vfio_udev_rule_file)
            
            # Create the udev rule content
            udev_rules_content = f"""# VFIO permissions for Glint VM management
# Created automatically by Glint VFIO Manager

# VFIO device permissions
KERNEL=="vfio/vfio", GROUP="{self.kvm_group}", MODE="0660"

# Additional VFIO devices
SUBSYSTEM=="vfio", GROUP="{self.kvm_group}", MODE="0660"

# KVM device permissions (backup)
KERNEL=="kvm", GROUP="{self.kvm_group}", MODE="0660"
"""
            
            # Create temporary file with the rules
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
                temp_file.write(udev_rules_content)
                temp_file_path = temp_file.name
            
            # Copy to system location with sudo
            result = run_command_live([
                "cp", temp_file_path, udev_rule_path
            ], as_root=True)
            
            # Clean up temp file
            os.unlink(temp_file_path)
            
            if result is not None:
                print_success(f"✅ Udev rules created at {udev_rule_path}")
                return True
            else:
                print_error("Failed to create udev rules")
                return False
                
        except Exception as e:
            self.logger.error(f"Error creating udev rules: {e}")
            print_error(f"Failed to create udev rules: {str(e)}")
            return False
    
    def _apply_udev_rules_and_permissions(self) -> bool:
        """Apply udev rules and set immediate permissions"""
        print_info("Applying udev rules and setting permissions...")
        
        try:
            # Reload udev rules
            result1 = run_command_live(["udevadm", "control", "--reload-rules"], as_root=True)
            result2 = run_command_live(["udevadm", "trigger"], as_root=True)
            
            if result1 is None or result2 is None:
                print_warning("Could not reload udev rules automatically")
            else:
                print_success("✅ Udev rules reloaded")
            
            # Set immediate permissions as fallback
            self._set_immediate_permissions()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error applying udev rules: {e}")
            print_error(f"Failed to apply udev rules: {str(e)}")
            return False
    
    def _set_immediate_permissions(self):
        """Set immediate permissions for current session"""
        try:
            # Set VFIO permissions
            if os.path.exists(self.vfio_device_path):
                run_command_live([
                    "chmod", "660", self.vfio_device_path
                ], as_root=True)
                run_command_live([
                    "chgrp", self.kvm_group, self.vfio_device_path
                ], as_root=True)
            
            # Set KVM permissions
            if os.path.exists(self.kvm_device_path):
                run_command_live([
                    "chmod", "660", self.kvm_device_path
                ], as_root=True)
                run_command_live([
                    "chgrp", self.kvm_group, self.kvm_device_path
                ], as_root=True)
            
            print_success("✅ Immediate permissions set")
            
        except Exception as e:
            self.logger.warning(f"Could not set immediate permissions: {e}")
            print_warning("Could not set immediate permissions")
    
    def validate_and_troubleshoot(self) -> bool:
        """
        Comprehensive validation and troubleshooting with guided fixes
        
        Returns:
            bool: True if all issues are resolved
        """
        print_header("VFIO Permission Validation and Troubleshooting")
        
        success, status_info = self.check_vfio_permissions()
        
        if success:
            print_success("✅ All VFIO permissions are configured correctly!")
            self._display_success_info()
            return True
        
        print_warning("⚠️  VFIO permission issues detected:")
        self._display_status_info(status_info)
        
        # Offer automatic fix
        import questionary
        if questionary.confirm("Would you like to automatically fix these issues?").ask():
            return self.setup_vfio_permissions_automatically()
        else:
            print_info("Manual troubleshooting steps:")
            self._display_manual_troubleshooting(status_info)
            return False
    
    def _display_status_info(self, status_info: Dict[str, any]):
        """Display detailed status information"""
        from rich.console import Console
        from rich.table import Table
        
        console = Console()
        
        # Create status table
        table = Table(title="VFIO Permission Status")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Details")
        
        # Add status rows
        table.add_row(
            "VFIO Device",
            "✅ OK" if status_info['vfio_device_exists'] else "❌ Missing",
            self.vfio_device_path if status_info['vfio_device_exists'] else "Device not found"
        )
        
        table.add_row(
            "VFIO Permissions",
            "✅ OK" if status_info['vfio_permissions_ok'] else "❌ No Access",
            "Read/Write access available" if status_info['vfio_permissions_ok'] else "No read/write access"
        )
        
        table.add_row(
            "KVM Device",
            "✅ OK" if status_info['kvm_device_exists'] else "❌ Missing",
            self.kvm_device_path if status_info['kvm_device_exists'] else "Device not found"
        )
        
        table.add_row(
            "KVM Permissions",
            "✅ OK" if status_info['kvm_permissions_ok'] else "❌ No Access",
            "Read/Write access available" if status_info['kvm_permissions_ok'] else "No read/write access"
        )
        
        table.add_row(
            "User in KVM Group",
            "✅ OK" if status_info['user_in_kvm_group'] else "❌ Not in Group",
            f"User '{self.current_user}' is in 'kvm' group" if status_info['user_in_kvm_group'] else f"User '{self.current_user}' needs to be added to 'kvm' group"
        )
        
        table.add_row(
            "VFIO Module",
            "✅ Loaded" if status_info['vfio_module_loaded'] else "❌ Not Loaded",
            "vfio-pci module is loaded" if status_info['vfio_module_loaded'] else "vfio-pci module needs to be loaded"
        )
        
        table.add_row(
            "Udev Rules",
            "✅ Exist" if status_info['udev_rule_exists'] else "❌ Missing",
            "Persistent rules configured" if status_info['udev_rule_exists'] else "Need to create udev rules"
        )
        
        console.print(table)
        
        # Display issues and suggestions
        if status_info['issues']:
            console.print("\n[bold red]Issues Found:[/bold red]")
            for issue in status_info['issues']:
                console.print(f"  • {issue}")
        
        if status_info['suggestions']:
            console.print("\n[bold yellow]Suggested Actions:[/bold yellow]")
            for suggestion in status_info['suggestions']:
                console.print(f"  • {suggestion}")
    
    def _display_success_info(self):
        """Display success information and usage tips"""
        from rich.console import Console
        from rich.panel import Panel
        
        console = Console()
        
        success_message = f"""[bold green]✅ VFIO Permissions Successfully Configured![/bold green]

[bold]Current Configuration:[/bold]
• User '{self.current_user}' is in the 'kvm' group
• VFIO device permissions are correctly set
• KVM device permissions are correctly set
• vfio-pci kernel module is loaded
• Persistent udev rules are in place

[bold]What this means:[/bold]
• You can now run VMs with PCI passthrough without sudo
• Permissions will persist across reboots
• VFIO modules will load automatically on boot

[bold]Next Steps:[/bold]
• You can now configure PCI passthrough in your VMs
• Use the GPU passthrough menu for graphics card passthrough
• Check IOMMU groups for device compatibility
"""
        
        console.print(Panel(success_message, border_style="green"))
    
    def _display_manual_troubleshooting(self, status_info: Dict[str, any]):
        """Display manual troubleshooting steps"""
        from rich.console import Console
        
        console = Console()
        
        console.print("\n[bold]Manual Troubleshooting Steps:[/bold]")
        
        if not status_info['user_in_kvm_group']:
            console.print(f"""
[bold cyan]1. Add user to KVM group:[/bold cyan]
   sudo usermod -aG kvm {self.current_user}
   # Then log out and back in
""")
        
        if not status_info['vfio_module_loaded']:
            console.print("""
[bold cyan]2. Load VFIO module:[/bold cyan]
   sudo modprobe vfio-pci
   
   # To make it persistent, add to /etc/modules-load.d/vfio.conf:
   echo 'vfio-pci' | sudo tee /etc/modules-load.d/vfio.conf
""")
        
        if not status_info['udev_rule_exists']:
            console.print(f"""
[bold cyan]3. Create udev rules:[/bold cyan]
   sudo nano /etc/udev/rules.d/10-vfio.rules
   
   # Add these lines:
   KERNEL=="vfio/vfio", GROUP="{self.kvm_group}", MODE="0660"
   SUBSYSTEM=="vfio", GROUP="{self.kvm_group}", MODE="0660"
   
   # Then reload rules:
   sudo udevadm control --reload-rules
   sudo udevadm trigger
""")
        
        console.print("""
[bold cyan]4. Verify setup:[/bold cyan]
   # Check group membership:
   groups
   
   # Check device permissions:
   ls -l /dev/vfio/vfio /dev/kvm
   
   # Check module loading:
   lsmod | grep vfio
""")


# Convenience function for backward compatibility
def check_vfio_permissions() -> bool:
    """
    Backward compatible function for checking VFIO permissions
    
    Returns:
        bool: True if permissions are OK
    """
    manager = VFIOManager()
    success, _ = manager.check_vfio_permissions()
    return success


def setup_vfio_permissions() -> bool:
    """
    Backward compatible function for setting up VFIO permissions
    
    Returns:
        bool: True if setup was successful
    """
    manager = VFIOManager()
    return manager.setup_vfio_permissions_automatically()