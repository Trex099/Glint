#!/usr/bin/env python3
# Made by trex099
# https://github.com/Trex099/Glint
"""
Installer ISO Management Module for Linux VMs

This module provides functionality for managing installer ISO attachments,
including automatic detachment after VM shutdown.
"""

import os
import json
import logging
from typing import Dict, Optional, Any

# Add parent directory to path for imports
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from src.core_utils import print_info, print_success
from src.linux_vm.error_handling import (
    StorageError, ValidationError, ErrorSeverity, get_error_handler
)
from src.linux_vm.storage.multi_disk import DiskManager, DiskType, DiskInterface
from src.config import CONFIG

logger = logging.getLogger(__name__)


class InstallerISOManager:
    """
    Manager for installer ISO attachments
    
    This class provides functionality for:
    - Attaching installer ISOs to VMs
    - Tracking installer ISO attachments
    - Automatically detaching installer ISOs after VM shutdown
    """
    
    def __init__(self, vm_name: str, disk_manager: DiskManager = None):
        """
        Initialize the Installer ISO Manager
        
        Args:
            vm_name: Name of the VM
            disk_manager: Optional DiskManager instance (created if not provided)
        """
        self.vm_name = vm_name
        self.disk_manager = disk_manager or DiskManager(vm_name)
        
        # Get VM directory
        self.vm_dir = self.disk_manager.vm_dir
        
        # Path to installer ISO configuration file
        self.iso_config_path = os.path.join(self.vm_dir, "installer_iso.json")
        
        # Load existing configuration
        self.iso_config = self._load_iso_config()
        
        logger.info(f"InstallerISOManager initialized for VM '{vm_name}'")
    
    def _load_iso_config(self) -> Dict[str, Any]:
        """
        Load installer ISO configuration from file
        
        Returns:
            Dict[str, Any]: Configuration dictionary
        """
        default_config = {
            "installer_iso_attached": False,
            "installer_iso_path": None,
            "installer_iso_disk_id": None,
            "auto_detach": CONFIG.get("AUTO_DETACH_INSTALLER", True)
        }
        
        try:
            if os.path.exists(self.iso_config_path):
                with open(self.iso_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                    # Ensure all required keys are present
                    for key in default_config:
                        if key not in config:
                            config[key] = default_config[key]
                    
                    return config
            else:
                return default_config
        except Exception as e:
            logger.error(f"Failed to load installer ISO configuration for VM '{self.vm_name}': {e}")
            return default_config
    
    def _save_iso_config(self) -> bool:
        """
        Save installer ISO configuration to file
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(self.iso_config_path, 'w', encoding='utf-8') as f:
                json.dump(self.iso_config, f, indent=2)
            
            logger.info(f"Saved installer ISO configuration for VM '{self.vm_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to save installer ISO configuration for VM '{self.vm_name}': {e}")
            return False
    
    def attach_installer_iso(self, iso_path: str) -> bool:
        """
        Attach an installer ISO to the VM
        
        Args:
            iso_path: Path to the ISO file
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Validate ISO path
            if not os.path.exists(iso_path):
                error = ValidationError(
                    message=f"ISO file not found: {iso_path}",
                    code="GLINT-E650",
                    severity=ErrorSeverity.ERROR,
                    details="Cannot attach non-existent ISO file",
                    suggestions=[
                        "Check the ISO path",
                        "Ensure the ISO file exists and is accessible"
                    ]
                )
                get_error_handler().handle_error(error)
                raise error
            
            # Check if an installer ISO is already attached
            if self.iso_config["installer_iso_attached"]:
                # If the same ISO is already attached, just return success
                if self.iso_config["installer_iso_path"] == iso_path:
                    print_info(f"Installer ISO '{os.path.basename(iso_path)}' is already attached")
                    return True
                
                # Otherwise, detach the current ISO first
                self.detach_installer_iso()
            
            # Attach the ISO as a disk
            disk_id = self.disk_manager.add_disk(
                size="0",  # Size doesn't matter for ISO
                disk_type=DiskType.RAW,
                interface=DiskInterface.IDE,  # Usually IDE for CDROM
                path=iso_path,
                readonly=True,
                boot=True  # Make it bootable for installation
            )
            
            # Update configuration
            self.iso_config["installer_iso_attached"] = True
            self.iso_config["installer_iso_path"] = iso_path
            self.iso_config["installer_iso_disk_id"] = disk_id
            self._save_iso_config()
            
            logger.info(f"Attached installer ISO '{os.path.basename(iso_path)}' to VM '{self.vm_name}'")
            print_success(f"Attached installer ISO '{os.path.basename(iso_path)}' to VM '{self.vm_name}'")
            
            return True
        except Exception as e:
            if not isinstance(e, ValidationError):
                error = StorageError(
                    message=f"Failed to attach installer ISO: {e}",
                    code="GLINT-E651",
                    severity=ErrorSeverity.ERROR,
                    details=f"Could not attach ISO file to VM '{self.vm_name}'",
                    suggestions=[
                        "Check if the ISO file is valid",
                        "Verify disk space and permissions",
                        "Check if the VM is in a valid state"
                    ],
                    original_exception=e
                )
                get_error_handler().handle_error(error)
            return False
    
    def detach_installer_iso(self) -> bool:
        """
        Detach the installer ISO from the VM
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if an installer ISO is attached
            if not self.iso_config["installer_iso_attached"]:
                logger.info(f"No installer ISO attached to VM '{self.vm_name}'")
                return True
            
            disk_id = self.iso_config["installer_iso_disk_id"]
            
            # Check if the disk exists
            if disk_id and disk_id in self.disk_manager.disks:
                # Detach the ISO
                self.disk_manager.remove_disk(disk_id, delete_file=False)
                
                # Update configuration
                self.iso_config["installer_iso_attached"] = False
                self.iso_config["installer_iso_path"] = None
                self.iso_config["installer_iso_disk_id"] = None
                self._save_iso_config()
                
                logger.info(f"Detached installer ISO from VM '{self.vm_name}'")
                print_success(f"Detached installer ISO from VM '{self.vm_name}'")
            else:
                # ISO was marked as attached but disk doesn't exist
                # Just update the configuration
                self.iso_config["installer_iso_attached"] = False
                self.iso_config["installer_iso_path"] = None
                self.iso_config["installer_iso_disk_id"] = None
                self._save_iso_config()
                
                logger.warning(f"Installer ISO was marked as attached but disk not found for VM '{self.vm_name}'")
            
            return True
        except Exception as e:
            error = StorageError(
                message=f"Failed to detach installer ISO: {e}",
                code="GLINT-E652",
                severity=ErrorSeverity.ERROR,
                details=f"Could not detach ISO file from VM '{self.vm_name}'",
                suggestions=[
                    "Check if the VM is in a valid state",
                    "Verify the disk configuration"
                ],
                original_exception=e
            )
            get_error_handler().handle_error(error)
            return False
    
    def is_installer_iso_attached(self) -> bool:
        """
        Check if an installer ISO is attached
        
        Returns:
            bool: True if an installer ISO is attached, False otherwise
        """
        return self.iso_config["installer_iso_attached"]
    
    def get_installer_iso_path(self) -> Optional[str]:
        """
        Get the path to the attached installer ISO
        
        Returns:
            Optional[str]: Path to the ISO file, or None if no ISO is attached
        """
        if self.iso_config["installer_iso_attached"]:
            return self.iso_config["installer_iso_path"]
        return None
    
    def set_auto_detach(self, enabled: bool) -> bool:
        """
        Set whether to automatically detach the installer ISO after VM shutdown
        
        Args:
            enabled: Whether to enable auto-detach
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.iso_config["auto_detach"] = enabled
            self._save_iso_config()
            
            logger.info(f"Set auto-detach to {enabled} for VM '{self.vm_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to set auto-detach for VM '{self.vm_name}': {e}")
            return False
    
    def is_auto_detach_enabled(self) -> bool:
        """
        Check if auto-detach is enabled
        
        Returns:
            bool: True if auto-detach is enabled, False otherwise
        """
        return self.iso_config["auto_detach"]
    
    def handle_vm_shutdown(self) -> bool:
        """
        Handle VM shutdown - detach installer ISO if auto-detach is enabled
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if auto-detach is enabled and an installer ISO is attached
            if self.iso_config["auto_detach"] and self.iso_config["installer_iso_attached"]:
                logger.info(f"Auto-detaching installer ISO for VM '{self.vm_name}'")
                return self.detach_installer_iso()
            return True
        except Exception as e:
            logger.error(f"Failed to handle VM shutdown for VM '{self.vm_name}': {e}")
            return False


def get_installer_iso_manager(vm_name: str) -> InstallerISOManager:
    """
    Get an InstallerISOManager instance for a VM
    
    Args:
        vm_name: Name of the VM
        
    Returns:
        InstallerISOManager instance
    """
    from src.linux_vm.storage.integration import get_disk_manager
    disk_manager = get_disk_manager(vm_name)
    return InstallerISOManager(vm_name, disk_manager)


def attach_installer_iso(vm_name: str, iso_path: str) -> bool:
    """
    Attach an installer ISO to a VM
    
    Args:
        vm_name: Name of the VM
        iso_path: Path to the ISO file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        iso_manager = get_installer_iso_manager(vm_name)
        return iso_manager.attach_installer_iso(iso_path)
    except Exception as e:
        logger.error(f"Failed to attach installer ISO to VM '{vm_name}': {e}")
        return False


def detach_installer_iso(vm_name: str) -> bool:
    """
    Detach the installer ISO from a VM
    
    Args:
        vm_name: Name of the VM
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        iso_manager = get_installer_iso_manager(vm_name)
        return iso_manager.detach_installer_iso()
    except Exception as e:
        logger.error(f"Failed to detach installer ISO from VM '{vm_name}': {e}")
        return False


def handle_vm_shutdown(vm_name: str) -> bool:
    """
    Handle VM shutdown - detach installer ISO if auto-detach is enabled
    
    Args:
        vm_name: Name of the VM
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        iso_manager = get_installer_iso_manager(vm_name)
        return iso_manager.handle_vm_shutdown()
    except Exception as e:
        logger.error(f"Failed to handle VM shutdown for VM '{vm_name}': {e}")
        return False