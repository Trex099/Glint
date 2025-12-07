# Made by trex099
# https://github.com/Trex099/Glint
"""
Networking Management Module for Linux VMs

This module provides enhanced networking capabilities including:
- Bridge networking with VLAN support
- Multiple network interfaces
- Network isolation and security
- Custom network configurations
- Network monitoring and troubleshooting
"""

from .bridge import (
    BridgeManager,
    BridgeConfig,
    BridgeInterface,
    BridgeStats,
    BridgeType,
    BridgeState,
    VLANConfig,
    get_bridge_manager,
    create_bridge,
    delete_bridge,
    add_interface_to_bridge,
    remove_interface_from_bridge,
    list_bridges,
    monitor_bridge,
    troubleshoot_bridge,
    display_bridge_info
)

from .bridge_ui import (
    BridgeNetworkingUI,
    get_bridge_ui,
    show_bridge_menu
)

__version__ = "1.0.0"

__all__ = [
    'BridgeManager',
    'BridgeConfig',
    'BridgeInterface',
    'BridgeStats',
    'BridgeType',
    'BridgeState',
    'VLANConfig',
    'get_bridge_manager',
    'create_bridge',
    'delete_bridge',
    'add_interface_to_bridge',
    'remove_interface_from_bridge',
    'list_bridges',
    'monitor_bridge',
    'troubleshoot_bridge',
    'display_bridge_info',
    'BridgeNetworkingUI',
    'get_bridge_ui',
    'show_bridge_menu'
]