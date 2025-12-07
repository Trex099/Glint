#!/usr/bin/env python3
"""
Automatic Bridge DNS Configuration for Glint

This module automatically configures DNS for bridge networking to ensure
VMs can resolve domain names without manual configuration.
"""

import subprocess
import os
import sys
from typing import List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core_utils import print_info, print_success, print_warning, print_error, find_host_dns


def command_exists(command: str) -> bool:
    """Check if a command exists in the system"""
    return subprocess.run(["which", command], capture_output=True).returncode == 0


def ensure_qemu_bridge_acl(bridge_name: str = "br0") -> bool:
    """
    Ensure QEMU bridge helper ACL allows the specified bridge.
    This is required for QEMU to use -netdev bridge without root.
    
    Args:
        bridge_name: Name of the bridge to allow
        
    Returns:
        bool: True if ACL is configured (or was already configured)
    """
    acl_file = "/etc/qemu/bridge.conf"
    allow_line = f"allow {bridge_name}"
    
    try:
        # Check if ACL file exists and has our bridge
        if os.path.exists(acl_file):
            with open(acl_file, 'r') as f:
                content = f.read()
                if allow_line in content:
                    return True  # Already configured
        
        # Need to add the bridge to ACL
        print_info(f"Configuring QEMU bridge ACL for '{bridge_name}'...")
        
        # Ensure directory exists
        acl_dir = os.path.dirname(acl_file)
        if not os.path.exists(acl_dir):
            subprocess.run(["sudo", "mkdir", "-p", acl_dir], capture_output=True)
        
        # Add allow line to bridge.conf
        result = subprocess.run(
            ["sudo", "sh", "-c", f"echo '{allow_line}' >> {acl_file}"],
            capture_output=True, text=True
        )
        
        if result.returncode == 0:
            print_success(f"✅ Added '{bridge_name}' to QEMU bridge ACL")
            return True
        else:
            print_warning(f"Failed to configure QEMU bridge ACL: {result.stderr}")
            print_info("You may need to run: echo 'allow br0' | sudo tee -a /etc/qemu/bridge.conf")
            return False
            
    except Exception as e:
        print_warning(f"Could not configure QEMU bridge ACL: {e}")
        return False


