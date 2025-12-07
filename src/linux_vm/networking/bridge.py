# Made by trex099
# https://github.com/Trex099/Glint
"""
Bridge Networking Implementation for Linux VM Management

This module provides comprehensive bridge networking functionality including:
- Automatic bridge creation and management
- Bridge interface binding and VLAN support
- Bridge monitoring and troubleshooting tools
- Bridge security and isolation features
"""

import os
import sys
import subprocess
import json
import time
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from core_utils import (
    print_info, print_success, print_warning, print_error
)
from linux_vm.error_handling import (
    NetworkError, ConfigurationError, ResourceError,
    DependencyError, ValidationError, get_error_handler, safe_operation
)

console = Console()


class BridgeType(Enum):
    """Types of network bridges"""
    STANDARD = "standard"       # Standard Linux bridge
    OVS = "ovs"                # Open vSwitch bridge
    MACVLAN = "macvlan"        # MACVLAN bridge
    IPVLAN = "ipvlan"          # IPVLAN bridge


class BridgeState(Enum):
    """Bridge operational states"""
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass
class VLANConfig:
    """VLAN configuration for bridge interfaces"""
    vlan_id: int
    name: str
    tagged: bool = True
    priority: int = 0
    
    def __post_init__(self):
        """Validate VLAN configuration"""
        if not (1 <= self.vlan_id <= 4094):
            raise ValueError(f"Invalid VLAN ID: {self.vlan_id}. Must be between 1 and 4094")


@dataclass
class BridgeInterface:
    """Bridge interface configuration"""
    name: str
    mac_address: Optional[str] = None
    mtu: int = 1500
    vlan_config: Optional[VLANConfig] = None
    enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return asdict(self)


@dataclass
class BridgeConfig:
    """Comprehensive bridge configuration"""
    name: str
    bridge_type: BridgeType = BridgeType.STANDARD
    interfaces: List[BridgeInterface] = None
    ip_address: Optional[str] = None
    netmask: Optional[str] = None
    gateway: Optional[str] = None
    dhcp_enabled: bool = False
    stp_enabled: bool = True
    forward_delay: int = 15
    hello_time: int = 2
    max_age: int = 20
    ageing_time: int = 300
    vlan_filtering: bool = False
    multicast_snooping: bool = True
    created_at: Optional[str] = None
    description: Optional[str] = None
    
    def __post_init__(self):
        """Initialize default values"""
        if self.interfaces is None:
            self.interfaces = []
        if self.created_at is None:
            self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data['bridge_type'] = self.bridge_type.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BridgeConfig':
        """Create from dictionary"""
        # Convert bridge_type string back to enum
        if 'bridge_type' in data:
            data['bridge_type'] = BridgeType(data['bridge_type'])
        
        # Convert interfaces
        if 'interfaces' in data and data['interfaces']:
            interfaces = []
            for iface_data in data['interfaces']:
                if 'vlan_config' in iface_data and iface_data['vlan_config']:
                    iface_data['vlan_config'] = VLANConfig(**iface_data['vlan_config'])
                interfaces.append(BridgeInterface(**iface_data))
            data['interfaces'] = interfaces
        
        return cls(**data)


@dataclass
class BridgeStats:
    """Bridge statistics and monitoring data"""
    name: str
    state: BridgeState
    rx_packets: int = 0
    tx_packets: int = 0
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_errors: int = 0
    tx_errors: int = 0
    rx_dropped: int = 0
    tx_dropped: int = 0
    interface_count: int = 0
    uptime: int = 0
    last_updated: Optional[str] = None
    
    def __post_init__(self):
        """Initialize timestamp"""
        if self.last_updated is None:
            self.last_updated = time.strftime("%Y-%m-%d %H:%M:%S")


