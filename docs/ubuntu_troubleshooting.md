# Ubuntu Troubleshooting Guide for Glint

This guide helps Ubuntu users resolve common issues when running Glint VM Manager.

## Quick Start Checklist

Before running Glint on Ubuntu, ensure:

1. **System is up to date**:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

2. **Python 3 is installed** (Ubuntu 20.04+ comes with Python 3.8+):
   ```bash
   python3 --version
   ```

3. **You have sudo privileges** for package installation

4. **Virtualization is enabled** in BIOS/UEFI

## Common Issues and Solutions

### 1. Dependency Installation Failures

#### Issue: `apt update` fails
**Solution:**
```bash
# Fix broken packages
sudo apt --fix-broken install

# Reset package lists
sudo rm -rf /var/lib/apt/lists/*
sudo apt update
```

#### Issue: Package not found errors
**Solutions:**
- Enable universe repository:
  ```bash
  sudo add-apt-repository universe
  sudo apt update
  ```
- For older Ubuntu versions, some packages may need backports:
  ```bash
  sudo add-apt-repository "deb http://archive.ubuntu.com/ubuntu $(lsb_release -sc)-backports main restricted universe multiverse"
  ```

### 2. QEMU/KVM Issues

#### Issue: "KVM not available" or "/dev/kvm not accessible"
**Solutions:**

1. **Check CPU virtualization support**:
   ```bash
   egrep -c '(vmx|svm)' /proc/cpuinfo
   ```
   If this returns 0, virtualization is not supported or not enabled in BIOS.

2. **Install KVM packages**:
   ```bash
   sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils
   ```

3. **Add user to required groups**:
   ```bash
   sudo usermod -aG kvm $USER
   sudo usermod -aG libvirt $USER
   ```

4. **Fix /dev/kvm permissions**:
   ```bash
   sudo chmod 666 /dev/kvm
   ```

5. **Restart and verify**:
   ```bash
   # Log out and back in, then check:
   groups
   ls -la /dev/kvm
   ```

#### Issue: OVMF/UEFI firmware not found
**Solution:**
```bash
sudo apt install ovmf
# Verify installation:
ls /usr/share/OVMF/
```

### 3. Python Package Issues

#### Issue: Python packages fail to install via apt
**Solutions:**

1. **Use pip as fallback**:
   ```bash
   pip3 install --user rich questionary pexpect requests tqdm
   ```

2. **For system-wide installation**:
   ```bash
   sudo apt install python3-pip
   sudo pip3 install rich questionary pexpect requests tqdm
   ```

#### Issue: "Module not found" errors after installation
**Solution:**
```bash
# Check Python path
python3 -c "import sys; print('\n'.join(sys.path))"

# Add user site-packages to path if needed
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 4. Ubuntu Version-Specific Issues

#### Ubuntu 18.04 (Bionic Beaver)
- **Issue**: Some packages may be outdated
- **Solution**: Consider upgrading to Ubuntu 20.04+ or use backports:
  ```bash
  sudo add-apt-repository "deb http://archive.ubuntu.com/ubuntu bionic-backports main restricted universe multiverse"
  sudo apt update
  ```

#### Ubuntu 22.04+ (Jammy and newer)
- **Issue**: Snap packages may conflict with apt packages
- **Solution**: Glint automatically prefers apt packages for better integration

### 5. WSL (Windows Subsystem for Linux) Issues

#### Issue: Running Glint in WSL
**Limitations:**
- Hardware virtualization is not available in WSL1
- WSL2 has limited virtualization support
- GPU passthrough is not supported

**Recommendation**: Use Glint on a native Ubuntu installation for full functionality.

### 6. Permission and Security Issues

#### Issue: "Operation not permitted" errors
**Solutions:**

1. **Check AppArmor/SELinux**:
   ```bash
   # Disable AppArmor for libvirt (if needed)
   sudo aa-disable /usr/sbin/libvirtd
   ```

2. **Verify user permissions**:
   ```bash
   # Check group membership
   groups $USER
   
   # Should include: kvm, libvirt
   ```

#### Issue: Secure Boot interference
**Solution:**
If Secure Boot is enabled, you may need to:
1. Disable Secure Boot in BIOS/UEFI, OR
2. Sign the KVM modules (advanced)

### 7. Network Issues

#### Issue: VM networking problems
**Solutions:**

1. **Install bridge utilities**:
   ```bash
   sudo apt install bridge-utils
   ```

2. **Configure default network**:
   ```bash
   sudo virsh net-start default
   sudo virsh net-autostart default
   ```

### 8. Storage and Disk Issues

#### Issue: Insufficient disk space
**Solution:**
```bash
# Check available space
df -h

# Clean package cache
sudo apt autoclean
sudo apt autoremove

# Clean snap packages (if using snaps)
sudo snap list --all | awk '/disabled/{print $1, $3}' | while read snapname revision; do sudo snap remove "$snapname" --revision="$revision"; done
```

#### Issue: Permission denied when creating VM directories
**Solution:**
```bash
# Ensure proper ownership
sudo chown -R $USER:$USER ~/glint-vm-manager/
chmod -R 755 ~/glint-vm-manager/
```

## Advanced Troubleshooting

### Enable Debug Logging
Add this to your shell profile for detailed logging:
```bash
export LIBVIRT_DEBUG=1
export QEMU_LOG=all
```

### Check System Logs
```bash
# Check for virtualization-related errors
sudo dmesg | grep -i kvm
sudo journalctl -u libvirtd

# Check for permission issues
sudo tail -f /var/log/auth.log
```

### Verify Hardware Support
```bash
# Check virtualization support
sudo apt install cpu-checker
sudo kvm-ok

# Check IOMMU support (for passthrough)
sudo dmesg | grep -i iommu
```

## Getting Help

If you're still experiencing issues:

1. **Check the GitHub Issues**: [Glint Issues](https://github.com/Trex099/Glint/issues)
2. **Provide system information**:
   ```bash
   # Gather system info for bug reports
   echo "=== System Information ==="
   lsb_release -a
   uname -a
   python3 --version
   
   echo "=== Virtualization Support ==="
   egrep -c '(vmx|svm)' /proc/cpuinfo
   ls -la /dev/kvm
   
   echo "=== Installed Packages ==="
   dpkg -l | grep -E "(qemu|ovmf|libvirt|python3-)"
   
   echo "=== User Groups ==="
   groups $USER
   ```

3. **Include error messages** and the output from the system information commands above

## Prevention Tips

1. **Keep Ubuntu updated**: `sudo apt update && sudo apt upgrade` regularly
2. **Don't mix package managers**: Prefer apt over snap for Glint dependencies
3. **Use LTS versions**: Ubuntu 20.04 or 22.04 LTS for best stability
4. **Regular cleanup**: Remove unused packages with `sudo apt autoremove`
5. **Monitor disk space**: VMs can consume significant storage

## Ubuntu Derivatives

This guide also applies to Ubuntu-based distributions:
- Pop!_OS
- Linux Mint
- elementary OS
- Zorin OS
- Kubuntu, Xubuntu, Lubuntu
- Ubuntu MATE, Ubuntu Budgie

Most solutions work identically, but package names or locations may vary slightly.