#!/usr/bin/env python3
# Made by trex099
# https://github.com/Trex099/Glint
"""
Privacy Mode Module for GLINT

Provides Tor-based network isolation for VMs:
- Routes VM traffic through Tor network
- Different IP address than host
- Identity rotation for fresh connections

IMPORTANT: This is NOT equivalent to Tor Browser.
For maximum privacy, use Tor Browser inside the VM.
"""

import os
import sys
import shutil
import subprocess
from typing import Tuple, Optional, List
from dataclasses import dataclass
from enum import Enum

# Add parent paths for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

try:
    from src.core_utils import print_info, print_error, print_success, print_warning
except ImportError:
    def print_info(msg): print(f"[INFO] {msg}")
    def print_error(msg): print(f"[ERROR] {msg}")
    def print_success(msg): print(f"[SUCCESS] {msg}")
    def print_warning(msg): print(f"[WARNING] {msg}")

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False


class PrivacyModeStatus(Enum):
    """Status of privacy mode"""
    DISABLED = "disabled"
    ENABLED = "enabled"
    NOT_AVAILABLE = "not_available"
    ERROR = "error"


@dataclass
class PrivacyModeConfig:
    """Configuration for privacy mode"""
    tor_trans_port: int = 9040
    tor_dns_port: int = 5353
    tor_control_port: int = 9051
    vm_network: str = "192.168.100.0/24"
    bridge_interface: str = "br0-privacy"
    bridge_ip: str = "192.168.100.1"


# Default configuration
DEFAULT_CONFIG = PrivacyModeConfig()


def check_tor_installed() -> Tuple[bool, str]:
    """
    Check if Tor is installed on the system.
    
    Returns:
        Tuple of (is_installed, message)
    """
    # Check for tor binary
    tor_path = shutil.which('tor')
    if not tor_path:
        return False, "Tor is not installed. Install with: sudo apt install tor"
    
    # Check if tor service exists
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'tor'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return True, f"Tor is installed and running ({tor_path})"
        else:
            return True, f"Tor is installed but not running ({tor_path})"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return True, f"Tor is installed ({tor_path})"


def check_stem_available() -> bool:
    """Check if stem library is available for Tor control."""
    try:
        import stem
        return True
    except ImportError:
        return False


def get_torrc_config(config: PrivacyModeConfig = None) -> str:
    """
    Generate torrc configuration for transparent proxy.
    
    Args:
        config: Privacy mode configuration
        
    Returns:
        torrc configuration string
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    return f"""# GLINT Privacy Mode - Transparent Proxy Configuration
# Generated automatically - DO NOT EDIT MANUALLY

# Transparent proxy settings
TransPort {config.tor_trans_port} IsolateClientAddr IsolateClientProtocol IsolateDestAddr IsolateDestPort
DNSPort {config.tor_dns_port}
AutomapHostsOnResolve 1
VirtualAddrNetworkIPv4 10.192.0.0/10

# Control port for identity rotation
ControlPort {config.tor_control_port}
CookieAuthentication 1

# Stream isolation for better privacy
IsolateSOCKSAuth 1
IsolateDestPort 1
IsolateDestAddr 1

# Logging
Log notice file /var/log/tor/glint-privacy.log
"""


def get_iptables_rules(config: PrivacyModeConfig = None) -> List[str]:
    """
    Generate iptables rules for redirecting VM traffic through Tor.
    
    Args:
        config: Privacy mode configuration
        
    Returns:
        List of iptables commands
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    # Get Tor user ID (varies by distro)
    tor_uid = _get_tor_uid()
    
    rules = [
        # Mark GLINT privacy rules for easy cleanup
        f"# GLINT Privacy Mode iptables rules",
        
        # NAT table - redirect VM traffic to Tor
        f"iptables -t nat -A PREROUTING -s {config.vm_network} -p tcp --syn -j REDIRECT --to-ports {config.tor_trans_port} -m comment --comment 'GLINT-PRIVACY'",
        f"iptables -t nat -A PREROUTING -s {config.vm_network} -p udp --dport 53 -j REDIRECT --to-ports {config.tor_dns_port} -m comment --comment 'GLINT-PRIVACY'",
        
        # Filter table - allow only TCP and DNS from VMs
        f"iptables -A FORWARD -s {config.vm_network} -p tcp -j ACCEPT -m comment --comment 'GLINT-PRIVACY'",
        f"iptables -A FORWARD -s {config.vm_network} -p udp --dport 53 -j ACCEPT -m comment --comment 'GLINT-PRIVACY'",
        
        # Block all other UDP (prevent leaks)
        f"iptables -A FORWARD -s {config.vm_network} -p udp -j DROP -m comment --comment 'GLINT-PRIVACY-LEAK-BLOCK'",
    ]
    
    return rules