class BridgeManager:
    """
    Comprehensive bridge networking management system
    
    This class provides all functionality for creating, managing, and monitoring
    network bridges with VLAN support, security features, and troubleshooting tools.
    """
    
    def __init__(self, config_dir: str = None):
        """
        Initialize the Bridge Manager
        
        Args:
            config_dir: Directory to store bridge configurations
        """
        self.config_dir = config_dir or os.path.expanduser("~/.config/glint/bridges")
        self.bridges: Dict[str, BridgeConfig] = {}
        self.error_handler = get_error_handler()
        
        # Ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Load existing bridge configurations
        self._load_bridge_configs()
        
        # Check system capabilities
        self._check_system_capabilities()
    
    def _check_system_capabilities(self):
        """Check system capabilities for bridge networking - Universal compatibility"""
        try:
            # Check for multiple bridge management tools in order of preference
            bridge_tools = [
                ("ip", "iproute2 package"),
                ("brctl", "bridge-utils package"),
                ("ovs-vsctl", "openvswitch package")
            ]
            
            available_tools = []
            for tool, package in bridge_tools:
                if self._command_exists(tool):
                    available_tools.append((tool, package))
            
            if not available_tools:
                # Provide distribution-specific installation suggestions
                distro_suggestions = self._get_distro_specific_suggestions()
                raise DependencyError(
                    "No bridge utilities found",
                    code="GLINT-E901",
                    suggestions=distro_suggestions
                )
            
            # Check if bridge module is available (try multiple methods)
            if not self._is_bridge_support_available():
                print_warning("Bridge support not detected, attempting to enable...")
                if not self._enable_bridge_support():
                    print_warning("Bridge module loading failed - some features may be limited")
                    print_info("Bridge networking will use available fallback methods")
            
            print_success("✅ Bridge networking capabilities verified")
            print_info(f"Available tools: {', '.join([tool for tool, _ in available_tools])}")
            
        except Exception as e:
            self.error_handler.handle_error(e)
    
    def _get_distro_specific_suggestions(self):
        """Get distribution-specific installation suggestions"""
        suggestions = [
            "Universal: Install iproute2 (recommended for all distributions)",
            "Debian/Ubuntu: sudo apt update && sudo apt install iproute2 bridge-utils",
            "RHEL/CentOS/Fedora: sudo dnf install iproute bridge-utils",
            "Arch Linux: sudo pacman -S iproute2 bridge-utils",
            "openSUSE: sudo zypper install iproute2 bridge-utils",
            "Alpine Linux: sudo apk add iproute2 bridge-utils",
            "Gentoo: sudo emerge sys-apps/iproute2 net-misc/bridge-utils",
            "Check if kernel bridge module is available: lsmod | grep bridge"
        ]
        
        # Try to detect distribution and prioritize relevant suggestions
        try:
            import platform
            distro_info = platform.freedesktop_os_release()
            distro_id = distro_info.get('ID', '').lower()
            
            if distro_id in ['ubuntu', 'debian']:
                suggestions.insert(0, "Debian/Ubuntu: sudo apt update && sudo apt install iproute2 bridge-utils")
            elif distro_id in ['fedora', 'rhel', 'centos']:
                suggestions.insert(0, "RHEL/CentOS/Fedora: sudo dnf install iproute bridge-utils")
            elif distro_id in ['arch', 'manjaro']:
                suggestions.insert(0, "Arch Linux: sudo pacman -S iproute2 bridge-utils")
            elif distro_id in ['opensuse', 'sles']:
                suggestions.insert(0, "openSUSE: sudo zypper install iproute2 bridge-utils")
            elif distro_id == 'alpine':
                suggestions.insert(0, "Alpine Linux: sudo apk add iproute2 bridge-utils")
        except Exception:
            pass  # Fallback to generic suggestions
        
        return suggestions
    
    def _is_bridge_support_available(self):
        """Check if bridge support is available using multiple methods"""
        # Method 1: Check if bridge module is loaded
        if self._is_bridge_module_loaded():
            return True
        
        # Method 2: Check if bridge module exists but isn't loaded
        if self._bridge_module_exists():
            return True
        
        # Method 3: Check if bridge functionality is built into kernel
        if self._is_bridge_builtin():
            return True
        
        # Method 4: Try creating a test bridge to see if it works
        return self._test_bridge_functionality()
    
    def _bridge_module_exists(self):
        """Check if bridge module exists in the system"""
        try:
            result = subprocess.run(
                ["modinfo", "bridge"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _is_bridge_builtin(self):
        """Check if bridge support is built into the kernel"""
        try:
            # Check /proc/config.gz if available
            if os.path.exists("/proc/config.gz"):
                result = subprocess.run(
                    ["zcat", "/proc/config.gz"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    return "CONFIG_BRIDGE=y" in result.stdout
            
            # Check /boot/config-* files
            import glob
            config_files = glob.glob("/boot/config-*")
            for config_file in config_files:
                try:
                    with open(config_file, 'r') as f:
                        content = f.read()
                        if "CONFIG_BRIDGE=y" in content:
                            return True
                except Exception:
                    continue
            
            return False
        except Exception:
            return False
    
    def _test_bridge_functionality(self):
        """Test if bridge functionality works by attempting basic operations"""
        try:
            # Try to list bridges - this should work even without bridges present
            if self._command_exists("ip"):
                result = subprocess.run(
                    ["ip", "link", "show", "type", "bridge"],
                    capture_output=True,
                    text=True
                )
                return result.returncode == 0
            elif self._command_exists("brctl"):
                result = subprocess.run(
                    ["brctl", "show"],
                    capture_output=True,
                    text=True
                )
                return result.returncode == 0
            
            return False
        except Exception:
            return False
    
    def _enable_bridge_support(self):
        """Try to enable bridge support using multiple methods"""
        # Method 1: Try to load bridge module
        if self._load_bridge_module():
            return True
        
        # Method 2: Try alternative module names
        alternative_modules = ["br_netfilter", "bridge_netfilter"]
        for module in alternative_modules:
            try:
                result = subprocess.run(
                    ["sudo", "modprobe", module],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    print_info(f"Loaded {module} module")
            except Exception:
                continue
        
        # Method 3: Check if functionality is now available
        return self._test_bridge_functionality()
    
    def _command_exists(self, command: str) -> bool:
        """Check if a command exists in the system"""
        return subprocess.run(
            ["which", command], 
            capture_output=True, 
            text=True
        ).returncode == 0
    
    def _is_bridge_module_loaded(self) -> bool:
        """Check if bridge kernel module is loaded"""
        try:
            result = subprocess.run(
                ["lsmod"], 
                capture_output=True, 
                text=True, 
                check=True
            )
            return "bridge" in result.stdout
        except subprocess.CalledProcessError:
            return False
    
    def _load_bridge_module(self) -> bool:
        """Load bridge kernel module"""
        try:
            result = subprocess.run(
                ["sudo", "modprobe", "bridge"], 
                capture_output=True, 
                text=True
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _load_bridge_configs(self):
        """Load existing bridge configurations from disk"""
        try:
            for filename in os.listdir(self.config_dir):
                if filename.endswith('.json'):
                    bridge_name = filename[:-5]  # Remove .json extension
                    config_path = os.path.join(self.config_dir, filename)
                    
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    
                    self.bridges[bridge_name] = BridgeConfig.from_dict(config_data)
                    
        except Exception as e:
            print_warning(f"Failed to load some bridge configurations: {e}")
    
    def _save_bridge_config(self, bridge_name: str):
        """Save bridge configuration to disk"""
        try:
            config_path = os.path.join(self.config_dir, f"{bridge_name}.json")
            config_data = self.bridges[bridge_name].to_dict()
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4)
                
        except Exception as e:
            raise ConfigurationError(
                f"Failed to save bridge configuration for {bridge_name}",
                code="GLINT-E201",
                details=str(e),
                suggestions=[
                    "Check write permissions for configuration directory",
                    "Ensure sufficient disk space",
                    "Verify configuration directory exists"
                ]
            )
    
    @safe_operation
    def create_bridge(self, 
                     name: str, 
                     bridge_type: BridgeType = BridgeType.STANDARD,
                     interfaces: List[str] = None,
                     ip_address: str = None,
                     netmask: str = None,
                     vlan_filtering: bool = False,
                     description: str = None) -> bool:
        """
        Create a new network bridge
        
        Args:
            name: Bridge name
            bridge_type: Type of bridge to create
            interfaces: List of interfaces to add to bridge
            ip_address: IP address for the bridge
            netmask: Network mask for the bridge
            vlan_filtering: Enable VLAN filtering
            description: Bridge description
            
        Returns:
            bool: True if bridge was created successfully
        """
        if name in self.bridges:
            raise ResourceError(
                f"Bridge '{name}' already exists",
                code="GLINT-E302",
                suggestions=[
                    "Use a different bridge name",
                    f"Delete existing bridge first: delete_bridge('{name}')",
                    "Modify existing bridge instead"
                ]
            )
        
        # Validate bridge name
        if not self._validate_bridge_name(name):
            raise ValidationError(
                f"Invalid bridge name '{name}'",
                code="GLINT-E801",
                suggestions=[
                    "Use only alphanumeric characters, hyphens, and underscores",
                    "Bridge name must be 1-15 characters long",
                    "Bridge name cannot start with a number"
                ]
            )
        
        try:
            # Create bridge configuration
            bridge_config = BridgeConfig(
                name=name,
                bridge_type=bridge_type,
                ip_address=ip_address,
                netmask=netmask,
                vlan_filtering=vlan_filtering,
                description=description
            )
            
            # Create the actual bridge
            if bridge_type == BridgeType.STANDARD:
                success = self._create_standard_bridge(name, bridge_config)
            elif bridge_type == BridgeType.OVS:
                success = self._create_ovs_bridge(name, bridge_config)
            else:
                raise ConfigurationError(
                    f"Bridge type '{bridge_type.value}' not yet implemented",
                    code="GLINT-E203",
                    suggestions=[
                        "Use BridgeType.STANDARD for now",
                        "OVS support coming in future updates"
                    ]
                )
            
            if not success:
                raise NetworkError(
                    f"Failed to create bridge '{name}'",
                    code="GLINT-E500",
                    suggestions=[
                        "Check system logs for detailed error information",
                        "Verify bridge utilities are properly installed",
                        "Ensure sufficient privileges for bridge operations"
                    ]
                )
            
            # Add interfaces if specified
            if interfaces:
                for interface in interfaces:
                    self.add_interface_to_bridge(name, interface)
            
            # Configure IP if specified
            if ip_address and netmask:
                self._configure_bridge_ip(name, ip_address, netmask)
            
            # Store configuration
            self.bridges[name] = bridge_config
            self._save_bridge_config(name)
            
            # Set up comprehensive DNS and networking for the bridge
            print_info("Setting up comprehensive bridge networking...")
            try:
                from .bridge_dns_fix import auto_fix_bridge_dns
                dns_success = auto_fix_bridge_dns(name)
                if not dns_success:
                    print_warning("Comprehensive networking setup incomplete - trying fallback")
                    # Fallback to the existing method
                    dns_success = self.setup_bridge_dns(name)
                    if not dns_success:
                        print_warning("Bridge DNS setup failed - VMs may need manual configuration")
                else:
                    print_success("✅ Bridge networking configured with full internet connectivity")
            except Exception as e:
                print_warning(f"Comprehensive networking setup error: {e}")
                # Fallback to the existing method
                dns_success = self.setup_bridge_dns(name)
                if not dns_success:
                    print_warning("Bridge DNS setup failed - VMs may need manual configuration")
            
            print_success(f"✅ Successfully created bridge '{name}'")
            return True
            
        except Exception as e:
            # Clean up on failure
            self._cleanup_failed_bridge(name)
            raise e
    
    def _validate_bridge_name(self, name: str) -> bool:
        """Validate bridge name according to Linux naming rules"""
        if not name or len(name) > 15:
            return False
        
        # Must start with letter or underscore
        if not (name[0].isalpha() or name[0] == '_'):
            return False
        
        # Only alphanumeric, hyphens, and underscores allowed
        return re.match(r'^[a-zA-Z_][a-zA-Z0-9_-]*$', name) is not None
    
    def _create_standard_bridge(self, name: str, config: BridgeConfig) -> bool:
        """Create a standard Linux bridge with universal compatibility"""
        try:
            # Try multiple methods in order of preference
            methods = [
                ("ip_modern", self._create_bridge_with_ip),
                ("brctl_legacy", self._create_bridge_with_brctl),
                ("ip_legacy", self._create_bridge_with_ip_legacy),
                ("netlink", self._create_bridge_with_netlink)
            ]
            
            for method_name, method_func in methods:
                try:
                    if method_func(name, config):
                        print_info(f"Bridge created using {method_name} method")
                        return True
                except Exception as e:
                    print_warning(f"{method_name} method failed: {e}")
                    continue
            
            print_error("All bridge creation methods failed")
            return False
            
        except Exception as e:
            print_error(f"Exception creating bridge: {e}")
            return False
    
    def _create_bridge_with_ip(self, name: str, config: BridgeConfig) -> bool:
        """Create bridge using modern ip command"""
        if not self._command_exists("ip"):
            return False
        
        # Create bridge
        result = subprocess.run(
            ["sudo", "ip", "link", "add", "name", name, "type", "bridge"],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            return False
        
        # Configure bridge parameters
        self._configure_bridge_parameters(name, config)
        
        # Bring bridge up
        subprocess.run(
            ["sudo", "ip", "link", "set", name, "up"],
            capture_output=True,
            text=True
        )
        
        return True
    
    def _create_bridge_with_brctl(self, name: str, config: BridgeConfig) -> bool:
        """Create bridge using legacy brctl command"""
        if not self._command_exists("brctl"):
            return False
        
        # Create bridge
        result = subprocess.run(
            ["sudo", "brctl", "addbr", name],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            return False
        
        # Configure STP
        if config.stp_enabled:
            subprocess.run(
                ["sudo", "brctl", "stp", name, "on"],
                capture_output=True,
                text=True
            )
        
        # Configure other brctl parameters
        try:
            subprocess.run(["sudo", "brctl", "setfd", name, str(config.forward_delay)], 
                         capture_output=True, text=True)
            subprocess.run(["sudo", "brctl", "sethello", name, str(config.hello_time)], 
                         capture_output=True, text=True)
            subprocess.run(["sudo", "brctl", "setmaxage", name, str(config.max_age)], 
                         capture_output=True, text=True)
        except Exception:
            pass  # Non-critical parameters
        
        # Bring bridge up (try multiple methods)
        for up_cmd in [["sudo", "ip", "link", "set", name, "up"],
                      ["sudo", "ifconfig", name, "up"],
                      ["sudo", "ifup", name]]:
            try:
                result = subprocess.run(up_cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    break
            except Exception:
                continue
        
        return True
    
    def _create_bridge_with_ip_legacy(self, name: str, config: BridgeConfig) -> bool:
        """Create bridge using legacy ip command syntax"""
        if not self._command_exists("ip"):
            return False
        
        # Try alternative ip command syntax
        result = subprocess.run(
            ["sudo", "ip", "link", "add", name, "type", "bridge"],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            return False
        
        # Bring bridge up
        subprocess.run(
            ["sudo", "ip", "link", "set", "dev", name, "up"],
            capture_output=True,
            text=True
        )
        
        return True
    
    def _create_bridge_with_netlink(self, name: str, config: BridgeConfig) -> bool:
        """Create bridge using netlink interface (if available)"""
        try:
            # This would require pyroute2 or similar library
            # For now, return False to indicate not available
            return False
        except Exception:
            return False
    
    def _create_ovs_bridge(self, name: str, config: BridgeConfig) -> bool:
        """Create an Open vSwitch bridge"""
        # Check if OVS is available
        if not self._command_exists("ovs-vsctl"):
            raise DependencyError(
                "Open vSwitch not found",
                code="GLINT-E901",
                suggestions=[
                    "Install Open vSwitch: sudo apt install openvswitch-switch",
                    "Start OVS service: sudo systemctl start openvswitch-switch",
                    "Use standard bridge type instead"
                ]
            )
        
        try:
            # Create OVS bridge
            result = subprocess.run(
                ["sudo", "ovs-vsctl", "add-br", name],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                print_error(f"Failed to create OVS bridge: {result.stderr}")
                return False
            
            # Configure OVS-specific parameters
            if config.stp_enabled:
                subprocess.run(
                    ["sudo", "ovs-vsctl", "set", "bridge", name, "stp_enable=true"],
                    capture_output=True,
                    text=True
                )
            
            return True
            
        except Exception as e:
            print_error(f"Exception creating OVS bridge: {e}")
            return False
    
    def _configure_bridge_parameters(self, name: str, config: BridgeConfig):
        """Configure bridge parameters using multiple methods for universal compatibility"""
        try:
            # Method 1: Try sysfs configuration (most direct)
            if self._configure_bridge_via_sysfs(name, config):
                return
            
            # Method 2: Try brctl configuration (legacy but widely supported)
            if self._configure_bridge_via_brctl(name, config):
                return
            
            # Method 3: Try ip command configuration (modern)
            if self._configure_bridge_via_ip(name, config):
                return
            
            print_warning("Some bridge parameters could not be configured - using defaults")
                    
        except Exception as e:
            print_warning(f"Failed to configure bridge parameters: {e}")
    
    def _configure_bridge_via_sysfs(self, name: str, config: BridgeConfig) -> bool:
        """Configure bridge parameters using sysfs"""
        try:
            bridge_path = f"/sys/class/net/{name}/bridge"
            
            if not os.path.exists(bridge_path):
                return False
            
            success_count = 0
            total_attempts = 0
            
            # Configure STP parameters
            if config.stp_enabled:
                total_attempts += 4
                if self._write_sysfs_value_safe(f"{bridge_path}/stp_state", "1"):
                    success_count += 1
                if self._write_sysfs_value_safe(f"{bridge_path}/forward_delay", str(config.forward_delay)):
                    success_count += 1
                if self._write_sysfs_value_safe(f"{bridge_path}/hello_time", str(config.hello_time)):
                    success_count += 1
                if self._write_sysfs_value_safe(f"{bridge_path}/max_age", str(config.max_age)):
                    success_count += 1
            
            # Configure ageing time
            total_attempts += 1
            if self._write_sysfs_value_safe(f"{bridge_path}/ageing_time", str(config.ageing_time)):
                success_count += 1
            
            # Configure VLAN filtering
            if config.vlan_filtering:
                total_attempts += 1
                if self._write_sysfs_value_safe(f"{bridge_path}/vlan_filtering", "1"):
                    success_count += 1
            
            # Configure multicast snooping
            if config.multicast_snooping:
                total_attempts += 1
                if self._write_sysfs_value_safe(f"{bridge_path}/multicast_snooping", "1"):
                    success_count += 1
            
            # Consider successful if at least half the parameters were set
            return success_count >= (total_attempts / 2) if total_attempts > 0 else True
                    
        except Exception:
            return False
    
    def _configure_bridge_via_brctl(self, name: str, config: BridgeConfig) -> bool:
        """Configure bridge parameters using brctl"""
        if not self._command_exists("brctl"):
            return False
        
        try:
            success_count = 0
            
            # Configure STP
            if config.stp_enabled:
                result = subprocess.run(
                    ["sudo", "brctl", "stp", name, "on"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    success_count += 1
                
                # Configure STP parameters
                for cmd, value in [
                    (["sudo", "brctl", "setfd", name, str(config.forward_delay)], "forward delay"),
                    (["sudo", "brctl", "sethello", name, str(config.hello_time)], "hello time"),
                    (["sudo", "brctl", "setmaxage", name, str(config.max_age)], "max age"),
                    (["sudo", "brctl", "setageing", name, str(config.ageing_time)], "ageing time")
                ]:
                    try:
                        result = subprocess.run(cmd, capture_output=True, text=True)
                        if result.returncode == 0:
                            success_count += 1
                    except Exception:
                        continue
            
            return success_count > 0
            
        except Exception:
            return False
    
    def _configure_bridge_via_ip(self, name: str, config: BridgeConfig) -> bool:
        """Configure bridge parameters using ip command"""
        if not self._command_exists("ip"):
            return False
        
        try:
            success_count = 0
            
            # Try to configure basic parameters
            # Note: ip command has limited bridge parameter configuration
            # Most parameters need to be set via sysfs or brctl
            
            # Set MTU if needed
            try:
                result = subprocess.run(
                    ["sudo", "ip", "link", "set", name, "mtu", "1500"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    success_count += 1
            except Exception:
                pass
            
            return success_count > 0
            
        except Exception:
            return False
    
    def _write_sysfs_value_safe(self, path: str, value: str) -> bool:
        """Safely write value to sysfs file with error handling"""
        try:
            # Check if file exists and is writable
            if not os.path.exists(path):
                return False
            
            # Try multiple methods to write the value
            methods = [
                ["sudo", "sh", "-c", f"echo {value} > {path}"],
                ["sudo", "tee", path],
                ["sudo", "bash", "-c", f"echo {value} > {path}"]
            ]
            
            for method in methods:
                try:
                    if method[1] == "tee":
                        # Special handling for tee
                        process = subprocess.Popen(
                            method + [path],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True
                        )
                        stdout, stderr = process.communicate(input=value)
                        if process.returncode == 0:
                            return True
                    else:
                        result = subprocess.run(
                            method,
                            capture_output=True,
                            text=True
                        )
                        if result.returncode == 0:
                            return True
                except Exception:
                    continue
            
            return False
            
        except Exception:
            return False
    
    def _write_sysfs_value(self, path: str, value: str):
        """Write value to sysfs file"""
        try:
            subprocess.run(
                ["sudo", "sh", "-c", f"echo {value} > {path}"],
                capture_output=True,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError as e:
            print_warning(f"Failed to write {value} to {path}: {e}")
    
    def _configure_bridge_ip(self, name: str, ip_address: str, netmask: str):
        """Configure IP address for bridge"""
        try:
            # Use ip command to set IP
            subprocess.run(
                ["sudo", "ip", "addr", "add", f"{ip_address}/{netmask}", "dev", name],
                capture_output=True,
                text=True,
                check=True
            )
            print_success(f"✅ Configured IP {ip_address}/{netmask} for bridge {name}")
            
        except subprocess.CalledProcessError as e:
            print_warning(f"Failed to configure IP for bridge {name}: {e}")
    
    def _cleanup_failed_bridge(self, name: str):
        """Clean up a failed bridge creation"""
        try:
            # Try to delete the bridge if it was partially created
            if self._bridge_exists(name):
                subprocess.run(
                    ["sudo", "ip", "link", "delete", name],
                    capture_output=True,
                    text=True
                )
        except Exception:
            pass  # Ignore cleanup errors
    
    def _bridge_exists(self, name: str) -> bool:
        """Check if a bridge exists in the system"""
        try:
            result = subprocess.run(
                ["ip", "link", "show", name],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception:
            return False
    
    @safe_operation
    def delete_bridge(self, name: str, force: bool = False) -> bool:
        """
        Delete a network bridge
        
        Args:
            name: Bridge name to delete
            force: Force deletion even if interfaces are attached
            
        Returns:
            bool: True if bridge was deleted successfully
        """
        if name not in self.bridges:
            raise ResourceError(
                f"Bridge '{name}' not found",
                code="GLINT-E301",
                suggestions=[
                    "Check available bridges with list_bridges()",
                    "Verify bridge name spelling"
                ]
            )
        
        try:
            # Check if bridge has attached interfaces
            interfaces = self.get_bridge_interfaces(name)
            if interfaces and not force:
                raise ConfigurationError(
                    f"Bridge '{name}' has attached interfaces",
                    code="GLINT-E202",
                    details=f"Attached interfaces: {', '.join(interfaces)}",
                    suggestions=[
                        "Remove interfaces first or use force=True",
                        "Use remove_interface_from_bridge() for each interface"
                    ]
                )
            
            # Remove all interfaces if force is True
            if force and interfaces:
                for interface in interfaces:
                    self.remove_interface_from_bridge(name, interface)
            
            # Delete the bridge
            bridge_config = self.bridges[name]
            
            if bridge_config.bridge_type == BridgeType.STANDARD:
                success = self._delete_standard_bridge(name)
            elif bridge_config.bridge_type == BridgeType.OVS:
                success = self._delete_ovs_bridge(name)
            else:
                success = self._delete_standard_bridge(name)  # Fallback
            
            if not success:
                raise NetworkError(
                    f"Failed to delete bridge '{name}'",
                    code="GLINT-E500",
                    suggestions=[
                        "Check if bridge is in use by running VMs",
                        "Try stopping VMs using this bridge first",
                        "Check system logs for detailed error information"
                    ]
                )
            
            # Remove from configuration
            del self.bridges[name]
            
            # Remove configuration file
            config_path = os.path.join(self.config_dir, f"{name}.json")
            if os.path.exists(config_path):
                os.remove(config_path)
            
            print_success(f"✅ Successfully deleted bridge '{name}'")
            return True
            
        except Exception as e:
            if isinstance(e, (ResourceError, ConfigurationError, NetworkError)):
                raise e
            else:
                raise NetworkError(
                    f"Unexpected error deleting bridge '{name}': {str(e)}",
                    code="GLINT-E500",
                    original_exception=e
                )
    
    def _delete_standard_bridge(self, name: str) -> bool:
        """Delete a standard Linux bridge"""
        try:
            # Bring bridge down first
            subprocess.run(
                ["sudo", "ip", "link", "set", name, "down"],
                capture_output=True,
                text=True
            )
            
            # Delete bridge
            result = subprocess.run(
                ["sudo", "ip", "link", "delete", name],
                capture_output=True,
                text=True
            )
            
            return result.returncode == 0
            
        except Exception as e:
            print_error(f"Exception deleting standard bridge: {e}")
            return False
    
    def _delete_ovs_bridge(self, name: str) -> bool:
        """Delete an Open vSwitch bridge"""
        try:
            result = subprocess.run(
                ["sudo", "ovs-vsctl", "del-br", name],
                capture_output=True,
                text=True
            )
            
            return result.returncode == 0
            
        except Exception as e:
            print_error(f"Exception deleting OVS bridge: {e}")
            return False
    
    @safe_operation
    def add_interface_to_bridge(self, bridge_name: str, interface_name: str, 
                               vlan_config: VLANConfig = None) -> bool:
        """
        Add a network interface to a bridge
        
        Args:
            bridge_name: Name of the bridge
            interface_name: Name of the interface to add
            vlan_config: Optional VLAN configuration
            
        Returns:
            bool: True if interface was added successfully
        """
        if bridge_name not in self.bridges:
            raise ResourceError(
                f"Bridge '{bridge_name}' not found",
                code="GLINT-E301"
            )
        
        # Check if interface exists
        if not self._interface_exists(interface_name):
            raise ResourceError(
                f"Interface '{interface_name}' not found",
                code="GLINT-E301",
                suggestions=[
                    "Check available interfaces with 'ip link show'",
                    "Verify interface name spelling",
                    "Ensure interface is not virtual or already in use"
                ]
            )
        
        try:
            bridge_config = self.bridges[bridge_name]
            
            # Add interface to bridge
            if bridge_config.bridge_type == BridgeType.STANDARD:
                success = self._add_interface_to_standard_bridge(bridge_name, interface_name)
            elif bridge_config.bridge_type == BridgeType.OVS:
                success = self._add_interface_to_ovs_bridge(bridge_name, interface_name)
            else:
                success = self._add_interface_to_standard_bridge(bridge_name, interface_name)
            
            if not success:
                raise NetworkError(
                    f"Failed to add interface '{interface_name}' to bridge '{bridge_name}'",
                    code="GLINT-E500"
                )
            
            # Configure VLAN if specified
            if vlan_config:
                self._configure_interface_vlan(bridge_name, interface_name, vlan_config)
            
            # Update bridge configuration
            bridge_interface = BridgeInterface(
                name=interface_name,
                vlan_config=vlan_config
            )
            bridge_config.interfaces.append(bridge_interface)
            self._save_bridge_config(bridge_name)
            
            print_success(f"✅ Added interface '{interface_name}' to bridge '{bridge_name}'")
            return True
            
        except Exception as e:
            if isinstance(e, (ResourceError, NetworkError)):
                raise e
            else:
                raise NetworkError(
                    f"Unexpected error adding interface: {str(e)}",
                    code="GLINT-E500",
                    original_exception=e
                )
    
    def _interface_exists(self, interface_name: str) -> bool:
        """Check if a network interface exists"""
        try:
            result = subprocess.run(
                ["ip", "link", "show", interface_name],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _add_interface_to_standard_bridge(self, bridge_name: str, interface_name: str) -> bool:
        """Add interface to standard Linux bridge"""
        try:
            # Use ip command (preferred)
            if self._command_exists("ip"):
                result = subprocess.run(
                    ["sudo", "ip", "link", "set", interface_name, "master", bridge_name],
                    capture_output=True,
                    text=True
                )
            else:
                # Fallback to brctl
                result = subprocess.run(
                    ["sudo", "brctl", "addif", bridge_name, interface_name],
                    capture_output=True,
                    text=True
                )
            
            return result.returncode == 0
            
        except Exception as e:
            print_error(f"Exception adding interface to standard bridge: {e}")
            return False
    
    def _add_interface_to_ovs_bridge(self, bridge_name: str, interface_name: str) -> bool:
        """Add interface to OVS bridge"""
        try:
            result = subprocess.run(
                ["sudo", "ovs-vsctl", "add-port", bridge_name, interface_name],
                capture_output=True,
                text=True
            )
            
            return result.returncode == 0
            
        except Exception as e:
            print_error(f"Exception adding interface to OVS bridge: {e}")
            return False
    
    def _configure_interface_vlan(self, bridge_name: str, interface_name: str, vlan_config: VLANConfig):
        """Configure VLAN for interface on bridge"""
        try:
            bridge_config = self.bridges[bridge_name]
            
            if bridge_config.bridge_type == BridgeType.OVS:
                # OVS VLAN configuration
                subprocess.run([
                    "sudo", "ovs-vsctl", "set", "port", interface_name, 
                    f"tag={vlan_config.vlan_id}"
                ], capture_output=True, text=True)
                
            elif bridge_config.vlan_filtering:
                # Standard bridge with VLAN filtering
                subprocess.run([
                    "sudo", "bridge", "vlan", "add", "vid", str(vlan_config.vlan_id),
                    "dev", interface_name
                ], capture_output=True, text=True)
            
            print_success(f"✅ Configured VLAN {vlan_config.vlan_id} for interface {interface_name}")
            
        except Exception as e:
            print_warning(f"Failed to configure VLAN: {e}")
    
    @safe_operation
    def remove_interface_from_bridge(self, bridge_name: str, interface_name: str) -> bool:
        """
        Remove a network interface from a bridge
        
        Args:
            bridge_name: Name of the bridge
            interface_name: Name of the interface to remove
            
        Returns:
            bool: True if interface was removed successfully
        """
        if bridge_name not in self.bridges:
            raise ResourceError(
                f"Bridge '{bridge_name}' not found",
                code="GLINT-E301"
            )
        
        try:
            bridge_config = self.bridges[bridge_name]
            
            # Remove interface from bridge
            if bridge_config.bridge_type == BridgeType.STANDARD:
                success = self._remove_interface_from_standard_bridge(bridge_name, interface_name)
            elif bridge_config.bridge_type == BridgeType.OVS:
                success = self._remove_interface_from_ovs_bridge(bridge_name, interface_name)
            else:
                success = self._remove_interface_from_standard_bridge(bridge_name, interface_name)
            
            if not success:
                raise NetworkError(
                    f"Failed to remove interface '{interface_name}' from bridge '{bridge_name}'",
                    code="GLINT-E500"
                )
            
            # Update bridge configuration
            bridge_config.interfaces = [
                iface for iface in bridge_config.interfaces 
                if iface.name != interface_name
            ]
            self._save_bridge_config(bridge_name)
            
            print_success(f"✅ Removed interface '{interface_name}' from bridge '{bridge_name}'")
            return True
            
        except Exception as e:
            if isinstance(e, (ResourceError, NetworkError)):
                raise e
            else:
                raise NetworkError(
                    f"Unexpected error removing interface: {str(e)}",
                    code="GLINT-E500",
                    original_exception=e
                )
    
    def _remove_interface_from_standard_bridge(self, bridge_name: str, interface_name: str) -> bool:
        """Remove interface from standard Linux bridge"""
        try:
            # Use ip command (preferred)
            if self._command_exists("ip"):
                result = subprocess.run(
                    ["sudo", "ip", "link", "set", interface_name, "nomaster"],
                    capture_output=True,
                    text=True
                )
            else:
                # Fallback to brctl
                result = subprocess.run(
                    ["sudo", "brctl", "delif", bridge_name, interface_name],
                    capture_output=True,
                    text=True
                )
            
            return result.returncode == 0
            
        except Exception as e:
            print_error(f"Exception removing interface from standard bridge: {e}")
            return False
    
    def _remove_interface_from_ovs_bridge(self, bridge_name: str, interface_name: str) -> bool:
        """Remove interface from OVS bridge"""
        try:
            result = subprocess.run(
                ["sudo", "ovs-vsctl", "del-port", bridge_name, interface_name],
                capture_output=True,
                text=True
            )
            
            return result.returncode == 0
            
        except Exception as e:
            print_error(f"Exception removing interface from OVS bridge: {e}")
            return False
    
    def get_bridge_interfaces(self, bridge_name: str) -> List[str]:
        """
        Get list of interfaces attached to a bridge
        
        Args:
            bridge_name: Name of the bridge
            
        Returns:
            List[str]: List of interface names
        """
        if bridge_name not in self.bridges:
            return []
        
        try:
            bridge_config = self.bridges[bridge_name]
            
            if bridge_config.bridge_type == BridgeType.STANDARD:
                return self._get_standard_bridge_interfaces(bridge_name)
            elif bridge_config.bridge_type == BridgeType.OVS:
                return self._get_ovs_bridge_interfaces(bridge_name)
            else:
                return self._get_standard_bridge_interfaces(bridge_name)
                
        except Exception as e:
            print_warning(f"Failed to get bridge interfaces: {e}")
            return []
    
    def _get_standard_bridge_interfaces(self, bridge_name: str) -> List[str]:
        """Get interfaces for standard Linux bridge"""
        try:
            # Check if bridge exists in system
            bridge_path = f"/sys/class/net/{bridge_name}/brif"
            if os.path.exists(bridge_path):
                return os.listdir(bridge_path)
            else:
                return []
        except Exception:
            return []
    
    def _get_ovs_bridge_interfaces(self, bridge_name: str) -> List[str]:
        """Get interfaces for OVS bridge"""
        try:
            result = subprocess.run(
                ["ovs-vsctl", "list-ports", bridge_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return result.stdout.strip().split('\n') if result.stdout.strip() else []
            else:
                return []
                
        except Exception:
            return []
    
    def list_bridges(self) -> Dict[str, BridgeConfig]:
        """
        Get all configured bridges
        
        Returns:
            Dict[str, BridgeConfig]: Dictionary of bridge configurations
        """
        return self.bridges.copy()
    
    def get_bridge_config(self, bridge_name: str) -> Optional[BridgeConfig]:
        """
        Get configuration for a specific bridge
        
        Args:
            bridge_name: Name of the bridge
            
        Returns:
            Optional[BridgeConfig]: Bridge configuration or None if not found
        """
        return self.bridges.get(bridge_name)
    
    def get_bridge_stats(self, bridge_name: str) -> Optional[BridgeStats]:
        """
        Get statistics for a bridge
        
        Args:
            bridge_name: Name of the bridge
            
        Returns:
            Optional[BridgeStats]: Bridge statistics or None if not found
        """
        if bridge_name not in self.bridges:
            return None
        
        try:
            # Get bridge state
            state = self._get_bridge_state(bridge_name)
            
            # Get network statistics
            stats_path = f"/sys/class/net/{bridge_name}/statistics"
            stats = BridgeStats(name=bridge_name, state=state)
            
            if os.path.exists(stats_path):
                try:
                    stats.rx_packets = int(self._read_sysfs_value(f"{stats_path}/rx_packets"))
                    stats.tx_packets = int(self._read_sysfs_value(f"{stats_path}/tx_packets"))
                    stats.rx_bytes = int(self._read_sysfs_value(f"{stats_path}/rx_bytes"))
                    stats.tx_bytes = int(self._read_sysfs_value(f"{stats_path}/tx_bytes"))
                    stats.rx_errors = int(self._read_sysfs_value(f"{stats_path}/rx_errors"))
                    stats.tx_errors = int(self._read_sysfs_value(f"{stats_path}/tx_errors"))
                    stats.rx_dropped = int(self._read_sysfs_value(f"{stats_path}/rx_dropped"))
                    stats.tx_dropped = int(self._read_sysfs_value(f"{stats_path}/tx_dropped"))
                except (ValueError, FileNotFoundError):
                    pass  # Use default values
            
            # Get interface count
            stats.interface_count = len(self.get_bridge_interfaces(bridge_name))
            
            return stats
            
        except Exception as e:
            print_warning(f"Failed to get bridge stats: {e}")
            return None
    
    def _get_bridge_state(self, bridge_name: str) -> BridgeState:
        """Get the operational state of a bridge"""
        try:
            result = subprocess.run(
                ["ip", "link", "show", bridge_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                if "state UP" in result.stdout:
                    return BridgeState.UP
                elif "state DOWN" in result.stdout:
                    return BridgeState.DOWN
            
            return BridgeState.UNKNOWN
            
        except Exception:
            return BridgeState.UNKNOWN
    
    def _read_sysfs_value(self, path: str) -> str:
        """Read value from sysfs file"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception:
            return "0"
    
    def monitor_bridge(self, bridge_name: str, duration: int = 60) -> Dict[str, Any]:
        """
        Monitor bridge performance for a specified duration
        
        Args:
            bridge_name: Name of the bridge to monitor
            duration: Monitoring duration in seconds
            
        Returns:
            Dict[str, Any]: Monitoring results
        """
        if bridge_name not in self.bridges:
            raise ResourceError(
                f"Bridge '{bridge_name}' not found",
                code="GLINT-E301"
            )
        
        print_info(f"Monitoring bridge '{bridge_name}' for {duration} seconds...")
        
        # Initial stats
        initial_stats = self.get_bridge_stats(bridge_name)
        if not initial_stats:
            raise NetworkError(
                f"Failed to get initial stats for bridge '{bridge_name}'",
                code="GLINT-E500"
            )
        
        # Monitor with progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"Monitoring {bridge_name}...", total=duration)
            
            for i in range(duration):
                time.sleep(1)
                progress.update(task, advance=1)
        
        # Final stats
        final_stats = self.get_bridge_stats(bridge_name)
        if not final_stats:
            raise NetworkError(
                f"Failed to get final stats for bridge '{bridge_name}'",
                code="GLINT-E500"
            )
        
        # Calculate deltas
        monitoring_results = {
            'bridge_name': bridge_name,
            'duration': duration,
            'initial_stats': initial_stats,
            'final_stats': final_stats,
            'deltas': {
                'rx_packets': final_stats.rx_packets - initial_stats.rx_packets,
                'tx_packets': final_stats.tx_packets - initial_stats.tx_packets,
                'rx_bytes': final_stats.rx_bytes - initial_stats.rx_bytes,
                'tx_bytes': final_stats.tx_bytes - initial_stats.tx_bytes,
                'rx_errors': final_stats.rx_errors - initial_stats.rx_errors,
                'tx_errors': final_stats.tx_errors - initial_stats.tx_errors,
                'rx_dropped': final_stats.rx_dropped - initial_stats.rx_dropped,
                'tx_dropped': final_stats.tx_dropped - initial_stats.tx_dropped,
            },
            'rates': {
                'rx_packets_per_sec': (final_stats.rx_packets - initial_stats.rx_packets) / duration,
                'tx_packets_per_sec': (final_stats.tx_packets - initial_stats.tx_packets) / duration,
                'rx_bytes_per_sec': (final_stats.rx_bytes - initial_stats.rx_bytes) / duration,
                'tx_bytes_per_sec': (final_stats.tx_bytes - initial_stats.tx_bytes) / duration,
            }
        }
        
        print_success(f"✅ Monitoring completed for bridge '{bridge_name}'")
        return monitoring_results
    
    def troubleshoot_bridge(self, bridge_name: str) -> Dict[str, Any]:
        """
        Perform comprehensive troubleshooting for a bridge
        
        Args:
            bridge_name: Name of the bridge to troubleshoot
            
        Returns:
            Dict[str, Any]: Troubleshooting results and recommendations
        """
        if bridge_name not in self.bridges:
            raise ResourceError(
                f"Bridge '{bridge_name}' not found",
                code="GLINT-E301"
            )
        
        print_info(f"Troubleshooting bridge '{bridge_name}'...")
        
        troubleshooting_results = {
            'bridge_name': bridge_name,
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'checks': {},
            'issues': [],
            'recommendations': []
        }
        
        bridge_config = self.bridges[bridge_name]
        
        # Check 1: Bridge existence in system
        bridge_exists = self._bridge_exists(bridge_name)
        troubleshooting_results['checks']['bridge_exists'] = bridge_exists
        
        if not bridge_exists:
            troubleshooting_results['issues'].append(
                f"Bridge '{bridge_name}' does not exist in system"
            )
            troubleshooting_results['recommendations'].append(
                f"Recreate bridge with create_bridge('{bridge_name}')"
            )
        
        # Check 2: Bridge state
        if bridge_exists:
            bridge_state = self._get_bridge_state(bridge_name)
            troubleshooting_results['checks']['bridge_state'] = bridge_state.value
            
            if bridge_state == BridgeState.DOWN:
                troubleshooting_results['issues'].append(
                    f"Bridge '{bridge_name}' is in DOWN state"
                )
                troubleshooting_results['recommendations'].append(
                    f"Bring bridge up: sudo ip link set {bridge_name} up"
                )
        
        # Check 3: Interface consistency
        configured_interfaces = [iface.name for iface in bridge_config.interfaces]
        actual_interfaces = self.get_bridge_interfaces(bridge_name)
        
        troubleshooting_results['checks']['configured_interfaces'] = configured_interfaces
        troubleshooting_results['checks']['actual_interfaces'] = actual_interfaces
        
        missing_interfaces = set(configured_interfaces) - set(actual_interfaces)
        extra_interfaces = set(actual_interfaces) - set(configured_interfaces)
        
        if missing_interfaces:
            troubleshooting_results['issues'].append(
                f"Missing interfaces: {', '.join(missing_interfaces)}"
            )
            troubleshooting_results['recommendations'].append(
                "Re-add missing interfaces or update configuration"
            )
        
        if extra_interfaces:
            troubleshooting_results['issues'].append(
                f"Extra interfaces not in configuration: {', '.join(extra_interfaces)}"
            )
            troubleshooting_results['recommendations'].append(
                "Remove extra interfaces or update configuration"
            )
        
        # Check 4: Interface states
        interface_states = {}
        for interface in actual_interfaces:
            try:
                result = subprocess.run(
                    ["ip", "link", "show", interface],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    if "state UP" in result.stdout:
                        interface_states[interface] = "UP"
                    elif "state DOWN" in result.stdout:
                        interface_states[interface] = "DOWN"
                    else:
                        interface_states[interface] = "UNKNOWN"
                else:
                    interface_states[interface] = "NOT_FOUND"
            except Exception:
                interface_states[interface] = "ERROR"
        
        troubleshooting_results['checks']['interface_states'] = interface_states
        
        down_interfaces = [iface for iface, state in interface_states.items() if state == "DOWN"]
        if down_interfaces:
            troubleshooting_results['issues'].append(
                f"Interfaces in DOWN state: {', '.join(down_interfaces)}"
            )
            troubleshooting_results['recommendations'].append(
                "Bring down interfaces up or check physical connectivity"
            )
        
        # Check 5: Bridge statistics for errors
        stats = self.get_bridge_stats(bridge_name)
        if stats:
            troubleshooting_results['checks']['stats'] = {
                'rx_errors': stats.rx_errors,
                'tx_errors': stats.tx_errors,
                'rx_dropped': stats.rx_dropped,
                'tx_dropped': stats.tx_dropped
            }
            
            if stats.rx_errors > 0 or stats.tx_errors > 0:
                troubleshooting_results['issues'].append(
                    f"Network errors detected (RX: {stats.rx_errors}, TX: {stats.tx_errors})"
                )
                troubleshooting_results['recommendations'].append(
                    "Check network cables and interface drivers"
                )
            
            if stats.rx_dropped > 0 or stats.tx_dropped > 0:
                troubleshooting_results['issues'].append(
                    f"Dropped packets detected (RX: {stats.rx_dropped}, TX: {stats.tx_dropped})"
                )
                troubleshooting_results['recommendations'].append(
                    "Check system resources and network buffer sizes"
                )
        
        # Summary
        if not troubleshooting_results['issues']:
            troubleshooting_results['summary'] = f"Bridge '{bridge_name}' appears to be healthy"
        else:
            troubleshooting_results['summary'] = f"Found {len(troubleshooting_results['issues'])} issues with bridge '{bridge_name}'"
        
        return troubleshooting_results
    
    def setup_bridge_dns(self, bridge_name: str = "br0", dns_servers: List[str] = None) -> bool:
        """
        Set up DNS services for bridge networking to ensure VMs can resolve domain names.
        This addresses the common issue where bridged VMs get IP addresses but can't resolve DNS.
        
        Args:
            bridge_name: Name of the bridge interface
            dns_servers: List of DNS servers to use (defaults to host DNS + public DNS)
            
        Returns:
            bool: True if DNS setup was successful
        """
        try:
            if dns_servers is None:
                # Import here to avoid circular imports
                import sys
                import os
                sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
                from core_utils import find_host_dns
                
                host_dns = find_host_dns()
                dns_servers = [host_dns, "8.8.8.8", "1.1.1.1"]  # Host DNS + fallbacks
            
            print_info(f"Setting up DNS for bridge '{bridge_name}'...")
            
            # Method 1: Try dnsmasq (most reliable for bridge networking)
            if self._setup_dnsmasq_for_bridge(bridge_name, dns_servers):
                return True
            
            # Method 2: Try systemd-resolved configuration
            if self._setup_systemd_resolved_for_bridge(bridge_name, dns_servers):
                return True
            
            # Method 3: Try NetworkManager configuration
            if self._setup_networkmanager_for_bridge(bridge_name, dns_servers):
                return True
            
            # Method 4: Manual iptables DNS forwarding
            if self._setup_manual_dns_forwarding(bridge_name, dns_servers):
                return True
            
            print_warning("Could not set up automatic DNS for bridge networking")
            print_info("VMs may need manual DNS configuration inside the guest OS")
            self._show_manual_dns_instructions(dns_servers)
            return False
            
        except Exception as e:
            print_error(f"Error setting up bridge DNS: {e}")
            return False
    
    def _install_dnsmasq(self) -> bool:
        """Automatically install dnsmasq using the system package manager"""
        try:
            print_info("🔧 Installing dnsmasq...")
            
            # Try different package managers in order of preference
            install_commands = [
                # Debian/Ubuntu
                ["sudo", "apt", "update", "&&", "sudo", "apt", "install", "-y", "dnsmasq"],
                # Alternative Debian/Ubuntu (single command)
                ["sudo", "sh", "-c", "apt update && apt install -y dnsmasq"],
                # Fedora/RHEL/CentOS
                ["sudo", "dnf", "install", "-y", "dnsmasq"],
                # Older RHEL/CentOS
                ["sudo", "yum", "install", "-y", "dnsmasq"],
                # Arch Linux
                ["sudo", "pacman", "-S", "--noconfirm", "dnsmasq"],
                # openSUSE
                ["sudo", "zypper", "install", "-y", "dnsmasq"],
                # Alpine Linux
                ["sudo", "apk", "add", "dnsmasq"]
            ]
            
            for cmd in install_commands:
                try:
                    print_info(f"Trying: {' '.join(cmd)}")
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    
                    if result.returncode == 0:
                        print_success("✅ dnsmasq installed successfully")
                        
                        # Enable and start the service
                        subprocess.run(["sudo", "systemctl", "enable", "dnsmasq"], 
                                     capture_output=True, text=True)
                        subprocess.run(["sudo", "systemctl", "start", "dnsmasq"], 
                                     capture_output=True, text=True)
                        
                        return True
                        
                except subprocess.TimeoutExpired:
                    print_warning("Installation command timed out")
                    continue
                except Exception as e:
                    print_warning(f"Installation attempt failed: {e}")
                    continue
            
            print_error("Could not install dnsmasq with any package manager")
            return False
            
        except Exception as e:
            print_error(f"Error during dnsmasq installation: {e}")
            return False

    def _setup_dnsmasq_for_bridge(self, bridge_name: str, dns_servers: List[str]) -> bool:
        """Set up dnsmasq to provide DNS services for the bridge"""
        try:
            # Check if dnsmasq is available, try to install if not
            if not self._command_exists("dnsmasq"):
                print_info("dnsmasq not found - installing automatically...")
                if not self._install_dnsmasq():
                    print_warning("Could not install dnsmasq automatically")
                    return False
            
            # Create dnsmasq configuration for the bridge
            config_dir = "/etc/dnsmasq.d"
            config_file = f"{config_dir}/glint-{bridge_name}.conf"
            
            # Get bridge IP range (assume 10.0.0.0/24 if not configured)
            bridge_ip = self._get_bridge_ip(bridge_name) or "10.0.0.1"
            network_base = ".".join(bridge_ip.split(".")[:-1])
            
            dnsmasq_config = f"""# Glint bridge DNS configuration for {bridge_name}
# Generated automatically - do not edit manually

# Bind to bridge interface only
interface={bridge_name}
bind-interfaces

# DHCP range for VMs
dhcp-range={network_base}.10,{network_base}.100,12h

# DNS servers to forward to
"""
            
            for dns in dns_servers:
                dnsmasq_config += f"server={dns}\n"
            
            dnsmasq_config += f"""
# Enable DNS forwarding
no-resolv
no-poll

# Cache settings
cache-size=1000
neg-ttl=60

# Logging (optional)
log-queries
log-dhcp
"""
            
            # Write configuration
            try:
                with open(config_file, 'w', encoding='utf-8') as f:
                    f.write(dnsmasq_config)
                
                # Restart dnsmasq to apply configuration
                restart_result = subprocess.run(
                    ["sudo", "systemctl", "restart", "dnsmasq"],
                    capture_output=True,
                    text=True
                )
                
                if restart_result.returncode == 0:
                    print_success(f"✅ dnsmasq configured for bridge '{bridge_name}'")
                    print_info(f"DNS servers: {', '.join(dns_servers)}")
                    print_info(f"DHCP range: {network_base}.10-{network_base}.100")
                    return True
                else:
                    print_warning(f"Failed to restart dnsmasq: {restart_result.stderr}")
                    return False
                    
            except PermissionError:
                print_warning("Need sudo access to configure dnsmasq")
                print_info("Run with sudo or configure dnsmasq manually")
                return False
                
        except Exception as e:
            print_warning(f"dnsmasq setup failed: {e}")
            return False
    
    def _setup_systemd_resolved_for_bridge(self, bridge_name: str, dns_servers: List[str]) -> bool:
        """Configure systemd-resolved for bridge DNS"""
        try:
            if not self._command_exists("systemd-resolve") and not self._command_exists("resolvectl"):
                return False
            
            # Use resolvectl (newer) or systemd-resolve (older)
            resolve_cmd = "resolvectl" if self._command_exists("resolvectl") else "systemd-resolve"
            
            # Set DNS servers for the bridge interface
            for dns in dns_servers:
                result = subprocess.run(
                    ["sudo", resolve_cmd, "--interface", bridge_name, "--set-dns", dns],
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    print_warning(f"Failed to set DNS {dns} for {bridge_name}")
                    return False
            
            print_success(f"✅ systemd-resolved configured for bridge '{bridge_name}'")
            return True
            
        except Exception as e:
            print_warning(f"systemd-resolved setup failed: {e}")
            return False
    
    def _setup_networkmanager_for_bridge(self, bridge_name: str, dns_servers: List[str]) -> bool:
        """Configure NetworkManager for bridge DNS"""
        try:
            if not self._command_exists("nmcli"):
                return False
            
            # Check if NetworkManager manages this bridge
            result = subprocess.run(
                ["nmcli", "connection", "show", bridge_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                return False
            
            # Set DNS servers
            dns_string = ",".join(dns_servers)
            result = subprocess.run(
                ["sudo", "nmcli", "connection", "modify", bridge_name, "ipv4.dns", dns_string],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                # Reload the connection
                subprocess.run(
                    ["sudo", "nmcli", "connection", "up", bridge_name],
                    capture_output=True,
                    text=True
                )
                print_success(f"✅ NetworkManager configured for bridge '{bridge_name}'")
                return True
            
            return False
            
        except Exception as e:
            print_warning(f"NetworkManager setup failed: {e}")
            return False
    
    def _setup_manual_dns_forwarding(self, bridge_name: str, dns_servers: List[str]) -> bool:
        """Set up manual DNS forwarding using iptables"""
        try:
            # This is a basic DNS forwarding setup
            # Enable IP forwarding
            subprocess.run(
                ["sudo", "sysctl", "-w", "net.ipv4.ip_forward=1"],
                capture_output=True,
                text=True
            )
            
            # Add iptables rules for DNS forwarding
            bridge_ip = self._get_bridge_ip(bridge_name)
            if not bridge_ip:
                return False
            
            # Allow DNS traffic through the bridge
            for dns in dns_servers:
                subprocess.run([
                    "sudo", "iptables", "-t", "nat", "-A", "POSTROUTING",
                    "-s", f"{bridge_ip}/24", "-d", dns, "-p", "udp", "--dport", "53",
                    "-j", "MASQUERADE"
                ], capture_output=True, text=True)
                
                subprocess.run([
                    "sudo", "iptables", "-t", "nat", "-A", "POSTROUTING", 
                    "-s", f"{bridge_ip}/24", "-d", dns, "-p", "tcp", "--dport", "53",
                    "-j", "MASQUERADE"
                ], capture_output=True, text=True)
            
            print_success(f"✅ Manual DNS forwarding configured for bridge '{bridge_name}'")
            return True
            
        except Exception as e:
            print_warning(f"Manual DNS forwarding setup failed: {e}")
            return False
    
    def _get_bridge_ip(self, bridge_name: str) -> Optional[str]:
        """Get the IP address of a bridge interface"""
        try:
            result = subprocess.run(
                ["ip", "addr", "show", bridge_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                import re
                # Look for inet address
                match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
                if match:
                    return match.group(1)
            
            return None
            
        except Exception:
            return None
    
    def _show_manual_dns_instructions(self, dns_servers: List[str]):
        """Show manual DNS configuration instructions for VMs"""
        print_info("Manual DNS configuration required inside VMs:")
        print_info("1. Edit /etc/resolv.conf in the VM:")
        for dns in dns_servers[:2]:  # Show first 2 DNS servers
            print_info(f"   echo 'nameserver {dns}' >> /etc/resolv.conf")
        
        print_info("2. Or configure DNS via network manager in the VM")
        print_info("3. For persistent configuration, edit network settings in the VM")
    
    def diagnose_bridge_dns(self, bridge_name: str = "br0") -> Dict[str, Any]:
        """
        Diagnose DNS issues with bridge networking
        
        Returns:
            Dict containing diagnostic information
        """
        diagnosis = {
            'bridge_exists': False,
            'bridge_ip': None,
            'dns_services': [],
            'recommendations': []
        }
        
        try:
            # Check if bridge exists
            result = subprocess.run(
                ["ip", "link", "show", bridge_name],
                capture_output=True,
                text=True
            )
            diagnosis['bridge_exists'] = result.returncode == 0
            
            if diagnosis['bridge_exists']:
                diagnosis['bridge_ip'] = self._get_bridge_ip(bridge_name)
            
            # Check for DNS services
            dns_services = []
            
            # Check dnsmasq
            if self._command_exists("dnsmasq"):
                result = subprocess.run(
                    ["systemctl", "is-active", "dnsmasq"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    dns_services.append("dnsmasq (active)")
                else:
                    dns_services.append("dnsmasq (inactive)")
            
            # Check systemd-resolved
            if self._command_exists("systemd-resolve") or self._command_exists("resolvectl"):
                result = subprocess.run(
                    ["systemctl", "is-active", "systemd-resolved"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    dns_services.append("systemd-resolved (active)")
                else:
                    dns_services.append("systemd-resolved (inactive)")
            
            diagnosis['dns_services'] = dns_services
            
            # Generate recommendations
            recommendations = []
            
            if not diagnosis['bridge_exists']:
                recommendations.append("Create bridge interface first")
            
            if not diagnosis['bridge_ip']:
                recommendations.append("Configure IP address for bridge")
            
            if not any("active" in service for service in dns_services):
                recommendations.append("Install and configure dnsmasq for bridge DNS")
                recommendations.append("Alternative: Configure systemd-resolved")
            
            diagnosis['recommendations'] = recommendations
            
            return diagnosis
            
        except Exception as e:
            diagnosis['error'] = str(e)
            return diagnosis

    def display_bridge_info(self, bridge_name: str = None):
        """
        Display comprehensive bridge information
        
        Args:
            bridge_name: Specific bridge name, or None for all bridges
        """
        if bridge_name:
            if bridge_name not in self.bridges:
                print_error(f"Bridge '{bridge_name}' not found")
                return
            bridges_to_show = {bridge_name: self.bridges[bridge_name]}
        else:
            bridges_to_show = self.bridges
        
        if not bridges_to_show:
            print_info("No bridges configured")
            return
        
        for name, config in bridges_to_show.items():
            # Bridge overview
            bridge_panel = f"[bold cyan]Bridge: {name}[/]\n"
            bridge_panel += f"Type: {config.bridge_type.value}\n"
            bridge_panel += f"Created: {config.created_at}\n"
            
            if config.description:
                bridge_panel += f"Description: {config.description}\n"
            
            # Network configuration
            if config.ip_address:
                bridge_panel += f"IP Address: {config.ip_address}"
                if config.netmask:
                    bridge_panel += f"/{config.netmask}"
                bridge_panel += "\n"
            
            # Bridge parameters
            bridge_panel += f"STP Enabled: {'Yes' if config.stp_enabled else 'No'}\n"
            bridge_panel += f"VLAN Filtering: {'Yes' if config.vlan_filtering else 'No'}\n"
            bridge_panel += f"Multicast Snooping: {'Yes' if config.multicast_snooping else 'No'}\n"
            
            console.print(Panel(
                bridge_panel,
                title="[green]Bridge Configuration[/]",
                border_style="green"
            ))
            
            # Interface table
            if config.interfaces:
                interface_table = Table(title=f"Interfaces on {name}")
                interface_table.add_column("Interface", style="cyan")
                interface_table.add_column("MAC Address", style="yellow")
                interface_table.add_column("MTU", style="green")
                interface_table.add_column("VLAN", style="magenta")
                interface_table.add_column("Status", style="blue")
                
                for interface in config.interfaces:
                    vlan_info = f"ID: {interface.vlan_config.vlan_id}" if interface.vlan_config else "None"
                    status = "Enabled" if interface.enabled else "Disabled"
                    
                    interface_table.add_row(
                        interface.name,
                        interface.mac_address or "Auto",
                        str(interface.mtu),
                        vlan_info,
                        status
                    )
                
                console.print(interface_table)
            else:
                print_info(f"No interfaces configured for bridge '{name}'")
            
            # Statistics
            stats = self.get_bridge_stats(name)
            if stats:
                stats_table = Table(title=f"Statistics for {name}")
                stats_table.add_column("Metric", style="cyan")
                stats_table.add_column("RX", style="green")
                stats_table.add_column("TX", style="yellow")
                
                stats_table.add_row("Packets", str(stats.rx_packets), str(stats.tx_packets))
                stats_table.add_row("Bytes", str(stats.rx_bytes), str(stats.tx_bytes))
                stats_table.add_row("Errors", str(stats.rx_errors), str(stats.tx_errors))
                stats_table.add_row("Dropped", str(stats.rx_dropped), str(stats.tx_dropped))
                
                console.print(stats_table)
            
            console.print()  # Add spacing between bridges


# Singleton instance for global access
_bridge_manager = None

def get_bridge_manager() -> BridgeManager:
    """
    Get the global bridge manager instance
    
    Returns:
        BridgeManager: The global bridge manager
    """
    global _bridge_manager
    if _bridge_manager is None:
        _bridge_manager = BridgeManager()
    return _bridge_manager


# Convenience functions for common operations
def create_bridge(name: str, **kwargs) -> bool:
    """Create a bridge using the global manager"""
    return get_bridge_manager().create_bridge(name, **kwargs)


def delete_bridge(name: str, force: bool = False) -> bool:
    """Delete a bridge using the global manager"""
    return get_bridge_manager().delete_bridge(name, force)


def add_interface_to_bridge(bridge_name: str, interface_name: str, vlan_config: VLANConfig = None) -> bool:
    """Add interface to bridge using the global manager"""
    return get_bridge_manager().add_interface_to_bridge(bridge_name, interface_name, vlan_config)


def remove_interface_from_bridge(bridge_name: str, interface_name: str) -> bool:
    """Remove interface from bridge using the global manager"""
    return get_bridge_manager().remove_interface_from_bridge(bridge_name, interface_name)


def list_bridges() -> Dict[str, BridgeConfig]:
    """List all bridges using the global manager"""
    return get_bridge_manager().list_bridges()


def monitor_bridge(bridge_name: str, duration: int = 60) -> Dict[str, Any]:
    """Monitor bridge using the global manager"""
    return get_bridge_manager().monitor_bridge(bridge_name, duration)


def troubleshoot_bridge(bridge_name: str) -> Dict[str, Any]:
    """Troubleshoot bridge using the global manager"""
    return get_bridge_manager().troubleshoot_bridge(bridge_name)


def display_bridge_info(bridge_name: str = None):
    """Display bridge information using the global manager"""
    return get_bridge_manager().display_bridge_info(bridge_name)


def setup_bridge_dns(bridge_name: str = "br0", dns_servers: List[str] = None) -> bool:
    """Set up DNS for bridge networking using the global manager"""
    return get_bridge_manager().setup_bridge_dns(bridge_name, dns_servers)


def diagnose_bridge_dns(bridge_name: str = "br0") -> Dict[str, Any]:
    """Diagnose bridge DNS issues using the global manager"""
    return get_bridge_manager().diagnose_bridge_dns(bridge_name)