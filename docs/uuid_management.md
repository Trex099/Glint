# UUID & System Identifier Management

## Overview

The UUID and System Identifier Management system ensures that every Linux VM created with Glint has completely unique system identifiers. This prevents issues with duplicate machine IDs, MAC addresses, disk UUIDs, and other system identifiers that can cause problems in networked environments or when cloning VMs.

## Key Features

### 🆔 Unique System Identifiers
- **VM UUID**: Unique QEMU virtual machine identifier
- **MAC Address**: Unique network interface identifier with QEMU vendor prefix
- **Machine ID**: Unique 32-character system identifier for `/etc/machine-id`
- **Disk UUIDs**: Unique identifiers for disk, partition, filesystem, boot, and swap
- **Hardware Serials**: Unique CPU and motherboard serial numbers
- **SMBIOS UUIDs**: Unique system management BIOS identifiers

### 🔄 Regeneration Options
- **Fresh Creation**: Generate completely new identifiers for new VMs
- **Disk Regeneration**: Regenerate only disk-related identifiers for overlays
- **Nuclear Reset (NUKE)**: Completely regenerate ALL identifiers and reset UEFI variables
- **Base Image Reset**: Regenerate identifiers when creating new base images

### 🔧 UEFI/TPM/Secure Boot Support
- **UEFI Variable Reset**: Fresh NVRAM (OVMF_VARS.fd) for each VM instance
- **TPM State Reset**: Clean TPM state for each VM
- **Secure Boot Reset**: Fresh secure boot variables

### 📜 Post-Installation Integration
- **Automatic Script Generation**: Creates scripts to set identifiers inside the VM
- **SSH Key Regeneration**: Ensures unique SSH host keys
- **Hostname Uniqueness**: Sets unique hostnames based on machine ID

## Architecture

### SystemIdentifiers Class
```python
class SystemIdentifiers:
    vm_uuid: str           # QEMU VM UUID
    machine_id: str        # /etc/machine-id
    mac_address: str       # Network interface MAC
    disk_uuid: str         # Primary disk UUID
    partition_uuid: str    # Partition UUID
    filesystem_uuid: str   # Filesystem UUID
    boot_uuid: str         # Boot partition UUID
    swap_uuid: str         # Swap partition UUID
    dmi_uuid: str          # DMI system UUID
    smbios_uuid: str       # SMBIOS UUID
    cpu_serial: str        # CPU serial number
    motherboard_serial: str # Motherboard serial
    bios_uuid: str         # BIOS UUID
    created_at: str        # Creation timestamp
```

### UUIDManager Class
The `UUIDManager` class handles all UUID operations:
- Identifier generation and persistence
- QEMU command enhancement
- UEFI variable management
- Post-install script creation

## Usage

### Creating a New VM
When creating a new VM, the system automatically:
1. Generates fresh system identifiers
2. Resets UEFI variables
3. Creates a post-install script
4. Applies identifiers to QEMU command

```python
from src.linux_vm.uuid_manager import get_uuid_manager

uuid_manager = get_uuid_manager()
identifiers = uuid_manager.generate_fresh_identifiers("my-vm")
```

### Menu Options

#### 1. View VM Identifiers
Display current system identifiers for VMs:
- Shows all identifier types
- Supports viewing specific VM or all VMs
- Displays creation timestamps

#### 2. Regenerate Overlay with Fresh Identifiers
For VMs using overlay disks:
- Regenerates disk-specific UUIDs
- Keeps VM UUID and MAC address
- Resets UEFI variables
- Creates fresh overlay file

#### 3. Regenerate Base Image Identifiers
For creating new base images:
- Generates completely fresh identifiers
- Resets UEFI variables
- Creates post-install script
- Use when cloning or creating new base images

#### 4. 🔥 NUKE VM Session (Complete Reset)
Nuclear option for complete fresh start:
- Regenerates ALL system identifiers
- Resets UEFI/TPM/Secure Boot variables
- Creates fresh overlay (if exists)
- Provides post-install script
- Use when you need completely fresh VM identity

## Implementation Details

### MAC Address Generation
```python
def _generate_mac_address(self) -> str:
    # Uses QEMU vendor prefix (52:54:00) for consistency
    return f"52:54:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"
```

### Machine ID Generation
```python
def _generate_machine_id(self) -> str:
    # Generates a unique 32-character machine ID
    return hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
```

### QEMU Command Enhancement
The system automatically enhances QEMU commands with:
- UUID parameter (`-uuid`)
- SMBIOS information (`-smbios`)
- Machine-specific parameters
- Hardware serial numbers

### Post-Install Script
Generated script (`set_identifiers.sh`) handles:
- Setting `/etc/machine-id`
- Setting `/var/lib/dbus/machine-id`
- Regenerating SSH host keys
- Setting unique hostname
- Updating system configurations
- Clearing cached network configurations

## File Structure

### VM Directory Layout
```
vms_linux/
└── vm-name/
    ├── identifiers.json      # System identifiers storage
    ├── base.qcow2           # Base disk image
    ├── overlay.qcow2        # Overlay disk (if used)
    ├── uefi-seed.fd         # UEFI variables template
    ├── uefi-instance.fd     # UEFI variables instance
    ├── config.json          # VM configuration
    └── shared/
        └── set_identifiers.sh # Post-install script
```

