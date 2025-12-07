# Made by trex099
# https://github.com/Trex099/Glint
"""
Disk Resize Module for Linux VMs

This module provides functionality to resize QCOW2 disk images:
- Offline resize using qemu-img (for stopped VMs)
- Live resize using QMP protocol (for running VMs)
"""

import os
import sys
import json
import socket
import subprocess
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

# Add parent paths for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

try:
    from src.core_utils import print_info, print_error, print_success, print_warning
except ImportError:
    # Fallback if core_utils not available
    def print_info(msg): print(f"[INFO] {msg}")
    def print_error(msg): print(f"[ERROR] {msg}")
    def print_success(msg): print(f"[SUCCESS] {msg}")
    def print_warning(msg): print(f"[WARNING] {msg}")


@dataclass
class ResizeResult:
    """Result of a disk resize operation"""
    success: bool
    message: str
    old_size: int = 0
    new_size: int = 0
    method: str = "offline"  # "offline" or "live"


def parse_size_to_bytes(size_str: str) -> int:
    """
    Convert size string to bytes.
    
    Args:
        size_str: Size string like '50G', '100M', '1T'
        
    Returns:
        Size in bytes
    """
    size_str = size_str.strip().upper()
    multipliers = {
        'B': 1,
        'K': 1024,
        'M': 1024 ** 2,
        'G': 1024 ** 3,
        'T': 1024 ** 4
    }
    
    for suffix, multiplier in multipliers.items():
        if size_str.endswith(suffix):
            try:
                value = float(size_str[:-1])
                return int(value * multiplier)
            except ValueError:
                return 0
    
    # Try parsing as raw bytes
    try:
        return int(size_str)
    except ValueError:
        return 0


def get_qmp_socket_path(vm_name: str) -> str:
    """
    Get the QMP socket path for a VM.
    
    Args:
        vm_name: Name of the VM
        
    Returns:
        Path to the QMP socket
    """
    # Standard path pattern used by GLINT
    try:
        from src.config import CONFIG
        vm_dir = os.path.join(CONFIG.get('VMS_DIR_LINUX', 'vms_linux'), vm_name)
    except ImportError:
        vm_dir = os.path.join('vms_linux', vm_name)
    
    return os.path.join(vm_dir, 'qmp.sock')


class QMPClient:
    """
    Client for QEMU Machine Protocol (QMP) communication.
    
    Allows sending commands to running QEMU instances via Unix socket.
    """
    
    def __init__(self, socket_path: str, timeout: float = 10.0):
        self.socket_path = socket_path
        self.timeout = timeout
        self.sock = None
        self.connected = False
    
    def connect(self) -> bool:
        """
        Connect to the QMP socket.
        
        Returns:
            True if connection successful, False otherwise
        """
        if not os.path.exists(self.socket_path):
            return False
        
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect(self.socket_path)
            
            # Read greeting
            greeting = self._recv_response()
            if not greeting or 'QMP' not in greeting:
                self.disconnect()
                return False
            
            # Send qmp_capabilities to enter command mode
            self._send_command({"execute": "qmp_capabilities"})
            response = self._recv_response()
            
            if response and 'return' in response:
                self.connected = True
                return True
            
            self.disconnect()
            return False
            
        except (socket.error, socket.timeout, OSError) as e:
            print_error(f"QMP connection failed: {e}")
            self.disconnect()
            return False
    
    def disconnect(self):
        """Close the QMP connection."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        self.connected = False
    
    def _send_command(self, cmd: Dict[str, Any]) -> bool:
        """Send a QMP command."""
        if not self.sock:
            return False
        
        try:
            data = json.dumps(cmd) + '\n'
            self.sock.sendall(data.encode('utf-8'))
            return True
        except (socket.error, OSError):
            return False
    
    def _recv_response(self) -> Optional[Dict[str, Any]]:
        """Receive a QMP response."""
        if not self.sock:
            return None
        
        try:
            buffer = b''
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                
                # Try to parse JSON
                try:
                    return json.loads(buffer.decode('utf-8'))
                except json.JSONDecodeError:
                    # Keep reading if JSON incomplete
                    if len(buffer) > 65536:  # Safety limit
                        break
                    continue
                    
        except (socket.error, socket.timeout, OSError):
            pass
        
        return None
    
    def execute(self, command: str, arguments: Dict[str, Any] = None) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute a QMP command.
        
        Args:
            command: QMP command name
            arguments: Optional command arguments
            
        Returns:
            Tuple of (success, response_data)
        """
        if not self.connected:
            return False, {"error": "Not connected"}
        
        cmd = {"execute": command}
        if arguments:
            cmd["arguments"] = arguments
        
        if not self._send_command(cmd):
            return False, {"error": "Failed to send command"}
        
        response = self._recv_response()
        if not response:
            return False, {"error": "No response received"}
        
        if 'error' in response:
            return False, response['error']
        
        return True, response.get('return', {})
    
    def block_resize(self, device: str, size_bytes: int) -> Tuple[bool, str]:
        """
        Resize a block device.
        
        Args:
            device: Block device name (e.g., 'virtio-disk0', 'drive-virtio-disk0')
            size_bytes: New size in bytes
            
        Returns:
            Tuple of (success, message)
        """
        success, result = self.execute("block_resize", {
            "device": device,
            "size": size_bytes
        })
        
        if success:
            return True, f"Successfully resized {device} to {size_bytes} bytes"
        else:
            return False, f"Failed to resize: {result}"


