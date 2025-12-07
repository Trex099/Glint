# Made by trex099
# https://github.com/Trex099/Glint
"""
Storage Integration Module

Integrates advanced snapshot system with existing VM management
"""

import os
import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn

from .snapshots import (
    SnapshotManager, SnapshotType, SnapshotStatus, RetentionPolicy,
    create_snapshot_dashboard
)

console = Console()


def handle_snapshot_menu(vm_name: str):
    """Handle snapshot management menu for a VM"""
    
    manager = SnapshotManager(vm_name)
    
    while True:
        console.clear()
        
        # Display snapshot dashboard
        dashboard = create_snapshot_dashboard(vm_name)
        console.print(dashboard)
        console.print()
        
        # Display snapshot tree if snapshots exist
        if manager.snapshots:
            tree = manager.visualize_snapshot_tree()
            console.print(Panel(tree, title="📸 Snapshot Tree", border_style="green"))
            console.print()
        
        choice = questionary.select(
            f"Snapshot Management - {vm_name}",
            choices=[
                questionary.Choice("📸 Create New Snapshot", value="create"),
                questionary.Choice("🗑️  Delete Snapshot", value="delete"),
                questionary.Choice("🔄 Restore from Snapshot", value="restore"),
                questionary.Choice("🔍 Search Snapshots", value="search"),
                questionary.Choice("📊 View Snapshot Details", value="details"),
                questionary.Choice("✏️  Edit Snapshot Metadata", value="edit"),
                questionary.Choice("🔀 Merge Snapshots", value="merge"),
                questionary.Separator("--- Management ---"),
                questionary.Choice("🧹 Cleanup & Retention", value="cleanup"),
                questionary.Choice("⚙️  Retention Policy", value="policy"),
                questionary.Choice("📤 Export Metadata", value="export"),
                questionary.Choice("📥 Import Metadata", value="import"),
                questionary.Separator(),
                questionary.Choice("🔙 Back", value="back")
            ],
            use_indicator=True
        ).ask()
        
        if choice == "back" or choice is None:
            break
        
        try:
            if choice == "create":
                handle_create_snapshot(manager)
            elif choice == "delete":
                handle_delete_snapshot(manager)
            elif choice == "restore":
                handle_restore_snapshot(manager)
            elif choice == "search":
                handle_search_snapshots(manager)
            elif choice == "details":
                handle_snapshot_details(manager)
            elif choice == "edit":
                handle_edit_snapshot(manager)
            elif choice == "merge":
                handle_merge_snapshots(manager)
            elif choice == "cleanup":
                handle_cleanup_snapshots(manager)
            elif choice == "policy":
                handle_retention_policy(manager)
            elif choice == "export":
                handle_export_metadata(manager)
            elif choice == "import":
                handle_import_metadata(manager)
        
        except KeyboardInterrupt:
            console.print("\n[yellow]Operation cancelled[/yellow]")
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
        
        if choice != "back":
            console.print("\n[dim]Press Enter to continue...[/dim]")
            input()


def handle_create_snapshot(manager: SnapshotManager):
    """Handle snapshot creation"""
    
    console.print("[bold blue]Create New Snapshot[/bold blue]")
    console.print()
    
    # Get snapshot details
    name = Prompt.ask("Snapshot name", default=f"snapshot_{int(__import__('time').time())}")
    description = Prompt.ask("Description (optional)", default="")
    
    # Get tags
    tags_input = Prompt.ask("Tags (comma-separated, optional)", default="")
    tags = [tag.strip() for tag in tags_input.split(",") if tag.strip()]
    
    # Get snapshot type
    snap_type = questionary.select(
        "Snapshot type",
        choices=[
            questionary.Choice("Manual", value=SnapshotType.MANUAL),
            questionary.Choice("Automatic", value=SnapshotType.AUTOMATIC),
            questionary.Choice("Backup", value=SnapshotType.BACKUP),
            questionary.Choice("Checkpoint", value=SnapshotType.CHECKPOINT)
        ]
    ).ask()
    
    # Get parent snapshot (optional)
    parent_id = None
    if manager.snapshots:
        use_parent = Confirm.ask("Create as child of existing snapshot?", default=False)
        if use_parent:
            parent_choices = [
                questionary.Choice(f"{snap.name} ({snap_id[:8]})", value=snap_id)
                for snap_id, snap in manager.snapshots.items()
                if snap.status == SnapshotStatus.ACTIVE
            ]
            if parent_choices:
                parent_id = questionary.select("Parent snapshot", choices=parent_choices).ask()
    
    # Get retention days (optional)
    retention_input = Prompt.ask("Retention days (optional)", default="")
    retention_days = int(retention_input) if retention_input.isdigit() else None
    
    # Create snapshot with progress indicator
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Creating snapshot...", total=None)
        
        try:
            snapshot_id = manager.create_snapshot(
                name=name,
                description=description,
                tags=tags,
                parent_id=parent_id,
                snapshot_type=snap_type,
                retention_days=retention_days
            )
            
            progress.update(task, description="Snapshot created successfully!")
            console.print(f"\n[green]✅ Snapshot created with ID: {snapshot_id}[/green]")
            
        except Exception as e:
            progress.update(task, description="Failed to create snapshot")
            console.print(f"\n[red]❌ Error creating snapshot: {e}[/red]")


