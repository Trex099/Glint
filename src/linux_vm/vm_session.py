# Made by trex099
# https://github.com/Trex099/Glint
"""
VM Session Management Module

Provides session-related functions for Linux VMs including
running status checks, session registration, and cleanup.
"""

import os
import sys
from datetime import datetime

# Use same import pattern as main.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG
from core_utils import print_warning, print_error, print_success, remove_file

# Import get_vm_paths from our new module
from linux_vm.vm_paths import get_vm_paths


def get_running_vm_info(vm_name):
    """
    Enhanced VM info retrieval using the new session manager.
    Maintains backward compatibility while providing better reliability.
    """
    try:
        from src.linux_vm.session_manager import get_session_manager
        session_manager = get_session_manager()
        
        session = session_manager.get_session_info(vm_name)
        if session:
            return {
                'pid': session.pid,
                'port': session.ssh_port,
                'uuid': session.uuid,
                'mac': session.mac_address,
                'start_time': session.start_time,
                'uptime': (datetime.now() - session.start_time).total_seconds() if session.start_time else 0
            }
        return None
        
    except ImportError:
        print_warning("Enhanced session manager not available, using fallback method.")
        return _get_running_vm_info_fallback(vm_name)
    except Exception as e:
        print_error(f"Error getting VM info: {e}")
        return _get_running_vm_info_fallback(vm_name)


def _get_running_vm_info_fallback(vm_name):
    """Fallback implementation for VM info retrieval"""
    paths = get_vm_paths(vm_name)
    pid_file, session_info_file = paths['pid_file'], paths['session_info']
    
    if not os.path.exists(pid_file):
        return None
        
    try:
        with open(pid_file, 'r', encoding='utf-8') as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # Check if process exists
        
        with open(session_info_file, 'r', encoding='utf-8') as f:
            ssh_port = int(f.read().strip())
            
        return {'pid': pid, 'port': ssh_port}
    except (IOError, ValueError, ProcessLookupError, OSError):
        # Cleanup stale files if process is not running
        for f in [pid_file, session_info_file]:
            if os.path.exists(f):
                remove_file(f)
        return None


def is_vm_running(vm_name):
    """Enhanced VM running check using the new session manager."""
    try:
        from src.linux_vm.session_manager import get_session_manager
        session_manager = get_session_manager()
        return session_manager.is_vm_running(vm_name)
    except ImportError:
        # Fallback to original implementation
        return get_running_vm_info(vm_name) is not None
    except Exception as e:
        print_error(f"Error checking VM status: {e}")
        return get_running_vm_info(vm_name) is not None


def cleanup_stale_sessions():
    """Enhanced stale session cleanup using the new session manager."""
    try:
        from src.linux_vm.session_manager import get_session_manager
        session_manager = get_session_manager()
        cleaned_count = session_manager.cleanup_stale_sessions()
        if cleaned_count > 0:
            print_success(f"Cleaned up {cleaned_count} stale sessions")
        return cleaned_count
    except ImportError:
        print_warning("Enhanced session manager not available, using fallback cleanup.")
        return _cleanup_stale_sessions_fallback()
    except Exception as e:
        print_error(f"Error during session cleanup: {e}")
        return _cleanup_stale_sessions_fallback()


def _cleanup_stale_sessions_fallback():
    """Fallback implementation for stale session cleanup"""
    vms_dir = CONFIG['VMS_DIR_LINUX']
    if not os.path.isdir(vms_dir):
        return 0
    
    cleaned_count = 0
    for vm_name in os.listdir(vms_dir):
        if os.path.isdir(os.path.join(vms_dir, vm_name)):
            # This will trigger cleanup if the VM is not running
            if not get_running_vm_info(vm_name):
                cleaned_count += 1
    
    return cleaned_count


def register_vm_session(vm_name, pid, ssh_port, uuid, mac_address, command_line=None):
    """
    Register a new VM session with the session manager
    """
    try:
        from src.linux_vm.session_manager import get_session_manager
        session_manager = get_session_manager()
        
        session = session_manager.create_session(
            vm_name=vm_name,
            pid=pid,
            ssh_port=ssh_port,
            uuid=uuid,
            mac_address=mac_address,
            command_line=command_line
        )
        
        print_success(f"Registered session for VM '{vm_name}' (PID: {pid})")
        return session
        
    except ImportError:
        print_warning("Enhanced session manager not available")
        return None
    except Exception as e:
        print_error(f"Failed to register session for VM '{vm_name}': {e}")
        return None


def get_vm_session_stats(vm_name):
    """
    Get detailed session statistics for a VM
    """
    try:
        from src.linux_vm.session_manager import get_session_manager
        session_manager = get_session_manager()
        
        stats = session_manager.get_session_stats(vm_name)
        return stats
        
    except ImportError:
        print_warning("Enhanced session manager not available")
        return None
    except Exception as e:
        print_error(f"Failed to get session stats for VM '{vm_name}': {e}")
        return None
