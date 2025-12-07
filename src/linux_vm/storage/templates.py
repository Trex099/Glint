import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from core_utils import wait_for_enter

#!/usr/bin/env python3
# Made by trex099
# https://github.com/Trex099/Glint
"""
Storage Templates System for Linux VMs

This module provides pre-configured storage layout templates with:
- Template creation and customization
- Template inheritance and versioning
- Template validation and compatibility checking
- Template sharing and import/export capabilities
- TUI for template management
"""

import os
import json
import subprocess
import uuid
import re
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Any
from enum import Enum
import questionary
from rich.console import Console
from rich.table import Table
# from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

# Import from main module
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
from src.linux_vm.main import print_header, print_info, print_success, print_warning, print_error

console = Console()

class TemplateType(Enum):
    """Storage template types"""
    BASIC = "basic"
    PERFORMANCE = "performance"
    DEVELOPMENT = "development"
    DATABASE = "database"
    GAMING = "gaming"
    BACKUP = "backup"
    CUSTOM = "custom"

class TemplateStatus(Enum):
    """Template status"""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DRAFT = "draft"
    ARCHIVED = "archived"

@dataclass
class DiskTemplate:
    """Individual disk configuration template"""
    name: str
    size: str  # e.g., "50G", "100G"
    disk_type: str = "qcow2"  # qcow2, raw, vmdk
    interface: str = "virtio"  # virtio, ide, scsi
    cache_mode: str = "writeback"  # writeback, writethrough, none
    encrypted: bool = False
    description: str = ""
    mount_point: str = ""  # Suggested mount point
    filesystem: str = "ext4"  # Suggested filesystem

@dataclass
class StorageTemplate:
    """Storage layout template configuration"""
    id: str
    name: str
    template_type: TemplateType
    version: str
    description: str
    disks: List[DiskTemplate]
    status: TemplateStatus = TemplateStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    author: str = "system"
    tags: List[str] = field(default_factory=list)
    parent_template_id: Optional[str] = None  # For inheritance
    compatibility: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())