def get_iptables_cleanup_rules() -> List[str]:
    """
    Generate commands to remove GLINT privacy iptables rules.
    
    Returns:
        List of iptables cleanup commands
    """
    return [
        # Remove all rules with GLINT-PRIVACY comment
        "iptables -t nat -S | grep 'GLINT-PRIVACY' | sed 's/-A/-D/' | xargs -I {} sh -c 'iptables -t nat {}'",
        "iptables -S | grep 'GLINT-PRIVACY' | sed 's/-A/-D/' | xargs -I {} sh -c 'iptables {}'",
    ]


def _get_tor_uid() -> int:
    """Get the UID of the Tor user."""
    try:
        import pwd
        for user in ['debian-tor', '_tor', 'tor']:
            try:
                return pwd.getpwnam(user).pw_uid
            except KeyError:
                continue
        return 0
    except ImportError:
        return 0


def rotate_identity() -> Tuple[bool, str]:
    """
    Request new Tor circuits (new exit IP).
    
    Uses the stem library to send NEWNYM signal to Tor.
    
    Returns:
        Tuple of (success, message)
    """
    if not check_stem_available():
        return False, "stem library not installed. Install with: pip install stem"
    
    try:
        from stem import Signal
        from stem.control import Controller
        
        with Controller.from_port(port=DEFAULT_CONFIG.tor_control_port) as controller:
            controller.authenticate()
            controller.signal(Signal.NEWNYM)
            return True, "Identity rotated. New circuits will be used for new connections."
    except Exception as e:
        return False, f"Failed to rotate identity: {e}"


