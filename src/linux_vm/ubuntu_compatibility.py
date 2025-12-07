#!/usr/bin/env python3
# Made by trex099
# https://github.com/Trex099/Glint
"""
Ubuntu Compatibility Module for Glint

This module provides Ubuntu-specific package information and installation helpers.
"""

import subprocess
import logging

logger = logging.getLogger(__name__)

# Ubuntu-specific package mappings with pip fallbacks
UBUNTU_PACKAGES = {
    "QEMU": {
        "primary": "qemu-system-x86",
        "alternatives": ["qemu-kvm"]
    },
    "OVMF/EDK2": {
        "primary": "ovmf",
        "alternatives": []
    },
    "Python Rich": {
        "primary": "python3-rich",
        "alternatives": [],
        "pip_fallback": "rich"
    },
    "Zenity": {
        "primary": "zenity",
        "alternatives": []
    },
    "Python Pexpect": {
        "primary": "python3-pexpect",
        "alternatives": [],
        "pip_fallback": "pexpect"
    },
    "Python Questionary": {
        "primary": "python3-questionary",
        "alternatives": [],
        "pip_fallback": "questionary"
    },
    "Python Requests": {
        "primary": "python3-requests",
        "alternatives": [],
        "pip_fallback": "requests"
    },
    "Python TQDM": {
        "primary": "python3-tqdm",
        "alternatives": [],
        "pip_fallback": "tqdm"
    },
    "ISO Info Tool": {
        "primary": "genisoimage",
        "alternatives": []
    },
    "GuestFS Tools": {
        "primary": "guestfs-tools",
        "alternatives": ["libguestfs-tools"]
    },
    "APFS FUSE Driver": {
        "primary": "apfs-fuse",
        "alternatives": []
    },
    "APFS Utilities": {
        "primary": "libfsapfs-utils",
        "alternatives": []
    }
}

def get_ubuntu_package_info(package_key: str) -> dict:
    """
    Get Ubuntu-specific package information
    
    Args:
        package_key: Key from UBUNTU_PACKAGES
        
    Returns:
        Package information dictionary
    """
    return UBUNTU_PACKAGES.get(package_key, {})


def install_ubuntu_package(package_name: str, alternatives: list = None, 
                          pip_fallback: str = None, ppa: str = None) -> bool:
    """
    Install a package on Ubuntu with fallback options
    
    Args:
        package_name: Primary package name
        alternatives: Alternative package names to try
        pip_fallback: Python package name for pip fallback
        ppa: PPA to add if package not found
        
    Returns:
        True if installation succeeded
    """
    alternatives = alternatives or []
    
    # Try primary package first
    packages_to_try = [package_name] + alternatives
    
    for pkg in packages_to_try:
        try:
            subprocess.run(
                ["sudo", "apt", "install", "-y", pkg],
                capture_output=True, text=True, check=True
            )
            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to install {pkg}: {e.stderr}")
            continue
    
    # Try pip fallback for Python packages
    if pip_fallback:
        try:
            subprocess.run(["pip3", "install", "--user", pip_fallback],
                         capture_output=True, text=True, check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Pip installation failed: {e.stderr}")
    
    return False


class UbuntuCompatibilityManager:
    """
    Ubuntu Compatibility Manager for enhanced Ubuntu support
    """
    
    def __init__(self):
        self.packages = UBUNTU_PACKAGES
        self.logger = logging.getLogger(__name__)
    
    def get_package_info(self, package_key: str) -> dict:
        """Get package information for Ubuntu"""
        return self.packages.get(package_key, {})
    
    def install_package(self, package_name: str, alternatives: list = None, 
                       pip_fallback: str = None, ppa: str = None) -> bool:
        """Install package with Ubuntu-specific handling"""
        return install_ubuntu_package(package_name, alternatives, pip_fallback, ppa)
    
    def check_ubuntu_version(self) -> str:
        """Check Ubuntu version"""
        try:
            result = subprocess.run(
                ["lsb_release", "-rs"],
                capture_output=True, text=True, check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "unknown"
    
    def get_recommended_packages(self) -> dict:
        """Get recommended package configuration for current Ubuntu version"""
        version = self.check_ubuntu_version()
        
        # Version-specific recommendations
        if version.startswith("22."):
            return {
                "ovmf_path": "/usr/share/OVMF/OVMF_CODE.fd",
                "recommended_qemu": "qemu-system-x86"
            }
        elif version.startswith("20."):
            return {
                "ovmf_path": "/usr/share/ovmf/OVMF_CODE.fd",
                "recommended_qemu": "qemu-kvm"
            }
        else:
            return {
                "ovmf_path": "/usr/share/OVMF/OVMF_CODE.fd",
                "recommended_qemu": "qemu-system-x86"
            }
    
    def troubleshoot_common_issues(self) -> list:
        """Get troubleshooting steps for common Ubuntu issues"""
        return [
            "Update package lists: sudo apt update",
            "Install universe repository: sudo add-apt-repository universe",
            "Install build essentials: sudo apt install build-essential",
            "Check OVMF installation: ls -la /usr/share/OVMF/",
            "Verify KVM support: kvm-ok"
        ]