def handle_delete_snapshot(manager: SnapshotManager):
    """Handle snapshot deletion"""
    
    if not manager.snapshots:
        console.print("[yellow]No snapshots available to delete[/yellow]")
        return
    
    console.print("[bold red]Delete Snapshot[/bold red]")
    console.print()
    
    # Select snapshot to delete
    choices = []
    for snap_id, snap in manager.snapshots.items():
        status_icon = "✅" if snap.status == SnapshotStatus.ACTIVE else "❌"
        children_info = f" ({len(snap.children_ids)} children)" if snap.children_ids else ""
        choices.append(
            questionary.Choice(
                f"{status_icon} {snap.name} - {snap.description[:50]}{children_info}",
                value=snap_id
            )
        )
    
    snapshot_id = questionary.select("Select snapshot to delete", choices=choices).ask()
    if not snapshot_id:
        return
    
    snapshot = manager.snapshots[snapshot_id]
    
    # Show snapshot details
    console.print("\n[bold]Snapshot Details:[/bold]")
    console.print(f"Name: {snapshot.name}")
    console.print(f"Description: {snapshot.description}")
    console.print(f"Created: {snapshot.timestamp}")
    console.print(f"Children: {len(snapshot.children_ids)}")
    
    # Confirm deletion
    if snapshot.children_ids:
        console.print(f"\n[yellow]⚠️  This snapshot has {len(snapshot.children_ids)} child snapshots[/yellow]")
        force = Confirm.ask("Delete entire branch (including children)?", default=False)
    else:
        force = False
    
    if Confirm.ask(f"Are you sure you want to delete '{snapshot.name}'?", default=False):
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Deleting snapshot...", total=None)
            
            success = manager.delete_snapshot(snapshot_id, force=force)
            
            if success:
                progress.update(task, description="Snapshot deleted successfully!")
                console.print(f"\n[green]✅ Snapshot '{snapshot.name}' deleted[/green]")
            else:
                progress.update(task, description="Failed to delete snapshot")
                console.print("\n[red]❌ Failed to delete snapshot[/red]")


def handle_restore_snapshot(manager: SnapshotManager):
    """Handle snapshot restoration"""
    
    active_snapshots = {
        snap_id: snap for snap_id, snap in manager.snapshots.items()
        if snap.status == SnapshotStatus.ACTIVE
    }
    
    if not active_snapshots:
        console.print("[yellow]No active snapshots available for restoration[/yellow]")
        return
    
    console.print("[bold yellow]Restore from Snapshot[/bold yellow]")
    console.print()
    
    # Select snapshot to restore
    choices = []
    for snap_id, snap in active_snapshots.items():
        age_days = (__import__('datetime').datetime.now() - 
                   __import__('datetime').datetime.fromisoformat(snap.timestamp)).days
        choices.append(
            questionary.Choice(
                f"{snap.name} - {snap.description[:50]} ({age_days} days old)",
                value=snap_id
            )
        )
    
    snapshot_id = questionary.select("Select snapshot to restore", choices=choices).ask()
    if not snapshot_id:
        return
    
    snapshot = active_snapshots[snapshot_id]
    
    # Show warning and confirm
    console.print("\n[bold red]⚠️  WARNING[/bold red]")
    console.print("Restoring will:")
    console.print("• Create a backup of the current state")
    console.print("• Replace current VM state with the selected snapshot")
    console.print("• This action cannot be easily undone")
    console.print()
    console.print(f"[bold]Restoring to:[/bold] {snapshot.name}")
    console.print(f"[bold]Created:[/bold] {snapshot.timestamp}")
    
    if Confirm.ask("Continue with restoration?", default=False):
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Restoring snapshot...", total=None)
            
            success = manager.restore_snapshot(snapshot_id)
            
            if success:
                progress.update(task, description="Snapshot restored successfully!")
                console.print(f"\n[green]✅ Successfully restored to '{snapshot.name}'[/green]")
            else:
                progress.update(task, description="Failed to restore snapshot")
                console.print("\n[red]❌ Failed to restore snapshot[/red]")


