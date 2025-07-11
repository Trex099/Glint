
# Made by trex099
# https://github.com/Trex099/Glint
"""
This module contains configuration settings for the Universal VM Manager.

It includes paths for assets, VM directories, and default VM settings.
It also contains distribution-specific information for package installation and system updates.
"""

CONFIG = {
    "ASSETS_DIR": "assets",

    "VMS_DIR_LINUX": "vms_linux",
    "VM_MEM": "4096M",
    "VM_CPU": "2",
    "BASE_DISK_SIZE": "20",
    "QEMU_BINARY": "qemu-system-x86_64",
    
    # Define lists of potential paths for firmware. The first one found will be used.
    "UEFI_CODE_PATHS": [
        "/usr/share/edk2/x64/OVMF_CODE.4m.fd",
        "/usr/share/OVMF/OVMF_CODE.fd"
    ],
    "UEFI_VARS_PATHS": [
        "/usr/share/edk2/x64/OVMF_VARS.4m.fd",
        "/usr/share/OVMF/OVMF_VARS.fd"
    ],

    "QEMU_DISPLAY": ["-display", "sdl", "-vga", "std"],
    "SHARED_DIR_MOUNT_TAG": "host_share",

    "VMS_DIR_MACOS": "vms_macos",
    "VMS_DIR_WINDOWS": "vms_windows",

    "OPENCORE_IMG": "assets/OpenCore.qcow2",
    "GENSMBIOS_SCRIPT": "assets/SMBIOS/GenSMBIOS.py",
    "FETCHMACOS_SCRIPT": "assets/fetch-macOS-v2.py",
    "OSK_KEY": "ourhardworkbythesewordsguardedpleasedontsteal(c)AppleComputerInc",
}

DISTRO_INFO = {
    "arch": {
        "cmd": "pacman -Syu --needed",
        "pkgs": {"qemu": "qemu-desktop", "ovmf": "edk2-ovmf", "mtools": "mtools"},
        "grub_update": "sudo grub-mkconfig -o /boot/grub/grub.cfg",
        "initramfs_update": "sudo mkinitcpio -P"
    },
    "manjaro": {
        "cmd": "pacman -Syu --needed",
        "pkgs": {"qemu": "qemu-desktop", "ovmf": "edk2-ovmf", "mtools": "mtools"},
        "grub_update": "sudo update-grub",
        "initramfs_update": "sudo mkinitcpio -P"
    },

    "endeavouros": {
        "cmd": "pacman -Syu --needed",
        "pkgs": {"qemu": "qemu-desktop", "ovmf": "edk2-ovmf", "mtools": "mtools"},
        "grub_update": "sudo grub-mkconfig -o /boot/grub/grub.cfg",
        "initramfs_update": "sudo mkinitcpio -P"
    },

    "debian": {
        "cmd": "apt update && apt install -y",
        "pkgs": {"qemu": "qemu-system-x86 qemu-utils", "ovmf": "ovmf", "mtools": "mtools"},
        "grub_update": "sudo update-grub",
        "initramfs_update": "sudo update-initramfs -u"
    },
    "ubuntu": {
        "cmd": "apt update && apt install -y",
        "pkgs": {"qemu": "qemu-system-x86 qemu-utils", "ovmf": "ovmf", "mtools": "mtools"},
        "grub_update": "sudo update-grub",
        "initramfs_update": "sudo update-initramfs -u"
    },
    "pop": {
        "cmd": "apt update && apt install -y",
        "pkgs": {"qemu": "qemu-system-x86 qemu-utils", "ovmf": "ovmf", "mtools": "mtools"},
        "grub_update": "Pop!_OS uses systemd-boot, please update kernel parameters manually.",
        "initramfs_update": "sudo update-initramfs -u"
    },
    "fedora": {
        "cmd": "dnf install -y",
        "pkgs": {"qemu": "qemu-kvm", "ovmf": "edk2-ovmf", "mtools": "mtools"},
        "grub_update": "sudo grub2-mkconfig -o /boot/efi/EFI/fedora/grub.cfg",
        "initramfs_update": "sudo dracut -f --kver `uname -r`"
    },
}
