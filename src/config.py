# --- Configuration (System-Wide) ---
CONFIG = {
    # --- General Paths ---
    "ASSETS_DIR": "assets",

    # --- Linux VM Settings ---
    "VMS_DIR_LINUX": "vms_linux",
    "VM_MEM": "4096M",
    "VM_CPU": "2",
    "BASE_DISK_SIZE": "20",
    "QEMU_BINARY": "qemu-system-x86_64",
    "UEFI_CODE": "/usr/share/edk2/x64/OVMF_CODE.4m.fd",
    "UEFI_VARS_TEMPLATE": "/usr/share/edk2/x64/OVMF_VARS.4m.fd",
    "QEMU_DISPLAY": ["-display", "gtk,gl=on,show-cursor=on,grab-on-hover=on"],
    "SHARED_DIR_MOUNT_TAG": "host_share",

    # --- macOS VM Settings ---
    "VMS_DIR_MACOS": "vms_macos",
    # --- The following paths are now discovered at runtime ---
    "MACOS_UEFI_CODE": "", 
    "MACOS_UEFI_VARS": "",
    "OPENCORE_IMG": "assets/OpenCore.qcow2",
    "GENSMBIOS_SCRIPT": "assets/GenSMBIOS/GenSMBIOS.py",
    "FETCHMACOS_SCRIPT": "assets/fetch-macOS-v2.py",
    "OSK_KEY": "ourhardworkbythesewordsguardedpleasedontsteal(c)AppleComputerInc",
}

# --- Distro "Knowledge Base" for Dependency Checking ---
DISTRO_INFO = {
    "arch": {"cmd": "pacman -Syu --needed", "pkgs": {"qemu": "qemu-desktop", "ovmf": "edk2-ovmf", "mtools": "mtools"}, "grub_update": "sudo grub-mkconfig -o /boot/grub/grub.cfg", "initramfs_update": "sudo mkinitcpio -P"},
    "manjaro": {"cmd": "pacman -Syu --needed", "pkgs": {"qemu": "qemu-desktop", "ovmf": "edk2-ovmf", "mtools": "mtools"}, "grub_update": "sudo update-grub", "initramfs_update": "sudo mkinitcpio -P"},
    "debian": {"cmd": "apt update && apt install -y", "pkgs": {"qemu": "qemu-system-x86 qemu-utils", "ovmf": "ovmf", "mtools": "mtools"}, "grub_update": "sudo update-grub", "initramfs_update": "sudo update-initramfs -u"},
    "ubuntu": {"cmd": "apt update && apt install -y", "pkgs": {"qemu": "qemu-system-x86 qemu-utils", "ovmf": "ovmf", "mtools": "mtools"}, "grub_update": "sudo update-grub", "initramfs_update": "sudo update-initramfs -u"},
    "pop": {"cmd": "apt update && apt install -y", "pkgs": {"qemu": "qemu-system-x86 qemu-utils", "ovmf": "ovmf", "mtools": "mtools"}, "grub_update": "Pop!_OS uses systemd-boot, please update kernel parameters manually.", "initramfs_update": "sudo update-initramfs -u"},
    "fedora": {"cmd": "dnf install -y", "pkgs": {"qemu": "qemu-kvm", "ovmf": "edk2-ovmf", "mtools": "mtools"}, "grub_update": "sudo grub2-mkconfig -o /boot/efi/EFI/fedora/grub.cfg", "initramfs_update": "sudo dracut -f --kver `uname -r`"},
}