def verify_tor_connection() -> Tuple[bool, str, Optional[str]]:
    """
    Verify that traffic is going through Tor.
    
    Returns:
        Tuple of (is_using_tor, message, exit_ip)
    """
    try:
        import urllib.request
        
        # Try check.torproject.org first
        try:
            req = urllib.request.Request(
                'https://check.torproject.org/api/ip',
                headers={'User-Agent': 'GLINT-Privacy-Check'}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                import json
                data = json.loads(response.read().decode())
                is_tor = data.get('IsTor', False)
                ip = data.get('IP', 'unknown')
                if is_tor:
                    return True, "Traffic is going through Tor", ip
                else:
                    return False, "Traffic is NOT going through Tor", ip
        except Exception:
            pass
        
        # Fallback to ifconfig.me
        req = urllib.request.Request(
            'https://ifconfig.me/ip',
            headers={'User-Agent': 'GLINT-Privacy-Check'}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            ip = response.read().decode().strip()
            return True, f"Got external IP (manual verification needed)", ip
            
    except Exception as e:
        return False, f"Could not verify: {e}", None


def get_host_ip() -> Optional[str]:
    """Get the host's real external IP address."""
    try:
        import urllib.request
        req = urllib.request.Request(
            'https://ifconfig.me/ip',
            headers={'User-Agent': 'GLINT-Host-Check'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode().strip()
    except Exception:
        return None


def show_privacy_mode_panel():
    """Display the privacy mode information panel with pros, cons, and disclaimer."""
    if not RICH_AVAILABLE:
        print("\n=== PRIVACY MODE (OPTIONAL) ===")
        print("Route all VM traffic through Tor network for IP isolation.")
        print("\nPROS:")
        print("  • VM gets different IP address than your host")
        print("  • Web services see Tor exit node, not your real IP")
        print("  • Can rotate identity for fresh connections")
        print("\nCONS:")
        print("  • Slower internet speeds (Tor overhead)")
        print("  • Some websites block Tor exit nodes")
        print("  • Only TCP traffic is anonymized (not UDP)")
        print("  • NOT equivalent to Tor Browser")
        print("\nDISCLAIMER:")
        print("  By enabling Privacy Mode, you acknowledge:")
        print("  • You are responsible for how you use this feature")
        print("  • This is NOT guaranteed anonymity")
        print("  • The developer is NOT liable for misuse")
        return
    
    # Rich panel
    pros_table = Table(show_header=False, box=None, padding=(0, 1))
    pros_table.add_column("", style="green")
    pros_table.add_row("✅ VM gets different IP address than your host")
    pros_table.add_row("✅ Web services see Tor exit node, not your real IP")
    pros_table.add_row("✅ Can rotate identity for fresh connections")
    
    cons_table = Table(show_header=False, box=None, padding=(0, 1))
    cons_table.add_column("", style="yellow")
    cons_table.add_row("⚠️  Slower internet speeds (Tor overhead)")
    cons_table.add_row("⚠️  Some websites block Tor exit nodes")
    cons_table.add_row("⚠️  Only TCP traffic is anonymized (not UDP)")
    cons_table.add_row("⚠️  NOT equivalent to Tor Browser")
    
    disclaimer = (
        "[bold red]⚖️ DISCLAIMER[/]\n"
        "By enabling Privacy Mode, you acknowledge:\n"
        "• You are responsible for how you use this feature\n"
        "• This is NOT guaranteed anonymity\n"
        "• The developer is NOT liable for misuse"
    )
    
    content = (
        "[bold cyan]Route all VM traffic through Tor network for IP isolation.[/]\n\n"
        "[bold green]PROS:[/]\n"
    )
    
    panel = Panel(
        f"{content}"
        "✅ VM gets different IP address than your host\n"
        "✅ Web services see Tor exit node, not your real IP\n"
        "✅ Can rotate identity for fresh connections\n\n"
        "[bold yellow]CONS:[/]\n"
        "⚠️  Slower internet speeds (Tor overhead)\n"
        "⚠️  Some websites block Tor exit nodes\n"
        "⚠️  Only TCP traffic is anonymized (not UDP)\n"
        "⚠️  NOT equivalent to Tor Browser\n\n"
        f"{disclaimer}",
        title="[bold magenta]🔒 PRIVACY MODE (OPTIONAL)[/]",
        border_style="magenta",
        width=70
    )
    
    console.print(panel)


def setup_privacy_bridge(config: PrivacyModeConfig = None) -> Tuple[bool, str]:
    """
    Create a network bridge for privacy mode VMs.
    
    Args:
        config: Privacy mode configuration
        
    Returns:
        Tuple of (success, message)
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    try:
        # Check if bridge already exists
        result = subprocess.run(
            ['ip', 'link', 'show', config.bridge_interface],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return True, f"Bridge {config.bridge_interface} already exists"
        
        # Create bridge
        commands = [
            ['ip', 'link', 'add', config.bridge_interface, 'type', 'bridge'],
            ['ip', 'addr', 'add', f"{config.bridge_ip}/24", 'dev', config.bridge_interface],
            ['ip', 'link', 'set', config.bridge_interface, 'up'],
        ]
        
        for cmd in commands:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return False, f"Failed to create bridge: {result.stderr}"
        
        return True, f"Created privacy bridge {config.bridge_interface}"
        
    except Exception as e:
        return False, f"Error setting up bridge: {e}"


def enable_ip_forwarding() -> bool:
    """Enable IP forwarding on the host."""
    try:
        result = subprocess.run(
            ['sysctl', '-w', 'net.ipv4.ip_forward=1'],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def get_privacy_qemu_args(config: PrivacyModeConfig = None, mac_addr: str = None) -> List[str]:
    """
    Get QEMU arguments for privacy mode networking.
    
    Args:
        config: Privacy mode configuration
        mac_addr: MAC address for the VM
        
    Returns:
        List of QEMU arguments
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    if mac_addr is None:
        import random
        mac_addr = f"52:54:00:{random.randint(0,255):02x}:{random.randint(0,255):02x}:{random.randint(0,255):02x}"
    
    return [
        "-netdev", f"bridge,id=privacy-net,br={config.bridge_interface}",
        "-device", f"virtio-net-pci,netdev=privacy-net,mac={mac_addr}"
    ]


def is_privacy_mode_available() -> Tuple[bool, List[str]]:
    """
    Check if all requirements for privacy mode are met.
    
    Returns:
        Tuple of (is_available, list_of_missing_requirements)
    """
    missing = []
    
    # Check Tor
    tor_installed, _ = check_tor_installed()
    if not tor_installed:
        missing.append("Tor not installed (sudo apt install tor)")
    
    # Check iptables
    if not shutil.which('iptables'):
        missing.append("iptables not found")
    
    # Check ip command
    if not shutil.which('ip'):
        missing.append("iproute2 not found (ip command)")
    
    # Check stem (optional but recommended)
    if not check_stem_available():
        missing.append("stem library for identity rotation (pip install stem)")
    
    return len(missing) == 0, missing


# Convenience function for menu integration
def privacy_mode_prompt() -> bool:
    """
    Show privacy mode panel and prompt user for confirmation.
    
    Returns:
        True if user wants to enable privacy mode
    """
    import questionary
    
    show_privacy_mode_panel()
    
    result = questionary.confirm(
        "Enable Privacy Mode for this session?",
        default=False
    ).ask()
    
    # Handle ESC/Ctrl+C gracefully
    return result if result is not None else False