class StorageTemplateManager:
    """Centralized storage template management system"""
    
    def __init__(self, config_dir: str = None):
        """Initialize storage template manager"""
        if config_dir is None:
            config_dir = os.path.join(os.path.expanduser("~"), ".glint", "storage_templates")
        
        self.config_dir = config_dir
        self.templates_file = os.path.join(config_dir, "templates.json")
        self.exports_dir = os.path.join(config_dir, "exports")
        self.imports_dir = os.path.join(config_dir, "imports")
        
        # Ensure directories exist
        os.makedirs(config_dir, exist_ok=True)
        os.makedirs(self.exports_dir, exist_ok=True)
        os.makedirs(self.imports_dir, exist_ok=True)
        
        self.templates: Dict[str, StorageTemplate] = {}
        self._load_templates()
        self._create_default_templates()
    
    def create_template(self, name: str, template_type: TemplateType, 
                       description: str, disks: List[DiskTemplate],
                       **kwargs) -> StorageTemplate:
        """Create a new storage template"""
        template = StorageTemplate(
            id=str(uuid.uuid4()),
            name=name,
            template_type=template_type,
            version="1.0.0",
            description=description,
            disks=disks,
            **kwargs
        )
        
        self.templates[template.id] = template
        self._save_templates()
        return template
    
    def get_template(self, template_id: str) -> Optional[StorageTemplate]:
        """Get template by ID"""
        return self.templates.get(template_id)
    
    def get_template_by_name(self, name: str) -> Optional[StorageTemplate]:
        """Get template by name"""
        for template in self.templates.values():
            if template.name == name:
                return template
        return None
    
    def list_templates(self, template_type: TemplateType = None, 
                      status: TemplateStatus = None) -> List[StorageTemplate]:
        """List templates with optional filtering"""
        templates = list(self.templates.values())
        
        if template_type:
            templates = [t for t in templates if t.template_type == template_type]
        
        if status:
            templates = [t for t in templates if t.status == status]
        
        return sorted(templates, key=lambda t: t.name)
    
    def update_template(self, template_id: str, **updates) -> bool:
        """Update an existing template"""
        try:
            if template_id not in self.templates:
                raise ValueError(f"Template '{template_id}' not found")
            
            template = self.templates[template_id]
            
            # Update fields
            for key, value in updates.items():
                if hasattr(template, key):
                    setattr(template, key, value)
            
            # Update timestamp
            template.updated_at = datetime.now()
            
            # Increment version if significant changes
            if any(key in ['disks', 'template_type'] for key in updates.keys()):
                version_parts = template.version.split('.')
                version_parts[1] = str(int(version_parts[1]) + 1)
                template.version = '.'.join(version_parts)
            
            self._save_templates()
            return True
            
        except Exception as e:
            print_error(f"Failed to update template: {e}")
            return False
    
    def delete_template(self, template_id: str) -> bool:
        """Delete a template"""
        try:
            if template_id not in self.templates:
                raise ValueError(f"Template '{template_id}' not found")
            
            # Check if template is being used as parent
            children = [t for t in self.templates.values() 
                       if t.parent_template_id == template_id]
            
            if children:
                child_names = [t.name for t in children]
                raise ValueError(f"Cannot delete template with children: {', '.join(child_names)}")
            
            del self.templates[template_id]
            self._save_templates()
            return True
            
        except Exception as e:
            print_error(f"Failed to delete template: {e}")
            return False
    
    def create_child_template(self, parent_id: str, name: str, 
                             description: str, **modifications) -> Optional[StorageTemplate]:
        """Create a child template inheriting from a parent"""
        try:
            parent = self.get_template(parent_id)
            if not parent:
                raise ValueError(f"Parent template '{parent_id}' not found")
            
            # Create child template based on parent
            child_disks = [
                DiskTemplate(
                    name=disk.name,
                    size=disk.size,
                    disk_type=disk.disk_type,
                    interface=disk.interface,
                    cache_mode=disk.cache_mode,
                    encrypted=disk.encrypted,
                    description=disk.description,
                    mount_point=disk.mount_point,
                    filesystem=disk.filesystem
                ) for disk in parent.disks
            ]
            
            child = StorageTemplate(
                id=str(uuid.uuid4()),
                name=name,
                template_type=parent.template_type,
                version="1.0.0",
                description=description,
                disks=child_disks,
                parent_template_id=parent_id,
                tags=parent.tags.copy(),
                compatibility=parent.compatibility.copy(),
                metadata=parent.metadata.copy()
            )
            
            # Apply modifications
            for key, value in modifications.items():
                if hasattr(child, key):
                    setattr(child, key, value)
            
            self.templates[child.id] = child
            self._save_templates()
            return child
            
        except Exception as e:
            print_error(f"Failed to create child template: {e}")
            return None
    
    def validate_template(self, template: StorageTemplate) -> Dict[str, List[str]]:
        """Validate template configuration"""
        result = {"errors": [], "warnings": []}
        
        # Basic validation
        if not template.name.strip():
            result["errors"].append("Template name cannot be empty")
        
        if not template.disks:
            result["errors"].append("Template must have at least one disk")
        
        # Disk validation
        disk_names = []
        total_size_gb = 0
        
        for disk in template.disks:
            # Check for duplicate names
            if disk.name in disk_names:
                result["errors"].append(f"Duplicate disk name: {disk.name}")
            disk_names.append(disk.name)
            
            # Validate disk size format
            if not self._validate_size_format(disk.size):
                result["errors"].append(f"Invalid size format for disk '{disk.name}': {disk.size}")
            else:
                total_size_gb += self._parse_size_to_gb(disk.size)
            
            # Check disk type
            if disk.disk_type not in ["qcow2", "raw", "vmdk"]:
                result["warnings"].append(f"Unusual disk type for '{disk.name}': {disk.disk_type}")
            
            # Check interface
            if disk.interface not in ["virtio", "ide", "scsi"]:
                result["warnings"].append(f"Unusual interface for '{disk.name}': {disk.interface}")
        
        # Size warnings
        if total_size_gb > 500:
            result["warnings"].append(f"Large total size: {total_size_gb}GB")
        elif total_size_gb < 10:
            result["warnings"].append(f"Small total size: {total_size_gb}GB")
        
        return result
    
    def check_compatibility(self, template: StorageTemplate, 
                          vm_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """Check template compatibility with VM configuration"""
        report = {
            "compatible": True,
            "issues": [],
            "recommendations": []
        }
        
        # Check template validation first
        validation = self.validate_template(template)
        if validation["errors"]:
            report["compatible"] = False
            report["issues"].extend(validation["errors"])
        
        # Add warnings as recommendations
        report["recommendations"].extend(validation["warnings"])
        
        # VM-specific compatibility checks
        if vm_config:
            # Check memory requirements
            vm_memory_gb = self._parse_memory_to_gb(vm_config.get("memory", "4G"))
            total_disk_gb = sum(self._parse_size_to_gb(disk.size) for disk in template.disks)
            
            if total_disk_gb > vm_memory_gb * 10:
                report["recommendations"].append(
                    f"Large disk-to-memory ratio: {total_disk_gb}GB disk vs {vm_memory_gb}GB RAM"
                )
            
            # Check CPU requirements for performance templates
            if template.template_type == TemplateType.PERFORMANCE:
                vm_cpus = int(vm_config.get("cpu_cores", "2"))
                if vm_cpus < 4:
                    report["recommendations"].append(
                        "Performance template recommended with 4+ CPU cores"
                    )
        
        return report
    
    def export_template(self, template_id: str, export_path: str = None) -> bool:
        """Export template to file"""
        try:
            template = self.get_template(template_id)
            if not template:
                raise ValueError(f"Template '{template_id}' not found")
            
            if export_path is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{template.name}_{timestamp}.json"
                export_path = os.path.join(self.exports_dir, filename)
            
            # Create export data
            export_data = {
                "format_version": "1.0",
                "export_timestamp": datetime.now().isoformat(),
                "template": self._template_to_dict(template)
            }
            
            # Write to file
            with open(export_path, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)
            
            print_success(f"Template exported to: {export_path}")
            return True
            
        except Exception as e:
            print_error(f"Failed to export template: {e}")
            return False
    
    def import_template(self, import_path: str, overwrite: bool = False) -> Optional[StorageTemplate]:
        """Import template from file"""
        try:
            if not os.path.exists(import_path):
                raise ValueError(f"Import file not found: {import_path}")
            
            with open(import_path, 'r') as f:
                import_data = json.load(f)
            
            # Validate import format
            if import_data.get("format_version") != "1.0":
                raise ValueError("Unsupported import format version")
            
            template_data = import_data["template"]
            
            # Convert back to objects
            template = self._dict_to_template(template_data)
            
            # Check for existing template
            existing = self.get_template_by_name(template.name)
            if existing and not overwrite:
                raise ValueError(f"Template '{template.name}' already exists. Use overwrite=True to replace.")
            
            # Generate new ID if importing
            template.id = str(uuid.uuid4())
            template.updated_at = datetime.now()
            
            # Validate imported template
            validation = self.validate_template(template)
            if validation["errors"]:
                raise ValueError(f"Invalid template: {', '.join(validation['errors'])}")
            
            self.templates[template.id] = template
            self._save_templates()
            
            print_success(f"Template '{template.name}' imported successfully")
            return template
            
        except Exception as e:
            print_error(f"Failed to import template: {e}")
            return None
    
    def apply_template_to_vm(self, template_id: str, vm_name: str, vm_path: str) -> bool:
        """Apply storage template to a VM"""
        try:
            template = self.get_template(template_id)
            if not template:
                raise ValueError(f"Template '{template_id}' not found")
            
            # Validate template
            validation = self.validate_template(template)
            if validation["errors"]:
                raise ValueError(f"Template validation failed: {', '.join(validation['errors'])}")
            
            # Create disks directory
            disks_dir = os.path.join(vm_path, "disks")
            os.makedirs(disks_dir, exist_ok=True)
            
            # Create each disk from template
            created_disks = []
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                
                for disk_template in template.disks:
                    task = progress.add_task(f"Creating disk {disk_template.name}...", total=None)
                    
                    # Skip system disk (usually handled separately)
                    if disk_template.name.lower() in ["system", "base", "root"]:
                        continue
                    
                    disk_filename = f"{disk_template.name}.{disk_template.disk_type}"
                    disk_path = os.path.join(disks_dir, disk_filename)
                    
                    # Create disk using qemu-img
                    cmd = [
                        "qemu-img", "create", 
                        "-f", disk_template.disk_type,
                        disk_path, disk_template.size
                    ]
                    
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        raise ValueError(f"Failed to create disk '{disk_template.name}': {result.stderr}")
                    
                    created_disks.append({
                        "name": disk_template.name,
                        "path": disk_path,
                        "template": disk_template
                    })
                    
                    progress.update(task, description=f"Created disk {disk_template.name}")
            
            # Save disk configuration
            disk_config = {
                "template_id": template_id,
                "template_name": template.name,
                "applied_at": datetime.now().isoformat(),
                "disks": created_disks
            }
            
            config_path = os.path.join(vm_path, "storage_template.json")
            with open(config_path, 'w') as f:
                json.dump(disk_config, f, indent=2, default=str)
            
            print_success(f"Applied template '{template.name}' to VM '{vm_name}'")
            return True
            
        except Exception as e:
            print_error(f"Failed to apply template: {e}")
            return False
    
    def _create_default_templates(self):
        """Create default storage templates if they don't exist"""
        default_templates = [
            {
                "name": "Basic Single Disk",
                "template_type": TemplateType.BASIC,
                "description": "Simple single disk configuration for basic VMs",
                "disks": [
                    DiskTemplate(
                        name="system",
                        size="50G",
                        description="Main system disk",
                        mount_point="/",
                        filesystem="ext4"
                    )
                ]
            },
            {
                "name": "Development Environment",
                "template_type": TemplateType.DEVELOPMENT,
                "description": "Multi-disk setup optimized for development work",
                "disks": [
                    DiskTemplate(
                        name="system",
                        size="40G",
                        description="System and applications",
                        mount_point="/",
                        filesystem="ext4"
                    ),
                    DiskTemplate(
                        name="workspace",
                        size="100G",
                        description="Development workspace",
                        mount_point="/home/dev",
                        filesystem="ext4"
                    ),
                    DiskTemplate(
                        name="cache",
                        size="20G",
                        cache_mode="none",
                        description="Build cache and temporary files",
                        mount_point="/tmp/cache",
                        filesystem="tmpfs"
                    )
                ]
            },
            {
                "name": "High Performance Gaming",
                "template_type": TemplateType.GAMING,
                "description": "Optimized storage for gaming VMs with GPU passthrough",
                "disks": [
                    DiskTemplate(
                        name="system",
                        size="80G",
                        interface="virtio",
                        cache_mode="writeback",
                        description="System disk with fast access",
                        mount_point="/",
                        filesystem="ext4"
                    ),
                    DiskTemplate(
                        name="games",
                        size="500G",
                        interface="virtio",
                        cache_mode="none",
                        description="Game storage with direct I/O",
                        mount_point="/games",
                        filesystem="ntfs"
                    )
                ]
            },
            {
                "name": "Database Server",
                "template_type": TemplateType.DATABASE,
                "description": "Optimized for database workloads with separate data and log disks",
                "disks": [
                    DiskTemplate(
                        name="system",
                        size="30G",
                        description="Operating system",
                        mount_point="/",
                        filesystem="ext4"
                    ),
                    DiskTemplate(
                        name="database",
                        size="200G",
                        interface="virtio",
                        cache_mode="none",
                        description="Database files",
                        mount_point="/var/lib/database",
                        filesystem="ext4"
                    ),
                    DiskTemplate(
                        name="logs",
                        size="50G",
                        interface="virtio",
                        cache_mode="writethrough",
                        description="Database logs",
                        mount_point="/var/log/database",
                        filesystem="ext4"
                    )
                ]
            }
        ]
        
        for template_data in default_templates:
            # Check if template already exists
            if not self.get_template_by_name(template_data["name"]):
                self.create_template(**template_data)
    
    def _load_templates(self):
        """Load templates from configuration file"""
        try:
            if os.path.exists(self.templates_file):
                with open(self.templates_file, 'r') as f:
                    data = json.load(f)
                
                for template_data in data.get("templates", []):
                    template = self._dict_to_template(template_data)
                    self.templates[template.id] = template
                    
        except Exception as e:
            print_warning(f"Failed to load templates: {e}")
    
    def _save_templates(self):
        """Save templates to configuration file"""
        try:
            data = {
                "version": "1.0",
                "templates": [self._template_to_dict(template) for template in self.templates.values()]
            }
            
            with open(self.templates_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
                
        except Exception as e:
            print_error(f"Failed to save templates: {e}")
    
    def _template_to_dict(self, template: StorageTemplate) -> Dict[str, Any]:
        """Convert template to dictionary for serialization"""
        data = asdict(template)
        
        # Convert enums to strings
        data["template_type"] = template.template_type.value
        data["status"] = template.status.value
        
        # Convert datetime to string
        data["created_at"] = template.created_at.isoformat()
        data["updated_at"] = template.updated_at.isoformat()
        
        return data
    
    def _dict_to_template(self, data: Dict[str, Any]) -> StorageTemplate:
        """Convert dictionary to template object"""
        # Convert strings back to enums
        data["template_type"] = TemplateType(data["template_type"])
        data["status"] = TemplateStatus(data["status"])
        
        # Convert strings back to datetime
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        
        # Convert disk dictionaries to DiskTemplate objects
        disks_data = data.pop("disks", [])
        disks = [DiskTemplate(**disk_data) for disk_data in disks_data]
        data["disks"] = disks
        
        return StorageTemplate(**data)
    
    def _validate_size_format(self, size: str) -> bool:
        """Validate disk size format (e.g., '50G', '1024M')"""
        pattern = r'^\d+[KMGT]$'
        return bool(re.match(pattern, size.upper()))
    
    def _parse_size_to_gb(self, size: str) -> float:
        """Parse size string to GB"""
        size = size.upper()
        if size.endswith('K'):
            return float(size[:-1]) / 1024 / 1024
        elif size.endswith('M'):
            return float(size[:-1]) / 1024
        elif size.endswith('G'):
            return float(size[:-1])
        elif size.endswith('T'):
            return float(size[:-1]) * 1024
        else:
            return float(size) / 1024**3  # Assume bytes
    
    def _parse_memory_to_gb(self, memory: str) -> float:
        """Parse memory string to GB"""
        return self._parse_size_to_gb(memory)

# Utility function for clearing screen
def clear_screen():
    """Clear the terminal screen"""
    os.system('clear' if os.name == 'posix' else 'cls')

# TUI Functions
def display_templates_summary(manager: StorageTemplateManager):
    """Display summary of available templates"""
    templates = manager.list_templates()
    
    if not templates:
        console.print("[yellow]No templates available[/yellow]")
        return
    
    # Separate default and user templates
    default_templates = [t for t in templates if t.author == "system"]
    user_templates = [t for t in templates if t.author != "system"]
    
    # Show user templates first if any exist
    if user_templates:
        table = Table(title="Your Custom Templates")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Disks", style="yellow")
        table.add_column("Total Size", style="blue")
        table.add_column("Status", style="magenta")
        
        for template in user_templates[:5]:  # Show first 5 user templates
            total_size = sum(manager._parse_size_to_gb(disk.size) for disk in template.disks)
            status_icon = "✅" if template.status == TemplateStatus.ACTIVE else "⚠️"
            
            table.add_row(
                template.name,
                template.template_type.value.title(),
                str(len(template.disks)),
                f"{total_size:.1f}GB",
                f"{status_icon} {template.status.value.title()}"
            )
        
        if len(user_templates) > 5:
            table.add_row("...", f"({len(user_templates) - 5} more)", "", "", "")
        
        console.print(table)
        console.print()
    
    # Show default templates summary
    if default_templates:
        console.print(f"[dim]Built-in Templates Available: {len(default_templates)} (Basic, Development, Gaming, Database)[/dim]")
        console.print("[dim]Use 'View All Templates' to see built-in template details[/dim]")
        console.print()
    
    # Show summary stats
    if user_templates:
        console.print(f"[bold]Summary:[/bold] {len(user_templates)} custom template(s), {len(default_templates)} built-in template(s)")
    else:
        console.print("[yellow]No custom templates created yet.[/yellow]")
        console.print(f"[dim]{len(default_templates)} built-in templates available as starting points.[/dim]")

def storage_templates_menu():
    """Main storage templates management menu"""
    manager = StorageTemplateManager()
    
    while True:
        clear_screen()
        print_header("Storage Templates Management")
        
        # Display template summary
        display_templates_summary(manager)
        
        choice = questionary.select(
            "Select an option:",
            choices=[
                questionary.Choice("📋 View All Templates (Built-in & Custom)", value="view_all"),
                questionary.Choice("➕ Create New Custom Template", value="create"),
                questionary.Choice("✏️  Edit Template", value="edit"),
                questionary.Choice("👥 Create Child Template (from Built-in)", value="create_child"),
                questionary.Choice("🔍 Template Details", value="details"),
                questionary.Choice("✅ Validate Template", value="validate"),
                questionary.Choice("📤 Export Template", value="export"),
                questionary.Choice("📥 Import Template", value="import"),
                questionary.Choice("🗑️ Delete Template", value="delete"),
                questionary.Separator(),
                questionary.Choice("🔙 Back to Storage Menu", value="back")
            ],
            use_indicator=True
        ).ask()
        
        if choice == "back" or choice is None:
            break
        
        try:
            if choice == "view_all":
                view_all_templates(manager)
            elif choice == "create":
                create_template_interactive(manager)
            elif choice == "edit":
                edit_template_interactive(manager)
            elif choice == "create_child":
                create_child_template_interactive(manager)
            elif choice == "details":
                view_template_details(manager)
            elif choice == "validate":
                validate_template_interactive(manager)
            elif choice == "export":
                export_template_interactive(manager)
            elif choice == "import":
                import_template_interactive(manager)
            elif choice == "delete":
                delete_template_interactive(manager)
        except Exception as e:
            print_error(f"Error: {e}")
        
        if choice != "back":
            wait_for_enter()

def view_all_templates(manager: StorageTemplateManager):
    """View all templates with detailed information"""
    clear_screen()
    print_header("All Storage Templates")
    
    templates = manager.list_templates()
    
    if not templates:
        print_warning("No templates available")
        return
    
    # Separate built-in and custom templates
    default_templates = [t for t in templates if t.author == "system"]
    user_templates = [t for t in templates if t.author != "system"]
    
    # Show custom templates first
    if user_templates:
        console.print(f"\n[bold green]Your Custom Templates ({len(user_templates)})[/bold green]")
        console.rule(style="dim")
        
        # Group custom templates by type
        by_type = {}
        for template in user_templates:
            template_type = template.template_type.value
            if template_type not in by_type:
                by_type[template_type] = []
            by_type[template_type].append(template)
        
        for template_type, type_templates in by_type.items():
            console.print(f"\n[bold]{template_type.title()} Templates[/bold]")
            
            table = Table()
            table.add_column("Name", style="cyan")
            table.add_column("Description", style="white")
            table.add_column("Disks", style="yellow")
            table.add_column("Size", style="green")
            table.add_column("Version", style="blue")
            table.add_column("Status", style="magenta")
            
            for template in type_templates:
                total_size = sum(manager._parse_size_to_gb(disk.size) for disk in template.disks)
                disk_info = ", ".join([f"{disk.name}({disk.size})" for disk in template.disks])
                if len(disk_info) > 30:
                    disk_info = disk_info[:27] + "..."
                
                status_icon = "✅" if template.status == TemplateStatus.ACTIVE else "⚠️"
                
                table.add_row(
                    template.name,
                    template.description[:40] + "..." if len(template.description) > 40 else template.description,
                    disk_info,
                    f"{total_size:.1f}GB",
                    template.version,
                    f"{status_icon} {template.status.value}"
                )
            
            console.print(table)
    
    # Show built-in templates
    if default_templates:
        console.print(f"\n[bold dim]Built-in Templates ({len(default_templates)}) - Ready to Use[/bold dim]")
        console.rule(style="dim")
        
        # Group built-in templates by type
        by_type = {}
        for template in default_templates:
            template_type = template.template_type.value
            if template_type not in by_type:
                by_type[template_type] = []
            by_type[template_type].append(template)
        
        for template_type, type_templates in by_type.items():
            console.print(f"\n[dim]{template_type.title()} Templates[/dim]")
            
            table = Table()
            table.add_column("Name", style="dim cyan")
            table.add_column("Description", style="dim white")
            table.add_column("Disks", style="dim yellow")
            table.add_column("Size", style="dim green")
            
            for template in type_templates:
                total_size = sum(manager._parse_size_to_gb(disk.size) for disk in template.disks)
                disk_info = ", ".join([f"{disk.name}({disk.size})" for disk in template.disks])
                if len(disk_info) > 30:
                    disk_info = disk_info[:27] + "..."
                
                table.add_row(
                    f"📋 {template.name}",
                    template.description[:50] + "..." if len(template.description) > 50 else template.description,
                    disk_info,
                    f"{total_size:.1f}GB"
                )
            
            console.print(table)
        
        console.print("\n[dim]💡 Tip: Use 'Create Child Template' to customize built-in templates[/dim]")

def create_template_interactive(manager: StorageTemplateManager):
    """Interactive template creation"""
    clear_screen()
    print_header("Create New Storage Template")
    
    # Get basic template info
    name = questionary.text(
        "Template name:",
        validate=lambda x: len(x.strip()) > 0
    ).ask()
    
    if not name:
        return
    
    # Check if name already exists
    if manager.get_template_by_name(name):
        print_error(f"Template '{name}' already exists")
        return
    
    template_type = questionary.select(
        "Template type:",
        choices=[
            questionary.Choice("Basic - Simple single disk", TemplateType.BASIC),
            questionary.Choice("Performance - High performance setup", TemplateType.PERFORMANCE),
            questionary.Choice("Development - Multi-disk dev environment", TemplateType.DEVELOPMENT),
            questionary.Choice("Database - Database server optimized", TemplateType.DATABASE),
            questionary.Choice("Gaming - Gaming VM with GPU passthrough", TemplateType.GAMING),
            questionary.Choice("Backup - Backup and archival", TemplateType.BACKUP),
            questionary.Choice("Custom - Custom configuration", TemplateType.CUSTOM)
        ]
    ).ask()
    
    description = questionary.text(
        "Description:",
        default=f"{template_type.value.title()} storage template"
    ).ask()
    
    # Create disks
    disks = []
    disk_count = 1
    
    while True:
        console.print(f"\n[bold]Configuring Disk {disk_count}[/bold]")
        
        disk_name = questionary.text(
            "Disk name:",
            default=f"disk{disk_count}" if disk_count > 1 else "system"
        ).ask()
        
        if not disk_name:
            break
        
        disk_size = questionary.text(
            "Disk size (e.g., 50G, 100G):",
            default="50G",
            validate=lambda x: manager._validate_size_format(x)
        ).ask()
        
        disk_type = questionary.select(
            "Disk type:",
            choices=["qcow2", "raw", "vmdk"],
            default="qcow2"
        ).ask()
        
        interface = questionary.select(
            "Interface:",
            choices=["virtio", "ide", "scsi"],
            default="virtio"
        ).ask()
        
        cache_mode = questionary.select(
            "Cache mode:",
            choices=["writeback", "writethrough", "none"],
            default="writeback"
        ).ask()
        
        encrypted = questionary.confirm("Enable encryption?", default=False).ask()
        
        disk_description = questionary.text(
            "Disk description (optional):",
            default=""
        ).ask()
        
        mount_point = questionary.text(
            "Suggested mount point (optional):",
            default="/" if disk_name == "system" else f"/mnt/{disk_name}"
        ).ask()
        
        filesystem = questionary.select(
            "Suggested filesystem:",
            choices=["ext4", "xfs", "btrfs", "ntfs", "fat32"],
            default="ext4"
        ).ask()
        
        disk = DiskTemplate(
            name=disk_name,
            size=disk_size,
            disk_type=disk_type,
            interface=interface,
            cache_mode=cache_mode,
            encrypted=encrypted,
            description=disk_description,
            mount_point=mount_point,
            filesystem=filesystem
        )
        
        disks.append(disk)
        
        if not questionary.confirm("Add another disk?", default=False).ask():
            break
        
        disk_count += 1
    
    if not disks:
        print_warning("No disks configured, template creation cancelled")
        return
    
    # Create template
    try:
        template = manager.create_template(
            name=name,
            template_type=template_type,
            description=description,
            disks=disks
        )
        
        print_success(f"Created template '{template.name}' with {len(disks)} disk(s)")
        
        # Show validation results
        validation = manager.validate_template(template)
        if validation["warnings"]:
            print_warning("Template warnings:")
            for warning in validation["warnings"]:
                console.print(f"  • {warning}")
        
    except Exception as e:
        print_error(f"Failed to create template: {e}")

def edit_template_interactive(manager: StorageTemplateManager):
    """Interactive template editing"""
    clear_screen()
    print_header("Edit Storage Template")
    
    templates = manager.list_templates()
    if not templates:
        print_warning("No templates available to edit")
        return
    
    # Select template to edit
    choices = [
        questionary.Choice(f"{t.name} ({t.template_type.value})", t.id)
        for t in templates
    ]
    
    template_id = questionary.select(
        "Select template to edit:",
        choices=choices
    ).ask()
    
    if not template_id:
        return
    
    template = manager.get_template(template_id)
    
    # Edit options
    edit_choice = questionary.select(
        f"What would you like to edit in '{template.name}'?",
        choices=[
            questionary.Choice("📝 Name and Description", value="basic"),
            questionary.Choice("🏷️  Tags and Metadata", value="metadata"),
            questionary.Choice("📊 Status", value="status")
        ]
    ).ask()
    
    updates = {}
    
    if edit_choice == "basic":
        new_name = questionary.text(
            "Template name:",
            default=template.name
        ).ask()
        
        new_description = questionary.text(
            "Description:",
            default=template.description
        ).ask()
        
        if new_name != template.name:
            updates["name"] = new_name
        if new_description != template.description:
            updates["description"] = new_description
    
    elif edit_choice == "metadata":
        # Edit tags
        current_tags = ", ".join(template.tags)
        new_tags_str = questionary.text(
            "Tags (comma-separated):",
            default=current_tags
        ).ask()
        
        if new_tags_str != current_tags:
            updates["tags"] = [tag.strip() for tag in new_tags_str.split(",") if tag.strip()]
    
    elif edit_choice == "status":
        new_status = questionary.select(
            "Template status:",
            choices=[
                questionary.Choice("Active", TemplateStatus.ACTIVE),
                questionary.Choice("Deprecated", TemplateStatus.DEPRECATED),
                questionary.Choice("Draft", TemplateStatus.DRAFT),
                questionary.Choice("Archived", TemplateStatus.ARCHIVED)
            ],
            default=template.status
        ).ask()
        
        if new_status != template.status:
            updates["status"] = new_status
    
    # Apply updates
    if updates:
        if manager.update_template(template_id, **updates):
            print_success("Template updated successfully")
        else:
            print_error("Failed to update template")
    else:
        print_info("No changes made")

def create_child_template_interactive(manager: StorageTemplateManager):
    """Interactive child template creation"""
    clear_screen()
    print_header("Create Child Template (Inheritance)")
    
    templates = manager.list_templates()
    if not templates:
        print_warning("No templates available as parents")
        return
    
    # Select parent template
    choices = [
        questionary.Choice(f"{t.name} ({t.template_type.value})", t.id)
        for t in templates
    ]
    
    parent_id = questionary.select(
        "Select parent template:",
        choices=choices
    ).ask()
    
    if not parent_id:
        return
    
    parent = manager.get_template(parent_id)
    
    # Show parent info
    console.print(f"\n[bold]Parent Template: {parent.name}[/bold]")
    console.print(f"Type: {parent.template_type.value}")
    console.print(f"Disks: {len(parent.disks)}")
    console.print(f"Description: {parent.description}")
    console.print()
    
    # Get child template info
    name = questionary.text(
        "Child template name:",
        validate=lambda x: len(x.strip()) > 0 and not manager.get_template_by_name(x.strip())
    ).ask()
    
    if not name:
        return
    
    description = questionary.text(
        "Child template description:",
        default=f"Based on {parent.name}"
    ).ask()
    
    # Create child template
    try:
        child = manager.create_child_template(
            parent_id=parent_id,
            name=name,
            description=description
        )
        
        if child:
            print_success(f"Created child template '{child.name}' based on '{parent.name}'")
        else:
            print_error("Failed to create child template")
            
    except Exception as e:
        print_error(f"Failed to create child template: {e}")

def view_template_details(manager: StorageTemplateManager):
    """View detailed template information"""
    clear_screen()
    print_header("Template Details")
    
    templates = manager.list_templates()
    if not templates:
        print_warning("No templates available")
        return
    
    # Select template
    choices = [
        questionary.Choice(f"{t.name} ({t.template_type.value})", t.id)
        for t in templates
    ]
    
    template_id = questionary.select(
        "Select template to view:",
        choices=choices
    ).ask()
    
    if not template_id:
        return
    
    template = manager.get_template(template_id)
    
    # Display detailed information
    console.print(f"\n[bold cyan]{template.name}[/bold cyan]")
    console.print("=" * len(template.name))
    
    # Basic info
    info_table = Table(show_header=False, box=None)
    info_table.add_column("Field", style="yellow")
    info_table.add_column("Value", style="white")
    
    info_table.add_row("ID", template.id)
    info_table.add_row("Type", template.template_type.value.title())
    info_table.add_row("Version", template.version)
    info_table.add_row("Status", template.status.value.title())
    info_table.add_row("Author", template.author)
    info_table.add_row("Created", template.created_at.strftime("%Y-%m-%d %H:%M"))
    info_table.add_row("Updated", template.updated_at.strftime("%Y-%m-%d %H:%M"))
    
    if template.parent_template_id:
        parent = manager.get_template(template.parent_template_id)
        parent_name = parent.name if parent else "Unknown"
        info_table.add_row("Parent", parent_name)
    
    if template.tags:
        info_table.add_row("Tags", ", ".join(template.tags))
    
    console.print(info_table)
    console.print()
    
    # Description
    console.print("[bold]Description:[/bold]")
    console.print(template.description)
    console.print()
    
    # Disk configuration
    console.print("[bold]Disk Configuration:[/bold]")
    
    disk_table = Table()
    disk_table.add_column("Name", style="cyan")
    disk_table.add_column("Size", style="green")
    disk_table.add_column("Type", style="yellow")
    disk_table.add_column("Interface", style="blue")
    disk_table.add_column("Cache", style="magenta")
    disk_table.add_column("Encrypted", style="red")
    disk_table.add_column("Mount Point", style="white")
    
    total_size = 0
    for disk in template.disks:
        disk_size_gb = manager._parse_size_to_gb(disk.size)
        total_size += disk_size_gb
        
        disk_table.add_row(
            disk.name,
            disk.size,
            disk.disk_type,
            disk.interface,
            disk.cache_mode,
            "Yes" if disk.encrypted else "No",
            disk.mount_point or "N/A"
        )
    
    console.print(disk_table)
    console.print(f"\n[bold]Total Size: {total_size:.1f}GB[/bold]")
    
    # Validation
    validation = manager.validate_template(template)
    if validation["errors"] or validation["warnings"]:
        console.print("\n[bold]Validation Results:[/bold]")
        
        if validation["errors"]:
            console.print("[red]Errors:[/red]")
            for error in validation["errors"]:
                console.print(f"  ❌ {error}")
        
        if validation["warnings"]:
            console.print("[yellow]Warnings:[/yellow]")
            for warning in validation["warnings"]:
                console.print(f"  ⚠️  {warning}")
    else:
        console.print("\n[green]✅ Template validation passed[/green]")

def validate_template_interactive(manager: StorageTemplateManager):
    """Interactive template validation"""
    clear_screen()
    print_header("Template Validation")
    
    templates = manager.list_templates()
    if not templates:
        print_warning("No templates available to validate")
        return
    
    # Select template
    choices = [
        questionary.Choice(f"{t.name} ({t.template_type.value})", t.id)
        for t in templates
    ]
    
    template_id = questionary.select(
        "Select template to validate:",
        choices=choices
    ).ask()
    
    if not template_id:
        return
    
    template = manager.get_template(template_id)
    
    console.print(f"\n[bold]Validating template: {template.name}[/bold]")
    
    # Run validation
    validation = manager.validate_template(template)
    
    if not validation["errors"] and not validation["warnings"]:
        console.print("[green]✅ Template validation passed - no issues found[/green]")
        return
    
    # Display results
    if validation["errors"]:
        console.print(f"\n[red bold]❌ Errors ({len(validation['errors'])}):[/red bold]")
        for i, error in enumerate(validation["errors"], 1):
            console.print(f"  {i}. {error}")
    
    if validation["warnings"]:
        console.print(f"\n[yellow bold]⚠️  Warnings ({len(validation['warnings'])}):[/yellow bold]")
        for i, warning in enumerate(validation["warnings"], 1):
            console.print(f"  {i}. {warning}")
    
    # Compatibility check
    if questionary.confirm("\nRun compatibility check with sample VM config?").ask():
        sample_vm_config = {
            "memory": "8G",
            "cpu_cores": "4",
            "disk_space": "200G"
        }
        
        compatibility = manager.check_compatibility(template, sample_vm_config)
        
        console.print("\n[bold]Compatibility Check:[/bold]")
        if compatibility["compatible"]:
            console.print("[green]✅ Compatible with sample VM configuration[/green]")
        else:
            console.print("[red]❌ Compatibility issues found[/red]")
        
        if compatibility["issues"]:
            console.print("[red]Issues:[/red]")
            for issue in compatibility["issues"]:
                console.print(f"  • {issue}")
        
        if compatibility["recommendations"]:
            console.print("[yellow]Recommendations:[/yellow]")
            for rec in compatibility["recommendations"]:
                console.print(f"  • {rec}")

def export_template_interactive(manager: StorageTemplateManager):
    """Interactive template export"""
    clear_screen()
    print_header("Export Storage Template")
    
    templates = manager.list_templates()
    if not templates:
        print_warning("No templates available to export")
        return
    
    # Select template
    choices = [
        questionary.Choice(f"{t.name} ({t.template_type.value})", t.id)
        for t in templates
    ]
    
    template_id = questionary.select(
        "Select template to export:",
        choices=choices
    ).ask()
    
    if not template_id:
        return
    
    template = manager.get_template(template_id)
    
    # Get export path
    default_filename = f"{template.name.replace(' ', '_')}.json"
    export_path = questionary.text(
        "Export file path:",
        default=os.path.join(manager.exports_dir, default_filename)
    ).ask()
    
    if not export_path:
        return
    
    # Export template
    if manager.export_template(template_id, export_path):
        console.print("[green]✅ Template exported successfully[/green]")
        console.print(f"File: {export_path}")
    else:
        console.print("[red]❌ Export failed[/red]")

def import_template_interactive(manager: StorageTemplateManager):
    """Interactive template import"""
    clear_screen()
    print_header("Import Storage Template")
    
    # Get import path
    import_path = questionary.text(
        "Import file path:",
        validate=lambda x: os.path.exists(x) if x else False
    ).ask()
    
    if not import_path:
        return
    
    # Check for existing template
    overwrite = False
    try:
        with open(import_path, 'r') as f:
            import_data = json.load(f)
        
        template_name = import_data["template"]["name"]
        existing = manager.get_template_by_name(template_name)
        
        if existing:
            overwrite = questionary.confirm(
                f"Template '{template_name}' already exists. Overwrite?"
            ).ask()
            
            if not overwrite:
                print_info("Import cancelled")
                return
    
    except Exception as e:
        print_error(f"Failed to read import file: {e}")
        return
    
    # Import template
    imported = manager.import_template(import_path, overwrite=overwrite)
    
    if imported:
        console.print("[green]✅ Template imported successfully[/green]")
        console.print(f"Name: {imported.name}")
        console.print(f"Type: {imported.template_type.value}")
        console.print(f"Disks: {len(imported.disks)}")
    else:
        console.print("[red]❌ Import failed[/red]")

def delete_template_interactive(manager: StorageTemplateManager):
    """Interactive template deletion"""
    clear_screen()
    print_header("Delete Storage Template")
    
    templates = manager.list_templates()
    if not templates:
        print_warning("No templates available to delete")
        return
    
    # Select template
    choices = [
        questionary.Choice(f"{t.name} ({t.template_type.value})", t.id)
        for t in templates
    ]
    
    template_id = questionary.select(
        "Select template to delete:",
        choices=choices
    ).ask()
    
    if not template_id:
        return
    
    template = manager.get_template(template_id)
    
    # Check for children
    children = [t for t in templates if t.parent_template_id == template_id]
    if children:
        console.print(f"[yellow]⚠️  This template has {len(children)} child template(s):[/yellow]")
        for child in children:
            console.print(f"  • {child.name}")
        console.print()
        print_error("Cannot delete template with children. Delete children first.")
        return
    
    # Confirm deletion
    console.print(f"[red]You are about to delete template: {template.name}[/red]")
    console.print(f"Type: {template.template_type.value}")
    console.print(f"Disks: {len(template.disks)}")
    console.print()
    
    if questionary.confirm("Are you sure you want to delete this template?").ask():
        if manager.delete_template(template_id):
            console.print(f"[green]✅ Template '{template.name}' deleted successfully[/green]")
        else:
            console.print("[red]❌ Failed to delete template[/red]")
    else:
        print_info("Deletion cancelled")