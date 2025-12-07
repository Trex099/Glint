# Made by trex099
# https://github.com/Trex099/Glint
"""
QEMU Command Builder Module

Provides QEMU command construction functions for Linux VMs.
"""

import os
import sys

# Use same import pattern as main.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG
from core_utils import print_info, print_warning, print_error, print_success, find_first_existing_path

# Import from refactored modules
from linux_vm.vm_paths import get_vm_paths


def _build_qemu_base_cmd(vm_name, vm_settings, ids):
    """Builds the base QEMU command list with enhanced UUID management."""
    paths = get_vm_paths(vm_name)
    uefi_code_path = find_first_existing_path(CONFIG['UEFI_CODE_PATHS'])
    if not uefi_code_path:
        print_error("Could not find a valid UEFI firmware file. Cannot proceed.")
        return None

    # QMP socket path for live operations (live resize, etc.)
    qmp_socket_path = os.path.join(paths['dir'], 'qmp.sock')

    qemu_cmd = [
        CONFIG["QEMU_BINARY"],
        "-enable-kvm",
        "-m", vm_settings["VM_MEM"],
        "-smp", vm_settings["VM_CPU"],
        "-uuid", ids['uuid'],
    ]
    
    # Add QMP socket for live management (enables live disk resize)
    qemu_cmd.extend(["-qmp", f"unix:{qmp_socket_path},server,nowait"])

    # Apply enhanced system identifiers if available
    try:
        from linux_vm.uuid_manager import get_uuid_manager
        uuid_manager = get_uuid_manager()
        identifiers = uuid_manager.get_identifiers(vm_name)
        
        if identifiers:
            # Apply all system identifiers to QEMU command
            qemu_cmd = uuid_manager.apply_identifiers_to_qemu_command(qemu_cmd, identifiers)
            print_info(f"✅ Applied enhanced system identifiers to QEMU command")
        else:
            print_warning("⚠️  No enhanced identifiers found, using basic UUID only")
            
    except ImportError:
        print_warning("⚠️  Enhanced UUID manager not available")

    # UEFI firmware configuration - only add the code file here
    # The variables file will be added by the specific command functions
    qemu_cmd.extend(["-drive", f"if=pflash,format=raw,readonly=on,file={uefi_code_path}"])
    qemu_cmd.extend(["-fsdev", f"local,security_model=mapped-xattr,id=fsdev0,path={paths['shared_dir']}"])
    qemu_cmd.extend(["-device", f"virtio-9p-pci,fsdev=fsdev0,mount_tag={CONFIG['SHARED_DIR_MOUNT_TAG']}"])
    qemu_cmd.extend(["-pidfile", paths['pid_file']])

    return qemu_cmd


def _add_network_args(qemu_cmd, ids, ssh_port, host_dns, networking_mode='nat'):
    """Adds networking arguments to the QEMU command."""
    if networking_mode == 'bridged':
        # For bridged networking, we need to properly configure the bridge
        # First ensure the QEMU bridge helper ACL is configured
        try:
            from linux_vm.networking.bridge_dns_fix import ensure_qemu_bridge_acl, setup_real_bridge_networking
            
            # Ensure QEMU can use the bridge
            ensure_qemu_bridge_acl("br0")
            
            # Set up real bridge networking (connects physical interface to bridge)
            bridge_ready = setup_real_bridge_networking("br0")
            
            if bridge_ready:
                # Use bridge helper for direct network access
                qemu_cmd.extend([
                    "-netdev", "bridge,id=n1,br=br0",
                    "-device", f"virtio-net-pci,netdev=n1,mac={ids['mac']}"
                ])
                print_success(f"✅ Bridge networking configured - VM will get IP from network DHCP")
                print_info(f"Host DNS server: {host_dns}")
                return
            else:
                print_warning("Bridge setup incomplete, falling back to NAT with DHCP")
                
        except Exception as e:
            print_warning(f"Bridge setup error: {e}, falling back to NAT with DHCP")
        
        # Fallback: Use user networking with full DHCP (works without root)
        # This provides internet access and DHCP, just NAT'd
        qemu_cmd.extend([
            "-netdev", f"user,id=n1,dns={host_dns},net=10.0.2.0/24,dhcpstart=10.0.2.15,hostfwd=tcp::{ssh_port}-:22",
            "-device", f"virtio-net-pci,netdev=n1,mac={ids['mac']}"
        ])
        print_info("Using NAT networking with DHCP (fallback)")
        print_info(f"SSH available on port {ssh_port}")
    else:
        # NAT networking configuration (default)
        if ssh_port > 0:
            qemu_cmd.extend([
                "-netdev", f"user,id=n1,dns={host_dns},hostfwd=tcp::{ssh_port}-:22",
                "-device", f"virtio-net-pci,netdev=n1,mac={ids['mac']}"
            ])
        else:
            qemu_cmd.extend(["-netdev", "user,id=n1", "-device", f"virtio-net-pci,netdev=n1,mac={ids['mac']}"])


