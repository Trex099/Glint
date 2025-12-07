# Made by trex099
# https://github.com/Trex099/Glint
"""
Enhanced Linux VM Management Module

This module provides comprehensive Linux VM management capabilities with
modular architecture for storage, networking, passthrough, monitoring,
security, and management features.
"""

# Import compatibility layer first to avoid circular imports
from .compatibility import BackwardCompatibilityLayer

# Import core components
# Defer LinuxVMManager import to avoid circular imports
def get_linux_vm_manager():
    from .core import LinuxVMManager
    return LinuxVMManager()

# Import error handling system
from .error_handling import (
    GlintError, ErrorSeverity, ErrorCategory, get_error_handler,
    PermissionError, ConfigurationError, ResourceError, HardwareError,
    NetworkError, StorageError, ProcessError, ValidationError,
    DependencyError, SystemError, InternalError
)

# Maintain backward compatibility
from .compatibility import (
    # Core VM operations
    create_new_vm,
    run_existing_vm,
    nuke_and_boot_fresh,
    stop_vm,
    nuke_vm_completely,
    
    # VM utilities
    select_vm,
    is_vm_running,
    get_vm_paths,
    get_running_vm_info,
    cleanup_stale_sessions,
    
    # Session management
    register_vm_session,
    get_vm_session_stats,
    
    # Passthrough operations
    run_vm_with_live_passthrough,
    run_gpu_passthrough_check,
    
    # Menu system
    linux_vm_menu,
    gpu_passthrough_menu,
    snapshot_management_menu,

    
    # System checks
    check_dependencies,
    find_iso_path,
    find_input_devices
)

__version__ = "2.0.0"
__all__ = [
    'get_linux_vm_manager',
    'BackwardCompatibilityLayer',
    # Error handling exports
    'GlintError', 'ErrorSeverity', 'ErrorCategory', 'get_error_handler',
    'PermissionError', 'ConfigurationError', 'ResourceError', 'HardwareError',
    'NetworkError', 'StorageError', 'ProcessError', 'ValidationError',
    'DependencyError', 'SystemError', 'InternalError',
    # Backward compatibility exports
    'create_new_vm',
    'run_existing_vm', 
    'nuke_and_boot_fresh',
    'stop_vm',
    'nuke_vm_completely',
    'select_vm',
    'is_vm_running',
    'get_vm_paths',
    'get_running_vm_info',
    'cleanup_stale_sessions',
    'register_vm_session',
    'get_vm_session_stats',
    'run_vm_with_live_passthrough',
    'run_gpu_passthrough_check',
    'linux_vm_menu',
    'gpu_passthrough_menu',
    'snapshot_management_menu',

    'check_dependencies',
    'find_iso_path',
    'find_input_devices'
]