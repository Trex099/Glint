# Made by trex099
# https://github.com/Trex099/Glint
"""
USB Passthrough Cursor Resolution Module

This module provides enhanced cursor visibility solutions for USB passthrough
scenarios in QEMU VMs, addressing the common "invisible cursor" issue.
"""

import os
import logging
import sys
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Import the new error handling system
# from src.linux_vm.error_handling import (
#     GlintError, ErrorSeverity, ErrorCategory, get_error_handler,
#     safe_operation, HardwareError, ConfigurationError
# )

console = Console()
logger = logging.getLogger(__name__)


class DisplayBackend(Enum):
    """Available display backends for cursor fix"""
    SDL = "sdl"
    GTK = "gtk"
    VNC = "vnc"
    SPICE = "spice"


class VGAAdapter(Enum):
    """Available VGA adapters"""
    VIRTIO = "virtio"
    STD = "std"
    QXL = "qxl"
    CIRRUS = "cirrus"


@dataclass
class CursorFixConfig:
    """Configuration for cursor visibility fix"""
    display_backend: DisplayBackend
    vga_adapter: VGAAdapter
    enable_gl: bool = False
    use_tablet: bool = True
    use_virtio_input: bool = True
    custom_args: List[str] = None
    
    def __post_init__(self):
        if self.custom_args is None:
            self.custom_args = []


