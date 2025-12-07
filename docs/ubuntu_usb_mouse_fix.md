# Ubuntu USB Mouse Fix Guide

## Overview

This guide addresses a common issue with Ubuntu VMs where USB controller passthrough works but physical USB mice don't function properly, while trackpads continue to work normally.

## The Problem

When using USB controller passthrough in Ubuntu VMs, you may encounter:
- ✅ Trackpad/touchpad works normally
- ❌ Physical USB mouse doesn't respond or move cursor
- ❌ USB mouse clicks don't register
- ❌ Mouse wheel doesn't scroll

This happens because Ubuntu's input handling in virtualized environments requires specific USB controller configurations and driver setups.

## Quick Fix

### Automatic Fix (Recommended)

Run the quick fix script from your Ubuntu VM:

```bash
python3 fix_usb_mouse.py
```

This will:
1. Detect if you're running Ubuntu in a VM
2. Diagnose common USB mouse issues
3. Apply automatic fixes
4. Guide you through any manual steps needed

### Manual QEMU Configuration

If you're launching VMs manually, add these QEMU arguments for Ubuntu guests:

```bash
# Enhanced USB controller setup for Ubuntu
-device ich9-usb-ehci1,id=usb \
-device ich9-usb-uhci1,masterbus=usb.0,firstport=0 \
-device ich9-usb-uhci2,masterbus=usb.0,firstport=2 \
-device ich9-usb-uhci3,masterbus=usb.0,firstport=4 \
-device usb-mouse,bus=usb.0 \
-global usb-mouse.usb_version=2 \
-global usb-tablet.usb_version=2
```

## Detailed Troubleshooting

### Step 1: Verify System Requirements

Check if you're running Ubuntu in a VM:
```bash
# Check OS
cat /etc/os-release | grep ubuntu

# Check virtualization
systemd-detect-virt
```

### Step 2: Install Required Packages

```bash
sudo apt update
sudo apt install -y \
    spice-vdagent \
    qemu-guest-agent \
    xserver-xorg-input-evdev \
    xserver-xorg-input-mouse \
    xserver-xorg-input-synaptics
```

### Step 3: Load USB Kernel Modules

```bash
sudo modprobe usbhid
sudo modprobe hid_generic
sudo modprobe hid_apple      # For Apple mice
sudo modprobe hid_logitech_dj # For Logitech mice
sudo modprobe hid_microsoft   # For Microsoft mice
```

### Step 4: Check Input Devices

```bash
# List all input devices
cat /proc/bus/input/devices

# Look for mouse entries
cat /proc/bus/input/devices | grep -A5 -i mouse

# Test mouse input (requires root)
sudo evtest
# Select your mouse device from the list
```

### Step 5: Configure Display Server

If using Wayland (which can cause input issues):

```bash
# Check current display server
echo $XDG_SESSION_TYPE

# Switch to X11 (recommended for USB passthrough)
sudo nano /etc/gdm3/custom.conf
```

Add under `[daemon]` section:
```ini
[daemon]
WaylandEnable=false
```

Then restart:
```bash
sudo systemctl restart gdm3
```

### Step 6: Create USB Device Rules

Create udev rules for better USB device handling:

```bash
sudo nano /etc/udev/rules.d/99-usb-mouse-fix.rules
```

Add:
```
# USB mouse fix for passthrough
SUBSYSTEM=="usb", ATTRS{idVendor}=="*", ATTRS{idProduct}=="*", MODE="0666"
KERNEL=="event*", SUBSYSTEM=="input", MODE="0666"
```

Reload rules:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Step 7: Restart Input Services

```bash
sudo systemctl restart systemd-logind
sudo systemctl restart gdm3
```

## Advanced Diagnostics

### Using the Diagnostic Tool

For detailed diagnosis, run:

