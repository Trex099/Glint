#!/usr/bin/env python3
"""
Automated Post-Installation System for Glint Linux VMs

This module automatically handles post-installation tasks like setting system identifiers,
configuring networking, and other VM-specific setup without manual intervention.
"""

import os
import sys
import subprocess
import time
import json
from typing import Optional, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core_utils import print_info, print_success, print_warning, print_error


class AutoPostInstaller:
    """Handles automated post-installation tasks for Linux VMs"""
    
    def __init__(self, vm_name: str, vm_dir: str):
        self.vm_name = vm_name
        self.vm_dir = vm_dir
        self.shared_dir = os.path.join(vm_dir, 'shared')
        self.config_file = os.path.join(vm_dir, 'config.json')
        
    def create_auto_setup_script(self, identifiers: Dict[str, str]) -> str:
        """Create an automated setup script that runs on first boot"""
        script_path = os.path.join(self.shared_dir, 'auto_setup.sh')
        
        # Get VM configuration for network setup
        vm_config = self._load_vm_config()
        networking_mode = vm_config.get('networking', {}).get('mode', 'user')
        
        script_content = f"""#!/bin/bash
# Automated post-installation setup for VM: {self.vm_name}
# This script runs automatically on first boot to configure the system

set -e  # Exit on any error

LOGFILE="/var/log/glint-auto-setup.log"
SETUP_MARKER="/var/lib/glint-setup-complete"

# Function to log messages
log_message() {{
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOGFILE"
}}

# Check if setup already completed
if [ -f "$SETUP_MARKER" ]; then
    log_message "Auto-setup already completed, skipping..."
    exit 0
fi

log_message "Starting automated post-installation setup for VM: {self.vm_name}"

# Create log directory if it doesn't exist
mkdir -p /var/log
mkdir -p /var/lib

# Set system identifiers
log_message "Setting unique system identifiers..."

# Set machine-id
echo "{identifiers.get('machine_id', '')}" > /etc/machine-id
echo "{identifiers.get('machine_id', '')}" > /var/lib/dbus/machine-id
log_message "Machine ID set: {identifiers.get('machine_id', '')}"

# Regenerate SSH host keys
log_message "Regenerating SSH host keys..."
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A
systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || true

# Set hostname with unique identifier
HOSTNAME_SUFFIX=$(echo "{identifiers.get('machine_id', '')}" | cut -c1-8)
NEW_HOSTNAME="{self.vm_name}-$HOSTNAME_SUFFIX"
log_message "Setting hostname to: $NEW_HOSTNAME"

echo "$NEW_HOSTNAME" > /etc/hostname
hostnamectl set-hostname "$NEW_HOSTNAME" 2>/dev/null || true

# Update /etc/hosts
sed -i "s/127.0.1.1.*/127.0.1.1\\t$NEW_HOSTNAME/" /etc/hosts

# Configure networking based on mode
log_message "Configuring networking for mode: {networking_mode}"
"""

        # Add networking configuration based on mode
        if networking_mode == 'bridged':
            script_content += """
# Configure bridged networking
log_message "Setting up bridged networking..."

# Configure DHCP for bridged interface
cat > /etc/netplan/01-glint-bridge.yaml << 'EOF'
network:
  version: 2
  ethernets:
    enp0s3:
      dhcp4: true
      dhcp6: false
      nameservers:
        addresses: [8.8.8.8, 1.1.1.1]
EOF

# Apply netplan configuration
netplan apply 2>/dev/null || true

# Alternative: Configure with systemd-networkd
mkdir -p /etc/systemd/network
cat > /etc/systemd/network/10-glint-bridge.network << 'EOF'
[Match]
Name=enp0s3

[Network]
DHCP=ipv4
DNS=8.8.8.8
DNS=1.1.1.1
EOF

systemctl enable systemd-networkd 2>/dev/null || true
systemctl restart systemd-networkd 2>/dev/null || true

log_message "Bridged networking configured"
"""
        else:
            script_content += """
# Configure user-mode networking (NAT)
log_message "User-mode networking detected, using default configuration"
"""

        script_content += f"""
# Clear any cached network configurations
log_message "Clearing network caches..."
rm -f /var/lib/dhcp/dhclient.leases 2>/dev/null || true
rm -f /var/lib/NetworkManager/*.lease 2>/dev/null || true

# Restart network services
systemctl restart systemd-journald 2>/dev/null || true

# Regenerate any cached network configurations
if command -v netplan >/dev/null 2>&1; then
    log_message "Regenerating netplan configuration..."
    netplan generate 2>/dev/null || true
fi

# Update GRUB if present
if command -v update-grub >/dev/null 2>&1; then
    log_message "Updating GRUB configuration..."
    update-grub 2>/dev/null || true
fi

# Distribution-specific configurations
log_message "Applying distribution-specific configurations..."

# Arch Linux specific
if [ -f /etc/arch-release ]; then
    log_message "Detected Arch Linux, applying specific configurations..."
    
    # Enable and start essential services
    systemctl enable systemd-networkd systemd-resolved 2>/dev/null || true
    
    # Configure pacman for better VM performance
    sed -i 's/#Color/Color/' /etc/pacman.conf 2>/dev/null || true
    sed -i 's/#ParallelDownloads = 5/ParallelDownloads = 5/' /etc/pacman.conf 2>/dev/null || true
fi

# Ubuntu/Debian specific
if [ -f /etc/debian_version ]; then
    log_message "Detected Debian/Ubuntu, applying specific configurations..."
    
    # Update package database
    apt update -qq 2>/dev/null || true
    
    # Install essential packages for VM
    apt install -y curl wget git vim 2>/dev/null || true
fi

# Create completion marker
log_message "Auto-setup completed successfully!"
echo "Setup completed on $(date)" > "$SETUP_MARKER"

# Schedule a reboot to ensure all changes take effect
log_message "Scheduling reboot in 10 seconds to apply all changes..."
shutdown -r +1 "System will reboot in 1 minute to complete setup" 2>/dev/null || reboot &

log_message "Automated setup script completed successfully"
"""
        
        # Write script to shared directory
        os.makedirs(self.shared_dir, exist_ok=True)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        # Make script executable
        os.chmod(script_path, 0o755)
        
        print_success(f"Created automated setup script: {script_path}")
        return script_path
    
    def create_systemd_service(self) -> str:
        """Create a systemd service to run the auto-setup script on first boot"""
        service_content = f"""[Unit]
Description=Glint VM Auto-Setup Service
After=network.target
Wants=network.target

[Service]
Type=oneshot
ExecStart=/shared/auto_setup.sh
StandardOutput=journal
StandardError=journal
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""
        
        service_path = os.path.join(self.shared_dir, 'glint-auto-setup.service')
        
        with open(service_path, 'w', encoding='utf-8') as f:
            f.write(service_content)
        
        # Create installation script for the service
        install_script_path = os.path.join(self.shared_dir, 'install_auto_setup.sh')
        install_script_content = f"""#!/bin/bash
