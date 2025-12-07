# USB Passthrough Cursor Fix Documentation

## Overview

This document provides information about the USB passthrough cursor fix feature in Glint, which addresses the common issue of invisible mouse cursors when using USB controller passthrough in Linux VMs.

## Problem Description

When passing through a USB controller to a Linux VM, users often encounter an issue where the mouse cursor becomes invisible within the VM. This happens because:

1. The default display backend (GTK) may not properly handle cursor rendering when USB input devices are passed through
2. The VM loses access to the host's cursor rendering capabilities
3. The guest OS may not have appropriate drivers to render its own cursor

## Solution

The USB Passthrough Cursor Fix module provides multiple strategies to resolve this issue:

### Display Backend Selection

The module can automatically select the optimal display backend based on the passthrough configuration:

- **SDL Backend**: Recommended for most USB passthrough scenarios
- **GTK Backend**: Good compatibility with standard configurations
- **VNC Backend**: Remote access friendly, useful for headless setups
- **SPICE Backend**: Advanced features and better integration

### VGA Adapter Selection

Different VGA adapters can be used to improve cursor visibility:

- **VirtIO GPU**: Best performance, recommended for most cases
- **Standard VGA**: Maximum compatibility for problematic setups
- **QXL**: Optimized for SPICE display backend
- **Cirrus**: Legacy compatibility for older systems

### Input Device Configuration

The module can configure input devices to improve cursor tracking:

- **USB Tablet**: Provides absolute positioning for better cursor tracking
- **VirtIO Input**: High-performance input devices when not conflicting with passthrough
- **Evdev Passthrough**: Direct input device passthrough for seamless experience

## Usage

The cursor fix is automatically applied when USB passthrough is detected. Users are presented with several options:

1. **Recommended Fix**: SDL display backend with VirtIO GPU (best for most cases)
2. **Safe Mode**: GTK display backend with Standard VGA (maximum compatibility)
3. **Performance Mode**: SDL with VirtIO and OpenGL acceleration (best performance)
4. **Compatibility Mode**: VNC with Cirrus VGA (works with problematic hardware)
5. **Custom Configuration**: User-defined settings for advanced users

## Troubleshooting

If you still experience cursor issues after applying the fix:

1. **Invisible Cursor**
   - Try a different display backend (SDL is recommended)
   - Enable USB tablet device for absolute positioning
   - Disable OpenGL if experiencing issues

2. **Cursor Lag or Jumping**
   - Switch to GTK display backend
   - Disable VirtIO input devices
   - Try Standard VGA adapter

3. **No Cursor Movement**
   - Ensure USB tablet is enabled
   - Check if USB controller is properly passed through
   - Verify VFIO permissions

4. **Display Issues**
   - Try different VGA adapters (VirtIO → STD → QXL)
   - Disable OpenGL acceleration
   - Use VNC for remote troubleshooting

## Advanced Configuration

Advanced users can create custom cursor fix configurations by selecting:

- Display backend (SDL, GTK, VNC, SPICE)
- VGA adapter (VirtIO, STD, QXL, Cirrus)
- OpenGL acceleration (on/off)
- USB tablet for absolute positioning (on/off)
- VirtIO input devices (on/off)

## Implementation Details

The cursor fix is implemented in the `src/linux_vm/passthrough/cursor_fix.py` module, which:

1. Detects when USB passthrough is being used
2. Analyzes the passthrough configuration to determine risk level
3. Offers appropriate cursor fix strategies
4. Modifies the QEMU command line to apply the selected fix

## Error Handling

The cursor fix module uses Glint's comprehensive error handling system to provide:

- Clear error messages with error codes
- Actionable troubleshooting suggestions
- Graceful fallback mechanisms
- Detailed logging for debugging

### Common Error Codes

- **GLINT-E420**: USB controller passthrough cursor issue
- **GLINT-E421**: Display backend configuration error
- **GLINT-E422**: VGA adapter compatibility issue
- **GLINT-E423**: Input device configuration error

## Future Improvements

Planned improvements for the cursor fix feature:

1. Automatic detection of optimal configuration based on hardware
2. Better integration with guest OS for seamless cursor handling
3. Support for specialized input devices (graphics tablets, etc.)
4. Improved diagnostics and self-healing capabilities