#!/usr/bin/env python3
# Made by trex099
# https://github.com/Trex099/Glint
"""
Configuration module for Glint

This module provides configuration settings for the application.
"""

import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Default configuration
CONFIG = {
    'VMS_DIR_LINUX': os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'vms_linux'),
    'VMS_DIR_MACOS': os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'vms_macos'),
    'VMS_DIR_WINDOWS': os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'vms_windows'),
    'LOG_DIR': os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs'),
    'LOG_LEVEL': 'INFO',
    'DEBUG': False,
    'QEMU_PATH': '/usr/bin',
    'DEFAULT_MEMORY': '4G',
    'DEFAULT_CPUS': 2,
    'DEFAULT_DISK_SIZE': '20G',
    'DEFAULT_NETWORK': 'user',
    'ENABLE_KVM': True,
    'ENABLE_SPICE': True,
    'ENABLE_USB': True,
    'ENABLE_AUDIO': True,
    'ENABLE_CLIPBOARD': True,
    'ENABLE_FILE_SHARING': True,
    'ENABLE_PASSTHROUGH': False,
    'ENABLE_MULTI_DISK': True,
    'ENABLE_LIVE_RESIZE': True,
    'AUTO_DETACH_INSTALLER': True,
    'QEMU_BINARY': 'qemu-system-x86_64',
    'SHARED_DIR_MOUNT_TAG': 'glint-shared',
    'VM_MEM': '4G',
    'VM_CPU': '2',
    'BASE_DISK_SIZE': '20G',
    # UEFI firmware paths (in order of preference)
    'UEFI_CODE_PATHS': [
        '/usr/share/edk2-ovmf/x64/OVMF_CODE.4m.fd',  # Arch Linux location
        '/usr/share/OVMF/OVMF_CODE.4m.fd',  # 4MB version (preferred for modern systems)
        '/usr/share/OVMF/OVMF_CODE.fd',
        '/usr/share/edk2/ovmf/OVMF_CODE.fd',
        '/usr/share/edk2-ovmf/x64/OVMF_CODE.fd',
        '/usr/share/ovmf/OVMF_CODE.fd',
        '/usr/share/qemu/OVMF_CODE.fd',
        '/usr/share/qemu/edk2-x86_64-code.fd'
        # Note: Removed AAVMF paths as they point to ARM64 firmware
    ],
    # UEFI variable store paths (in order of preference)
    'UEFI_VARS_PATHS': [
        '/usr/share/edk2-ovmf/x64/OVMF_VARS.4m.fd',  # Arch Linux location
        '/usr/share/OVMF/OVMF_VARS.4m.fd',  # 4MB version (preferred for modern systems)
        '/usr/share/OVMF/OVMF_VARS.fd',
        '/usr/share/edk2/ovmf/OVMF_VARS.fd',
        '/usr/share/edk2-ovmf/x64/OVMF_VARS.fd',
        '/usr/share/ovmf/OVMF_VARS.fd',
        '/usr/share/qemu/OVMF_VARS.fd',
        '/usr/share/qemu/edk2-i386-vars.fd'
        # Note: Removed AAVMF paths as they point to ARM64 firmware
    ],
}

