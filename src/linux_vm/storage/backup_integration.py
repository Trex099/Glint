#!/usr/bin/env python3
# Made by trex099
# https://github.com/Trex099/Glint
"""
Backup System Integration Module

This module provides integration between the disk management menu
and the automated backup system.
"""

import os
import questionary
from rich.console import Console
from rich.panel import Panel
from datetime import datetime

# Import from backup module
from .backup import (
    BackupManager, BackupSchedule, RetentionPolicy, 
    BackupType, BackupStatus, CompressionType, create_backup_dashboard,
    clear_screen
)

# Import wait_for_enter from core_utils
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from core_utils import wait_for_enter

console = Console()

def configure_vm_for_backup(backup_manager, vm_name, vm_paths=None):
    """
    Configure a VM for backup
    
    Args:
        backup_manager: The BackupManager instance
        vm_name: Name of the VM to configure
        vm_paths: Optional dictionary of VM paths
    
    Returns:
        bool: True if configuration was successful, False otherwise
    """
    console.print(f"[bold blue]Configure Backup for VM: {vm_name}[/bold blue]")
    
    # Determine VM path
    if vm_paths:
        vm_path = vm_paths['dir']
    else:
        vm_path = os.path.expanduser(f"~/vms_linux/{vm_name}")
    
    if not os.path.exists(vm_path):
        console.print(f"[red]VM path not found: {vm_path}[/red]")
        return False
    
    # Set backup directory
    default_backup_dir = os.path.expanduser(f"~/.glint/backup/{vm_name}")
    backup_dir = questionary.text(
        "Backup directory:",
        default=default_backup_dir
    ).ask()
    
    if not backup_dir:
        return False
    
    # Create backup directory if it doesn't exist
    os.makedirs(backup_dir, exist_ok=True)
    
    # Configure backup schedule
    schedule_choices = [
        questionary.Choice("Daily (recommended)", value="daily"),
        questionary.Choice("Weekly", value="weekly"),
        questionary.Choice("Monthly", value="monthly"),
        questionary.Choice("Manual only (no automatic backups)", value="manual")
    ]
    
    schedule_frequency = questionary.select(
        "Backup schedule frequency:",
        choices=schedule_choices
    ).ask()
    
    if not schedule_frequency:
        return False
    
    # Configure backup type
    backup_type_choices = [
        questionary.Choice("Incremental (recommended, smaller backups)", value=BackupType.INCREMENTAL),
        questionary.Choice("Full (complete backup each time)", value=BackupType.FULL),
        questionary.Choice("Differential (changes since last full backup)", value=BackupType.DIFFERENTIAL)
    ]
    
    backup_type = questionary.select(
        "Backup type:",
        choices=backup_type_choices
    ).ask()
    
    if not backup_type:
        return False
    
    # Configure compression
    compression_choices = [
        questionary.Choice("GZIP (recommended, good balance)", value=CompressionType.GZIP),
        questionary.Choice("None (fastest, largest size)", value=CompressionType.NONE),
        questionary.Choice("BZIP2 (better compression, slower)", value=CompressionType.BZIP2),
        questionary.Choice("XZ (best compression, slowest)", value=CompressionType.XZ),
        questionary.Choice("LZ4 (fast compression)", value=CompressionType.LZ4)
    ]
    
    compression = questionary.select(
        "Compression type:",
        choices=compression_choices
    ).ask()
    
    if compression is None:
        return False
    
    # Configure retention policy
    retention_days = questionary.text(
        "Retention period (days):",
        default="30",
        validate=lambda s: s.isdigit() and int(s) > 0
    ).ask()
    
    if not retention_days:
        return False
    
    retention_days = int(retention_days)
    
    # Configure encryption
    encryption_enabled = questionary.confirm(
        "Enable backup encryption?",
        default=False
    ).ask()
    
    encryption_key = None
    if encryption_enabled:
        encryption_key = questionary.password(
            "Enter encryption key (keep this safe, you'll need it for restoration):"
        ).ask()
        
        confirm_key = questionary.password(
            "Confirm encryption key:"
        ).ask()
        
        if encryption_key != confirm_key:
            console.print("[red]Encryption keys don't match. Encryption disabled.[/red]")
            encryption_enabled = False
            encryption_key = None
    
    # Create schedule
    schedules = []
    if schedule_frequency != "manual":
        backup_time = "02:00"  # Default to 2 AM
        
        if schedule_frequency == "weekly":
            days_of_week = ["monday"]  # Default to Monday
        else:
            days_of_week = None
            
        if schedule_frequency == "monthly":
            day_of_month = 1  # Default to 1st of month
        else:
            day_of_month = None
            
        schedule = BackupSchedule(
            name=f"{schedule_frequency}_backup",
            enabled=True,
            backup_type=backup_type,
            frequency=schedule_frequency,
            time=backup_time,
            days_of_week=days_of_week,
            day_of_month=day_of_month,
            retention_days=retention_days,
            compression=compression,
            encryption_enabled=encryption_enabled,
            verify_after_backup=True,
            created_at=datetime.now()
        )
        
        schedules.append(schedule)
    
    # Create retention policy
    retention_policy = RetentionPolicy(
        daily_retention=min(retention_days, 7),
        weekly_retention=min(retention_days // 7, 4),
        monthly_retention=min(retention_days // 30, 12),
        yearly_retention=min(retention_days // 365, 5),
        max_total_backups=100,
        auto_cleanup=True
    )
    
    # Create backup configuration
    success = backup_manager.create_backup_config(
        vm_name=vm_name,
        backup_dir=backup_dir,
        schedules=schedules,
        retention_policy=retention_policy
    )
    
    if success:
        # Update encryption key if needed
        if encryption_enabled and encryption_key:
            backup_manager.update_backup_config(
                vm_name=vm_name,
                encryption_key=encryption_key
            )
        
        console.print(f"[green]✅ Backup configuration for VM '{vm_name}' created successfully![/green]")
        
        # Show configuration summary
        panel = Panel(
            f"[bold]Backup Configuration Summary:[/bold]\n\n"
            f"VM: [cyan]{vm_name}[/cyan]\n"
            f"Backup Directory: [cyan]{backup_dir}[/cyan]\n"
            f"Schedule: [cyan]{schedule_frequency if schedule_frequency != 'manual' else 'Manual only'}[/cyan]\n"
            f"Backup Type: [cyan]{backup_type.value}[/cyan]\n"
            f"Compression: [cyan]{compression.value}[/cyan]\n"
            f"Retention: [cyan]{retention_days} days[/cyan]\n"
            f"Encryption: [cyan]{'Enabled' if encryption_enabled else 'Disabled'}[/cyan]",
            title="Backup Configuration",
            border_style="green"
        )
        console.print(panel)
        
        return True
    else:
        console.print("[red]Failed to create backup configuration.[/red]")
        return False

def create_manual_backup(backup_manager, vm_name, vm_paths=None):
    """
    Create a manual backup for a VM
    
    Args:
        backup_manager: The BackupManager instance
        vm_name: Name of the VM to backup
        vm_paths: Optional dictionary of VM paths
    
    Returns:
        str: Backup ID if successful, None otherwise
    """
    # Check if VM is configured for backup
    if vm_name not in backup_manager.backup_configs:
        console.print(f"[yellow]VM '{vm_name}' is not configured for backup.[/yellow]")
        if questionary.confirm("Would you like to configure it now?").ask():
            if not configure_vm_for_backup(backup_manager, vm_name, vm_paths):
                return None
        else:
            return None
    
    # Select backup type
    backup_type_choices = [
        questionary.Choice("Incremental (recommended, smaller backups)", value=BackupType.INCREMENTAL),
        questionary.Choice("Full (complete backup each time)", value=BackupType.FULL),
        questionary.Choice("Differential (changes since last full backup)", value=BackupType.DIFFERENTIAL),
        questionary.Choice("Snapshot (fastest, uses QEMU snapshots)", value=BackupType.SNAPSHOT)
    ]
    
    backup_type = questionary.select(
        "Select backup type:",
        choices=backup_type_choices,
        use_indicator=True
    ).ask()
    
    if not backup_type:
        return None
    
    # Select compression
    compression_choices = [
        questionary.Choice("GZIP (recommended, good balance)", value=CompressionType.GZIP),
        questionary.Choice("None (fastest, largest size)", value=CompressionType.NONE),
        questionary.Choice("BZIP2 (better compression, slower)", value=CompressionType.BZIP2),
        questionary.Choice("XZ (best compression, slowest)", value=CompressionType.XZ),
        questionary.Choice("LZ4 (fast compression)", value=CompressionType.LZ4)
    ]
    
    compression = questionary.select(
        "Select compression type:",
        choices=compression_choices,
        use_indicator=True
    ).ask()
    
    if compression is None:
        return None
    
    # Ask for encryption
    encrypt = questionary.confirm("Encrypt backup?", default=False).ask()
    
    if encrypt is None:
        return None
    
    # Create backup with progress
    console.print(f"[green]Creating {backup_type.value} backup for VM {vm_name}...[/green]")
    
    # Use vm_paths if provided
    if vm_paths:
        vm_path = vm_paths['dir']
    else:
        vm_path = None
    
    # Create backup
    backup_id = backup_manager.create_backup(
        vm_name=vm_name,
        backup_type=backup_type,
        compression=compression,
        encrypt=encrypt,
        vm_path=vm_path
    )
    
    if backup_id:
        console.print(f"[green]Backup created successfully: {backup_id}[/green]")
    else:
        console.print("[red]Failed to create backup. Check logs for details.[/red]")
    
    return backup_id

def restore_backup(backup_manager, vm_name=None):
    """
    Restore a backup
    
    Args:
        backup_manager: The BackupManager instance
        vm_name: Optional name of the VM to filter backups
    
    Returns:
        bool: True if restoration was successful, False otherwise
    """
    # Get backups
    backups = backup_manager.list_backups(vm_name)
    
    if not backups:
        console.print("[yellow]No backups found.[/yellow]")
        return False
    
    # Create backup choices
    backup_choices = []
    for backup in backups:
        date_str = backup.created_at.strftime("%Y-%m-%d %H:%M")
        backup_choices.append(questionary.Choice(
            f"{backup.vm_name} - {backup.backup_type.value} - {date_str}",
            value=backup.backup_id
        ))
    
    # Add back option
    backup_choices.append(questionary.Separator())
    backup_choices.append(questionary.Choice("Cancel", value="cancel"))
    
    # Select backup
    backup_id = questionary.select(
        "Select backup to restore:",
        choices=backup_choices,
        use_indicator=True
    ).ask()
    
    if backup_id == "cancel" or backup_id is None:
        return False
    
    # Get selected backup
    selected_backup = next((b for b in backups if b.backup_id == backup_id), None)
    if not selected_backup:
        console.print("[red]Selected backup not found.[/red]")
        return False
    
    # Get restore path
    restore_path = questionary.text(
        "Enter restore path:",
        default=f"restore_backup/restore_{selected_backup.vm_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    ).ask()
    
    if not restore_path:
        return False
    
    # Confirm restoration
    confirm = questionary.confirm(
        f"Are you sure you want to restore backup {backup_id} to {restore_path}?",
        default=False
    ).ask()
    
    if not confirm:
        return False
    
    # Restore backup
    console.print(f"[green]Restoring backup {backup_id} to {restore_path}...[/green]")
    
    # Restore backup
    result = backup_manager.restore_backup(backup_id, restore_path)
    
    if result:
        console.print(f"[green]Backup restored successfully to {restore_path}[/green]")
        return True
    else:
        console.print("[red]Failed to restore backup. Check logs for details.[/red]")
        return False

def enhanced_backup_management_menu(vm_name=None, vm_paths=None):
    """
    Enhanced backup management menu with VM-specific integration
    
    Args:
        vm_name: Optional name of the VM to manage backups for
        vm_paths: Optional dictionary of VM paths
    """
    backup_manager = BackupManager()
    
    # Check if the VM is configured for backup if vm_name is provided
    if vm_name and vm_name not in backup_manager.backup_configs:
        clear_screen()
        console.print(f"[bold blue]Backup Management - {vm_name}[/bold blue]\n")
        console.print(f"[yellow]VM '{vm_name}' is not configured for backup.[/yellow]")
        
        if questionary.confirm("Would you like to configure it now?").ask():
            if configure_vm_for_backup(backup_manager, vm_name, vm_paths):
                console.print("[green]VM configured for backup successfully![/green]")
            else:
                console.print("[yellow]Backup configuration cancelled.[/yellow]")
            
            wait_for_enter()
    
    while True:
        clear_screen()
        
        # Display backup dashboard with VM filter if provided
        console.print(create_backup_dashboard(vm_name))
        
        # Build menu options
        menu_title = "Backup Management"
        if vm_name:
            menu_title = f"Backup Management - {vm_name}"
        
        choices = [
            questionary.Choice("📋 Show Backup List", value="list"),
            questionary.Choice("📦 Create Manual Backup", value="create"),
            questionary.Choice("⏱️ Configure Backup Schedule", value="schedule"),
            questionary.Choice("🔄 Restore Backup", value="restore"),
            questionary.Choice("🗑️ Delete Backup", value="delete"),
            questionary.Choice("🧹 Cleanup Old Backups", value="cleanup"),
            questionary.Choice("✅ Verify Backup", value="verify"),
            questionary.Choice("📊 Show Backup Statistics", value="stats"),
            questionary.Separator(),
            questionary.Choice("🔙 Back", value="back")
        ]
        
        choice = questionary.select(
            menu_title,
            choices=choices,
            use_indicator=True
        ).ask()
        
        if choice == "back" or choice is None:
            break
        
        if choice == "list":
            show_backup_list(backup_manager, vm_name)
        elif choice == "create":
            create_manual_backup(backup_manager, vm_name, vm_paths)
            wait_for_enter()
        elif choice == "schedule":
            configure_backup_schedule(backup_manager, vm_name)
        elif choice == "restore":
            restore_backup(backup_manager, vm_name)
            wait_for_enter()
        elif choice == "delete":
            delete_backup(backup_manager, vm_name)
        elif choice == "cleanup":
            cleanup_old_backups(backup_manager, vm_name)
        elif choice == "verify":
            verify_backup(backup_manager, vm_name)
        elif choice == "stats":
            show_backup_statistics(backup_manager, vm_name)

def show_backup_list(backup_manager, vm_name=None):
    """Show detailed backup list"""
    if vm_name is None:
        vm_name = questionary.text("Filter by VM name (leave empty for all):").ask()
        if vm_name == "":
            vm_name = None
    
    backups = backup_manager.list_backups(vm_name)
    
    if not backups:
        console.print("[yellow]No backups found.[/yellow]")
        wait_for_enter()
        return
    
    table_title = "Backup List"
    if vm_name:
        table_title = f"Backup List for {vm_name}"
    
    from rich.table import Table
    table = Table(title=table_title)
    table.add_column("Backup ID", style="cyan")
    table.add_column("VM", style="green")
    table.add_column("Type", style="yellow")
    table.add_column("Created", style="blue")
    table.add_column("Size", style="magenta")
    table.add_column("Status", style="red")
    table.add_column("Path", style="white")
    
    for backup in backups:
        # Format size
        size_str = "N/A"
        if backup.size_bytes > 0:
            if backup.size_bytes < 1024 * 1024:
                size_str = f"{backup.size_bytes / 1024:.1f} KB"
            elif backup.size_bytes < 1024 * 1024 * 1024:
                size_str = f"{backup.size_bytes / (1024 * 1024):.1f} MB"
            else:
                size_str = f"{backup.size_bytes / (1024 * 1024 * 1024):.1f} GB"
        
        # Format status with color
        status_str = backup.status.value
        status_style = ""
        if backup.status == BackupStatus.COMPLETED or backup.status == BackupStatus.VERIFIED:
            status_style = "green"
        elif backup.status == BackupStatus.FAILED or backup.status == BackupStatus.CANCELLED:
            status_style = "red"
        elif backup.status == BackupStatus.RUNNING or backup.status == BackupStatus.VERIFYING:
            status_style = "yellow"
        
        # Format date
        date_str = backup.created_at.strftime("%Y-%m-%d %H:%M")
        
        table.add_row(
            backup.backup_id,
            backup.vm_name,
            backup.backup_type.value,
            date_str,
            size_str,
            f"[{status_style}]{status_str}[/{status_style}]",
            backup.backup_path
        )
    
    console.print(table)
    wait_for_enter()

def configure_backup_schedule(backup_manager, vm_name=None):
    """Configure backup schedule for a VM"""
    if vm_name is None:
        # Get available VMs
        vm_configs = backup_manager.backup_configs
        
        if not vm_configs:
            console.print("[yellow]No VMs configured for backup. Please configure a VM first.[/yellow]")
            wait_for_enter()
            return
        
        # Select VM
        vm_choices = [questionary.Choice(vm, value=vm) for vm in vm_configs.keys()]
        vm_name = questionary.select(
            "Select VM to configure backup schedule:",
            choices=vm_choices,
            use_indicator=True
        ).ask()
        
        if not vm_name:
            return
    
    # Check if VM is configured for backup
    if vm_name not in backup_manager.backup_configs:
        console.print(f"[yellow]VM '{vm_name}' is not configured for backup.[/yellow]")
        if questionary.confirm("Would you like to configure it now?").ask():
            configure_vm_for_backup(backup_manager, vm_name)
        return
    
    # Get current schedules
    config = backup_manager.backup_configs[vm_name]
    schedules = config.schedules
    
    # Show current schedules
    console.print(f"[bold blue]Current Backup Schedules for {vm_name}:[/bold blue]")
    
    if not schedules:
        console.print("[yellow]No schedules configured.[/yellow]")
    else:
        from rich.table import Table
        table = Table(title=f"Backup Schedules for {vm_name}")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Frequency", style="yellow")
        table.add_column("Time", style="blue")
        table.add_column("Enabled", style="magenta")
        table.add_column("Last Run", style="red")
        table.add_column("Next Run", style="white")
        
        for schedule in schedules:
            table.add_row(
                schedule.name,
                schedule.backup_type.value,
                schedule.frequency,
                schedule.time,
                "✅" if schedule.enabled else "❌",
                schedule.last_run.strftime("%Y-%m-%d %H:%M") if schedule.last_run else "Never",
                schedule.next_run.strftime("%Y-%m-%d %H:%M") if schedule.next_run else "Not scheduled"
            )
        
        console.print(table)
    
    # Schedule management options
    schedule_options = [
        questionary.Choice("Add New Schedule", value="add"),
        questionary.Choice("Edit Existing Schedule", value="edit"),
        questionary.Choice("Delete Schedule", value="delete"),
        questionary.Choice("Enable/Disable Schedule", value="toggle"),
        questionary.Separator(),
        questionary.Choice("Back", value="back")
    ]
    
    choice = questionary.select(
        "Schedule Management:",
        choices=schedule_options,
        use_indicator=True
    ).ask()
    
    if choice == "back" or choice is None:
        return
    
    # Implement schedule management options
    if choice == "add":
        # Add new schedule
        schedule_name = questionary.text(
            "Enter schedule name:",
            default=f"schedule_{len(schedules) + 1}"
        ).ask()
        
        if not schedule_name:
            wait_for_enter()
            return
        
        # Select backup type
        backup_type_choices = [
            questionary.Choice("Incremental (recommended)", value=BackupType.INCREMENTAL),
            questionary.Choice("Full", value=BackupType.FULL),
            questionary.Choice("Differential", value=BackupType.DIFFERENTIAL)
        ]
        backup_type = questionary.select("Backup type:", choices=backup_type_choices).ask()
        
        if not backup_type:
            wait_for_enter()
            return
        
        # Select frequency
        frequency = questionary.select(
            "Frequency:",
            choices=["daily", "weekly", "monthly"]
        ).ask()
        
        if not frequency:
            wait_for_enter()
            return
        
        # Select time
        backup_time = questionary.text("Backup time (HH:MM):", default="02:00").ask()
        
        if not backup_time:
            wait_for_enter()
            return
        
        # Days of week for weekly
        days_of_week = None
        if frequency == "weekly":
            days_of_week = questionary.checkbox(
                "Select days:",
                choices=["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            ).ask()
            if not days_of_week:
                days_of_week = ["monday"]
        
        # Day of month for monthly
        day_of_month = None
        if frequency == "monthly":
            day_of_month = int(questionary.text("Day of month (1-28):", default="1").ask() or "1")
        
        # Select compression
        compression = questionary.select(
            "Compression:",
            choices=[
                questionary.Choice("GZIP (recommended)", value=CompressionType.GZIP),
                questionary.Choice("None", value=CompressionType.NONE),
                questionary.Choice("LZ4", value=CompressionType.LZ4)
            ]
        ).ask()
        
        if compression is None:
            wait_for_enter()
            return
        
        # Create new schedule
        new_schedule = BackupSchedule(
            name=schedule_name,
            enabled=True,
            backup_type=backup_type,
            frequency=frequency,
            time=backup_time,
            days_of_week=days_of_week,
            day_of_month=day_of_month,
            retention_days=30,
            compression=compression,
            encryption_enabled=False,
            verify_after_backup=True,
            created_at=datetime.now()
        )
        
        # Add to config
        config.schedules.append(new_schedule)
        backup_manager._save_backup_config(vm_name, config)
        console.print(f"[green]✅ Schedule '{schedule_name}' added successfully![/green]")
        
    elif choice == "edit":
        if not schedules:
            console.print("[yellow]No schedules to edit.[/yellow]")
            wait_for_enter()
            return
        
        # Select schedule to edit
        schedule_choices = [questionary.Choice(s.name, value=i) for i, s in enumerate(schedules)]
        schedule_idx = questionary.select("Select schedule to edit:", choices=schedule_choices).ask()
        
        if schedule_idx is None:
            wait_for_enter()
            return
        
        schedule = schedules[schedule_idx]
        
        # Edit fields
        new_time = questionary.text(f"Backup time (current: {schedule.time}):", default=schedule.time).ask()
        if new_time:
            schedule.time = new_time
        
        new_retention = questionary.text(
            f"Retention days (current: {schedule.retention_days}):",
            default=str(schedule.retention_days)
        ).ask()
        if new_retention and new_retention.isdigit():
            schedule.retention_days = int(new_retention)
        
        # Save updated config
        backup_manager._save_backup_config(vm_name, config)
        console.print(f"[green]✅ Schedule '{schedule.name}' updated![/green]")
        
    elif choice == "delete":
        if not schedules:
            console.print("[yellow]No schedules to delete.[/yellow]")
            wait_for_enter()
            return
        
        # Select schedule to delete
        schedule_choices = [questionary.Choice(s.name, value=i) for i, s in enumerate(schedules)]
        schedule_idx = questionary.select("Select schedule to delete:", choices=schedule_choices).ask()
        
        if schedule_idx is None:
            wait_for_enter()
            return
        
        schedule_name = schedules[schedule_idx].name
        
        # Confirm deletion
        if questionary.confirm(f"Delete schedule '{schedule_name}'?", default=False).ask():
            config.schedules.pop(schedule_idx)
            backup_manager._save_backup_config(vm_name, config)
            console.print(f"[green]✅ Schedule '{schedule_name}' deleted![/green]")
        
    elif choice == "toggle":
        if not schedules:
            console.print("[yellow]No schedules to toggle.[/yellow]")
            wait_for_enter()
            return
        
        # Select schedule to toggle
        schedule_choices = [
            questionary.Choice(f"{s.name} ({'✅ Enabled' if s.enabled else '❌ Disabled'})", value=i)
            for i, s in enumerate(schedules)
        ]
        schedule_idx = questionary.select("Select schedule to toggle:", choices=schedule_choices).ask()
        
        if schedule_idx is None:
            wait_for_enter()
            return
        
        schedule = schedules[schedule_idx]
        schedule.enabled = not schedule.enabled
        backup_manager._save_backup_config(vm_name, config)
        status = "enabled" if schedule.enabled else "disabled"
        console.print(f"[green]✅ Schedule '{schedule.name}' {status}![/green]")
    
    wait_for_enter()

def delete_backup(backup_manager, vm_name=None):
    """Delete backup menu"""
    backups = backup_manager.list_backups(vm_name)
    
    if not backups:
        console.print("[yellow]No backups found.[/yellow]")
        wait_for_enter()
        return
    
    # Create backup choices
    backup_choices = []
    for backup in backups:
        date_str = backup.created_at.strftime("%Y-%m-%d %H:%M")
        backup_choices.append(questionary.Choice(
            f"{backup.vm_name} - {backup.backup_type.value} - {date_str}",
            value=backup.backup_id
        ))
    
    # Add back option
    backup_choices.append(questionary.Separator())
    backup_choices.append(questionary.Choice("Cancel", value="cancel"))
    
    # Select backup
    backup_id = questionary.select(
        "Select backup to delete:",
        choices=backup_choices,
        use_indicator=True
    ).ask()
    
    if backup_id == "cancel" or backup_id is None:
        return
    
    # Confirm deletion
    confirm = questionary.confirm(
        f"Are you sure you want to delete backup {backup_id}?",
        default=False
    ).ask()
    
    if not confirm:
        return
    
    # Delete backup
    result = backup_manager.delete_backup(backup_id)
    
    if result:
        console.print(f"[green]Backup {backup_id} deleted successfully[/green]")
    else:
        console.print("[red]Failed to delete backup. Check logs for details.[/red]")
    
    wait_for_enter()

def cleanup_old_backups(backup_manager, vm_name=None):
    """Cleanup old backups menu"""
    if vm_name is None:
        vm_name = questionary.text("VM name (leave empty for all VMs):").ask()
        if vm_name == "":
            vm_name = None
    
    # Confirm cleanup
    confirm = questionary.confirm(
        f"Are you sure you want to clean up old backups{f' for {vm_name}' if vm_name else ''}?",
        default=False
    ).ask()
    
    if not confirm:
        return
    
    # Cleanup backups
    cleaned_count = backup_manager.cleanup_old_backups(vm_name)
    
    console.print(f"[green]Cleaned up {cleaned_count} old backups[/green]")
    wait_for_enter()

def verify_backup(backup_manager, vm_name=None):
    """Verify backup menu"""
    backups = backup_manager.list_backups(vm_name)
    
    if not backups:
        console.print("[yellow]No backups found.[/yellow]")
        wait_for_enter()
        return
    
    # Create backup choices
    backup_choices = []
    for backup in backups:
        date_str = backup.created_at.strftime("%Y-%m-%d %H:%M")
        backup_choices.append(questionary.Choice(
            f"{backup.vm_name} - {backup.backup_type.value} - {date_str}",
            value=backup.backup_id
        ))
    
    # Add back option
    backup_choices.append(questionary.Separator())
    backup_choices.append(questionary.Choice("Cancel", value="cancel"))
    
    # Select backup
    backup_id = questionary.select(
        "Select backup to verify:",
        choices=backup_choices,
        use_indicator=True
    ).ask()
    
    if backup_id == "cancel" or backup_id is None:
        return
    
    # Verify backup
    console.print(f"[green]Verifying backup {backup_id}...[/green]")
    
    # Verify backup
    result = backup_manager._verify_backup(backup_id)
    
    if result:
        console.print(f"[green]Backup {backup_id} verified successfully[/green]")
    else:
        console.print("[red]Backup verification failed. Check logs for details.[/red]")
    
    wait_for_enter()

def show_backup_statistics(backup_manager, vm_name=None):
    """Show backup statistics"""
    backups = backup_manager.list_backups(vm_name)
    
    if not backups:
        console.print("[yellow]No backups found.[/yellow]")
        wait_for_enter()
        return
    
    # Calculate statistics
    total_backups = len(backups)
    total_size = sum(b.size_bytes for b in backups if b.size_bytes > 0)
    compressed_size = sum(b.compressed_size_bytes for b in backups if b.compressed_size_bytes > 0)
    
    # Count by type
    type_counts = {}
    for backup in backups:
        type_name = backup.backup_type.value
        if type_name not in type_counts:
            type_counts[type_name] = 0
        type_counts[type_name] += 1
    
    # Count by status
    status_counts = {}
    for backup in backups:
        status_name = backup.status.value
        if status_name not in status_counts:
            status_counts[status_name] = 0
        status_counts[status_name] += 1
    
    # Count by VM
    vm_counts = {}
    for backup in backups:
        vm_name = backup.vm_name
        if vm_name not in vm_counts:
            vm_counts[vm_name] = 0
        vm_counts[vm_name] += 1
    
    # Format sizes
    def format_size(size_bytes):
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    
    # Create statistics table
    from rich.table import Table
    table = Table(title="Backup Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Total Backups", str(total_backups))
    table.add_row("Total Size", format_size(total_size))
    
    if compressed_size > 0:
        table.add_row("Compressed Size", format_size(compressed_size))
        if total_size > 0:
            compression_ratio = (total_size - compressed_size) / total_size * 100
            table.add_row("Compression Ratio", f"{compression_ratio:.1f}%")
    
    # Add type counts
    table.add_row("", "")
    table.add_row("[bold]Backup Types[/bold]", "")
    for type_name, count in type_counts.items():
        table.add_row(type_name, str(count))
    
    # Add status counts
    table.add_row("", "")
    table.add_row("[bold]Backup Status[/bold]", "")
    for status_name, count in status_counts.items():
        table.add_row(status_name, str(count))
    
    # Add VM counts if not filtering by VM
    if vm_name is None and len(vm_counts) > 1:
        table.add_row("", "")
        table.add_row("[bold]Backups by VM[/bold]", "")
        for vm_name, count in vm_counts.items():
            table.add_row(vm_name, str(count))
    
    console.print(table)
    wait_for_enter()