def resize_disk(disk_path: str, new_size: str) -> bool:
    """
    Resize a QCOW2 disk image to a new size (offline mode).
    
    Args:
        disk_path: Path to the disk image
        new_size: New size (e.g., '50G', '100G')
        
    Returns:
        True if successful, False otherwise
    """
    if not os.path.exists(disk_path):
        return False
    
    try:
        # Run qemu-img resize command
        subprocess.run(
            ['qemu-img', 'resize', disk_path, new_size],
            capture_output=True,
            text=True,
            check=True
        )
        
        return True
    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False


def get_disk_info(disk_path: str) -> Optional[dict]:
    """
    Get information about a disk image.
    
    Args:
        disk_path: Path to the disk image
        
    Returns:
        Dictionary with disk information or None if failed
    """
    if not os.path.exists(disk_path):
        return None
    
    try:
        # Run qemu-img info command
        result = subprocess.run(
            ['qemu-img', 'info', '--output=json', disk_path],
            capture_output=True,
            text=True,
            check=True
        )
        
        return json.loads(result.stdout)
    except Exception:
        return None


def live_resize_disk(vm_name: str, disk_path: str, new_size: str, 
                     device_id: str = "virtio0") -> ResizeResult:
    """
    Resize a disk on a running VM using QMP protocol.
    
    This performs a live resize which doesn't require stopping the VM.
    The guest OS still needs to extend the filesystem to use the new space.
    
    Args:
        vm_name: Name of the VM
        disk_path: Path to the disk image (for verification)
        new_size: New size (e.g., '100G', '+50G' for relative)
        device_id: QEMU block device ID (default: 'virtio0')
        
    Returns:
        ResizeResult with success status and details
    """
    # Get current disk info
    disk_info = get_disk_info(disk_path)
    if not disk_info:
        return ResizeResult(
            success=False,
            message=f"Cannot read disk info: {disk_path}",
            method="live"
        )
    
    old_size = disk_info.get('virtual-size', 0)
    
    # Calculate new size in bytes
    if new_size.startswith('+'):
        # Relative size
        add_bytes = parse_size_to_bytes(new_size[1:])
        new_size_bytes = old_size + add_bytes
    else:
        new_size_bytes = parse_size_to_bytes(new_size)
    
    if new_size_bytes <= old_size:
        return ResizeResult(
            success=False,
            message=f"New size ({new_size_bytes}) must be larger than current size ({old_size})",
            old_size=old_size,
            new_size=new_size_bytes,
            method="live"
        )
    
    # Get QMP socket path
    qmp_socket = get_qmp_socket_path(vm_name)
    
    if not os.path.exists(qmp_socket):
        print_warning(f"QMP socket not found: {qmp_socket}")
        print_info("The VM may not have been started with QMP support.")
        print_info("Falling back to offline resize (requires VM restart)...")
        
        # Fall back to offline resize
        if resize_disk(disk_path, new_size):
            return ResizeResult(
                success=True,
                message="Disk resized (offline). Restart VM to apply changes.",
                old_size=old_size,
                new_size=new_size_bytes,
                method="offline"
            )
        else:
            return ResizeResult(
                success=False,
                message="Failed to resize disk offline",
                old_size=old_size,
                method="offline"
            )
    
    # Connect to QMP
    qmp = QMPClient(qmp_socket)
    if not qmp.connect():
        qmp.disconnect()
        return ResizeResult(
            success=False,
            message="Failed to connect to QMP socket. Is the VM running?",
            old_size=old_size,
            method="live"
        )
    
    try:
        # Try common device ID patterns
        device_patterns = [
            device_id,
            f"drive-{device_id}",
            "virtio-disk0",
            "drive-virtio-disk0",
            "virtio0",
            "drive0"
        ]
        
        success = False
        last_error = ""
        
        for pattern in device_patterns:
            ok, msg = qmp.block_resize(pattern, new_size_bytes)
            if ok:
                success = True
                print_success(f"Live resize successful using device: {pattern}")
                break
            else:
                last_error = msg
        
        if success:
            # Verify the resize
            new_info = get_disk_info(disk_path)
            actual_new_size = new_info.get('virtual-size', 0) if new_info else 0
            
            return ResizeResult(
                success=True,
                message="Live resize completed! Run 'growpart' and 'resize2fs' inside the VM.",
                old_size=old_size,
                new_size=actual_new_size,
                method="live"
            )
        else:
            return ResizeResult(
                success=False,
                message=f"QMP block_resize failed: {last_error}",
                old_size=old_size,
                method="live"
            )
            
    finally:
        qmp.disconnect()