```bash
python3 -c "
from src.linux_vm.ubuntu_usb_mouse_fix import UbuntuUSBMouseFix
fix = UbuntuUSBMouseFix()
diagnosis = fix.diagnose_mouse_issue()
fix.display_diagnosis_results(diagnosis)
"
```

### Manual Hardware Check

```bash
# Check USB controllers
lspci | grep -i usb

# Check USB devices
lsusb

# Check input event devices
ls -la /dev/input/

# Monitor input events
sudo cat /dev/input/mice  # Should show data when moving mouse
```

### QEMU Guest Agent

Ensure QEMU guest agent is running:

```bash
sudo systemctl status qemu-guest-agent
sudo systemctl enable qemu-guest-agent
sudo systemctl start qemu-guest-agent
```

## Common Issues and Solutions

### Issue: Mouse Detected but No Movement

**Solution:**
```bash
# Check if mouse is bound to correct driver
lsusb -t

# Rebind USB device
echo "1-1" | sudo tee /sys/bus/usb/drivers/usb/unbind
echo "1-1" | sudo tee /sys/bus/usb/drivers/usb/bind
```

### Issue: Mouse Works in Terminal but Not in GUI

**Solution:**
```bash
# Restart display manager
sudo systemctl restart gdm3

# Or switch to different display manager
sudo dpkg-reconfigure gdm3
```

### Issue: Only Some Mouse Buttons Work

**Solution:**
```bash
# Install additional input drivers
sudo apt install xserver-xorg-input-all

# Configure X11 input
sudo nano /etc/X11/xorg.conf.d/40-libinput.conf
```

Add:
```
Section "InputClass"
    Identifier "libinput pointer catchall"
    MatchIsPointer "on"
    MatchDevicePath "/dev/input/event*"
    Driver "libinput"
EndSection
```

### Issue: Mouse Lag or Stuttering

**Solution:**
```bash
# Adjust mouse acceleration
xinput list  # Find your mouse device
xinput set-prop <device-id> "libinput Accel Speed" 0

# Disable mouse acceleration
xinput set-prop <device-id> "libinput Accel Profile Enabled" 0, 1
```

## Integration with Glint

When using Glint's VM management system, the USB mouse fix is automatically integrated:

1. **Automatic Detection**: Glint detects Ubuntu VMs with USB passthrough
2. **Smart Prompts**: Offers to apply Ubuntu-specific fixes
3. **QEMU Integration**: Automatically adds proper USB controller arguments
4. **Diagnostic Tools**: Provides detailed troubleshooting when needed

### Using with Glint

```bash
# Launch Glint
python3 glint.py

# When creating or starting an Ubuntu VM with USB passthrough:
# - Glint will detect the Ubuntu + USB passthrough combination
# - It will offer to apply automatic fixes
# - Choose "Apply Ubuntu USB mouse fixes" when prompted
```

## Prevention

To avoid USB mouse issues in future Ubuntu VMs:

1. **Use the Ubuntu USB Fix profile** in Glint's cursor fix options
2. **Install guest tools early** in the Ubuntu installation process
3. **Prefer X11 over Wayland** for VMs with USB passthrough
4. **Keep Ubuntu updated** for latest input driver improvements

## Troubleshooting Checklist

- [ ] Confirmed running Ubuntu in VM
- [ ] USB controller passthrough is working
- [ ] Required packages installed
- [ ] USB kernel modules loaded
- [ ] Using X11 (not Wayland)
- [ ] QEMU guest agent running
- [ ] Input services restarted
- [ ] System rebooted after changes

## Getting Help

If the automatic fixes don't resolve your issue:

1. Run the diagnostic tool and save the output
2. Check the system logs: `journalctl -f`
3. Test with a different USB mouse if available
4. Consider using evdev passthrough as an alternative
5. Report the issue with diagnostic information

## Related Documentation

- [USB Passthrough Guide](usb_passthrough_cursor_fix.md)
- [Ubuntu Troubleshooting](ubuntu_troubleshooting.md)
- [VFIO Setup Guide](../README.md#vfio-setup)