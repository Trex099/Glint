#!/usr/bin/env python3
# Made by trex099
# https://github.com/Trex099/Glint
"""
Ubuntu USB Mouse Fix Utility

Specific utility to diagnose and fix USB mouse issues in Ubuntu VMs
where physical mouse doesn't work but trackpad does.
"""

import os
import sys
import subprocess
import logging
from typing import Dict, List, Optional
from pathlib import Path

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

# Add parent directories to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# from error_handling import GlintError, ErrorSeverity, ErrorCategory

console = Console()
logger = logging.getLogger(__name__)


class UbuntuUSBMouseFix:
    """
    Ubuntu-specific USB mouse fix utility
    
    Addresses the common issue where USB controller passthrough works
    but physical mice don't function properly in Ubuntu VMs.
    """
    
    def __init__(self):
        self.console = Console()
        self.logger = logging.getLogger(__name__)
        
        # Ubuntu-specific mouse driver packages
        self.required_packages = [
            "spice-vdagent",
            "qemu-guest-agent", 
            "xserver-xorg-input-evdev",
            "xserver-xorg-input-mouse",
            "xserver-xorg-input-synaptics"
        ]
        
        # USB mouse kernel modules
        self.usb_modules = [
            "usbhid",
            "hid_generic", 
            "hid_apple",
            "hid_logitech_dj",
            "hid_microsoft"
        ]
    
    def diagnose_mouse_issue(self) -> Dict[str, any]:
        """
        Comprehensive diagnosis of USB mouse issues in Ubuntu VM
        
        Returns:
            Dictionary with diagnosis results
        """
        self.console.print(Panel(
            "[bold cyan]Ubuntu USB Mouse Diagnostic Tool[/]\n"
            "[white]Checking for common USB mouse issues...[/]",
            title="Diagnostic Starting",
            border_style="cyan"
        ))
        
        diagnosis = {
            'is_ubuntu': False,
            'is_vm': False,
            'usb_controllers': [],
            'input_devices': [],
            'missing_packages': [],
            'kernel_modules': {},
            'display_server': None,
            'wayland_active': False,
            'mouse_detected': False,
            'trackpad_detected': False,
            'usb_passthrough_detected': False,
            'issues': [],
            'recommendations': []
        }
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console
        ) as progress:
            
            # Check if running Ubuntu
            task1 = progress.add_task("Checking Ubuntu version...", total=None)
            diagnosis['is_ubuntu'] = self._check_ubuntu()
            progress.update(task1, completed=True)
            
            # Check if running in VM
            task2 = progress.add_task("Detecting virtualization...", total=None)
            diagnosis['is_vm'] = self._check_virtualization()
            progress.update(task2, completed=True)
            
            # Check USB controllers
            task3 = progress.add_task("Scanning USB controllers...", total=None)
            diagnosis['usb_controllers'] = self._get_usb_controllers()
            progress.update(task3, completed=True)
            
            # Check input devices
            task4 = progress.add_task("Checking input devices...", total=None)
            diagnosis['input_devices'] = self._get_input_devices()
            diagnosis['mouse_detected'] = self._check_mouse_detected(diagnosis['input_devices'])
            diagnosis['trackpad_detected'] = self._check_trackpad_detected(diagnosis['input_devices'])
            progress.update(task4, completed=True)
            
            # Check packages
            task5 = progress.add_task("Verifying packages...", total=None)
            diagnosis['missing_packages'] = self._check_packages()
            progress.update(task5, completed=True)
            
            # Check kernel modules
            task6 = progress.add_task("Checking kernel modules...", total=None)
            diagnosis['kernel_modules'] = self._check_kernel_modules()
            progress.update(task6, completed=True)
            
            # Check display server
            task7 = progress.add_task("Checking display server...", total=None)
            diagnosis['display_server'] = self._get_display_server()
            diagnosis['wayland_active'] = self._is_wayland_active()
            progress.update(task7, completed=True)
            
            # Check for USB passthrough
            task8 = progress.add_task("Detecting USB passthrough...", total=None)
            diagnosis['usb_passthrough_detected'] = self._detect_usb_passthrough()
            progress.update(task8, completed=True)
        
        # Analyze results and generate recommendations
        self._analyze_diagnosis(diagnosis)
        
        return diagnosis
    
    def _check_ubuntu(self) -> bool:
        """Check if running Ubuntu"""
        try:
            with open('/etc/os-release', 'r') as f:
                content = f.read()
                return 'ubuntu' in content.lower()
        except FileNotFoundError:
            return False
    
    def _check_virtualization(self) -> bool:
        """Check if running in a virtual machine"""
        try:
            result = subprocess.run(['systemd-detect-virt'], 
                                  capture_output=True, text=True)
            return result.returncode == 0 and result.stdout.strip() != 'none'
        except FileNotFoundError:
            # Fallback check
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    content = f.read()
                    return any(virt in content.lower() for virt in 
                             ['hypervisor', 'vmware', 'virtualbox', 'qemu', 'kvm'])
            except FileNotFoundError:
                return False
    
    def _get_usb_controllers(self) -> List[Dict]:
        """Get USB controller information"""
        controllers = []
        try:
            result = subprocess.run(['lspci', '-v'], capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                current_device = None
                
                for line in lines:
                    if 'USB controller' in line:
                        current_device = {
                            'name': line.strip(),
                            'driver': None,
                            'kernel_modules': []
                        }
                        controllers.append(current_device)
                    elif current_device and 'Kernel driver in use:' in line:
                        current_device['driver'] = line.split(':')[1].strip()
                    elif current_device and 'Kernel modules:' in line:
                        modules = line.split(':')[1].strip().split(', ')
                        current_device['kernel_modules'] = modules
        except Exception as e:
            self.logger.warning(f"Could not get USB controller info: {e}")
        
        return controllers
    
    def _get_input_devices(self) -> List[Dict]:
        """Get input device information"""
        devices = []
        try:
            with open('/proc/bus/input/devices', 'r') as f:
                content = f.read()
                
            device_blocks = content.split('\n\n')
            for block in device_blocks:
                if not block.strip():
                    continue
                    
                device = {'name': '', 'handlers': [], 'type': 'unknown'}
                lines = block.split('\n')
                
                for line in lines:
                    if line.startswith('N: Name='):
                        device['name'] = line.split('=', 1)[1].strip('"')
                    elif line.startswith('H: Handlers='):
                        device['handlers'] = line.split('=', 1)[1].split()
                
                # Classify device type
                name_lower = device['name'].lower()
                if any(term in name_lower for term in ['mouse', 'optical', 'wireless']):
                    device['type'] = 'mouse'
                elif any(term in name_lower for term in ['touchpad', 'trackpad', 'synaptics']):
                    device['type'] = 'trackpad'
                elif 'keyboard' in name_lower:
                    device['type'] = 'keyboard'
                
                devices.append(device)
                
        except FileNotFoundError:
            self.logger.warning("Could not read /proc/bus/input/devices")
        
        return devices
    
    def _check_mouse_detected(self, devices: List[Dict]) -> bool:
        """Check if any mouse devices are detected"""
        return any(device['type'] == 'mouse' for device in devices)
    
    def _check_trackpad_detected(self, devices: List[Dict]) -> bool:
        """Check if trackpad is detected"""
        return any(device['type'] == 'trackpad' for device in devices)
    
    def _check_packages(self) -> List[str]:
        """Check for missing required packages"""
        missing = []
        for package in self.required_packages:
            try:
                result = subprocess.run(['dpkg', '-l', package], 
                                      capture_output=True, text=True)
                if result.returncode != 0:
                    missing.append(package)
            except Exception:
                missing.append(package)
        
        return missing
    
    def _check_kernel_modules(self) -> Dict[str, bool]:
        """Check if USB-related kernel modules are loaded"""
        modules = {}
        try:
            with open('/proc/modules', 'r') as f:
                loaded_modules = f.read()
            
            for module in self.usb_modules:
                modules[module] = module in loaded_modules
                
        except FileNotFoundError:
            for module in self.usb_modules:
                modules[module] = False
        
        return modules
    
    def _get_display_server(self) -> Optional[str]:
        """Get current display server (X11/Wayland)"""
        try:
            if os.environ.get('WAYLAND_DISPLAY'):
                return 'wayland'
            elif os.environ.get('DISPLAY'):
                return 'x11'
            else:
                return None
        except Exception:
            return None
    
    def _is_wayland_active(self) -> bool:
        """Check if Wayland is active"""
        return self._get_display_server() == 'wayland'
    
    def _detect_usb_passthrough(self) -> bool:
        """Detect if USB passthrough is likely active"""
        try:
            # Check for VFIO devices
            vfio_path = Path('/dev/vfio')
            if vfio_path.exists():
                vfio_devices = list(vfio_path.glob('*'))
                if len(vfio_devices) > 1:  # More than just /dev/vfio/vfio
                    return True
            
            # Check dmesg for VFIO messages
            result = subprocess.run(['dmesg'], capture_output=True, text=True)
            if result.returncode == 0:
                dmesg_content = result.stdout.lower()
                if 'vfio' in dmesg_content and 'usb' in dmesg_content:
                    return True
            
        except Exception as e:
            self.logger.debug(f"Could not detect USB passthrough: {e}")
        
        return False
    
    def _analyze_diagnosis(self, diagnosis: Dict[str, any]):
        """Analyze diagnosis results and generate recommendations"""
        issues = []
        recommendations = []
        
        # Check for common issues
        if not diagnosis['is_ubuntu']:
            issues.append("Not running Ubuntu - this tool is Ubuntu-specific")
        
        if not diagnosis['is_vm']:
            issues.append("Not running in a virtual machine")
        
        if diagnosis['trackpad_detected'] and not diagnosis['mouse_detected']:
            issues.append("Trackpad detected but no physical mouse found")
            recommendations.append("Install USB mouse drivers and check USB passthrough")
        
        if diagnosis['missing_packages']:
            issues.append(f"Missing packages: {', '.join(diagnosis['missing_packages'])}")
            recommendations.append("Install missing packages for better input support")
        
        unloaded_modules = [mod for mod, loaded in diagnosis['kernel_modules'].items() if not loaded]
        if unloaded_modules:
            issues.append(f"USB modules not loaded: {', '.join(unloaded_modules)}")
            recommendations.append("Load missing USB kernel modules")
        
        if diagnosis['wayland_active']:
            issues.append("Wayland may cause input issues with USB passthrough")
            recommendations.append("Consider switching to X11 for better USB mouse support")
        
        if diagnosis['usb_passthrough_detected']:
            issues.append("USB passthrough detected - may need specific configuration")
            recommendations.append("Apply USB passthrough-specific mouse fixes")
        
        diagnosis['issues'] = issues
        diagnosis['recommendations'] = recommendations
    
    def display_diagnosis_results(self, diagnosis: Dict[str, any]):
        """Display comprehensive diagnosis results"""
        # System Information Table
        system_table = Table(title="System Information")
        system_table.add_column("Component", style="cyan")
        system_table.add_column("Status", style="bold")
        system_table.add_column("Details")
        
        system_table.add_row(
            "Operating System",
            "✅ Ubuntu" if diagnosis['is_ubuntu'] else "❌ Not Ubuntu",
            "Ubuntu detected" if diagnosis['is_ubuntu'] else "This tool is Ubuntu-specific"
        )
        
        system_table.add_row(
            "Virtualization",
            "✅ VM Detected" if diagnosis['is_vm'] else "❌ Physical System",
            "Running in virtual machine" if diagnosis['is_vm'] else "Running on physical hardware"
        )
        
        system_table.add_row(
            "Display Server",
            f"📺 {diagnosis['display_server'].upper()}" if diagnosis['display_server'] else "❓ Unknown",
            "Wayland (may cause issues)" if diagnosis['wayland_active'] else "X11 (recommended)"
        )
        
        self.console.print(system_table)
        
        # Input Devices Table
        input_table = Table(title="Input Devices")
        input_table.add_column("Device Type", style="cyan")
        input_table.add_column("Status", style="bold")
        input_table.add_column("Count")
        
        mouse_count = len([d for d in diagnosis['input_devices'] if d['type'] == 'mouse'])
        trackpad_count = len([d for d in diagnosis['input_devices'] if d['type'] == 'trackpad'])
        
        input_table.add_row(
            "Physical Mouse",
            "✅ Detected" if diagnosis['mouse_detected'] else "❌ Not Found",
            str(mouse_count)
        )
        
        input_table.add_row(
            "Trackpad",
            "✅ Detected" if diagnosis['trackpad_detected'] else "❌ Not Found", 
            str(trackpad_count)
        )
        
        input_table.add_row(
            "USB Passthrough",
            "⚠️  Detected" if diagnosis['usb_passthrough_detected'] else "❌ Not Detected",
            "May need special config" if diagnosis['usb_passthrough_detected'] else "Standard setup"
        )
        
        self.console.print(input_table)
        
        # Issues and Recommendations
        if diagnosis['issues']:
            self.console.print(Panel(
                "\n".join(f"• {issue}" for issue in diagnosis['issues']),
                title="[bold red]Issues Found[/]",
                border_style="red"
            ))
        
        if diagnosis['recommendations']:
            self.console.print(Panel(
                "\n".join(f"• {rec}" for rec in diagnosis['recommendations']),
                title="[bold yellow]Recommendations[/]",
                border_style="yellow"
            ))
    
    def apply_automatic_fixes(self, diagnosis: Dict[str, any]) -> bool:
        """Apply automatic fixes based on diagnosis"""
        if not diagnosis['is_ubuntu']:
            self.console.print("[red]Cannot apply fixes - not running Ubuntu[/]")
            return False
        
        self.console.print(Panel(
            "[bold cyan]Applying Automatic USB Mouse Fixes[/]\n"
            "[white]This will install packages and configure drivers...[/]",
            title="Auto-Fix Starting",
            border_style="cyan"
        ))
        
        success = True
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console
        ) as progress:
            
            # Install missing packages
            if diagnosis['missing_packages']:
                task1 = progress.add_task("Installing missing packages...", total=None)
                if not self._install_packages(diagnosis['missing_packages']):
                    success = False
                progress.update(task1, completed=True)
            
            # Load kernel modules
            unloaded_modules = [mod for mod, loaded in diagnosis['kernel_modules'].items() if not loaded]
            if unloaded_modules:
                task2 = progress.add_task("Loading USB kernel modules...", total=None)
                if not self._load_kernel_modules(unloaded_modules):
                    success = False
                progress.update(task2, completed=True)
            
            # Configure X11 if Wayland is active
            if diagnosis['wayland_active']:
                task3 = progress.add_task("Configuring display server...", total=None)
                if not self._configure_x11():
                    success = False
                progress.update(task3, completed=True)
            
            # Apply USB passthrough fixes
            if diagnosis['usb_passthrough_detected']:
                task4 = progress.add_task("Applying USB passthrough fixes...", total=None)
                if not self._apply_usb_passthrough_fixes():
                    success = False
                progress.update(task4, completed=True)
            
            # Restart input services
            task5 = progress.add_task("Restarting input services...", total=None)
            if not self._restart_input_services():
                success = False
            progress.update(task5, completed=True)
        
        return success
    
    def _install_packages(self, packages: List[str]) -> bool:
        """Install missing packages"""
        try:
            self.console.print(f"Installing packages: {', '.join(packages)}")
            
            # Update package list first
            result = subprocess.run(['sudo', 'apt', 'update'], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                self.console.print(f"[red]Failed to update package list: {result.stderr}[/]")
                return False
            
            # Install packages
            cmd = ['sudo', 'apt', 'install', '-y'] + packages
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.console.print("[green]✅ Packages installed successfully[/]")
                return True
            else:
                self.console.print(f"[red]Failed to install packages: {result.stderr}[/]")
                return False
                
        except Exception as e:
            self.console.print(f"[red]Error installing packages: {e}[/]")
            return False
    
    def _load_kernel_modules(self, modules: List[str]) -> bool:
        """Load kernel modules"""
        success = True
        for module in modules:
            try:
                result = subprocess.run(['sudo', 'modprobe', module],
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    self.console.print(f"[green]✅ Loaded module: {module}[/]")
                else:
                    self.console.print(f"[red]Failed to load module {module}: {result.stderr}[/]")
                    success = False
            except Exception as e:
                self.console.print(f"[red]Error loading module {module}: {e}[/]")
                success = False
        
        return success
    
    def _configure_x11(self) -> bool:
        """Configure system to use X11 instead of Wayland"""
        try:
            self.console.print("Configuring X11 display server...")
            
            # Modify GDM configuration
            gdm_config = "/etc/gdm3/custom.conf"
            if os.path.exists(gdm_config):
                # Read current config
                with open(gdm_config, 'r') as f:
                    content = f.read()
                
                # Add WaylandEnable=false if not present
                if 'WaylandEnable=false' not in content:
                    if '[daemon]' in content:
                        content = content.replace('[daemon]', '[daemon]\nWaylandEnable=false')
                    else:
                        content += '\n[daemon]\nWaylandEnable=false\n'
                    
                    # Write back
                    with open('/tmp/gdm_custom.conf', 'w') as f:
                        f.write(content)
                    
                    result = subprocess.run(['sudo', 'cp', '/tmp/gdm_custom.conf', gdm_config],
                                          capture_output=True, text=True)
                    
                    if result.returncode == 0:
                        self.console.print("[green]✅ X11 configured (restart required)[/]")
                        return True
                    else:
                        self.console.print(f"[red]Failed to configure X11: {result.stderr}[/]")
                        return False
            
        except Exception as e:
            self.console.print(f"[red]Error configuring X11: {e}[/]")
            return False
        
        return True
    
    def _apply_usb_passthrough_fixes(self) -> bool:
        """Apply USB passthrough specific fixes"""
        try:
            self.console.print("Applying USB passthrough fixes...")
            
            # Create udev rule for USB devices
            udev_rule = '''# USB mouse fix for passthrough
SUBSYSTEM=="usb", ATTRS{idVendor}=="*", ATTRS{idProduct}=="*", MODE="0666"
KERNEL=="event*", SUBSYSTEM=="input", MODE="0666"
'''
            
            with open('/tmp/99-usb-mouse-fix.rules', 'w') as f:
                f.write(udev_rule)
            
            result = subprocess.run([
                'sudo', 'cp', '/tmp/99-usb-mouse-fix.rules', 
                '/etc/udev/rules.d/99-usb-mouse-fix.rules'
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                # Reload udev rules
                subprocess.run(['sudo', 'udevadm', 'control', '--reload-rules'])
                subprocess.run(['sudo', 'udevadm', 'trigger'])
                self.console.print("[green]✅ USB passthrough fixes applied[/]")
                return True
            else:
                self.console.print(f"[red]Failed to apply USB fixes: {result.stderr}[/]")
                return False
                
        except Exception as e:
            self.console.print(f"[red]Error applying USB fixes: {e}[/]")
            return False
    
    def _restart_input_services(self) -> bool:
        """Restart input-related services"""
        services = ['systemd-logind', 'gdm3']
        success = True
        
        for service in services:
            try:
                result = subprocess.run(['sudo', 'systemctl', 'restart', service],
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    self.console.print(f"[green]✅ Restarted {service}[/]")
                else:
                    self.console.print(f"[yellow]Warning: Could not restart {service}[/]")
            except Exception as e:
                self.console.print(f"[yellow]Warning: Error restarting {service}: {e}[/]")
                success = False
        
        return success
    
    def run_interactive_fix(self):
        """Run interactive diagnosis and fix process"""
        self.console.print(Panel(
            "[bold cyan]Ubuntu USB Mouse Fix Utility[/]\n\n"
            "[white]This tool will diagnose and fix common USB mouse issues\n"
            "in Ubuntu VMs with USB controller passthrough.[/]\n\n"
            "[yellow]⚠️  Some fixes may require a system restart to take effect.[/]",
            title="Welcome",
            border_style="cyan"
        ))
        
        if not questionary.confirm("Start diagnosis?").ask():
            return
        
        # Run diagnosis
        diagnosis = self.diagnose_mouse_issue()
        
        # Display results
        self.display_diagnosis_results(diagnosis)
        
        # Offer to apply fixes
        if diagnosis['issues']:
            if questionary.confirm("Apply automatic fixes?").ask():
                success = self.apply_automatic_fixes(diagnosis)
                
                if success:
                    self.console.print(Panel(
                        "[bold green]✅ Fixes Applied Successfully![/]\n\n"
                        "[white]Please restart your system for all changes to take effect.\n"
                        "After restart, test your USB mouse functionality.[/]\n\n"
                        "[yellow]If issues persist, check the troubleshooting guide.[/]",
                        title="Success",
                        border_style="green"
                    ))
                else:
                    self.console.print(Panel(
                        "[bold red]⚠️  Some fixes failed to apply[/]\n\n"
                        "[white]Check the error messages above and try manual fixes.\n"
                        "You may need to run this tool with different permissions.[/]",
                        title="Partial Success",
                        border_style="yellow"
                    ))
        else:
            self.console.print(Panel(
                "[bold green]✅ No issues detected![/]\n\n"
                "[white]Your USB mouse configuration appears to be correct.\n"
                "If you're still experiencing issues, they may be hardware-related.[/]",
                title="All Good",
                border_style="green"
            ))


def main():
    """Main entry point for the USB mouse fix utility"""
    try:
        fix_utility = UbuntuUSBMouseFix()
        fix_utility.run_interactive_fix()
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/]")
        logger.exception("Unexpected error in USB mouse fix utility")


if __name__ == "__main__":
    main()