class USBPassthroughCursorFix:
    """
    Enhanced USB passthrough cursor visibility resolver
    
    Provides multiple strategies to fix the invisible cursor issue
    that commonly occurs with USB controller passthrough.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.console = Console()
        
        # Predefined fix configurations
        self.fix_profiles = {
            "recommended": CursorFixConfig(
                display_backend=DisplayBackend.SDL,
                vga_adapter=VGAAdapter.VIRTIO,
                enable_gl=False,
                use_tablet=True,
                use_virtio_input=True
            ),
            "safe_mode": CursorFixConfig(
                display_backend=DisplayBackend.GTK,
                vga_adapter=VGAAdapter.STD,
                enable_gl=False,
                use_tablet=True,
                use_virtio_input=False
            ),
            "performance": CursorFixConfig(
                display_backend=DisplayBackend.SDL,
                vga_adapter=VGAAdapter.VIRTIO,
                enable_gl=True,
                use_tablet=False,
                use_virtio_input=True
            ),
            "compatibility": CursorFixConfig(
                display_backend=DisplayBackend.VNC,
                vga_adapter=VGAAdapter.CIRRUS,
                enable_gl=False,
                use_tablet=True,
                use_virtio_input=False
            ),
            "ubuntu_usb_fix": CursorFixConfig(
                display_backend=DisplayBackend.SDL,
                vga_adapter=VGAAdapter.STD,
                enable_gl=False,
                use_tablet=True,
                use_virtio_input=False,
                custom_args=[
                    "-device", "ich9-usb-ehci1,id=usb",
                    "-device", "ich9-usb-uhci1,masterbus=usb.0,firstport=0",
                    "-device", "ich9-usb-uhci2,masterbus=usb.0,firstport=2", 
                    "-device", "ich9-usb-uhci3,masterbus=usb.0,firstport=4",
                    "-device", "usb-mouse,bus=usb.0"
                ]
            )
        }
    
    def detect_cursor_issue_risk(self, passthrough_info: Dict) -> Tuple[bool, str]:
        """
        Analyze passthrough configuration to detect cursor issue risk
        
        Returns:
            Tuple of (has_risk, risk_description)
        """
        is_usb_passthrough = any(
            d.get('class_code') == '0c03' 
            for d in passthrough_info.get('devices', {}).values()
        )
        
        is_gpu_passthrough = any(
            d.get('class_code') == '0300' 
            for d in passthrough_info.get('devices', {}).values()
        )
        
        if is_usb_passthrough and not is_gpu_passthrough:
            return True, "USB controller passthrough without GPU passthrough detected"
        elif is_usb_passthrough and is_gpu_passthrough:
            return True, "Combined USB and GPU passthrough detected"
        
        return False, "No cursor issue risk detected"
    
    def get_user_preference(self, risk_description: str) -> Optional[str]:
        """
        Interactive selection of cursor fix strategy
        
        Returns:
            Selected profile name or None if cancelled
        """
        self.console.print(Panel(
            f"[yellow]⚠️  Cursor Issue Risk Detected[/]\n\n"
            f"[white]{risk_description}[/]\n\n"
            f"[cyan]This may cause an invisible mouse cursor in the VM.[/]",
            title="USB Passthrough Warning",
            border_style="yellow"
        ))
        
        choices = [
            questionary.Choice(
                "🎯 Recommended Fix (SDL + VirtIO GPU)",
                value="recommended"
            ),
            questionary.Choice(
                "🛡️  Safe Mode (GTK + Standard VGA)",
                value="safe_mode"
            ),
            questionary.Choice(
                "⚡ Performance Mode (SDL + VirtIO + OpenGL)",
                value="performance"
            ),
            questionary.Choice(
                "🔧 Compatibility Mode (VNC + Cirrus)",
                value="compatibility"
            ),
            questionary.Separator(),
            questionary.Choice(
                "⚙️  Custom Configuration",
                value="custom"
            ),
            questionary.Choice(
                "❌ Skip Fix (Keep Current Settings)",
                value="skip"
            )
        ]
        
        selection = questionary.select(
            "Choose a cursor visibility fix strategy:",
            choices=choices,
            use_indicator=True
        ).ask()
        
        if selection == "custom":
            return self._get_custom_configuration()
        
        return selection
    
    def _get_custom_configuration(self) -> str:
        """
        Interactive custom configuration builder
        
        Returns:
            Profile name for the custom configuration
        """
        self.console.print("\n[bold cyan]Custom Cursor Fix Configuration[/]")
        
        # Display backend selection
        display_choices = [
            questionary.Choice("SDL (Recommended for performance)", DisplayBackend.SDL),
            questionary.Choice("GTK (Good compatibility)", DisplayBackend.GTK),
            questionary.Choice("VNC (Remote access friendly)", DisplayBackend.VNC),
            questionary.Choice("SPICE (Advanced features)", DisplayBackend.SPICE)
        ]
        
        display_backend = questionary.select(
            "Select display backend:",
            choices=display_choices
        ).ask()
        
        # VGA adapter selection
        vga_choices = [
            questionary.Choice("VirtIO GPU (Best performance)", VGAAdapter.VIRTIO),
            questionary.Choice("Standard VGA (Maximum compatibility)", VGAAdapter.STD),
            questionary.Choice("QXL (SPICE optimized)", VGAAdapter.QXL),
            questionary.Choice("Cirrus (Legacy compatibility)", VGAAdapter.CIRRUS)
        ]
        
        vga_adapter = questionary.select(
            "Select VGA adapter:",
            choices=vga_choices
        ).ask()
        
        # Additional options
        enable_gl = questionary.confirm(
            "Enable OpenGL acceleration? (May cause issues on some systems)"
        ).ask()
        
        use_tablet = questionary.confirm(
            "Use USB tablet for absolute positioning? (Recommended)"
        ).ask()
        
        use_virtio_input = questionary.confirm(
            "Use VirtIO input devices? (Better performance)"
        ).ask()
        
        # Create custom profile
        custom_config = CursorFixConfig(
            display_backend=display_backend,
            vga_adapter=vga_adapter,
            enable_gl=enable_gl,
            use_tablet=use_tablet,
            use_virtio_input=use_virtio_input
        )
        
        self.fix_profiles["custom"] = custom_config
        
        # Show configuration summary
        self._display_config_summary(custom_config)
        
        return "custom"
    
    def _display_config_summary(self, config: CursorFixConfig):
        """Display configuration summary to user"""
        table = Table(show_header=False, box=None)
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="white")
        
        table.add_row("Display Backend:", config.display_backend.value.upper())
        table.add_row("VGA Adapter:", config.vga_adapter.value.upper())
        table.add_row("OpenGL:", "✅ Enabled" if config.enable_gl else "❌ Disabled")
        table.add_row("USB Tablet:", "✅ Enabled" if config.use_tablet else "❌ Disabled")
        table.add_row("VirtIO Input:", "✅ Enabled" if config.use_virtio_input else "❌ Disabled")
        
        self.console.print(Panel(
            table,
            title="[bold green]Custom Configuration Summary[/]",
            border_style="green"
        ))
    
    def apply_cursor_fix(self, qemu_cmd: List[str], profile_name: str, 
                        passthrough_info: Dict) -> List[str]:
        """
        Apply cursor fix configuration to QEMU command
        
        Args:
            qemu_cmd: Current QEMU command list
            profile_name: Selected fix profile name
            passthrough_info: Passthrough device information
            
        Returns:
            Modified QEMU command list
        """
        if profile_name == "skip":
            self.logger.info("Skipping cursor fix as requested by user")
            return qemu_cmd
        
        if profile_name not in self.fix_profiles:
            self.logger.warning(f"Unknown profile '{profile_name}', using recommended")
            profile_name = "recommended"
        
        config = self.fix_profiles[profile_name]
        self.logger.info(f"Applying cursor fix profile: {profile_name}")
        
        # Remove existing display/VGA arguments
        qemu_cmd = self._remove_existing_display_args(qemu_cmd)
        
        # Apply display backend configuration
        qemu_cmd.extend(self._get_display_args(config))
        
        # Apply VGA adapter configuration
        qemu_cmd.extend(self._get_vga_args(config))
        
        # Apply input device configuration
        qemu_cmd.extend(self._get_input_args(config, passthrough_info))
        
        # Apply Ubuntu-specific USB mouse fixes
        qemu_cmd.extend(self._get_ubuntu_usb_mouse_fixes(passthrough_info))
        
        # Add any custom arguments
        if config.custom_args:
            qemu_cmd.extend(config.custom_args)
        
        self.logger.debug(f"Applied cursor fix configuration: {config}")
        return qemu_cmd
    
    def _remove_existing_display_args(self, qemu_cmd: List[str]) -> List[str]:
        """Remove existing display and VGA arguments from QEMU command"""
        filtered_cmd = []
        skip_next = False
        
        for i, arg in enumerate(qemu_cmd):
            if skip_next:
                skip_next = False
                continue
                
            if arg in ["-display", "-vga", "-device"]:
                # Check if next argument is display/VGA related
                if i + 1 < len(qemu_cmd):
                    next_arg = qemu_cmd[i + 1]
                    if (arg == "-display" or 
                        (arg == "-vga") or
                        (arg == "-device" and any(dev in next_arg for dev in 
                         ["virtio-gpu", "virtio-vga", "virtio-keyboard", "virtio-mouse", "usb-tablet"]))):
                        skip_next = True
                        continue
            
            filtered_cmd.append(arg)
        
        return filtered_cmd
    
    def _get_display_args(self, config: CursorFixConfig) -> List[str]:
        """Generate display backend arguments"""
        args = []
        
        if config.display_backend == DisplayBackend.SDL:
            display_arg = "sdl"
            if config.enable_gl:
                display_arg += ",gl=on"
        elif config.display_backend == DisplayBackend.GTK:
            display_arg = "gtk"
            if config.enable_gl:
                display_arg += ",gl=on"
            else:
                display_arg += ",gl=off"
        elif config.display_backend == DisplayBackend.VNC:
            display_arg = "vnc=:1"
        elif config.display_backend == DisplayBackend.SPICE:
            display_arg = "spice-app"
        else:
            display_arg = "gtk,gl=off"  # fallback
        
        args.extend(["-display", display_arg])
        return args
    
    def _get_vga_args(self, config: CursorFixConfig) -> List[str]:
        """Generate VGA adapter arguments"""
        return ["-vga", config.vga_adapter.value]
    
    def _get_input_args(self, config: CursorFixConfig, passthrough_info: Dict) -> List[str]:
        """Generate input device arguments"""
        args = []
        
        # Add USB tablet for absolute positioning (helps with cursor tracking)
        if config.use_tablet:
            args.extend(["-device", "usb-tablet"])
        
        # Add VirtIO input devices if requested and not conflicting with passthrough
        if config.use_virtio_input:
            is_usb_passthrough = any(
                d.get('class_code') == '0c03' 
                for d in passthrough_info.get('devices', {}).values()
            )
            
            if not is_usb_passthrough:
                # Safe to add VirtIO input devices
                args.extend([
                    "-device", "virtio-keyboard-pci",
                    "-device", "virtio-mouse-pci"
                ])
            else:
                # USB passthrough detected, use alternative approach
                self.logger.info("USB passthrough detected, skipping VirtIO input devices")
        
        return args
    
    def test_cursor_visibility(self, vm_name: str) -> bool:
        """
        Test cursor visibility in a running VM
        
        This is a placeholder for future implementation that could
        connect to the VM and test cursor functionality.
        """
        self.logger.info(f"Testing cursor visibility for VM: {vm_name}")
        
        # Future implementation could:
        # 1. Connect to VM via VNC/SPICE
        # 2. Send mouse movement commands
        # 3. Capture screen to detect cursor
        # 4. Return success/failure
        
        return True
    
    def _get_ubuntu_usb_mouse_fixes(self, passthrough_info: Dict) -> List[str]:
        """
        Apply Ubuntu-specific USB mouse fixes for physical mouse not working
        
        This addresses the common issue where trackpad works but physical USB mouse
        doesn't work properly with USB controller passthrough in Ubuntu VMs.
        """
        args = []
        
        # Check if USB controller passthrough is detected
        is_usb_passthrough = any(
            d.get('class_code') == '0c03' 
            for d in passthrough_info.get('devices', {}).values()
        )
        
        if is_usb_passthrough:
            self.logger.info("Applying Ubuntu-specific USB mouse fixes")
            
            # Add EHCI and UHCI controllers for better USB compatibility
            args.extend([
                "-device", "ich9-usb-ehci1,id=usb",
                "-device", "ich9-usb-uhci1,masterbus=usb.0,firstport=0,multifunction=on",
                "-device", "ich9-usb-uhci2,masterbus=usb.0,firstport=2,multifunction=on",
                "-device", "ich9-usb-uhci3,masterbus=usb.0,firstport=4,multifunction=on"
            ])
            
            # Add USB hub for better device management
            args.extend(["-device", "usb-hub,bus=usb.0,port=1"])
            
            # Force USB 2.0 mode for better compatibility with physical mice
            args.extend(["-device", "usb-mouse,bus=usb.0,port=2"])
            
            # Add specific Ubuntu mouse driver compatibility
            args.extend([
                "-global", "usb-mouse.usb_version=2",
                "-global", "usb-tablet.usb_version=2"
            ])
            
            # Enable USB legacy support for older mice
            args.extend(["-device", "piix3-usb-uhci,id=uhci"])
            
            # Add mouse wheel support
            args.extend(["-device", "usb-mouse,wheel=on,bus=uhci.0"])
            
        return args
    
    def detect_ubuntu_mouse_issue(self) -> bool:
        """
        Detect if we're running Ubuntu and likely to have USB mouse issues
        """
        try:
            # Check if running on Ubuntu
            with open('/etc/os-release', 'r') as f:
                content = f.read()
                if 'ubuntu' in content.lower():
                    return True
        except FileNotFoundError:
            pass
        
        # Check for Ubuntu-specific paths
        ubuntu_indicators = [
            '/usr/bin/ubuntu-bug',
            '/etc/apt/sources.list',
            '/usr/share/ubuntu'
        ]
        
        return any(os.path.exists(path) for path in ubuntu_indicators)
    
    def get_ubuntu_specific_troubleshooting(self) -> str:
        """
        Get Ubuntu-specific troubleshooting steps for USB mouse issues
        """
        return """