### Identifiers File Format
```json
{
  "vm_uuid": "550e8400-e29b-41d4-a716-446655440000",
  "machine_id": "a1b2c3d4e5f6789012345678901234567890abcd",
  "mac_address": "52:54:00:12:34:56",
  "disk_uuid": "123e4567-e89b-12d3-a456-426614174000",
  "partition_uuid": "987fcdeb-51a2-43d7-8f9e-123456789abc",
  "filesystem_uuid": "456789ab-cdef-1234-5678-90abcdef1234",
  "boot_uuid": "fedcba98-7654-3210-fedc-ba9876543210",
  "swap_uuid": "13579bdf-2468-ace0-1357-9bdf2468ace0",
  "dmi_uuid": "abcdef12-3456-7890-abcd-ef1234567890",
  "smbios_uuid": "98765432-10fe-dcba-9876-543210fedcba",
  "cpu_serial": "CPU1234567890",
  "motherboard_serial": "MB0987654321",
  "bios_uuid": "11223344-5566-7788-99aa-bbccddeeff00",
  "created_at": "2025-07-24T19:12:10.844677"
}
```

## Best Practices

### When to Use Each Option

#### Fresh VM Creation
- Always generates new identifiers automatically
- No manual intervention needed
- Ensures complete uniqueness

#### Overlay Regeneration
Use when:
- Creating a new overlay from existing base
- Want to keep VM identity but fresh disk IDs
- Switching between different overlay configurations

#### Base Image Regeneration
Use when:
- Creating a new base image from scratch
- Cloning a base image from another VM
- After major system changes to base image

#### Nuclear Reset (NUKE)
Use when:
- Complete fresh start needed
- VM has been compromised or corrupted
- Want to ensure absolutely no trace of previous identity
- Testing scenarios requiring clean slate

### Security Considerations

1. **Unique Machine IDs**: Prevents systemd service conflicts
2. **Unique SSH Keys**: Prevents SSH fingerprint collisions
3. **Unique MAC Addresses**: Prevents network conflicts
4. **Fresh UEFI Variables**: Prevents TPM/Secure Boot issues
5. **Unique Disk UUIDs**: Prevents filesystem mounting conflicts

### Performance Impact

- **Minimal Runtime Impact**: Identifiers generated once at creation
- **Fast Regeneration**: Disk identifier regeneration is quick
- **Efficient Storage**: JSON format for identifier persistence
- **Lazy Loading**: Identifiers loaded only when needed

## Troubleshooting

### Common Issues

#### Identifiers Not Applied
**Symptoms**: VM has default/duplicate identifiers
**Solution**: 
1. Check if post-install script was run
2. Verify identifiers.json exists
3. Run NUKE operation if needed

#### UEFI Variables Not Reset
**Symptoms**: Boot issues, TPM errors
**Solution**:
1. Check UEFI template file exists
2. Verify permissions on UEFI files
3. Use NUKE operation to force reset

#### Network Conflicts
**Symptoms**: MAC address conflicts
**Solution**:
1. Regenerate identifiers for conflicting VMs
2. Check for manual MAC address overrides
3. Ensure QEMU vendor prefix is used

### Debug Information

Enable debug output by checking:
- VM configuration files
- Identifier JSON files
- Post-install script logs
- QEMU command line parameters

## API Reference

### UUIDManager Methods

#### `generate_fresh_identifiers(vm_name, force_regenerate=False)`
Generate fresh system identifiers for a VM.

#### `regenerate_disk_identifiers(vm_name)`
Regenerate only disk-specific identifiers.

#### `reset_uefi_variables(vm_name)`
Reset UEFI variables to fresh state.

#### `nuke_and_regenerate_all(vm_name)`
Nuclear option: regenerate everything.

#### `apply_identifiers_to_qemu_command(base_command, identifiers)`
Apply identifiers to QEMU command line.

#### `create_post_install_script(vm_name, identifiers)`
Create script for setting identifiers inside VM.

### SystemIdentifiers Methods

#### `to_dict()`
Convert identifiers to dictionary for serialization.

#### `from_dict(data)`
Create SystemIdentifiers from dictionary.

## Testing

The system includes comprehensive tests:
- Unit tests for all components
- Integration tests for workflows
- Demo scripts for verification

Run tests:
```bash
python TEST/test_uuid_manager.py
python TEST/demo_uuid_management.py
```

## Future Enhancements

### Planned Features
- **Cloud Integration**: Support for cloud-specific identifiers
- **Backup/Restore**: Identifier backup and restoration
- **Template System**: Predefined identifier templates
- **Audit Logging**: Track identifier changes
- **Bulk Operations**: Manage multiple VMs simultaneously

### Extensibility
The system is designed to be extensible:
- Add new identifier types easily
- Support additional virtualization platforms
- Integrate with external identity systems
- Custom identifier generation algorithms

## Conclusion

The UUID and System Identifier Management system ensures that every Linux VM created with Glint has completely unique system identifiers, preventing conflicts and ensuring proper isolation. The system provides multiple levels of identifier management, from simple regeneration to nuclear reset options, making it suitable for various use cases from development to production environments.