def resize_with_snapshot(disk_path: str, new_size: str, create_backup: bool = True) -> ResizeResult:
    """
    Resize a disk with automatic snapshot/backup for rollback capability.
    
    Args:
        disk_path: Path to the disk image
        new_size: New size
        create_backup: Whether to create a backup snapshot first
        
    Returns:
        ResizeResult with success status
    """
    disk_info = get_disk_info(disk_path)
    if not disk_info:
        return ResizeResult(
            success=False,
            message=f"Cannot read disk info: {disk_path}"
        )
    
    old_size = disk_info.get('virtual-size', 0)
    backup_path = None
    
    if create_backup:
        # Create a snapshot before resize
        backup_path = disk_path + ".pre_resize_backup"
        try:
            subprocess.run(
                ['qemu-img', 'snapshot', '-c', 'pre_resize_backup', disk_path],
                capture_output=True,
                text=True,
                check=True
            )
            print_info(f"Created backup snapshot: pre_resize_backup")
        except subprocess.CalledProcessError as e:
            print_warning(f"Failed to create internal snapshot: {e}")
            # Try external backup copy instead
            try:
                import shutil
                shutil.copy2(disk_path, backup_path)
                print_info(f"Created backup copy: {backup_path}")
            except Exception as copy_error:
                print_warning(f"Could not create backup: {copy_error}")
                backup_path = None
    
    # Perform resize
    if resize_disk(disk_path, new_size):
        new_info = get_disk_info(disk_path)
        actual_new_size = new_info.get('virtual-size', 0) if new_info else 0
        
        return ResizeResult(
            success=True,
            message="Disk resized with backup. Extend filesystem in guest to use new space.",
            old_size=old_size,
            new_size=actual_new_size,
            method="offline"
        )
    else:
        # Attempt rollback if resize failed
        if backup_path and os.path.exists(backup_path):
            try:
                import shutil
                shutil.copy2(backup_path, disk_path)
                print_info("Restored from backup after failed resize")
            except Exception:
                pass
        
        return ResizeResult(
            success=False,
            message="Resize failed",
            old_size=old_size,
            method="offline"
        )


def get_qmp_args_for_vm(vm_name: str) -> list:
    """
    Get QEMU command line arguments to enable QMP socket for a VM.
    
    This should be added to QEMU command when starting the VM.
    
    Args:
        vm_name: Name of the VM
        
    Returns:
        List of QEMU command line arguments
    """
    socket_path = get_qmp_socket_path(vm_name)
    
    return [
        "-qmp", f"unix:{socket_path},server,nowait"
    ]


def is_vm_qmp_enabled(vm_name: str) -> bool:
    """
    Check if a VM has QMP socket available.
    
    Args:
        vm_name: Name of the VM
        
    Returns:
        True if QMP socket exists
    """
    socket_path = get_qmp_socket_path(vm_name)
    return os.path.exists(socket_path)