[bold cyan]Ubuntu USB Mouse Troubleshooting[/]

[yellow]Physical Mouse Not Working (Trackpad Works):[/]

1. [bold]Check USB Controller Passthrough[/]
   • Verify USB controller is properly bound to VFIO
   • Check lspci -k for vfio-pci driver binding
   • Ensure IOMMU groups are correct

2. [bold]Ubuntu Guest Fixes[/]
   • Install: sudo apt install spice-vdagent
   • Install: sudo apt install qemu-guest-agent
   • Enable services: sudo systemctl enable spice-vdagent

3. [bold]USB Driver Issues[/]
   • Check dmesg | grep usb in guest
   • Try: sudo modprobe usbhid
   • Restart input services: sudo systemctl restart systemd-logind

4. [bold]Input Device Configuration[/]
   • Check /proc/bus/input/devices in guest
   • Verify mouse is detected: cat /proc/bus/input/devices | grep -A5 mouse
   • Test raw input: sudo evtest (select mouse device)

5. [bold]QEMU USB Configuration[/]
   • Use USB 2.0 controllers for better compatibility
   • Enable USB legacy support
   • Add multiple USB controller types (EHCI + UHCI)

6. [bold]Ubuntu Display Manager Issues[/]
   • Switch to X11: sudo dpkg-reconfigure gdm3
   • Disable Wayland: edit /etc/gdm3/custom.conf
   • Add: WaylandEnable=false under [daemon]

