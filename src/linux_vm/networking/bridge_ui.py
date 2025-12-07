# Made by trex099
# https://github.com/Trex099/Glint
"""
Bridge Networking UI Integration for Linux VM Management

This module provides user interface components for bridge networking management,
integrating seamlessly with the existing Glint TUI system.
"""

import os
import sys
import questionary
from typing import List

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
# from rich.columns import Columns
# from rich.text import Text

from core_utils import (
    print_header, print_info, print_success, print_warning, print_error, 
    clear_screen, wait_for_enter
)
from linux_vm.networking.bridge import (
    get_bridge_manager, BridgeType, VLANConfig
)
from linux_vm.error_handling import get_error_handler

console = Console()


class BridgeNetworkingUI:
    """
    User Interface for Bridge Networking Management
    
    Provides a comprehensive TUI for managing bridge networks with
    visual consistency matching the existing Glint interface.
    """
    
    def __init__(self):
        """Initialize the Bridge Networking UI"""
        self.bridge_manager = get_bridge_manager()
        self.error_handler = get_error_handler()
    
    def show_bridge_menu(self):
        """Display the main bridge networking menu"""
        while True:
            clear_screen()
            self._display_bridge_dashboard()
            
            choice = questionary.select(
                "Bridge Networking Management",
                choices=[
                    questionary.Choice("🌉 Create New Bridge", value="create"),
                    questionary.Choice("🗑️  Delete Bridge", value="delete"),
                    questionary.Separator("--- Interface Management ---"),
                    questionary.Choice("🔗 Add Interface to Bridge", value="add_interface"),
                    questionary.Choice("❌ Remove Interface from Bridge", value="remove_interface"),
                    questionary.Separator("--- VLAN Configuration ---"),
                    questionary.Choice("🏷️  Configure VLAN", value="configure_vlan"),
                    questionary.Choice("📋 List VLANs", value="list_vlans"),
                    questionary.Separator("--- Monitoring & Troubleshooting ---"),
                    questionary.Choice("📊 Monitor Bridge", value="monitor"),
                    questionary.Choice("🔍 Troubleshoot Bridge", value="troubleshoot"),
                    questionary.Choice("📈 Show Bridge Statistics", value="statistics"),
                    questionary.Separator("--- Information ---"),
                    questionary.Choice("ℹ️  Bridge Information", value="info"),
                    questionary.Choice("📜 List All Bridges", value="list"),
                    questionary.Separator(),
                    questionary.Choice("🔙 Back to Network Menu", value="back")
                ],
                use_indicator=True
            ).ask()
            
            if choice == "back" or choice is None:
                break
            
            try:
                self._handle_menu_choice(choice)
            except Exception as e:
                self.error_handler.handle_error(e)
                wait_for_enter()
    
    def _display_bridge_dashboard(self):
        """Display the bridge networking dashboard"""
        print_header("🌉 Bridge Networking Dashboard")
        
        bridges = self.bridge_manager.list_bridges()
        
        if not bridges:
            console.print(Panel(
                "[yellow]No bridges configured[/]\n\n"
                "Create your first bridge to get started with advanced networking!",
                title="[blue]Bridge Status[/]",
                border_style="blue"
            ))
            return
        
        # Create bridge overview table
        bridge_table = Table(title="Bridge Overview")
        bridge_table.add_column("Name", style="cyan", no_wrap=True)
        bridge_table.add_column("Type", style="green")
        bridge_table.add_column("State", style="yellow")
        bridge_table.add_column("Interfaces", style="magenta")
        bridge_table.add_column("IP Address", style="blue")
        bridge_table.add_column("VLAN", style="red")
        
        for name, config in bridges.items():
            # Get bridge state
            stats = self.bridge_manager.get_bridge_stats(name)
            state = stats.state.value.upper() if stats else "UNKNOWN"
            
            # Get interface count
            interface_count = len(config.interfaces)
            interface_text = f"{interface_count} interface{'s' if interface_count != 1 else ''}"
            
            # Get IP info
            ip_info = config.ip_address if config.ip_address else "None"
            if config.ip_address and config.netmask:
                ip_info = f"{config.ip_address}/{config.netmask}"
            
            # Check for VLAN configuration
            vlan_info = "Enabled" if config.vlan_filtering else "Disabled"
            
            bridge_table.add_row(
                name,
                config.bridge_type.value.upper(),
                state,
                interface_text,
                ip_info,
                vlan_info
            )
        
        console.print(bridge_table)
        console.print()
    
    def _handle_menu_choice(self, choice: str):
        """Handle menu choice selection"""
        if choice == "create":
            self._create_bridge_wizard()
        elif choice == "delete":
            self._delete_bridge_wizard()
        elif choice == "add_interface":
            self._add_interface_wizard()
        elif choice == "remove_interface":
            self._remove_interface_wizard()
        elif choice == "configure_vlan":
            self._configure_vlan_wizard()
        elif choice == "list_vlans":
            self._list_vlans()
        elif choice == "monitor":
            self._monitor_bridge_wizard()
        elif choice == "troubleshoot":
            self._troubleshoot_bridge_wizard()
        elif choice == "statistics":
            self._show_bridge_statistics()
        elif choice == "info":
            self._show_bridge_info()
        elif choice == "list":
            self._list_all_bridges()
    
    def _create_bridge_wizard(self):
        """Wizard for creating a new bridge"""
        clear_screen()
        print_header("🌉 Create New Bridge")
        
        # Bridge name
        bridge_name = questionary.text(
            "Enter bridge name:",
            validate=lambda x: len(x) > 0 and len(x) <= 15 and x.replace('-', '').replace('_', '').isalnum()
        ).ask()
        
        if not bridge_name:
            return
        
        # Bridge type
        bridge_type = questionary.select(
            "Select bridge type:",
            choices=[
                questionary.Choice("Standard Linux Bridge (Recommended)", value=BridgeType.STANDARD),
                questionary.Choice("Open vSwitch Bridge (Advanced)", value=BridgeType.OVS)
            ]
        ).ask()
        
        # Description
        description = questionary.text(
            "Enter description (optional):",
            default=""
        ).ask()
        
        # Network configuration
        configure_ip = questionary.confirm("Configure IP address for bridge?").ask()
        
        ip_address = None
        netmask = None
        if configure_ip:
            ip_address = questionary.text(
                "Enter IP address:",
                validate=lambda x: self._validate_ip_address(x) if x else True
            ).ask()
            
            if ip_address:
                netmask = questionary.text(
                    "Enter netmask (e.g., 24 for /24):",
                    validate=lambda x: x.isdigit() and 1 <= int(x) <= 32 if x else True
                ).ask()
        
        # VLAN filtering
        vlan_filtering = questionary.confirm("Enable VLAN filtering?").ask()
        
        # Initial interfaces
        add_interfaces = questionary.confirm("Add interfaces to bridge now?").ask()
        interfaces = []
        
        if add_interfaces:
            interfaces = self._select_interfaces_wizard()
        
        # Confirmation
        console.print("\n[bold]Bridge Configuration Summary:[/]")
        console.print(f"Name: [cyan]{bridge_name}[/]")
        console.print(f"Type: [green]{bridge_type.value}[/]")
        if description:
            console.print(f"Description: [yellow]{description}[/]")
        if ip_address:
            console.print(f"IP Address: [blue]{ip_address}/{netmask}[/]")
        console.print(f"VLAN Filtering: [magenta]{'Enabled' if vlan_filtering else 'Disabled'}[/]")
        if interfaces:
            console.print(f"Initial Interfaces: [white]{', '.join(interfaces)}[/]")
        
        if not questionary.confirm("\nCreate bridge with these settings?").ask():
            return
        
        # Create the bridge
        try:
            success = self.bridge_manager.create_bridge(
                name=bridge_name,
                bridge_type=bridge_type,
                interfaces=interfaces,
                ip_address=ip_address,
                netmask=netmask,
                vlan_filtering=vlan_filtering,
                description=description
            )
            
            if success:
                print_success(f"✅ Successfully created bridge '{bridge_name}'")
                
                # Show next steps
                console.print("\n[bold green]Next Steps:[/]")
                console.print("• Add more interfaces if needed")
                console.print("• Configure VLANs if required")
                console.print("• Attach VMs to this bridge")
                
            else:
                print_error("❌ Failed to create bridge")
                
        except Exception as e:
            self.error_handler.handle_error(e)
        
        wait_for_enter()
    
    def _delete_bridge_wizard(self):
        """Wizard for deleting a bridge"""
        clear_screen()
        print_header("🗑️ Delete Bridge")
        
        bridges = self.bridge_manager.list_bridges()
        if not bridges:
            print_warning("No bridges available to delete")
            wait_for_enter()
            return
        
        # Select bridge to delete
        bridge_choices = [
            questionary.Choice(f"{name} ({config.bridge_type.value})", value=name)
            for name, config in bridges.items()
        ]
        
        bridge_name = questionary.select(
            "Select bridge to delete:",
            choices=bridge_choices
        ).ask()
        
        if not bridge_name:
            return
        
        # Show bridge information
        config = bridges[bridge_name]
        interfaces = self.bridge_manager.get_bridge_interfaces(bridge_name)
        
        console.print(f"\n[bold red]Bridge to Delete:[/] [cyan]{bridge_name}[/]")
        console.print(f"Type: [green]{config.bridge_type.value}[/]")
        if interfaces:
            console.print(f"Attached Interfaces: [yellow]{', '.join(interfaces)}[/]")
            console.print("[bold red]Warning:[/] All interfaces will be detached!")
        
        # Confirmation
        if not questionary.confirm(f"\nAre you sure you want to delete bridge '{bridge_name}'?").ask():
            return
        
        # Force deletion if interfaces are attached
        force = len(interfaces) > 0
        
        try:
            success = self.bridge_manager.delete_bridge(bridge_name, force=force)
            
            if success:
                print_success(f"✅ Successfully deleted bridge '{bridge_name}'")
            else:
                print_error("❌ Failed to delete bridge")
                
        except Exception as e:
            self.error_handler.handle_error(e)
        
        wait_for_enter()
    
    def _add_interface_wizard(self):
        """Wizard for adding interface to bridge"""
        clear_screen()
        print_header("🔗 Add Interface to Bridge")
        
        bridges = self.bridge_manager.list_bridges()
        if not bridges:
            print_warning("No bridges available")
            wait_for_enter()
            return
        
        # Select bridge
        bridge_choices = [
            questionary.Choice(f"{name} ({config.bridge_type.value})", value=name)
            for name, config in bridges.items()
        ]
        
        bridge_name = questionary.select(
            "Select bridge:",
            choices=bridge_choices
        ).ask()
        
        if not bridge_name:
            return
        
        # Get available interfaces
        available_interfaces = self._get_available_interfaces()
        if not available_interfaces:
            print_warning("No available interfaces found")
            wait_for_enter()
            return
        
        # Select interface
        interface_name = questionary.select(
            "Select interface to add:",
            choices=available_interfaces
        ).ask()
        
        if not interface_name:
            return
        
        # VLAN configuration
        configure_vlan = questionary.confirm("Configure VLAN for this interface?").ask()
        vlan_config = None
        
        if configure_vlan:
            vlan_id = questionary.text(
                "Enter VLAN ID (1-4094):",
                validate=lambda x: x.isdigit() and 1 <= int(x) <= 4094
            ).ask()
            
            if vlan_id:
                vlan_name = questionary.text(
                    "Enter VLAN name:",
                    default=f"vlan{vlan_id}"
                ).ask()
                
                tagged = questionary.confirm("Tagged VLAN?", default=True).ask()
                
                vlan_config = VLANConfig(
                    vlan_id=int(vlan_id),
                    name=vlan_name,
                    tagged=tagged
                )
        
        # Add interface
        try:
            success = self.bridge_manager.add_interface_to_bridge(
                bridge_name, interface_name, vlan_config
            )
            
            if success:
                print_success(f"✅ Successfully added interface '{interface_name}' to bridge '{bridge_name}'")
                if vlan_config:
                    print_info(f"VLAN {vlan_config.vlan_id} configured")
            else:
                print_error("❌ Failed to add interface")
                
        except Exception as e:
            self.error_handler.handle_error(e)
        
        wait_for_enter()
    
    def _remove_interface_wizard(self):
        """Wizard for removing interface from bridge"""
        clear_screen()
        print_header("❌ Remove Interface from Bridge")
        
        bridges = self.bridge_manager.list_bridges()
        if not bridges:
            print_warning("No bridges available")
            wait_for_enter()
            return
        
        # Select bridge
        bridge_choices = []
        for name, config in bridges.items():
            interface_count = len(config.interfaces)
            if interface_count > 0:
                bridge_choices.append(
                    questionary.Choice(f"{name} ({interface_count} interfaces)", value=name)
                )
        
        if not bridge_choices:
            print_warning("No bridges with interfaces found")
            wait_for_enter()
            return
        
        bridge_name = questionary.select(
            "Select bridge:",
            choices=bridge_choices
        ).ask()
        
        if not bridge_name:
            return
        
        # Get bridge interfaces
        interfaces = self.bridge_manager.get_bridge_interfaces(bridge_name)
        if not interfaces:
            print_warning(f"No interfaces found on bridge '{bridge_name}'")
            wait_for_enter()
            return
        
        # Select interface to remove
        interface_name = questionary.select(
            "Select interface to remove:",
            choices=interfaces
        ).ask()
        
        if not interface_name:
            return
        
        # Confirmation
        if not questionary.confirm(f"Remove interface '{interface_name}' from bridge '{bridge_name}'?").ask():
            return
        
        # Remove interface
        try:
            success = self.bridge_manager.remove_interface_from_bridge(bridge_name, interface_name)
            
            if success:
                print_success(f"✅ Successfully removed interface '{interface_name}' from bridge '{bridge_name}'")
            else:
                print_error("❌ Failed to remove interface")
                
        except Exception as e:
            self.error_handler.handle_error(e)
        
        wait_for_enter()
    
    def _configure_vlan_wizard(self):
        """Wizard for configuring VLANs"""
        clear_screen()
        print_header("🏷️ Configure VLAN")
        
        print_info("VLAN configuration wizard")
        print_warning("This feature requires bridges with VLAN filtering enabled")
        
        bridges = self.bridge_manager.list_bridges()
        vlan_bridges = {name: config for name, config in bridges.items() if config.vlan_filtering}
        
        if not vlan_bridges:
            print_warning("No bridges with VLAN filtering enabled")
            
            enable_vlan = questionary.confirm("Enable VLAN filtering on an existing bridge?").ask()
            if enable_vlan:
                print_info("Use the bridge modification feature (coming soon) to enable VLAN filtering")
            
            wait_for_enter()
            return
        
        # Select bridge
        bridge_choices = [
            questionary.Choice(f"{name} (VLAN enabled)", value=name)
            for name in vlan_bridges.keys()
        ]
        
        bridge_name = questionary.select(
            "Select bridge:",
            choices=bridge_choices
        ).ask()
        
        if not bridge_name:
            return
        
        print_info(f"VLAN configuration for bridge '{bridge_name}' is managed per interface")
        print_info("Use 'Add Interface to Bridge' to configure VLANs when adding interfaces")
        
        wait_for_enter()
    
    def _list_vlans(self):
        """List VLAN configurations"""
        clear_screen()
        print_header("📋 VLAN Configuration List")
        
        bridges = self.bridge_manager.list_bridges()
        vlan_info_found = False
        
        for bridge_name, config in bridges.items():
            if config.vlan_filtering and config.interfaces:
                vlan_interfaces = [iface for iface in config.interfaces if iface.vlan_config]
                
                if vlan_interfaces:
                    vlan_info_found = True
                    
                    vlan_table = Table(title=f"VLANs on Bridge: {bridge_name}")
                    vlan_table.add_column("Interface", style="cyan")
                    vlan_table.add_column("VLAN ID", style="yellow")
                    vlan_table.add_column("VLAN Name", style="green")
                    vlan_table.add_column("Tagged", style="magenta")
                    
                    for interface in vlan_interfaces:
                        vlan_table.add_row(
                            interface.name,
                            str(interface.vlan_config.vlan_id),
                            interface.vlan_config.name,
                            "Yes" if interface.vlan_config.tagged else "No"
                        )
                    
                    console.print(vlan_table)
                    console.print()
        
        if not vlan_info_found:
            console.print(Panel(
                "[yellow]No VLAN configurations found[/]\n\n"
                "Configure VLANs when adding interfaces to bridges with VLAN filtering enabled.",
                title="[blue]VLAN Status[/]",
                border_style="blue"
            ))
        
        wait_for_enter()
    
    def _monitor_bridge_wizard(self):
        """Wizard for monitoring bridge performance"""
        clear_screen()
        print_header("📊 Monitor Bridge Performance")
        
        bridges = self.bridge_manager.list_bridges()
        if not bridges:
            print_warning("No bridges available to monitor")
            wait_for_enter()
            return
        
        # Select bridge
        bridge_choices = [
            questionary.Choice(f"{name} ({config.bridge_type.value})", value=name)
            for name, config in bridges.items()
        ]
        
        bridge_name = questionary.select(
            "Select bridge to monitor:",
            choices=bridge_choices
        ).ask()
        
        if not bridge_name:
            return
        
        # Monitoring duration
        duration = questionary.select(
            "Select monitoring duration:",
            choices=[
                questionary.Choice("30 seconds", value=30),
                questionary.Choice("1 minute", value=60),
                questionary.Choice("2 minutes", value=120),
                questionary.Choice("5 minutes", value=300),
                questionary.Choice("Custom", value="custom")
            ]
        ).ask()
        
        if duration == "custom":
            duration_input = questionary.text(
                "Enter duration in seconds:",
                validate=lambda x: x.isdigit() and int(x) > 0
            ).ask()
            duration = int(duration_input) if duration_input else 60
        
        # Start monitoring
        try:
            results = self.bridge_manager.monitor_bridge(bridge_name, duration)
            
            # Display results
            clear_screen()
            print_header(f"📊 Monitoring Results: {bridge_name}")
            
            # Create results table
            results_table = Table(title=f"Performance Data ({duration}s)")
            results_table.add_column("Metric", style="cyan")
            results_table.add_column("Total", style="green")
            results_table.add_column("Rate/sec", style="yellow")
            
            deltas = results['deltas']
            rates = results['rates']
            
            results_table.add_row("RX Packets", str(deltas['rx_packets']), f"{rates['rx_packets_per_sec']:.2f}")
            results_table.add_row("TX Packets", str(deltas['tx_packets']), f"{rates['tx_packets_per_sec']:.2f}")
            results_table.add_row("RX Bytes", str(deltas['rx_bytes']), f"{rates['rx_bytes_per_sec']:.2f}")
            results_table.add_row("TX Bytes", str(deltas['tx_bytes']), f"{rates['tx_bytes_per_sec']:.2f}")
            
            console.print(results_table)
            
            # Show any errors or drops
            if deltas['rx_errors'] > 0 or deltas['tx_errors'] > 0:
                print_warning(f"Errors detected: RX={deltas['rx_errors']}, TX={deltas['tx_errors']}")
            
            if deltas['rx_dropped'] > 0 or deltas['tx_dropped'] > 0:
                print_warning(f"Dropped packets: RX={deltas['rx_dropped']}, TX={deltas['tx_dropped']}")
            
        except Exception as e:
            self.error_handler.handle_error(e)
        
        wait_for_enter()
    
    def _troubleshoot_bridge_wizard(self):
        """Wizard for troubleshooting bridge issues"""
        clear_screen()
        print_header("🔍 Troubleshoot Bridge")
        
        bridges = self.bridge_manager.list_bridges()
        if not bridges:
            print_warning("No bridges available to troubleshoot")
            wait_for_enter()
            return
        
        # Select bridge
        bridge_choices = [
            questionary.Choice(f"{name} ({config.bridge_type.value})", value=name)
            for name, config in bridges.items()
        ]
        
        bridge_name = questionary.select(
            "Select bridge to troubleshoot:",
            choices=bridge_choices
        ).ask()
        
        if not bridge_name:
            return
        
        # Run troubleshooting
        try:
            results = self.bridge_manager.troubleshoot_bridge(bridge_name)
            
            # Display results
            clear_screen()
            print_header(f"🔍 Troubleshooting Results: {bridge_name}")
            
            # Summary
            if results['issues']:
                console.print(Panel(
                    f"[red]{results['summary']}[/]",
                    title="[red]Issues Found[/]",
                    border_style="red"
                ))
            else:
                console.print(Panel(
                    f"[green]{results['summary']}[/]",
                    title="[green]Health Check[/]",
                    border_style="green"
                ))
            
            # Issues and recommendations
            if results['issues']:
                console.print("\n[bold red]Issues Found:[/]")
                for i, issue in enumerate(results['issues'], 1):
                    console.print(f"  {i}. {issue}")
                
                console.print("\n[bold green]Recommendations:[/]")
                for i, recommendation in enumerate(results['recommendations'], 1):
                    console.print(f"  {i}. {recommendation}")
            
            # Detailed checks
            console.print("\n[bold]Detailed Checks:[/]")
            checks_table = Table()
            checks_table.add_column("Check", style="cyan")
            checks_table.add_column("Result", style="green")
            
            for check, result in results['checks'].items():
                if isinstance(result, bool):
                    result_text = "✅ Pass" if result else "❌ Fail"
                elif isinstance(result, list):
                    result_text = ", ".join(result) if result else "None"
                else:
                    result_text = str(result)
                
                checks_table.add_row(check.replace('_', ' ').title(), result_text)
            
            console.print(checks_table)
            
        except Exception as e:
            self.error_handler.handle_error(e)
        
        wait_for_enter()
    
    def _show_bridge_statistics(self):
        """Show detailed bridge statistics"""
        clear_screen()
        print_header("📈 Bridge Statistics")
        
        bridges = self.bridge_manager.list_bridges()
        if not bridges:
            print_warning("No bridges available")
            wait_for_enter()
            return
        
        # Select bridge or show all
        choices = [questionary.Choice("All Bridges", value="all")]
        choices.extend([
            questionary.Choice(f"{name} ({config.bridge_type.value})", value=name)
            for name, config in bridges.items()
        ])
        
        selection = questionary.select(
            "Select bridge for statistics:",
            choices=choices
        ).ask()
        
        if not selection:
            return
        
        if selection == "all":
            # Show statistics for all bridges
            for bridge_name in bridges.keys():
                self._display_bridge_statistics(bridge_name)
                console.print()
        else:
            # Show statistics for selected bridge
            self._display_bridge_statistics(selection)
        
        wait_for_enter()
    
    def _display_bridge_statistics(self, bridge_name: str):
        """Display statistics for a specific bridge"""
        stats = self.bridge_manager.get_bridge_stats(bridge_name)
        if not stats:
            print_warning(f"No statistics available for bridge '{bridge_name}'")
            return
        
        # Create statistics panel
        stats_content = f"[bold]Bridge:[/] {bridge_name}\n"
        stats_content += f"[bold]State:[/] {stats.state.value.upper()}\n"
        stats_content += f"[bold]Interfaces:[/] {stats.interface_count}\n"
        stats_content += f"[bold]Last Updated:[/] {stats.last_updated}\n\n"
        
        stats_content += "[bold]Traffic Statistics:[/]\n"
        stats_content += f"  RX Packets: {stats.rx_packets:,}\n"
        stats_content += f"  TX Packets: {stats.tx_packets:,}\n"
        stats_content += f"  RX Bytes: {stats.rx_bytes:,}\n"
        stats_content += f"  TX Bytes: {stats.tx_bytes:,}\n\n"
        
        if stats.rx_errors > 0 or stats.tx_errors > 0 or stats.rx_dropped > 0 or stats.tx_dropped > 0:
            stats_content += "[bold red]Error Statistics:[/]\n"
            stats_content += f"  RX Errors: {stats.rx_errors}\n"
            stats_content += f"  TX Errors: {stats.tx_errors}\n"
            stats_content += f"  RX Dropped: {stats.rx_dropped}\n"
            stats_content += f"  TX Dropped: {stats.tx_dropped}\n"
        
        console.print(Panel(
            stats_content,
            title=f"[blue]Statistics: {bridge_name}[/]",
            border_style="blue"
        ))
    
    def _show_bridge_info(self):
        """Show detailed bridge information"""
        clear_screen()
        print_header("ℹ️ Bridge Information")
        
        bridges = self.bridge_manager.list_bridges()
        if not bridges:
            print_warning("No bridges available")
            wait_for_enter()
            return
        
        # Select bridge or show all
        choices = [questionary.Choice("All Bridges", value="all")]
        choices.extend([
            questionary.Choice(f"{name} ({config.bridge_type.value})", value=name)
            for name, config in bridges.items()
        ])
        
        selection = questionary.select(
            "Select bridge for information:",
            choices=choices
        ).ask()
        
        if not selection:
            return
        
        if selection == "all":
            self.bridge_manager.display_bridge_info()
        else:
            self.bridge_manager.display_bridge_info(selection)
        
        wait_for_enter()
    
    def _list_all_bridges(self):
        """List all bridges with summary information"""
        clear_screen()
        print_header("📜 All Bridges")
        
        self._display_bridge_dashboard()
        
        wait_for_enter()
    
    def _select_interfaces_wizard(self) -> List[str]:
        """Wizard for selecting multiple interfaces"""
        available_interfaces = self._get_available_interfaces()
        if not available_interfaces:
            return []
        
        selected_interfaces = []
        
        while True:
            remaining_interfaces = [iface for iface in available_interfaces if iface not in selected_interfaces]
            
            if not remaining_interfaces:
                break
            
            choices = remaining_interfaces + ["Done selecting interfaces"]
            
            selection = questionary.select(
                f"Select interface to add ({len(selected_interfaces)} selected):",
                choices=choices
            ).ask()
            
            if selection == "Done selecting interfaces" or not selection:
                break
            
            selected_interfaces.append(selection)
        
        return selected_interfaces
    
    def _get_available_interfaces(self) -> List[str]:
        """Get list of available network interfaces"""
        try:
            import subprocess
            result = subprocess.run(
                ["ip", "link", "show"],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                return []
            
            interfaces = []
            for line in result.stdout.split('\n'):
                if ': ' in line and not line.startswith(' '):
                    # Extract interface name
                    parts = line.split(': ')
                    if len(parts) >= 2:
                        interface_name = parts[1].split('@')[0]  # Remove VLAN suffix if present
                        
                        # Skip loopback and bridge interfaces
                        if not interface_name.startswith(('lo', 'br-', 'docker', 'veth')):
                            interfaces.append(interface_name)
            
            return sorted(interfaces)
            
        except Exception:
            return []
    
    def _validate_ip_address(self, ip: str) -> bool:
        """Validate IP address format"""
        try:
            parts = ip.split('.')
            if len(parts) != 4:
                return False
            
            for part in parts:
                if not (0 <= int(part) <= 255):
                    return False
            
            return True
        except (ValueError, AttributeError):
            return False


# Global UI instance
_bridge_ui = None

def get_bridge_ui() -> BridgeNetworkingUI:
    """Get the global bridge UI instance"""
    global _bridge_ui
    if _bridge_ui is None:
        _bridge_ui = BridgeNetworkingUI()
    return _bridge_ui


def show_bridge_menu():
    """Show the bridge networking menu"""
    get_bridge_ui().show_bridge_menu()