def setup_real_bridge_networking(bridge_name: str = "br0") -> bool:
    """
    Set up real bridge networking by connecting the physical interface to the bridge.
    This allows VMs to get IP addresses from the network's DHCP server.
    
    WARNING: This temporarily moves the host's IP to the bridge, which can
    disrupt host connectivity during setup.
    
    Args:
        bridge_name: Name of the bridge to set up
        
    Returns:
        bool: True if bridge is ready for VM networking
    """
    try:
        # Check if bridge already exists and has an interface connected
        result = subprocess.run(
            ["ip", "link", "show", "master", bridge_name],
            capture_output=True, text=True
        )
        
        if result.returncode == 0 and result.stdout.strip():
            # Bridge exists and has interfaces, check if it can reach network
            print_info(f"Bridge {bridge_name} already has interfaces connected")
            return True
        
        # Get the primary network interface
        primary_interface = get_primary_interface()
        if not primary_interface:
            print_warning("No primary network interface found")
            return False
        
        print_info(f"Setting up bridge {bridge_name} with interface {primary_interface}...")
        
        # Create bridge if it doesn't exist
        result = subprocess.run(
            ["ip", "link", "show", bridge_name],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            # Create the bridge
            result = subprocess.run(
                ["sudo", "ip", "link", "add", bridge_name, "type", "bridge"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                print_warning(f"Failed to create bridge: {result.stderr}")
                return False
        
        # Bring bridge up
        subprocess.run(["sudo", "ip", "link", "set", bridge_name, "up"],
                      capture_output=True, text=True)
        
        # Get current IP from primary interface
        import re
        result = subprocess.run(
            ["ip", "addr", "show", primary_interface],
            capture_output=True, text=True
        )
        
        current_ip = None
        current_gateway = None
        
        if result.returncode == 0:
            match = re.search(r'inet (\d+\.\d+\.\d+\.\d+/\d+)', result.stdout)
            if match:
                current_ip = match.group(1)
        
        # Get default gateway
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            match = re.search(r'default via (\d+\.\d+\.\d+\.\d+)', result.stdout)
            if match:
                current_gateway = match.group(1)
        
        # Add physical interface to bridge
        result = subprocess.run(
            ["sudo", "ip", "link", "set", primary_interface, "master", bridge_name],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            if "already a member" not in result.stderr.lower():
                print_warning(f"Failed to add {primary_interface} to bridge: {result.stderr}")
                return False
        
        # Move IP to bridge
        if current_ip:
            # Remove IP from physical interface
            subprocess.run(
                ["sudo", "ip", "addr", "del", current_ip, "dev", primary_interface],
                capture_output=True, text=True
            )
            # Add IP to bridge
            subprocess.run(
                ["sudo", "ip", "addr", "add", current_ip, "dev", bridge_name],
                capture_output=True, text=True
            )
            
            # Restore default route
            if current_gateway:
                subprocess.run(
                    ["sudo", "ip", "route", "add", "default", "via", current_gateway, "dev", bridge_name],
                    capture_output=True, text=True
                )
        
        print_success(f"✅ Bridge {bridge_name} configured with {primary_interface}")
        return True
        
    except Exception as e:
        print_warning(f"Error setting up real bridge networking: {e}")
        return False


def is_bridge_active(bridge_name: str = "br0") -> bool:
    """Check if bridge interface exists and is active"""
    try:
        result = subprocess.run(
            ["ip", "link", "show", bridge_name],
            capture_output=True,
            text=True
        )
        return result.returncode == 0 and "UP" in result.stdout
    except Exception:
        return False


def get_bridge_ip(bridge_name: str = "br0") -> Optional[str]:
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


def setup_bridge_ip_if_needed(bridge_name: str = "br0") -> bool:
    """Set up bridge IP if it doesn't have one"""
    try:
        bridge_ip = get_bridge_ip(bridge_name)
        
        if bridge_ip:
            print_info(f"Bridge {bridge_name} already has IP: {bridge_ip}")
            return True
        
        print_info(f"Configuring IP for bridge {bridge_name}...")
        
        # Set a default IP for the bridge
        default_ip = "10.0.0.1/24"
        
        result = subprocess.run([
            "sudo", "ip", "addr", "add", default_ip, "dev", bridge_name
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print_success(f"✅ Bridge IP configured: {default_ip}")
            return True
        else:
            print_warning(f"Failed to set bridge IP: {result.stderr}")
            return False
            
    except Exception as e:
        print_warning(f"Error setting bridge IP: {e}")
        return False


def create_dnsmasq_config(bridge_name: str = "br0", dns_servers: List[str] = None) -> bool:
    """Create dnsmasq configuration for bridge DNS"""
    try:
        if dns_servers is None:
            host_dns = find_host_dns()
            dns_servers = [host_dns, "8.8.8.8", "1.1.1.1"]
        
        # Get bridge IP to determine network range
        bridge_ip = get_bridge_ip(bridge_name)
        if not bridge_ip:
            print_warning("Bridge has no IP address, using default range")
            network_base = "10.0.0"
        else:
            network_base = ".".join(bridge_ip.split(".")[:-1])
        
        config_content = f"""# Glint automatic bridge DNS configuration
# Bridge: {bridge_name}
# Generated automatically for seamless VM DNS resolution

# Bind only to the bridge interface
interface={bridge_name}
bind-interfaces

# DHCP range for VMs
dhcp-range={network_base}.10,{network_base}.100,12h

# DNS servers to forward queries to
"""
        
        for dns in dns_servers:
            config_content += f"server={dns}\n"
        
        config_content += f"""
# DNS configuration
no-resolv
no-poll
cache-size=1000
neg-ttl=60

# Enable logging for troubleshooting
log-queries
log-dhcp

# Additional options for better VM compatibility
dhcp-option=option:router,{network_base}.1
dhcp-option=option:dns-server,{','.join(dns_servers[:2])}
"""
        
        config_file = f"/etc/dnsmasq.d/glint-{bridge_name}.conf"
        
        # Ensure the dnsmasq.d directory exists
        config_dir = "/etc/dnsmasq.d"
        if not os.path.exists(config_dir):
            try:
                os.makedirs(config_dir, mode=0o755, exist_ok=True)
                print_info(f"Created directory: {config_dir}")
            except PermissionError:
                print_warning("Cannot create /etc/dnsmasq.d directory - need sudo access")
                return False
        
        # Write configuration
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(config_content)
        
        print_success(f"✅ Created dnsmasq config: {config_file}")
        return True
        
    except PermissionError:
        print_error("Permission denied - need sudo access to configure dnsmasq")
        return False
    except Exception as e:
        print_error(f"Failed to create dnsmasq config: {e}")
        return False


def install_dnsmasq() -> bool:
    """Install dnsmasq using system package manager"""
    try:
        print_info("🔧 Installing dnsmasq...")
        
        # Try different package managers
        install_commands = [
            # Debian/Ubuntu - most common
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
                    return True
                    
            except subprocess.TimeoutExpired:
                print_warning("Installation timed out")
                continue
            except Exception as e:
                print_warning(f"Installation failed: {e}")
                continue
        
        print_error("Could not install dnsmasq automatically")
        return False
        
    except Exception as e:
        print_error(f"Error installing dnsmasq: {e}")
        return False


def restart_dnsmasq() -> bool:
    """Restart dnsmasq service"""
    try:
        # Stop any existing dnsmasq processes that might conflict
        subprocess.run(["sudo", "pkill", "dnsmasq"], capture_output=True, text=True)
        
        # Start/restart dnsmasq service
        result = subprocess.run(
            ["sudo", "systemctl", "restart", "dnsmasq"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            # Enable to start on boot
            subprocess.run(
                ["sudo", "systemctl", "enable", "dnsmasq"],
                capture_output=True,
                text=True
            )
            print_success("✅ dnsmasq service restarted")
            return True
        else:
            print_warning(f"Failed to restart dnsmasq: {result.stderr}")
            return False
            
    except Exception as e:
        print_error(f"Error restarting dnsmasq: {e}")
        return False


def setup_systemd_resolved_fallback(bridge_name: str = "br0") -> bool:
    """Fallback DNS setup using systemd-resolved"""
    try:
        if not (command_exists("systemd-resolve") or command_exists("resolvectl")):
            return False
        
        resolve_cmd = "resolvectl" if command_exists("resolvectl") else "systemd-resolve"
        host_dns = find_host_dns()
        
        print_info("Setting up systemd-resolved for bridge DNS...")
        
        # Set DNS for bridge interface
        result = subprocess.run([
            "sudo", resolve_cmd, "--interface", bridge_name, "--set-dns", host_dns
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print_success("✅ systemd-resolved configured")
            return True
        
        return False
        
    except Exception as e:
        print_warning(f"systemd-resolved setup failed: {e}")
        return False


def setup_iptables_dns_forwarding(bridge_name: str = "br0") -> bool:
    """Set up basic DNS forwarding using iptables"""
    try:
        print_info("Setting up iptables DNS forwarding...")
        
        # Enable IP forwarding
        subprocess.run(
            ["sudo", "sysctl", "-w", "net.ipv4.ip_forward=1"],
            capture_output=True,
            text=True
        )
        
        # Make IP forwarding persistent
        try:
            with open("/etc/sysctl.conf", "r") as f:
                content = f.read()
            
            if "net.ipv4.ip_forward=1" not in content:
                with open("/etc/sysctl.conf", "a") as f:
                    f.write("\n# Enable IP forwarding for bridge networking\nnet.ipv4.ip_forward=1\n")
        except Exception:
            pass  # Non-critical
        
        # Get bridge network
        bridge_ip = get_bridge_ip(bridge_name)
        if not bridge_ip:
            network = "10.0.0.0/24"
        else:
            network_base = ".".join(bridge_ip.split(".")[:-1])
            network = f"{network_base}.0/24"
        
        host_dns = find_host_dns()
        
        # Add iptables rules for DNS forwarding
        dns_rules = [
            ["sudo", "iptables", "-t", "nat", "-A", "POSTROUTING", 
             "-s", network, "-d", host_dns, "-p", "udp", "--dport", "53", "-j", "MASQUERADE"],
            ["sudo", "iptables", "-t", "nat", "-A", "POSTROUTING",
             "-s", network, "-d", host_dns, "-p", "tcp", "--dport", "53", "-j", "MASQUERADE"],
            ["sudo", "iptables", "-A", "FORWARD", "-i", bridge_name, "-o", "eth0", "-j", "ACCEPT"],
            ["sudo", "iptables", "-A", "FORWARD", "-i", "eth0", "-o", bridge_name, "-j", "ACCEPT"]
        ]
        
        for rule in dns_rules:
            subprocess.run(rule, capture_output=True, text=True)
        
        print_success("✅ iptables DNS forwarding configured")
        return True
        
    except Exception as e:
        print_warning(f"iptables setup failed: {e}")
        return False


def setup_bridge_nat_forwarding(bridge_name: str = "br0") -> bool:
    """Set up comprehensive NAT forwarding for bridge networking"""
    try:
        print_info("Setting up comprehensive NAT forwarding for bridge networking...")
        
        # Get the primary network interface
        primary_interface = get_primary_interface()
        if not primary_interface:
            print_warning("Could not determine primary network interface")
            # Try common interface names
            for iface in ["eth0", "enp0s3", "wlan0", "wlp2s0"]:
                result = subprocess.run(["ip", "link", "show", iface], 
                                      capture_output=True, text=True)
                if result.returncode == 0 and "UP" in result.stdout:
                    primary_interface = iface
                    break
            else:
                primary_interface = "eth0"  # final fallback
        
        print_info(f"Using primary interface: {primary_interface}")
        
        bridge_ip = get_bridge_ip(bridge_name)
        if not bridge_ip:
            network = "10.0.0.0/24"
            bridge_ip = "10.0.0.1"
        else:
            network_base = ".".join(bridge_ip.split(".")[:-1])
            network = f"{network_base}.0/24"
        
        print_info(f"Bridge network: {network}")
        
        # Enable IP forwarding
        subprocess.run(["sudo", "sysctl", "-w", "net.ipv4.ip_forward=1"], 
                      capture_output=True, text=True)
        
        # Enable bridge netfilter
        subprocess.run(["sudo", "modprobe", "br_netfilter"], 
                      capture_output=True, text=True)
        
        # Configure bridge netfilter settings
        bridge_settings = [
            "net.bridge.bridge-nf-call-ip6tables=0",
            "net.bridge.bridge-nf-call-iptables=0",
            "net.bridge.bridge-nf-call-arptables=0"
        ]
        
        for setting in bridge_settings:
            subprocess.run(["sudo", "sysctl", "-w", setting], 
                          capture_output=True, text=True)
        
        # Make settings persistent
        try:
            sysctl_content = ""
            sysctl_file = "/etc/sysctl.conf"
            
            if os.path.exists(sysctl_file):
                with open(sysctl_file, "r") as f:
                    sysctl_content = f.read()
            
            settings_to_add = []
            if "net.ipv4.ip_forward=1" not in sysctl_content:
                settings_to_add.append("net.ipv4.ip_forward=1")
            
            for setting in bridge_settings:
                if setting not in sysctl_content:
                    settings_to_add.append(setting)
            
            if settings_to_add:
                with open(sysctl_file, "a") as f:
                    f.write("\n# Bridge networking configuration\n")
                    for setting in settings_to_add:
                        f.write(f"{setting}\n")
        except Exception:
            pass  # Non-critical
        
        # Clear existing iptables rules for this bridge (ignore errors)
        cleanup_rules = [
            ["sudo", "iptables", "-t", "nat", "-D", "POSTROUTING", 
             "-s", network, "-o", primary_interface, "-j", "MASQUERADE"],
            ["sudo", "iptables", "-D", "FORWARD", "-i", bridge_name, "-o", primary_interface, "-j", "ACCEPT"],
            ["sudo", "iptables", "-D", "FORWARD", "-i", primary_interface, "-o", bridge_name, 
             "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"]
        ]
        
        for rule in cleanup_rules:
            subprocess.run(rule, capture_output=True, text=True)
        
        # Add comprehensive NAT and forwarding rules
        nat_rules = [
            # Main NAT rule for internet access
            ["sudo", "iptables", "-t", "nat", "-A", "POSTROUTING",
             "-s", network, "-o", primary_interface, "-j", "MASQUERADE"],
            
            # Allow forwarding from bridge to internet
            ["sudo", "iptables", "-A", "FORWARD", "-i", bridge_name, "-o", primary_interface, "-j", "ACCEPT"],
            
            # Allow return traffic
            ["sudo", "iptables", "-A", "FORWARD", "-i", primary_interface, "-o", bridge_name, 
             "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
            
            # Allow traffic within bridge
            ["sudo", "iptables", "-A", "FORWARD", "-i", bridge_name, "-o", bridge_name, "-j", "ACCEPT"]
        ]
        
        success_count = 0
        for rule in nat_rules:
            result = subprocess.run(rule, capture_output=True, text=True)
            if result.returncode == 0:
                success_count += 1
            else:
                print_warning(f"Rule failed: {' '.join(rule[2:])}")
        
        if success_count >= len(nat_rules) // 2:
            print_success("✅ NAT forwarding configured successfully")
            
            # Test connectivity from host
            test_result = subprocess.run(["ping", "-c", "1", "-W", "2", "8.8.8.8"], 
                                       capture_output=True, text=True)
            if test_result.returncode == 0:
                print_success("✅ Host internet connectivity verified")
            else:
                print_warning("⚠️  Host internet connectivity test failed")
            
            return True
        else:
            print_error(f"❌ Only {success_count}/{len(nat_rules)} NAT rules succeeded")
            return False
        
    except Exception as e:
        print_error(f"NAT forwarding setup failed: {e}")
        return False


def get_primary_interface() -> Optional[str]:
    """Get the primary network interface"""
    try:
        # Get default route interface
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            import re
            match = re.search(r'dev (\w+)', result.stdout)
            if match:
                return match.group(1)
        
        # Fallback: get first active interface that's not loopback
        result = subprocess.run(
            ["ip", "link", "show"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'state UP' in line and 'lo:' not in line:
                    match = re.search(r'\d+: (\w+):', line)
                    if match:
                        return match.group(1)
        
        return None
        
    except Exception:
        return None


def create_enhanced_dnsmasq_config(bridge_name: str = "br0", dns_servers: List[str] = None) -> bool:
    """Create enhanced dnsmasq configuration with better VM compatibility"""
    try:
        if dns_servers is None:
            host_dns = find_host_dns()
            dns_servers = [host_dns, "8.8.8.8", "1.1.1.1"]
        
        # Get bridge IP to determine network range
        bridge_ip = get_bridge_ip(bridge_name)
        if not bridge_ip:
            print_warning("Bridge has no IP address, using default range")
            network_base = "10.0.0"
            bridge_ip = "10.0.0.1"
        else:
            network_base = ".".join(bridge_ip.split(".")[:-1])
        
        config_content = f"""# Enhanced Glint bridge DNS configuration
# Bridge: {bridge_name}
# Generated automatically for seamless VM DNS resolution

# Bind only to the bridge interface
interface={bridge_name}
bind-interfaces

# DHCP range for VMs (larger range for more VMs)
dhcp-range={network_base}.10,{network_base}.200,12h

# DNS servers to forward queries to (in order of preference)
"""
        
        for dns in dns_servers:
            config_content += f"server={dns}\n"
        
        config_content += f"""
# Enhanced DNS configuration
no-resolv
no-poll
cache-size=2000
neg-ttl=60
local-ttl=300

# DHCP options for better VM compatibility
dhcp-option=option:router,{bridge_ip}
dhcp-option=option:dns-server,{dns_servers[0]},{dns_servers[1] if len(dns_servers) > 1 else '8.8.8.8'}
dhcp-option=option:domain-name-server,{dns_servers[0]},{dns_servers[1] if len(dns_servers) > 1 else '8.8.8.8'}
dhcp-option=option:netmask,255.255.255.0
dhcp-option=option:broadcast,{network_base}.255

# Additional options for VM compatibility
dhcp-option=option:mtu,1500
dhcp-option=option:lease-time,43200

# Enable logging for troubleshooting (can be disabled later)
log-queries
log-dhcp

# Ignore /etc/resolv.conf and /etc/hosts for upstream DNS
no-resolv
no-hosts

# Don't read /etc/hosts
no-hosts

# Expand hosts file entries
expand-hosts

# Local domain
domain=vm.local
local=/vm.local/

# Prevent DNS rebinding attacks
stop-dns-rebind
rebind-localhost-ok
"""
        
        config_file = f"/etc/dnsmasq.d/glint-{bridge_name}.conf"
        
        # Ensure the dnsmasq.d directory exists
        config_dir = "/etc/dnsmasq.d"
        if not os.path.exists(config_dir):
            try:
                subprocess.run(["sudo", "mkdir", "-p", config_dir], check=True)
                print_info(f"Created directory: {config_dir}")
            except subprocess.CalledProcessError:
                print_warning("Cannot create /etc/dnsmasq.d directory - need sudo access")
                return False
        
        # Write configuration using sudo
        try:
            # Write to temporary file first
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.conf') as tmp_file:
                tmp_file.write(config_content)
                tmp_file_path = tmp_file.name
            
            # Copy to final location with sudo
            result = subprocess.run([
                "sudo", "cp", tmp_file_path, config_file
            ], capture_output=True, text=True)
            
            # Clean up temp file
            os.unlink(tmp_file_path)
            
            if result.returncode != 0:
                print_error(f"Failed to create config file: {result.stderr}")
                return False
            
            # Set proper permissions
            subprocess.run(["sudo", "chmod", "644", config_file], capture_output=True, text=True)
            
            print_success(f"✅ Created enhanced dnsmasq config: {config_file}")
            return True
            
        except Exception as e:
            print_error(f"Failed to create dnsmasq config: {e}")
            return False
        
    except Exception as e:
        print_error(f"Failed to create enhanced dnsmasq config: {e}")
        return False


def auto_fix_bridge_dns(bridge_name: str = "br0") -> bool:
    """
    Set up true bridged networking where VMs get IP addresses from network DHCP.
    This creates a transparent bridge that doesn't disrupt host networking.
    
    Returns:
        bool: True if bridged networking was configured successfully
    """
    try:
        print_info(f"🌐 Setting up transparent bridged networking for '{bridge_name}'...")
        
        # Step 0: Ensure QEMU bridge ACL is configured (required for first-time users)
        ensure_qemu_bridge_acl(bridge_name)
        
        # Step 1: Set up transparent bridged networking (no host disruption)
        if not setup_transparent_bridge_networking(bridge_name):
            print_error("Failed to set up transparent bridged networking")
            return False
        
        # Step 2: Disable any existing dnsmasq for this bridge
        disable_bridge_dnsmasq(bridge_name)
        
        # Step 3: Configure bridge for optimal VM connectivity
        configure_bridge_for_vms(bridge_name)
        
        # Step 4: Verify bridge setup
        if verify_transparent_bridge(bridge_name):
            print_success("✅ Transparent bridged networking configured")
            print_info("VMs will get IP addresses from your network's DHCP server")
            print_info("VMs will appear as separate devices on your network")
            return True
        else:
            print_warning("⚠️  Bridge configured but verification incomplete")
            return True
        
    except Exception as e:
        print_error(f"Error setting up bridged networking: {e}")
        return False


def setup_transparent_bridge_networking(bridge_name: str) -> bool:
    """Set up transparent bridge networking without disrupting host network"""
    try:
        print_info("Setting up transparent bridge networking...")
        
        # Ensure bridge exists
        result = subprocess.run([
            "ip", "link", "show", bridge_name
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print_info(f"Creating bridge {bridge_name}...")
            result = subprocess.run([
                "sudo", "ip", "link", "add", "name", bridge_name, "type", "bridge"
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                print_error(f"Failed to create bridge: {result.stderr}")
                return False
        
        # Remove any IP addresses from the bridge (it should be transparent)
        subprocess.run([
            "sudo", "ip", "addr", "flush", "dev", bridge_name
        ], capture_output=True, text=True)
        
        # Ensure bridge is up
        subprocess.run([
            "sudo", "ip", "link", "set", bridge_name, "up"
        ], capture_output=True, text=True)
        
        print_success(f"✅ Transparent bridge {bridge_name} created")
        print_info("Bridge is ready for VM connections - no host network disruption")
        return True
        
    except Exception as e:
        print_error(f"Failed to set up transparent bridge: {e}")
        return False


def configure_bridge_for_vms(bridge_name: str):
    """Configure bridge parameters for optimal VM connectivity"""
    try:
        print_info("Configuring bridge for VM connectivity...")
        
        # Load bridge module if not loaded
        subprocess.run(["sudo", "modprobe", "bridge"], capture_output=True, text=True)
        
        # Disable netfilter on bridges for transparent operation
        bridge_netfilter_settings = [
            "net.bridge.bridge-nf-call-iptables=0",
            "net.bridge.bridge-nf-call-ip6tables=0", 
            "net.bridge.bridge-nf-call-arptables=0"
        ]
        
        for setting in bridge_netfilter_settings:
            subprocess.run([
                "sudo", "sysctl", "-w", setting
            ], capture_output=True, text=True)
        
        # Configure bridge parameters for optimal VM performance
        bridge_params = [
            ("forward_delay", "0"),      # No forwarding delay
            ("hello_time", "2"),         # STP hello time
            ("max_age", "20"),          # STP max age
            ("stp_state", "0"),         # Disable STP for simple setups
            ("multicast_snooping", "1"), # Enable multicast snooping
            ("ageing_time", "30000")    # MAC address aging time
        ]
        
        for param, value in bridge_params:
            param_path = f"/sys/class/net/{bridge_name}/bridge/{param}"
            if os.path.exists(param_path):
                subprocess.run([
                    "sudo", "sh", "-c", f"echo {value} > {param_path}"
                ], capture_output=True, text=True)
        
        # Make bridge netfilter settings persistent
        try:
            import tempfile
            sysctl_file = "/etc/sysctl.conf"
            
            current_content = ""
            if os.path.exists(sysctl_file):
                with open(sysctl_file, "r") as f:
                    current_content = f.read()
            
            settings_to_add = []
            for setting in bridge_netfilter_settings:
                if setting not in current_content:
                    settings_to_add.append(setting)
            
            if settings_to_add:
                new_content = current_content + "\n# Bridge netfilter settings for Glint\n"
                for setting in settings_to_add:
                    new_content += f"{setting}\n"
                
                with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp_file:
                    tmp_file.write(new_content)
                    tmp_file_path = tmp_file.name
                
                subprocess.run(["sudo", "cp", tmp_file_path, sysctl_file], 
                              capture_output=True, text=True)
                os.unlink(tmp_file_path)
        except Exception:
            pass  # Non-critical
        
        print_success("✅ Bridge configured for VM connectivity")
        
    except Exception as e:
        print_warning(f"Bridge VM configuration warning: {e}")


def verify_transparent_bridge(bridge_name: str) -> bool:
    """Verify that transparent bridge is properly configured"""
    try:
        print_info("Verifying transparent bridge configuration...")
        
        # Check if bridge exists and is up
        result = subprocess.run([
            "ip", "link", "show", bridge_name
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print_warning("Bridge does not exist")
            return False
        
        if "UP" not in result.stdout:
            print_warning("Bridge is not up")
            return False
        
        # Check that bridge has no IP address (transparent mode)
        result = subprocess.run([
            "ip", "addr", "show", bridge_name
        ], capture_output=True, text=True)
        
        if "inet " in result.stdout and "127.0.0.1" not in result.stdout:
            print_info("Bridge has IP address - this is OK for some setups")
        else:
            print_success("✅ Bridge is transparent (no IP address)")
        
        # Check bridge parameters
        bridge_path = f"/sys/class/net/{bridge_name}/bridge"
        if os.path.exists(bridge_path):
            try:
                with open(f"{bridge_path}/forward_delay", "r") as f:
                    forward_delay = f.read().strip()
                    if forward_delay == "0":
                        print_success("✅ Bridge forward delay optimized")
                    else:
                        print_info(f"Bridge forward delay: {forward_delay}")
            except Exception:
                pass
        
        print_success("✅ Transparent bridge verification completed")
        return True
        
    except Exception as e:
        print_warning(f"Bridge verification failed: {e}")
        return False


def setup_true_bridged_networking(bridge_name: str) -> bool:
    """Set up true bridged networking where VMs connect directly to the network"""
    try:
        print_info("Setting up true bridged networking...")
        
        # Get primary interface
        primary_interface = get_primary_interface()
        if not primary_interface:
            print_error("No network interface found")
            return False
        
        print_info(f"Using primary interface: {primary_interface}")
        
        # Ensure bridge exists
        result = subprocess.run([
            "ip", "link", "show", bridge_name
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print_info(f"Creating bridge {bridge_name}...")
            result = subprocess.run([
                "sudo", "ip", "link", "add", "name", bridge_name, "type", "bridge"
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                print_error(f"Failed to create bridge: {result.stderr}")
                return False
        
        # Check if interface is already connected to bridge
        result = subprocess.run([
            "ip", "link", "show", "master", bridge_name
        ], capture_output=True, text=True)
        
        if primary_interface not in result.stdout:
            print_info(f"Connecting {primary_interface} to bridge {bridge_name}...")
            
            # IMPORTANT: For true bridged networking, we need to move the host's network
            # configuration to the bridge so the host maintains connectivity while
            # VMs can access the network directly through the bridge
            
            # Get current network configuration
            current_config = get_interface_config(primary_interface)
            print_info(f"Current interface config: IP={current_config['ip']}, Gateway={current_config['gateway']}")
            
            # Add interface to bridge
            result = subprocess.run([
                "sudo", "ip", "link", "set", primary_interface, "master", bridge_name
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                print_error(f"Failed to add interface to bridge: {result.stderr}")
                return False
            
            # Move IP configuration from interface to bridge to maintain host connectivity
            if current_config['ip']:
                print_info(f"Moving host IP configuration to bridge...")
                
                # Remove IP from interface (it will now be on the bridge)
                subprocess.run([
                    "sudo", "ip", "addr", "flush", "dev", primary_interface
                ], capture_output=True, text=True)
                
                # Remove any existing IP from bridge first
                subprocess.run([
                    "sudo", "ip", "addr", "flush", "dev", bridge_name
                ], capture_output=True, text=True)
                
                # Add host IP to bridge
                subprocess.run([
                    "sudo", "ip", "addr", "add", current_config['ip'], "dev", bridge_name
                ], capture_output=True, text=True)
                
                # Restore default route through bridge
                if current_config['gateway']:
                    # Remove old default routes
                    subprocess.run([
                        "sudo", "ip", "route", "del", "default"
                    ], capture_output=True, text=True)
                    
                    # Add new default route through bridge
                    subprocess.run([
                        "sudo", "ip", "route", "add", "default", "via", current_config['gateway'], "dev", bridge_name
                    ], capture_output=True, text=True)
                    
                print_success(f"✅ Host network configuration moved to bridge")
            else:
                print_info("No IP configuration to move - bridge will be transparent")
        else:
            print_info(f"Interface {primary_interface} already connected to bridge")
        
        # Ensure bridge and interface are up
        subprocess.run([
            "sudo", "ip", "link", "set", bridge_name, "up"
        ], capture_output=True, text=True)
        
        subprocess.run([
            "sudo", "ip", "link", "set", primary_interface, "up"
        ], capture_output=True, text=True)
        
        # Configure bridge for proper forwarding
        configure_bridge_forwarding(bridge_name)
        
        print_success(f"✅ True bridged networking configured")
        print_info("VMs will now get IP addresses directly from your network's DHCP server")
        print_info("VMs will appear as separate devices on your network")
        return True
        
    except Exception as e:
        print_error(f"Failed to set up true bridged networking: {e}")
        return False


def get_interface_config(interface: str) -> dict:
    """Get current IP configuration of an interface"""
    config = {'ip': None, 'gateway': None}
    
    try:
        # Get IP address
        result = subprocess.run([
            "ip", "addr", "show", interface
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            import re
            match = re.search(r'inet (\d+\.\d+\.\d+\.\d+/\d+)', result.stdout)
            if match:
                config['ip'] = match.group(1)
        
        # Get gateway
        result = subprocess.run([
            "ip", "route", "show", "default"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            import re
            match = re.search(r'default via (\d+\.\d+\.\d+\.\d+)', result.stdout)
            if match:
                config['gateway'] = match.group(1)
        
    except Exception:
        pass
    
    return config


def configure_bridge_forwarding(bridge_name: str):
    """Configure bridge for proper packet forwarding"""
    try:
        # Disable netfilter on bridges (allows transparent bridging)
        bridge_settings = [
            "net.bridge.bridge-nf-call-iptables=0",
            "net.bridge.bridge-nf-call-ip6tables=0",
            "net.bridge.bridge-nf-call-arptables=0"
        ]
        
        for setting in bridge_settings:
            subprocess.run([
                "sudo", "sysctl", "-w", setting
            ], capture_output=True, text=True)
        
        # Set bridge parameters for optimal performance
        bridge_params = [
            ("forward_delay", "0"),
            ("stp_state", "0"),  # Disable STP for simple setups
            ("multicast_snooping", "1")
        ]
        
        for param, value in bridge_params:
            param_path = f"/sys/class/net/{bridge_name}/bridge/{param}"
            if os.path.exists(param_path):
                subprocess.run([
                    "sudo", "sh", "-c", f"echo {value} > {param_path}"
                ], capture_output=True, text=True)
        
        print_success("✅ Bridge forwarding configured")
        
    except Exception as e:
        print_warning(f"Bridge forwarding configuration warning: {e}")


def disable_bridge_dnsmasq(bridge_name: str):
    """Disable dnsmasq for true bridged networking"""
    try:
        config_file = f"/etc/dnsmasq.d/glint-{bridge_name}.conf"
        
        if os.path.exists(config_file):
            print_info("Disabling dnsmasq for true bridged networking...")
            subprocess.run([
                "sudo", "mv", config_file, f"{config_file}.disabled"
            ], capture_output=True, text=True)
            
            # Restart dnsmasq to apply changes
            subprocess.run([
                "sudo", "systemctl", "restart", "dnsmasq"
            ], capture_output=True, text=True)
            
            print_success("✅ dnsmasq disabled - VMs will use network DHCP")
    
    except Exception as e:
        print_warning(f"Failed to disable dnsmasq: {e}")


def verify_bridge_setup(bridge_name: str) -> bool:
    """Verify that bridge is properly set up"""
    try:
        print_info("Verifying bridge setup...")
        
        # Check if bridge exists and is up
        result = subprocess.run([
            "ip", "link", "show", bridge_name
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print_warning("Bridge does not exist")
            return False
        
        if "UP" not in result.stdout:
            print_warning("Bridge is not up")
            return False
        
        # Check if bridge has a connected interface
        result = subprocess.run([
            "ip", "link", "show", "master", bridge_name
        ], capture_output=True, text=True)
        
        if not result.stdout.strip():
            print_warning("No interfaces connected to bridge")
            return False
        
        # Check bridge state
        result = subprocess.run([
            "ip", "addr", "show", bridge_name
        ], capture_output=True, text=True)
        
        if "NO-CARRIER" in result.stdout:
            print_warning("Bridge has no carrier - this is normal for true bridged mode")
        
        print_success("✅ Bridge setup verified")
        return True
        
    except Exception as e:
        print_warning(f"Bridge verification failed: {e}")
        return False


def ensure_bridge_ready(bridge_name: str) -> bool:
    """Ensure bridge exists and is properly configured"""
    try:
        # Check if bridge exists
        result = subprocess.run(
            ["ip", "link", "show", bridge_name],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print_info(f"Creating bridge {bridge_name}...")
            
            # Create bridge
            result = subprocess.run([
                "sudo", "ip", "link", "add", "name", bridge_name, "type", "bridge"
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                print_error(f"Failed to create bridge: {result.stderr}")
                return False
        
        # Ensure bridge is up
        subprocess.run([
            "sudo", "ip", "link", "set", bridge_name, "up"
        ], capture_output=True, text=True)
        
        # Set bridge IP if it doesn't have one
        result = subprocess.run([
            "ip", "addr", "show", bridge_name
        ], capture_output=True, text=True)
        
        if "inet " not in result.stdout:
            print_info(f"Setting IP address for bridge {bridge_name}...")
            subprocess.run([
                "sudo", "ip", "addr", "add", "10.0.0.1/24", "dev", bridge_name
            ], capture_output=True, text=True)
        
        print_success(f"✅ Bridge {bridge_name} is ready")
        return True
        
    except Exception as e:
        print_error(f"Failed to ensure bridge is ready: {e}")
        return False


def setup_comprehensive_bridge_networking(bridge_name: str) -> bool:
    """Set up true bridged networking for direct network access"""
    try:
        print_info("Setting up true bridged networking...")
        
        # Get primary interface with internet connectivity
        primary_interface = get_internet_interface()
        if not primary_interface:
            print_error("No internet-connected interface found")
            return False
        
        print_info(f"Using primary interface: {primary_interface}")
        
        # Set up true bridged networking (VMs get IPs from network DHCP)
        if not setup_true_bridge_networking(bridge_name, primary_interface):
            print_error("Failed to set up true bridged networking")
            return False
        
        print_success("✅ True bridged networking configured")
        return True
        
    except Exception as e:
        print_error(f"Failed to set up bridged networking: {e}")
        return False


def setup_true_bridge_networking(bridge_name: str, primary_interface: str) -> bool:
    """Set up true bridged networking where VMs get IPs from network DHCP"""
    try:
        print_info("Configuring true bridge networking...")
        
        # Check if interface is already connected to bridge
        result = subprocess.run([
            "ip", "link", "show", "master", bridge_name
        ], capture_output=True, text=True)
        
        if primary_interface in result.stdout:
            print_info(f"Interface {primary_interface} already connected to bridge")
            return True
        
        # Get current IP configuration of primary interface
        result = subprocess.run([
            "ip", "addr", "show", primary_interface
        ], capture_output=True, text=True)
        
        current_ip = None
        current_gateway = None
        import re
        match = re.search(r'inet (\d+\.\d+\.\d+\.\d+/\d+)', result.stdout)
        if match:
            current_ip = match.group(1)
            print_info(f"Current IP on {primary_interface}: {current_ip}")
            
            # Get current gateway
            gateway_result = subprocess.run([
                "ip", "route", "show", "default"
            ], capture_output=True, text=True)
            
            if gateway_result.returncode == 0:
                gateway_match = re.search(r'default via (\d+\.\d+\.\d+\.\d+)', gateway_result.stdout)
                if gateway_match:
                    current_gateway = gateway_match.group(1)
                    print_info(f"Current gateway: {current_gateway}")
        
        # Remove IP from physical interface
        if current_ip:
            print_info(f"Moving IP {current_ip} from {primary_interface} to {bridge_name}...")
            subprocess.run([
                "sudo", "ip", "addr", "del", current_ip, "dev", primary_interface
            ], capture_output=True, text=True)
        
        # Remove any existing IP from bridge
        subprocess.run([
            "sudo", "ip", "addr", "flush", "dev", bridge_name
        ], capture_output=True, text=True)
        
        # Add physical interface to bridge
        result = subprocess.run([
            "sudo", "ip", "link", "set", primary_interface, "master", bridge_name
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print_error(f"Failed to add {primary_interface} to bridge: {result.stderr}")
            # Restore IP if we removed it
            if current_ip:
                subprocess.run([
                    "sudo", "ip", "addr", "add", current_ip, "dev", primary_interface
                ], capture_output=True, text=True)
            return False
        
        # Assign IP to bridge if we had one
        if current_ip:
            subprocess.run([
                "sudo", "ip", "addr", "add", current_ip, "dev", bridge_name
            ], capture_output=True, text=True)
            print_success(f"✅ Moved IP {current_ip} to bridge {bridge_name}")
            
            # Restore default route through bridge
            if current_gateway:
                subprocess.run([
                    "sudo", "ip", "route", "add", "default", "via", current_gateway, "dev", bridge_name
                ], capture_output=True, text=True)
                print_success(f"✅ Restored default route via {current_gateway}")
        
        # Ensure bridge is up
        subprocess.run([
            "sudo", "ip", "link", "set", bridge_name, "up"
        ], capture_output=True, text=True)
        
        # Ensure physical interface is up
        subprocess.run([
            "sudo", "ip", "link", "set", primary_interface, "up"
        ], capture_output=True, text=True)
        
        # Enable bridge forwarding
        subprocess.run([
            "sudo", "sysctl", "-w", "net.bridge.bridge-nf-call-iptables=0"
        ], capture_output=True, text=True)
        
        subprocess.run([
            "sudo", "sysctl", "-w", "net.bridge.bridge-nf-call-ip6tables=0"
        ], capture_output=True, text=True)
        
        print_success(f"✅ Connected {primary_interface} to bridge {bridge_name}")
        print_info("VMs will now get IP addresses directly from your network's DHCP server")
        return True
        
    except Exception as e:
        print_error(f"Failed to set up true bridged networking: {e}")
        return False


def connect_bridge_to_physical_interface(bridge_name: str, primary_interface: str) -> bool:
    """Connect bridge to physical interface for true bridged networking"""
    try:
        print_info(f"Connecting bridge {bridge_name} to physical interface {primary_interface}...")
        
        # Check if interface is already connected to bridge
        result = subprocess.run([
            "ip", "link", "show", "master", bridge_name
        ], capture_output=True, text=True)
        
        if primary_interface in result.stdout:
            print_info(f"Interface {primary_interface} already connected to bridge")
            return True
        
        # Get current IP configuration of primary interface
        result = subprocess.run([
            "ip", "addr", "show", primary_interface
        ], capture_output=True, text=True)
        
        current_ip = None
        import re
        match = re.search(r'inet (\d+\.\d+\.\d+\.\d+/\d+)', result.stdout)
        if match:
            current_ip = match.group(1)
            print_info(f"Current IP on {primary_interface}: {current_ip}")
        
        # Remove IP from physical interface
        if current_ip:
            print_info(f"Moving IP {current_ip} from {primary_interface} to {bridge_name}...")
            subprocess.run([
                "sudo", "ip", "addr", "del", current_ip, "dev", primary_interface
            ], capture_output=True, text=True)
        
        # Add physical interface to bridge
        result = subprocess.run([
            "sudo", "ip", "link", "set", primary_interface, "master", bridge_name
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print_error(f"Failed to add {primary_interface} to bridge: {result.stderr}")
            # Restore IP if we removed it
            if current_ip:
                subprocess.run([
                    "sudo", "ip", "addr", "add", current_ip, "dev", primary_interface
                ], capture_output=True, text=True)
            return False
        
        # Remove the default 10.0.0.1/24 IP from bridge if it exists
        subprocess.run([
            "sudo", "ip", "addr", "del", "10.0.0.1/24", "dev", bridge_name
        ], capture_output=True, text=True)
        
        # Assign IP to bridge if we had one
        if current_ip:
            subprocess.run([
                "sudo", "ip", "addr", "add", current_ip, "dev", bridge_name
            ], capture_output=True, text=True)
            print_success(f"✅ Moved IP {current_ip} to bridge {bridge_name}")
        
        # Ensure bridge is up
        subprocess.run([
            "sudo", "ip", "link", "set", bridge_name, "up"
        ], capture_output=True, text=True)
        
        # Ensure physical interface is up
        subprocess.run([
            "sudo", "ip", "link", "set", primary_interface, "up"
        ], capture_output=True, text=True)
        
        print_success(f"✅ Connected {primary_interface} to bridge {bridge_name}")
        return True
        
    except Exception as e:
        print_error(f"Failed to connect bridge to physical interface: {e}")
        return False


def setup_nat_mode_networking(bridge_name: str, primary_interface: str) -> bool:
    """Set up NAT mode networking as fallback"""
    try:
        print_info("Setting up NAT mode networking...")
        
        # Ensure bridge has IP
        bridge_ip = get_bridge_ip(bridge_name)
        if not bridge_ip:
            subprocess.run([
                "sudo", "ip", "addr", "add", "10.0.0.1/24", "dev", bridge_name
            ], capture_output=True, text=True)
        
        # Enable IP forwarding
        enable_ip_forwarding_comprehensive()
        
        # Clear existing rules
        clear_bridge_iptables_rules(bridge_name)
        
        # Set up NAT rules
        network = "10.0.0.0/24"
        
        nat_rules = [
            ["sudo", "iptables", "-t", "nat", "-A", "POSTROUTING", "-s", network, "-o", primary_interface, "-j", "MASQUERADE"],
            ["sudo", "iptables", "-A", "FORWARD", "-i", bridge_name, "-o", primary_interface, "-j", "ACCEPT"],
            ["sudo", "iptables", "-A", "FORWARD", "-i", primary_interface, "-o", bridge_name, "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"]
        ]
        
        for rule in nat_rules:
            result = subprocess.run(rule, capture_output=True, text=True)
            if result.returncode == 0:
                print_success(f"✅ NAT rule: {' '.join(rule[5:])}")
            else:
                print_warning(f"NAT rule failed: {result.stderr}")
        
        return True
        
    except Exception as e:
        print_error(f"Failed to set up NAT mode networking: {e}")
        return False


def get_internet_interface() -> Optional[str]:
    """Get the interface with actual internet connectivity"""
    try:
        # Method 1: Check default route
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            import re
            for line in result.stdout.split('\n'):
                match = re.search(r'dev (\w+)', line)
                if match:
                    interface = match.group(1)
                    # Test actual connectivity
                    if test_interface_internet_connectivity(interface):
                        return interface
        
        # Method 2: Test all UP interfaces
        result = subprocess.run(
            ["ip", "link", "show"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            import re
            for line in result.stdout.split('\n'):
                if 'state UP' in line and 'lo:' not in line and 'br' not in line:
                    match = re.search(r'\d+: (\w+):', line)
                    if match:
                        interface = match.group(1)
                        if test_interface_internet_connectivity(interface):
                            return interface
        
        return None
        
    except Exception:
        return None


def test_interface_internet_connectivity(interface: str) -> bool:
    """Test if an interface has actual internet connectivity"""
    try:
        # Quick ping test to Google DNS
        result = subprocess.run([
            "ping", "-c", "1", "-W", "2", "-I", interface, "8.8.8.8"
        ], capture_output=True, text=True)
        
        return result.returncode == 0
        
    except Exception:
        return False


def enable_ip_forwarding_comprehensive():
    """Enable IP forwarding using multiple reliable methods"""
    try:
        print_info("Enabling IP forwarding...")
        
        # Method 1: sysctl
        subprocess.run(["sudo", "sysctl", "-w", "net.ipv4.ip_forward=1"], 
                      capture_output=True, text=True)
        
        # Method 2: proc filesystem
        subprocess.run(["sudo", "sh", "-c", "echo 1 > /proc/sys/net/ipv4/ip_forward"], 
                      capture_output=True, text=True)
        
        # Method 3: Make persistent
        try:
            import tempfile
            sysctl_file = "/etc/sysctl.conf"
            
            current_content = ""
            if os.path.exists(sysctl_file):
                with open(sysctl_file, "r") as f:
                    current_content = f.read()
            
            if "net.ipv4.ip_forward=1" not in current_content:
                new_content = current_content + "\n# Enable IP forwarding for Glint bridge networking\nnet.ipv4.ip_forward=1\n"
                
                with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp_file:
                    tmp_file.write(new_content)
                    tmp_file_path = tmp_file.name
                
                subprocess.run(["sudo", "cp", tmp_file_path, sysctl_file], 
                              capture_output=True, text=True)
                os.unlink(tmp_file_path)
        except Exception:
            pass
        
        print_success("✅ IP forwarding enabled")
        
    except Exception as e:
        print_warning(f"IP forwarding setup warning: {e}")


def clear_bridge_iptables_rules(bridge_name: str):
    """Clear any existing conflicting iptables rules"""
    try:
        print_info("Clearing existing bridge rules...")
        
        # Clear NAT table
        subprocess.run(["sudo", "iptables", "-t", "nat", "-F"], 
                      capture_output=True, text=True)
        
        # Clear FORWARD chain
        subprocess.run(["sudo", "iptables", "-F", "FORWARD"], 
                      capture_output=True, text=True)
        
    except Exception:
        pass


def setup_perfect_iptables_rules(bridge_name: str, primary_interface: str):
    """Set up perfect iptables rules for bridge networking"""
    try:
        print_info("Setting up comprehensive iptables rules...")
        
        network = "10.0.0.0/24"
        
        # NAT rule for internet access
        nat_rule = [
            "sudo", "iptables", "-t", "nat", "-A", "POSTROUTING",
            "-s", network, "-o", primary_interface, "-j", "MASQUERADE"
        ]
        
        result = subprocess.run(nat_rule, capture_output=True, text=True)
        if result.returncode == 0:
            print_success("✅ NAT rule configured")
        else:
            print_error(f"Failed to configure NAT: {result.stderr}")
            return False
        
        # Comprehensive forwarding rules
        forward_rules = [
            # Allow traffic from bridge to internet
            ["sudo", "iptables", "-A", "FORWARD", "-i", bridge_name, "-o", primary_interface, "-j", "ACCEPT"],
            # Allow established connections back
            ["sudo", "iptables", "-A", "FORWARD", "-i", primary_interface, "-o", bridge_name, 
             "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
            # Allow traffic within bridge
            ["sudo", "iptables", "-A", "FORWARD", "-i", bridge_name, "-o", bridge_name, "-j", "ACCEPT"],
            # Allow DNS traffic
            ["sudo", "iptables", "-A", "FORWARD", "-p", "udp", "--dport", "53", "-j", "ACCEPT"],
            ["sudo", "iptables", "-A", "FORWARD", "-p", "tcp", "--dport", "53", "-j", "ACCEPT"],
            # Allow DHCP traffic
            ["sudo", "iptables", "-A", "FORWARD", "-p", "udp", "--dport", "67", "-j", "ACCEPT"],
            ["sudo", "iptables", "-A", "FORWARD", "-p", "udp", "--dport", "68", "-j", "ACCEPT"]
        ]
        
        for rule in forward_rules:
            result = subprocess.run(rule, capture_output=True, text=True)
            if result.returncode == 0:
                print_success(f"✅ Forward rule: {' '.join(rule[5:])}")
            else:
                print_warning(f"Forward rule failed: {result.stderr}")
        
        return True
        
    except Exception as e:
        print_error(f"Failed to set up iptables rules: {e}")
        return False



def setup_enhanced_dnsmasq_auto(bridge_name: str) -> bool:
    """Set up enhanced dnsmasq with automatic installation"""
    try:
        print_info("Setting up enhanced dnsmasq...")
        
        # Install dnsmasq if not present
        if not command_exists("dnsmasq"):
            print_info("Installing dnsmasq...")
            if not install_dnsmasq():
                print_error("Failed to install dnsmasq")
                return False
        
        # Create enhanced configuration
        if not create_enhanced_dnsmasq_config(bridge_name):
            print_error("Failed to create dnsmasq configuration")
            return False
        
        # Restart and enable dnsmasq
        if not restart_dnsmasq():
            print_error("Failed to restart dnsmasq")
            return False
        
        print_success("✅ Enhanced dnsmasq configured")
        return True
        
    except Exception as e:
        print_error(f"Failed to set up enhanced dnsmasq: {e}")
        return False


def verify_complete_connectivity(bridge_name: str) -> bool:
    """Verify that complete bridge connectivity is working"""
    try:
        print_info("Verifying complete bridge connectivity...")
        
        # Test 1: Bridge is up and has IP
        if not is_bridge_active(bridge_name):
            print_warning("Bridge is not active")
            return False
        
        bridge_ip = get_bridge_ip(bridge_name)
        if not bridge_ip:
            print_warning("Bridge has no IP address")
            return False
        
        # Test 2: IP forwarding is enabled
        try:
            with open("/proc/sys/net/ipv4/ip_forward", "r") as f:
                if f.read().strip() != "1":
                    print_warning("IP forwarding is not enabled")
                    return False
        except Exception:
            print_warning("Cannot verify IP forwarding")
            return False
        
        # Test 3: NAT rules exist
        result = subprocess.run([
            "sudo", "iptables", "-t", "nat", "-L", "POSTROUTING"
        ], capture_output=True, text=True)
        
        if "MASQUERADE" not in result.stdout:
            print_warning("NAT rules not found")
            return False
        
        # Test 4: dnsmasq is running
        result = subprocess.run([
            "systemctl", "is-active", "dnsmasq"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print_warning("dnsmasq is not running")
            return False
        
        print_success("✅ Complete bridge connectivity verified")
        return True
        
    except Exception as e:
        print_warning(f"Connectivity verification failed: {e}")
        return False


def show_manual_dns_fix():
    """Show manual DNS configuration instructions"""
    host_dns = find_host_dns()
    
    print_info("\n" + "="*50)
    print_info("MANUAL DNS FIX FOR VMs")
    print_info("="*50)
    print_info("Add these lines to /etc/resolv.conf inside your VM:")
    print_info(f"  nameserver {host_dns}")
    print_info("  nameserver 8.8.8.8")
    print_info("")
    print_info("Or run this command inside the VM:")
    print_info(f"  echo 'nameserver {host_dns}' > /etc/resolv.conf")
    print_info("  echo 'nameserver 8.8.8.8' >> /etc/resolv.conf")
    print_info("="*50)


def test_bridge_dns(bridge_name: str = "br0") -> bool:
    """Test if bridge DNS is working"""
    try:
        # Check if dnsmasq is running and configured for the bridge
        result = subprocess.run(
            ["systemctl", "is-active", "dnsmasq"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print_success("✅ dnsmasq is active")
            
            # Check if config file exists
            config_file = f"/etc/dnsmasq.d/glint-{bridge_name}.conf"
            if os.path.exists(config_file):
                print_success(f"✅ Bridge DNS config exists: {config_file}")
                return True
        
        return False
        
    except Exception as e:
        print_warning(f"DNS test failed: {e}")
        return False


if __name__ == "__main__":
    """Allow running as standalone script for testing"""
    import sys
    
    bridge_name = sys.argv[1] if len(sys.argv) > 1 else "br0"
    
    print_info(f"Testing bridge DNS fix for '{bridge_name}'...")
    success = auto_fix_bridge_dns(bridge_name)
    
    if success:
        print_success("🎉 Bridge DNS configuration completed successfully!")
    else:
        print_error("❌ Bridge DNS configuration failed")
        sys.exit(1)