# Install the auto-setup service

# Copy service file to systemd directory
cp /shared/glint-auto-setup.service /etc/systemd/system/

# Enable the service
systemctl daemon-reload
systemctl enable glint-auto-setup.service

echo "Auto-setup service installed and enabled"
echo "The service will run automatically on next boot"
"""
        
        with open(install_script_path, 'w', encoding='utf-8') as f:
            f.write(install_script_content)
        
        os.chmod(install_script_path, 0o755)
        
        print_success(f"Created systemd service: {service_path}")
        print_success(f"Created service installer: {install_script_path}")
        
        return service_path
    
    def create_cloud_init_config(self, identifiers: Dict[str, str]) -> str:
        """Create cloud-init configuration for automatic setup"""
        cloud_init_dir = os.path.join(self.shared_dir, 'cloud-init')
        os.makedirs(cloud_init_dir, exist_ok=True)
        
        # User data configuration
        user_data = f"""#cloud-config
# Glint VM Auto-Configuration

# Set hostname
hostname: {self.vm_name}
fqdn: {self.vm_name}.vm.local

# Configure users
users:
  - default
  - name: glint
    groups: sudo
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL

# Package updates and installations
package_update: true
package_upgrade: true

packages:
  - curl
  - wget
  - git
  - vim
  - htop
  - net-tools