def handle_search_snapshots(manager: SnapshotManager):
    """Handle snapshot search"""
    
    if not manager.snapshots:
        console.print("[yellow]No snapshots available to search[/yellow]")
        return
    
    console.print("[bold blue]Search Snapshots[/bold blue]")
    console.print()
    
    # Get search criteria
    name_pattern = Prompt.ask("Name pattern (optional)", default="")
    tags_input = Prompt.ask("Tags (comma-separated, optional)", default="")
    tags = [tag.strip() for tag in tags_input.split(",") if tag.strip()] if tags_input else None
    
    # Date range
    date_from = Prompt.ask("From date (YYYY-MM-DD, optional)", default="")
    date_to = Prompt.ask("To date (YYYY-MM-DD, optional)", default="")
    
    # Convert dates
    if date_from:
        try:
            date_from = __import__('datetime').datetime.strptime(date_from, "%Y-%m-%d").isoformat()
        except ValueError:
            console.print("[red]Invalid from date format[/red]")
            date_from = None
    
    if date_to:
        try:
            date_to = __import__('datetime').datetime.strptime(date_to, "%Y-%m-%d").isoformat()
        except ValueError:
            console.print("[red]Invalid to date format[/red]")
            date_to = None
    
    # Perform search
    results = manager.search_snapshots(
        name_pattern=name_pattern or None,
        tags=tags,
        date_from=date_from,
        date_to=date_to
    )
    
    if not results:
        console.print("[yellow]No snapshots found matching criteria[/yellow]")
        return
    
    # Display results
    table = Table(title=f"Search Results ({len(results)} found)")
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Created", style="green")
    table.add_column("Tags", style="yellow")
    table.add_column("Type", style="blue")
    
    for snap_id in results:
        snap = manager.snapshots[snap_id]
        table.add_row(
            snap.name,
            snap.description[:30] + "..." if len(snap.description) > 30 else snap.description,
            snap.timestamp[:10],  # Just the date part
            ", ".join(snap.tags[:3]),  # First 3 tags
            snap.snapshot_type.value
        )
    
    console.print(table)


def handle_snapshot_details(manager: SnapshotManager):
    """Handle viewing snapshot details"""
    
    if not manager.snapshots:
        console.print("[yellow]No snapshots available[/yellow]")
        return
    
    # Select snapshot
    choices = [
        questionary.Choice(f"{snap.name} ({snap_id[:8]})", value=snap_id)
        for snap_id, snap in manager.snapshots.items()
    ]
    
    snapshot_id = questionary.select("Select snapshot to view", choices=choices).ask()
    if not snapshot_id:
        return
    
    # Get detailed info
    info = manager.get_snapshot_info(snapshot_id)
    if not info:
        console.print("[red]Snapshot not found[/red]")
        return
    
    # Create details table
    table = Table(title=f"Snapshot Details - {info['name']}")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")
    
    table.add_row("ID", info['id'])
    table.add_row("Name", info['name'])
    table.add_row("Description", info['description'] or "None")
    table.add_row("Created", info['timestamp'])
    table.add_row("Age", f"{info['age_days']} days")
    table.add_row("Size", f"{info['size_mb']} MB")
    table.add_row("Status", info['status'])
    table.add_row("Type", info['type'])
    table.add_row("Created By", info['created_by'])
    table.add_row("Tags", ", ".join(info['tags']) if info['tags'] else "None")
    table.add_row("Parent", info['parent_name'] or "None")
    table.add_row("Children", ", ".join(info['children_names']) if info['children_names'] else "None")
    table.add_row("Retention Days", str(info['retention_days']) if info['retention_days'] else "None")
    table.add_row("Disk Path", info['disk_path'])
    table.add_row("Snapshot Path", info['snapshot_path'])
    
    console.print(table)


