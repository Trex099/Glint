<p align="center">
  <img src="https://raw.githubusercontent.com/Trex099/Glint/main/assets/Showcase/LOGO.png" alt="Glint Logo" width="250">
</p>

# Glint

A VM manager for macOS, Windows, and Linux. It handles the annoying parts of QEMU so you don't have to.

If you've ever tried to get a macOS VM working on Linux, you know the pain: OpenCore configs, SMBIOS generation, broken display output, and hours of googling. Glint does all of that automatically.

---

## What's in the box

**VM Types:**
- **macOS** - Auto-generates OpenCore, SMBIOS, valid serials. Factory reset without reinstalling.
- **Windows** - Downloads VirtIO drivers, handles UEFI setup.
- **Linux** - GPU passthrough with VFIO, disposable sessions.

**Storage stuff:**
- Storage pools to organize your VMs
- LUKS encryption for disk images (via qemu-img)
- Branching snapshots with metadata/tags
- Live disk resize while VM is running (QMP)
- Backup scheduling with compression

**Other features:**
- GPU/USB/NVMe passthrough with host setup wizard
- Privacy mode (routes traffic through Tor)
- SFTP file transfer to/from running VMs
- Session management that cleans up after crashes
- Ubuntu USB mouse fix utility

---

## Quick start

```bash
git clone https://github.com/Trex099/Glint.git
cd Glint
python3 glint.py
```

First run will check for dependencies (QEMU, OVMF, guestfs-tools) and offer to install them.

Put your installer files in the Glint directory:
- macOS: `.iso` or `BaseSystem.dmg`
- Windows: `.iso` (grab `virtio-win.iso` too)
- Linux: any `.iso`

---

## The "Nuke" system

Glint uses an overlay model. Your base OS image (`base.qcow2` or `macOS.qcow2`) stays untouched. Session data goes in overlays.

**Regenerate Identity** - Rebuilds OpenCore with new SMBIOS/MAC/serials. Fixes iMessage issues.

**Factory Reset** - Wipes user accounts via guestfs. Back to Setup Assistant, no reinstall needed.

Neither option touches your base image.

---

## GPU Passthrough

The host setup wizard handles most of the IOMMU configuration:
- Adds kernel parameters to GRUB
- Sets up VFIO modules
- Updates initramfs

For macOS iGPU passthrough, there's a menu to apply framebuffer patches to OpenCore.

It's not magic though - edge cases might still need manual tweaking.

---

## File Transfer

Uses SSH/SFTP. You'll need to enable the SSH server on the guest first:

```bash
# macOS
sudo systemsetup -setremotelogin on

# Linux
sudo apt install openssh-server  # or equivalent

# Windows
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
```

Then use the transfer menu in Glint.

---

## Privacy Mode

Routes VM traffic through Tor. Requires Tor installed on host. Useful if you need a different exit IP than your machine.

---

## Credits

Built on top of:
- QEMU
- OpenCore
- OSX-KVM project
- GenSMBIOS

---

## Legal

Running macOS on non-Apple hardware violates Apple's EULA. This project is for educational purposes. You're responsible for compliance with software licenses.

---

## License

MIT