# Write files
write_files:
  - path: /etc/machine-id
    content: {identifiers.get('machine_id', '')}
    permissions: '0644'
  - path: /var/lib/dbus/machine-id
    content: {identifiers.get('machine_id', '')}
    permissions: '0644'

# Run commands
runcmd:
  - echo "Starting Glint VM auto-configuration..."
  - rm -f /etc/ssh/ssh_host_*
  - ssh-keygen -A
  - systemctl restart ssh || systemctl restart sshd || true
  - echo "Auto-configuration completed"

# Final message
final_message: "Glint VM {self.vm_name} is ready!"
"""
        
        user_data_path = os.path.join(cloud_init_dir, 'user-data')
        with open(user_data_path, 'w', encoding='utf-8') as f:
            f.write(user_data)
        
        # Meta data
        meta_data = f"""instance-id: {identifiers.get('vm_uuid', 'glint-vm')}
local-hostname: {self.vm_name}
"""
        
        meta_data_path = os.path.join(cloud_init_dir, 'meta-data')
        with open(meta_data_path, 'w', encoding='utf-8') as f:
            f.write(meta_data)
        
        print_success(f"Created cloud-init configuration: {cloud_init_dir}")
        return cloud_init_dir
    
    def _load_vm_config(self) -> Dict[str, Any]:
        """Load VM configuration from config.json"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print_warning(f"Failed to load VM config: {e}")
        
        return {}
    
    def create_legacy_identifier_script(self, identifiers: Dict[str, str]) -> str:
        """Create the legacy set_identifiers.sh script for compatibility"""
        script_path = os.path.join(self.shared_dir, 'set_identifiers.sh')
        
        script_content = f"""#!/bin/bash
# Legacy manual post-installation script to set unique system identifiers
# Generated for VM: {self.vm_name}

echo "Setting unique system identifiers for VM: {self.vm_name}"

# Set machine-id
echo "Setting machine-id..."
echo "{identifiers.get('machine_id', '')}" | sudo tee /etc/machine-id > /dev/null
echo "{identifiers.get('machine_id', '')}" | sudo tee /var/lib/dbus/machine-id > /dev/null

# Regenerate SSH host keys
echo "Regenerating SSH host keys..."
sudo rm -f /etc/ssh/ssh_host_*
sudo ssh-keygen -A

# Set hostname to include unique identifier
HOSTNAME_SUFFIX=$(echo "{identifiers.get('machine_id', '')}" | cut -c1-8)
NEW_HOSTNAME="{self.vm_name}-$HOSTNAME_SUFFIX"
echo "Setting hostname to: $NEW_HOSTNAME"
echo "$NEW_HOSTNAME" | sudo tee /etc/hostname > /dev/null
sudo hostnamectl set-hostname "$NEW_HOSTNAME" 2>/dev/null || true

# Update /etc/hosts
sudo sed -i "s/127.0.1.1.*/127.0.1.1\\t$NEW_HOSTNAME/" /etc/hosts

# Clear systemd journal machine-id cache
sudo systemctl restart systemd-journald 2>/dev/null || true

# Regenerate any cached network configurations
if command -v netplan >/dev/null 2>&1; then
    echo "Regenerating netplan configuration..."
    sudo netplan generate 2>/dev/null || true
fi

# Clear any cached hardware information
sudo rm -f /var/lib/dhcp/dhclient.leases 2>/dev/null || true
sudo rm -f /var/lib/NetworkManager/*.lease 2>/dev/null || true

# Update GRUB if present (to reflect new machine-id in boot entries)
if command -v update-grub >/dev/null 2>&1; then
    echo "Updating GRUB configuration..."
    sudo update-grub 2>/dev/null || true
fi

echo "System identifiers have been set successfully!"
echo "Machine ID: {identifiers.get('machine_id', '')}"
echo "VM UUID: {identifiers.get('vm_uuid', '')}"
echo "MAC Address: {identifiers.get('mac_address', '')}"
echo ""
echo "Please reboot the VM to ensure all changes take effect."
"""
        
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        # Make script executable
        os.chmod(script_path, 0o755)
        
        print_success(f"Created legacy identifier script: {script_path}")
        return script_path

    def create_manual_setup_instructions(self) -> str:
        """Create manual setup instructions as fallback"""
        instructions_path = os.path.join(self.shared_dir, 'SETUP_INSTRUCTIONS.md')
        
        instructions_content = f"""# Manual Setup Instructions for {self.vm_name}

If the automated setup doesn't work, follow these manual steps:

## 1. Run the Automated Setup Script
```bash
sudo /shared/auto_setup.sh
```

## 2. Alternative: Install Systemd Service
```bash
sudo /shared/install_auto_setup.sh
sudo reboot
```

## 3. Manual Steps (if automation fails)

### Set System Identifiers
```bash
sudo /shared/set_identifiers.sh
```

### Configure Networking (for bridged mode)
```bash
# For Ubuntu/Debian with netplan
sudo nano /etc/netplan/01-network-manager-all.yaml

# Add DHCP configuration:
network:
  version: 2
  ethernets:
    enp0s3:
      dhcp4: true
      nameservers:
        addresses: [8.8.8.8, 1.1.1.1]

sudo netplan apply
```

### Test Network Connectivity
```bash
ping google.com
nslookup google.com
```

## 4. Troubleshooting

### Check Auto-Setup Log
```bash
sudo tail -f /var/log/glint-auto-setup.log
```

### Check Service Status
```bash
sudo systemctl status glint-auto-setup
```

### Manual Network Configuration
```bash
# Check interfaces
ip addr show

# Configure DHCP manually
sudo dhclient enp0s3

# Set DNS manually
echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf
```

## Files in this directory:
- `auto_setup.sh` - Main automated setup script
- `set_identifiers.sh` - Legacy identifier setup script
- `install_auto_setup.sh` - Install systemd service
- `glint-auto-setup.service` - Systemd service file
- `cloud-init/` - Cloud-init configuration (if supported)
"""
        
        with open(instructions_path, 'w', encoding='utf-8') as f:
            f.write(instructions_content)
        
        print_success(f"Created setup instructions: {instructions_path}")
        return instructions_path