def handle_edit_snapshot(manager: SnapshotManager):
    """Handle editing snapshot metadata"""
    
    if not manager.snapshots:
        console.print("[yellow]No snapshots available to edit[/yellow]")
        return
    
    # Select snapshot
    choices = [
        questionary.Choice(f"{snap.name} - {snap.description[:30]}", value=snap_id)
        for snap_id, snap in manager.snapshots.items()
    ]
    
    snapshot_id = questionary.select("Select snapshot to edit", choices=choices).ask()
    if not snapshot_id:
        return
    
    snapshot = manager.snapshots[snapshot_id]
    
    console.print(f"\n[bold]Editing: {snapshot.name}[/bold]")
    console.print()
    
    # Get new values
    new_name = Prompt.ask("New name", default=snapshot.name)
    new_description = Prompt.ask("New description", default=snapshot.description)
    
    tags_input = Prompt.ask("Tags (comma-separated)", default=", ".join(snapshot.tags))
    new_tags = [tag.strip() for tag in tags_input.split(",") if tag.strip()]
    
    retention_input = Prompt.ask(
        "Retention days", 
        default=str(snapshot.retention_days) if snapshot.retention_days else ""
    )
    new_retention = int(retention_input) if retention_input.isdigit() else None
    
    # Update metadata
    success = manager.update_snapshot_metadata(
        snapshot_id,
        name=new_name,
        description=new_description,
        tags=new_tags,
        retention_days=new_retention
    )
    
    if success:
        console.print("\n[green]✅ Snapshot metadata updated[/green]")
    else:
        console.print("\n[red]❌ Failed to update metadata[/red]")


def handle_merge_snapshots(manager: SnapshotManager):
    """Handle snapshot merging"""
    
    active_snapshots = {
        snap_id: snap for snap_id, snap in manager.snapshots.items()
        if snap.status == SnapshotStatus.ACTIVE
    }
    
    if len(active_snapshots) < 2:
        console.print("[yellow]Need at least 2 active snapshots to merge[/yellow]")
        return
    
    console.print("[bold purple]Merge Snapshots[/bold purple]")
    console.print()
    
    # Select source snapshot
    choices = [
        questionary.Choice(f"{snap.name} - {snap.description[:30]}", value=snap_id)
        for snap_id, snap in active_snapshots.items()
    ]
    
    source_id = questionary.select("Select source snapshot (will be deleted)", choices=choices).ask()
    if not source_id:
        return
    
    # Select target snapshot (exclude source)
    target_choices = [
        questionary.Choice(f"{snap.name} - {snap.description[:30]}", value=snap_id)
        for snap_id, snap in active_snapshots.items()
        if snap_id != source_id
    ]
    
    target_id = questionary.select("Select target snapshot (will receive merge)", choices=target_choices).ask()
    if not target_id:
        return
    
    source_snap = active_snapshots[source_id]
    target_snap = active_snapshots[target_id]
    
    console.print("\n[bold]Merge Operation:[/bold]")
    console.print(f"Source: {source_snap.name} → Target: {target_snap.name}")
    console.print("[red]Warning: Source snapshot will be deleted after merge[/red]")
    
    if Confirm.ask("Continue with merge?", default=False):
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Merging snapshots...", total=None)
            
            success = manager.merge_snapshots(source_id, target_id)
            
            if success:
                progress.update(task, description="Snapshots merged successfully!")
                console.print("\n[green]✅ Successfully merged snapshots[/green]")
            else:
                progress.update(task, description="Failed to merge snapshots")
                console.print("\n[red]❌ Failed to merge snapshots[/red]")