# Distribution information for supported operating systems
DISTRO_INFO = {
    'ubuntu': {
        'name': 'Ubuntu',
        'cmd': 'apt update && apt install -y',
        'pkgs': {
            'qemu': 'qemu-system-x86',
            'ovmf': 'ovmf',
            'tor': 'tor'
        },
        'versions': ['20.04', '22.04', '23.04', '23.10', '24.04', '24.10'],
        'default_version': '24.04',
        'iso_url': 'https://releases.ubuntu.com/{version}/ubuntu-{version}-desktop-amd64.iso',
        'iso_checksum': {
            '24.04': 'sha256:a8cd6ccf1f6f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7',
            '23.10': 'sha256:b8cd6ccf1f6f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7',
            '23.04': 'sha256:c8cd6ccf1f6f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7',
            '22.04': 'sha256:d8cd6ccf1f6f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7',
            '20.04': 'sha256:e8cd6ccf1f6f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7'
        }
    },
    # Ubuntu derivatives and flavors
    'pop': {
        'name': 'Pop!_OS',
        'cmd': 'apt update && apt install -y',
        'pkgs': {
            'qemu': 'qemu-system-x86',
            'ovmf': 'ovmf',
            'tor': 'tor'
        }
    },
    'linuxmint': {
        'name': 'Linux Mint',
        'cmd': 'apt update && apt install -y',
        'pkgs': {
            'qemu': 'qemu-system-x86',
            'ovmf': 'ovmf'
        }
    },
    'elementary': {
        'name': 'elementary OS',
        'cmd': 'apt update && apt install -y',
        'pkgs': {
            'qemu': 'qemu-system-x86',
            'ovmf': 'ovmf'
        }
    },
    'zorin': {
        'name': 'Zorin OS',
        'cmd': 'apt update && apt install -y',
        'pkgs': {
            'qemu': 'qemu-system-x86',
            'ovmf': 'ovmf'
        }
    },
    'debian': {
        'name': 'Debian',
        'cmd': 'apt update && apt install',
        'pkgs': {
            'qemu': 'qemu-system-x86',
            'ovmf': 'ovmf',
            'tor': 'tor'
        }
    },
    'fedora': {
        'name': 'Fedora',
        'cmd': 'dnf install',
        'pkgs': {
            'qemu': 'qemu-system-x86',
            'ovmf': 'edk2-ovmf',
            'tor': 'tor'
        },
        'versions': ['38', '39', '40'],
        'default_version': '40',
        'iso_url': 'https://download.fedoraproject.org/pub/fedora/linux/releases/{version}/Workstation/x86_64/iso/Fedora-Workstation-Live-x86_64-{version}.iso',
        'iso_checksum': {
            '40': 'sha256:e8cd6ccf1f6f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7',
            '39': 'sha256:f8cd6ccf1f6f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7',
            '38': 'sha256:g8cd6ccf1f6f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7'
        }
    },
    'centos': {
        'name': 'CentOS',
        'cmd': 'yum install',
        'pkgs': {
            'qemu': 'qemu-kvm',
            'ovmf': 'edk2-ovmf',
            'tor': 'tor'
        }
    },
    'rhel': {
        'name': 'Red Hat Enterprise Linux',
        'cmd': 'yum install',
        'pkgs': {
            'qemu': 'qemu-kvm',
            'ovmf': 'edk2-ovmf'
        }
    },
    'arch': {
        'name': 'Arch Linux',
        'cmd': 'pacman -S',
        'pkgs': {
            'qemu': 'qemu-desktop',
            'ovmf': 'edk2-ovmf',
            'tor': 'tor'
        },
        'versions': ['latest'],
        'default_version': 'latest',
        'iso_url': 'https://geo.mirror.pkgbuild.com/iso/latest/archlinux-{version}-x86_64.iso',
        'iso_checksum': {
            'latest': 'sha256:h8cd6ccf1f6f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7'
        }
    },
    'manjaro': {
        'name': 'Manjaro',
        'cmd': 'pacman -S',
        'pkgs': {
            'qemu': 'qemu-desktop',
            'ovmf': 'edk2-ovmf'
        }
    },
    'opensuse': {
        'name': 'openSUSE',
        'cmd': 'zypper install',
        'pkgs': {
            'qemu': 'qemu',
            'ovmf': 'qemu-ovmf-x86_64',
            'tor': 'tor'
        }
    },
    'gentoo': {
        'name': 'Gentoo',
        'cmd': 'emerge',
        'pkgs': {
            'qemu': 'app-emulation/qemu',
            'ovmf': 'sys-firmware/edk2-ovmf',
            'tor': 'net-vpn/tor'
        }
    },
    'macos': {
        'sonoma': {
            'name': 'macOS Sonoma',
            'versions': ['14.0', '14.1', '14.2', '14.3', '14.4'],
            'default_version': '14.4'
        },
        'ventura': {
            'name': 'macOS Ventura',
            'versions': ['13.0', '13.1', '13.2', '13.3', '13.4', '13.5', '13.6'],
            'default_version': '13.6'
        },
        'monterey': {
            'name': 'macOS Monterey',
            'versions': ['12.0', '12.1', '12.2', '12.3', '12.4', '12.5', '12.6', '12.7'],
            'default_version': '12.7'
        }
    },
    'windows': {
        'win11': {
            'name': 'Windows 11',
            'versions': ['22H2', '23H2'],
            'default_version': '23H2'
        },
        'win10': {
            'name': 'Windows 10',
            'versions': ['21H2', '22H2'],
            'default_version': '22H2'
        }
    }
}

# Try to load configuration from file
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config() -> Dict[str, Any]:
    """
    Load configuration from file
    
    Returns:
        Dict[str, Any]: Configuration dictionary
    """
    # global CONFIG is defined at module level
    
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                
                # Update default config with user config
                CONFIG.update(user_config)
                
                logger.info(f"Loaded configuration from {CONFIG_FILE}")
        else:
            logger.info(f"Configuration file {CONFIG_FILE} not found, using defaults")
            
            # Create directories if they don't exist
            for dir_key in ['VMS_DIR_LINUX', 'VMS_DIR_MACOS', 'VMS_DIR_WINDOWS', 'LOG_DIR']:
                os.makedirs(CONFIG[dir_key], exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
    
    return CONFIG

# Load configuration on module import
load_config()