# Made by trex099
# https://github.com/Trex099/Glint
"""
Core Linux VM Management Module

This module provides the core enhanced Linux VM management functionality
with integration to the new session management system.
"""

import os
import sys
from typing import Dict, Optional, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Import moved to function level to avoid circular imports
# from .session_manager import get_session_manager, SessionInfo


class LinuxVMManager:
    """
    Enhanced Linux VM Manager with comprehensive session management
    """
    
    def __init__(self, vms_dir: str = None):
        """Initialize the Linux VM Manager"""
        # Import here to avoid circular imports
        from .session_manager import get_session_manager
        self.session_manager = get_session_manager()
        self.vms_dir = vms_dir or self.session_manager.vms_dir
    
    def create_vm_session(self, vm_name: str, pid: int, ssh_port: int, 
                         uuid: str, mac_address: str, command_line: str = None):
        """Create a new VM session"""
        return self.session_manager.create_session(
            vm_name=vm_name,
            pid=pid,
            ssh_port=ssh_port,
            uuid=uuid,
            mac_address=mac_address,
            command_line=command_line
        )
    
    def get_vm_session(self, vm_name: str):
        """Get VM session information"""
        return self.session_manager.get_session_info(vm_name)
    
    def is_vm_running(self, vm_name: str) -> bool:
        """Check if VM is running"""
        return self.session_manager.is_vm_running(vm_name)
    
    def stop_vm(self, vm_name: str, force: bool = False) -> bool:
        """Stop a VM"""
        return self.session_manager.stop_session(vm_name, force=force)
    
    def get_all_vms(self) -> Dict[str, Any]:
        """Get all active VM sessions"""
        return self.session_manager.get_all_sessions()
    
    def cleanup_stale_sessions(self) -> int:
        """Clean up stale sessions"""
        return self.session_manager.cleanup_stale_sessions()
    
    def get_vm_stats(self, vm_name: str) -> Optional[Dict[str, Any]]:
        """Get VM statistics"""
        return self.session_manager.get_session_stats(vm_name)
    
    def validate_vm_session(self, vm_name: str) -> Dict[str, Any]:
        """Validate VM session integrity"""
        return self.session_manager.validate_session_integrity(vm_name)
    
    def recover_vm_session(self, vm_name: str) -> bool:
        """Attempt to recover a corrupted VM session"""
        return self.session_manager.recover_session(vm_name)
    
    def update_vm_heartbeat(self, vm_name: str) -> bool:
        """Update VM session heartbeat"""
        return self.session_manager.update_session_heartbeat(vm_name)
    
    def shutdown(self):
        """Shutdown the VM manager"""
        if self.session_manager:
            self.session_manager.shutdown()


# Global VM manager instance
_vm_manager = None

def get_vm_manager() -> LinuxVMManager:
    """Get the global VM manager instance"""
    global _vm_manager
    if _vm_manager is None:
        _vm_manager = LinuxVMManager()
    return _vm_manager