def handle_cleanup_snapshots(manager: SnapshotManager):
    """Handle snapshot cleanup"""
    
    console.print("[bold orange1]Snapshot Cleanup[/bold orange1]")
    console.print()
    
    # Show current policy
    policy = manager.get_retention_policy()
    console.print("[bold]Current Retention Policy:[/bold]")
    console.print(f"Max Snapshots: {policy.max_snapshots}")
    console.print(f"Max Age: {policy.max_age_days} days")
    console.print(f"Keep Daily: {policy.keep_daily}")
    console.print(f"Keep Weekly: {policy.keep_weekly}")
    console.print(f"Keep Monthly: {policy.keep_monthly}")
    console.print(f"Auto Cleanup: {policy.auto_cleanup}")
    console.print()
    
    # Dry run first
    console.print("[yellow]Running cleanup analysis...[/yellow]")
    result = manager.apply_retention_policy(dry_run=True)
    
    console.print("\n[bold]Cleanup Analysis:[/bold]")
    console.print(f"Snapshots to delete: {len(result['deleted'])}")
    console.print(f"Snapshots to keep: {len(result['kept'])}")
    
    if result['deleted']:
        console.print("\n[red]Snapshots that would be deleted:[/red]")
        for snap_id in result['deleted']:
            if snap_id in manager.snapshots:
                snap = manager.snapshots[snap_id]
                console.print(f"  • {snap.name} ({snap.timestamp[:10]})")
    
    if result['deleted'] and Confirm.ask("\nProceed with cleanup?", default=False):
        console.print("[yellow]Applying retention policy...[/yellow]")
        final_result = manager.apply_retention_policy(dry_run=False)
        console.print(f"[green]✅ Cleanup complete. Deleted {len(final_result['deleted'])} snapshots[/green]")
    else:
        console.print("[yellow]Cleanup cancelled[/yellow]")


def handle_retention_policy(manager: SnapshotManager):
    """Handle retention policy configuration"""
    
    current_policy = manager.get_retention_policy()
    
    console.print("[bold blue]Retention Policy Configuration[/bold blue]")
    console.print()
    
    # Get new policy values
    max_snapshots = int(Prompt.ask("Max snapshots", default=str(current_policy.max_snapshots)))
    max_age_days = int(Prompt.ask("Max age (days)", default=str(current_policy.max_age_days)))
    keep_daily = int(Prompt.ask("Keep daily", default=str(current_policy.keep_daily)))
    keep_weekly = int(Prompt.ask("Keep weekly", default=str(current_policy.keep_weekly)))
    keep_monthly = int(Prompt.ask("Keep monthly", default=str(current_policy.keep_monthly)))
    auto_cleanup = Confirm.ask("Enable auto cleanup", default=current_policy.auto_cleanup)
    
    # Create new policy
    new_policy = RetentionPolicy(
        max_snapshots=max_snapshots,
        max_age_days=max_age_days,
        keep_daily=keep_daily,
        keep_weekly=keep_weekly,
        keep_monthly=keep_monthly,
        auto_cleanup=auto_cleanup
    )
    
    # Set policy
    manager.set_retention_policy(new_policy)
    console.print("[green]✅ Retention policy updated[/green]")


def handle_export_metadata(manager: SnapshotManager):
    """Handle metadata export"""
    
    console.print("[bold green]Export Snapshot Metadata[/bold green]")
    console.print()
    
    output_file = Prompt.ask(
        "Output file", 
        default=f"{manager.vm_name}_snapshots_export.json"
    )
    
    try:
        result_file = manager.export_snapshot_metadata(output_file)
        console.print(f"[green]✅ Metadata exported to {result_file}[/green]")
    except Exception as e:
        console.print(f"[red]❌ Export failed: {e}[/red]")


def handle_import_metadata(manager: SnapshotManager):
    """Handle metadata import"""
    
    console.print("[bold green]Import Snapshot Metadata[/bold green]")
    console.print()
    
    import_file = Prompt.ask("Import file path")
    
    if not os.path.exists(import_file):
        console.print(f"[red]File not found: {import_file}[/red]")
        return
    
    merge = Confirm.ask("Merge with existing snapshots?", default=True)
    
    try:
        success = manager.import_snapshot_metadata(import_file, merge=merge)
        if success:
            console.print("[green]✅ Metadata imported successfully[/green]")
        else:
            console.print("[red]❌ Import failed[/red]")
    except Exception as e:
        console.print(f"[red]❌ Import failed: {e}[/red]")