[green]Advanced Ubuntu Fixes:[/]
• Install Ubuntu hardware enablement stack
• Update kernel: sudo apt install linux-generic-hwe-22.04
• Check for proprietary drivers: ubuntu-drivers devices
        """
    
    def get_troubleshooting_info(self) -> str:
        """
        Generate troubleshooting information for cursor issues
        """
        base_info = """
[bold cyan]USB Passthrough Cursor Troubleshooting Guide[/]

[yellow]Common Issues and Solutions:[/]

1. [bold]Invisible Cursor[/]
   • Try SDL display backend with VirtIO GPU
   • Enable USB tablet device for absolute positioning
   • Disable OpenGL if experiencing issues

2. [bold]Cursor Lag or Jumping[/]
   • Switch to GTK display backend
   • Disable VirtIO input devices
   • Try Standard VGA adapter

3. [bold]No Cursor Movement[/]
   • Ensure USB tablet is enabled
   • Check if USB controller is properly passed through
   • Verify VFIO permissions

4. [bold]Display Issues[/]
   • Try different VGA adapters (VirtIO → STD → QXL)
   • Disable OpenGL acceleration
   • Use VNC for remote troubleshooting

[green]Advanced Options:[/]
• Use SPICE for advanced cursor features
• Enable guest tools for better integration
• Consider evdev passthrough for direct input
        """
        
        # Add Ubuntu-specific info if detected
        if self.detect_ubuntu_mouse_issue():
            base_info += "\n" + self.get_ubuntu_specific_troubleshooting()
        
        return base_info


def create_cursor_fix_manager() -> USBPassthroughCursorFix:
    """Factory function to create cursor fix manager"""
    return USBPassthroughCursorFix()