def create_automated_post_install_system(vm_name: str, vm_dir: str, identifiers: Dict[str, str]) -> bool:
    """
    Create a comprehensive automated post-installation system
    
    Args:
        vm_name: Name of the VM
        vm_dir: VM directory path
        identifiers: System identifiers dictionary
    
    Returns:
        bool: True if system was created successfully
    """
    try:
        print_info(f"🤖 Creating automated post-installation system for '{vm_name}'...")
        
        installer = AutoPostInstaller(vm_name, vm_dir)
        
        # Create all automation components
        installer.create_auto_setup_script(identifiers)
        installer.create_systemd_service()
        installer.create_cloud_init_config(identifiers)
        installer.create_legacy_identifier_script(identifiers)
        installer.create_manual_setup_instructions()
        
        print_success("✅ Automated post-installation system created!")
        print_info("🔧 The VM will automatically configure itself on first boot")
        print_info("📋 Manual instructions available in shared/SETUP_INSTRUCTIONS.md")
        
        return True
        
    except Exception as e:
        print_error(f"Failed to create automated post-installation system: {e}")
        return False


if __name__ == "__main__":
    """Allow running as standalone script for testing"""
    import sys
    
    if len(sys.argv) < 3:
        print_error("Usage: python auto_post_install.py <vm_name> <vm_dir>")
        sys.exit(1)
    
    vm_name = sys.argv[1]
    vm_dir = sys.argv[2]
    
    # Test identifiers
    test_identifiers = {
        'machine_id': 'test123456789abcdef',
        'vm_uuid': 'test-uuid-1234-5678',
        'mac_address': '52:54:00:12:34:56'
    }
    
    success = create_automated_post_install_system(vm_name, vm_dir, test_identifiers)
    
    if success:
        print_success("🎉 Automated post-installation system test completed!")
    else:
        print_error("❌ Test failed")
        sys.exit(1)