def _get_enhanced_qemu_command(vm_name, vm_settings, input_devices, ids, host_dns,
                             ssh_port, iso_path=None, encryption_config=None, 
                             additional_disks=None, passthrough_info=None, identifiers=None):
    """Enhanced QEMU command with all advanced features."""
    
    # Start with base command
    qemu_cmd = _build_qemu_base_cmd(vm_name, vm_settings, ids)
    if not qemu_cmd:
        return None
    
    # Add encryption secrets if needed
    if encryption_config:
        qemu_cmd.extend(["-object", f"secret,id=sec0,data={encryption_config.passphrase}"])
        if additional_disks:
            for i, disk in enumerate(additional_disks):
                if disk.encrypted:
                    qemu_cmd.extend(["-object", f"secret,id=sec{i+1},data={encryption_config.passphrase}"])
    
    # Add network configuration
    networking_mode = vm_settings.get('NETWORKING_MODE', 'nat')
    _add_network_args(qemu_cmd, ids, ssh_port, host_dns, networking_mode)
    
    # Add passthrough if configured
    if passthrough_info:
        # Lazy import to avoid circular dependency
        from linux_vm.main import _add_passthrough_args
        _add_passthrough_args(qemu_cmd, passthrough_info, input_devices)
    else:
        # Graphics configuration optimized for performance
        # QXL with high VRAM is faster than virtio-vga without virglrenderer
        qemu_cmd.extend(["-cpu", "host"])
        qemu_cmd.extend(["-device", "qxl-vga,vgamem_mb=256"])  # 256MB VRAM for high-res
        qemu_cmd.extend(["-display", "gtk,gl=off,window-close=on"])
    
    # Add storage devices
    paths = get_vm_paths(vm_name)
    
    # Base disk
    if encryption_config:
        encrypted_path = paths['base'].replace('.qcow2', '_encrypted.qcow2')
        qemu_cmd.extend(["-drive", f"file={encrypted_path},if=virtio,encrypt.key-secret=sec0"])
    else:
        qemu_cmd.extend(["-drive", f"file={paths['base']},if=virtio"])
    
    # Additional disks
    if additional_disks:
        for i, disk_config in enumerate(additional_disks):
            disk_path = os.path.join(paths['dir'], f"{disk_config.name}.qcow2")
            if disk_config.encrypted and encryption_config:
                qemu_cmd.extend(["-drive", f"file={disk_path},if=virtio,encrypt.key-secret=sec{i+1}"])
            else:
                qemu_cmd.extend(["-drive", f"file={disk_path},if=virtio"])
    
    # Add ISO
    if iso_path:
        qemu_cmd.extend(["-cdrom", iso_path])
    
    # Add shutdown action
    qemu_cmd.extend(["-action", "reboot=shutdown"])
    
    return qemu_cmd
