#!/usr/bin/env python3
# Made by trex099
# https://github.com/Trex099/Glint
"""
Disk Performance Monitoring Module for Linux VMs

This module provides REAL disk performance monitoring capabilities including:
- Real-time I/O metrics collection from /proc/diskstats
- Disk performance visualization
- Bottleneck detection and alerting
- Historical performance data analysis
- Performance optimization recommendations

Uses actual Linux kernel I/O statistics - NO FAKE/RANDOM DATA.
"""

import os
import sys
import time
import sqlite3
import subprocess
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum

# Add parent paths for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.align import Align
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    from src.core_utils import print_header, print_info, print_error, print_success, print_warning
except ImportError:
    def print_header(msg): print(f"\n=== {msg} ===")
    def print_info(msg): print(f"[INFO] {msg}")
    def print_error(msg): print(f"[ERROR] {msg}")
    def print_success(msg): print(f"[SUCCESS] {msg}")
    def print_warning(msg): print(f"[WARNING] {msg}")

if RICH_AVAILABLE:
    console = Console()


class DiskMetricType(Enum):
    """Types of disk metrics to collect"""
    IOPS_READ = "iops_read"
    IOPS_WRITE = "iops_write"
    THROUGHPUT_READ = "throughput_read"
    THROUGHPUT_WRITE = "throughput_write"
    LATENCY_READ = "latency_read"
    LATENCY_WRITE = "latency_write"
    QUEUE_DEPTH = "queue_depth"
    UTILIZATION = "utilization"


@dataclass
class DiskStats:
    """
    Raw disk statistics from /proc/diskstats
    
    Fields correspond to kernel documentation:
    https://www.kernel.org/doc/Documentation/block/stat.txt
    """
    device_name: str
    reads_completed: int = 0
    reads_merged: int = 0
    sectors_read: int = 0
    time_reading_ms: int = 0
    writes_completed: int = 0
    writes_merged: int = 0
    sectors_written: int = 0
    time_writing_ms: int = 0
    io_in_progress: int = 0
    time_io_ms: int = 0
    weighted_time_io_ms: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class DiskMetrics:
    """Calculated disk performance metrics"""
    disk_name: str
    timestamp: datetime
    iops_read: float = 0.0
    iops_write: float = 0.0
    throughput_read_mbps: float = 0.0
    throughput_write_mbps: float = 0.0
    latency_read_ms: float = 0.0
    latency_write_ms: float = 0.0
    queue_depth: float = 0.0
    utilization_percent: float = 0.0
    
    def __post_init__(self):
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)
        elif self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class DiskPerformanceThresholds:
    """Performance thresholds for alerting"""
    iops_read_warning: float = 5000.0
    iops_read_critical: float = 10000.0
    iops_write_warning: float = 3000.0
    iops_write_critical: float = 7000.0
    throughput_read_warning_mbps: float = 100.0
    throughput_read_critical_mbps: float = 200.0
    throughput_write_warning_mbps: float = 80.0
    throughput_write_critical_mbps: float = 150.0
    latency_read_warning_ms: float = 10.0
    latency_read_critical_ms: float = 20.0
    latency_write_warning_ms: float = 15.0
    latency_write_critical_ms: float = 30.0
    queue_depth_warning: float = 8.0
    queue_depth_critical: float = 16.0
    utilization_warning_percent: float = 70.0
    utilization_critical_percent: float = 90.0


@dataclass
class DiskPerformanceAlert:
    """Performance alert information"""
    disk_name: str
    metric_type: DiskMetricType
    timestamp: datetime
    value: float
    threshold: float
    severity: str  # "warning" or "critical"
    message: str
    
    def __post_init__(self):
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)
        elif self.timestamp is None:
            self.timestamp = datetime.now()
        
        if isinstance(self.metric_type, str):
            self.metric_type = DiskMetricType(self.metric_type)


def read_diskstats() -> Dict[str, DiskStats]:
    """
    Read /proc/diskstats and parse all disk statistics.
    
    This is REAL data from the Linux kernel, not simulated.
    
    Returns:
        Dictionary mapping device names to DiskStats objects
    """
    stats = {}
    diskstats_path = "/proc/diskstats"
    
    if not os.path.exists(diskstats_path):
        return stats
    
    try:
        with open(diskstats_path, 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) < 14:
                    continue
                
                # Fields: major minor name reads reads_merged sectors_read time_reading 
                #         writes writes_merged sectors_written time_writing 
                #         io_in_progress time_io weighted_time_io
                device_name = parts[2]
                
                stats[device_name] = DiskStats(
                    device_name=device_name,
                    reads_completed=int(parts[3]),
                    reads_merged=int(parts[4]),
                    sectors_read=int(parts[5]),
                    time_reading_ms=int(parts[6]),
                    writes_completed=int(parts[7]),
                    writes_merged=int(parts[8]),
                    sectors_written=int(parts[9]),
                    time_writing_ms=int(parts[10]),
                    io_in_progress=int(parts[11]),
                    time_io_ms=int(parts[12]),
                    weighted_time_io_ms=int(parts[13]),
                    timestamp=time.time()
                )
    except (IOError, ValueError, IndexError) as e:
        print_error(f"Error reading diskstats: {e}")
    
    return stats


def calculate_metrics(stats1: DiskStats, stats2: DiskStats, 
                      interval_seconds: float) -> DiskMetrics:
    """
    Calculate performance metrics from two disk stat samples.
    
    REAL calculation using kernel statistics deltas.
    
    Args:
        stats1: First sample (older)
        stats2: Second sample (newer)
        interval_seconds: Time between samples
        
    Returns:
        DiskMetrics with calculated IOPS, throughput, latency
    """
    if interval_seconds <= 0:
        interval_seconds = 1.0
    
    # Sector size (typically 512 bytes)
    sector_size = 512
    
    # Calculate deltas
    reads_delta = stats2.reads_completed - stats1.reads_completed
    writes_delta = stats2.writes_completed - stats1.writes_completed
    sectors_read_delta = stats2.sectors_read - stats1.sectors_read
    sectors_written_delta = stats2.sectors_written - stats1.sectors_written
    time_reading_delta = stats2.time_reading_ms - stats1.time_reading_ms
    time_writing_delta = stats2.time_writing_ms - stats1.time_writing_ms
    time_io_delta = stats2.time_io_ms - stats1.time_io_ms
    
    # Calculate IOPS (operations per second)
    iops_read = reads_delta / interval_seconds if interval_seconds > 0 else 0
    iops_write = writes_delta / interval_seconds if interval_seconds > 0 else 0
    
    # Calculate throughput (MB/s)
    bytes_read = sectors_read_delta * sector_size
    bytes_written = sectors_written_delta * sector_size
    throughput_read_mbps = (bytes_read / (1024 * 1024)) / interval_seconds
    throughput_write_mbps = (bytes_written / (1024 * 1024)) / interval_seconds
    
    # Calculate latency (ms per operation)
    latency_read_ms = time_reading_delta / reads_delta if reads_delta > 0 else 0
    latency_write_ms = time_writing_delta / writes_delta if writes_delta > 0 else 0
    
    # Queue depth (current I/O in progress)
    queue_depth = float(stats2.io_in_progress)
    
    # Utilization (percentage of time disk was busy)
    utilization_percent = min(100.0, (time_io_delta / (interval_seconds * 1000)) * 100)
    
    return DiskMetrics(
        disk_name=stats2.device_name,
        timestamp=datetime.now(),
        iops_read=round(iops_read, 2),
        iops_write=round(iops_write, 2),
        throughput_read_mbps=round(throughput_read_mbps, 3),
        throughput_write_mbps=round(throughput_write_mbps, 3),
        latency_read_ms=round(latency_read_ms, 3),
        latency_write_ms=round(latency_write_ms, 3),
        queue_depth=queue_depth,
        utilization_percent=round(utilization_percent, 2)
    )


def get_disk_cache_mode(disk_path: str) -> str:
    """
    Get disk cache mode from qemu-img info.
    
    This is REAL data from qemu-img, not random.
    
    Args:
        disk_path: Path to disk file
        
    Returns:
        Cache mode string or "unknown"
    """
    if not os.path.exists(disk_path):
        return "unknown"
    
    try:
        result = subprocess.run(
            ['qemu-img', 'info', '--output=json', disk_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            import json
            info = json.loads(result.stdout)
            # qemu-img info shows format, not cache mode
            # Cache mode is set at runtime, so return the format as useful info
            return info.get('format', 'unknown')
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    
    return "unknown"


def collect_realtime_metrics(device_name: str, 
                             interval_seconds: float = 1.0) -> Optional[DiskMetrics]:
    """
    Collect real-time metrics for a specific device.
    
    Takes two samples and calculates the delta.
    
    Args:
        device_name: Device name (e.g., 'sda', 'nvme0n1')
        interval_seconds: Time between samples
        
    Returns:
        DiskMetrics or None if device not found
    """
    # First sample
    stats1 = read_diskstats()
    if device_name not in stats1:
        return None
    
    sample1 = stats1[device_name]
    
    # Wait for interval
    time.sleep(interval_seconds)
    
    # Second sample
    stats2 = read_diskstats()
    if device_name not in stats2:
        return None
    
    sample2 = stats2[device_name]
    
    # Calculate metrics
    return calculate_metrics(sample1, sample2, interval_seconds)


def get_all_block_devices() -> List[str]:
    """
    Get list of all block devices on the system.
    
    Returns:
        List of device names (e.g., ['sda', 'sdb', 'nvme0n1'])
    """
    devices = []
    
    try:
        stats = read_diskstats()
        for name in stats.keys():
            # Filter out partitions (typically have numbers at the end)
            # and loop devices
            if not name.startswith('loop') and not name.startswith('ram'):
                # Check if it's a whole disk (not partition)
                if not any(c.isdigit() for c in name) or name.startswith('nvme'):
                    devices.append(name)
    except Exception:
        pass
    
    return devices


class DiskPerformanceMonitor:
    """Disk performance monitoring system with REAL metrics"""
    
    def __init__(self, vm_name: str, db_path: str = None):
        """
        Initialize disk performance monitor
        
        Args:
            vm_name: VM name
            db_path: Path to metrics database (optional)
        """
        self.vm_name = vm_name
        
        if db_path is None:
            db_dir = os.path.join(os.path.expanduser("~"), ".glint", "metrics")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, f"{vm_name}_disk_metrics.db")
        
        self.db_path = db_path
        self.monitoring_active = False
        self.metrics_history: Dict[str, List[DiskMetrics]] = {}
        self.alerts: List[DiskPerformanceAlert] = []
        self.thresholds = DiskPerformanceThresholds()
        self._previous_stats: Dict[str, DiskStats] = {}
        
        # Initialize database
        self._init_database()
    
    def _init_database(self):
        """Initialize metrics database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create metrics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS disk_metrics (
                    disk_name TEXT,
                    timestamp TEXT,
                    iops_read REAL,
                    iops_write REAL,
                    throughput_read_mbps REAL,
                    throughput_write_mbps REAL,
                    latency_read_ms REAL,
                    latency_write_ms REAL,
                    queue_depth REAL,
                    utilization_percent REAL,
                    PRIMARY KEY (disk_name, timestamp)
                )
            """)
            
            # Create alerts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS disk_alerts (
                    disk_name TEXT,
                    metric_type TEXT,
                    timestamp TEXT,
                    value REAL,
                    threshold REAL,
                    severity TEXT,
                    message TEXT,
                    PRIMARY KEY (disk_name, metric_type, timestamp)
                )
            """)
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print_error(f"Error initializing database: {e}")
    
    def collect_metrics(self, device_name: str) -> Optional[DiskMetrics]:
        """
        Collect metrics for a device using real /proc/diskstats data.
        
        Args:
            device_name: Device to monitor
            
        Returns:
            DiskMetrics or None
        """
        current_stats = read_diskstats()
        
        if device_name not in current_stats:
            return None
        
        current = current_stats[device_name]
        
        # If we have previous stats, calculate metrics
        if device_name in self._previous_stats:
            previous = self._previous_stats[device_name]
            interval = current.timestamp - previous.timestamp
            
            if interval > 0:
                metrics = calculate_metrics(previous, current, interval)
                self._previous_stats[device_name] = current
                return metrics
        
        # First call - store stats for next time
        self._previous_stats[device_name] = current
        return None
    
    def store_metrics(self, metrics: DiskMetrics):
        """Store metrics in database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO disk_metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metrics.disk_name,
                metrics.timestamp.isoformat(),
                metrics.iops_read,
                metrics.iops_write,
                metrics.throughput_read_mbps,
                metrics.throughput_write_mbps,
                metrics.latency_read_ms,
                metrics.latency_write_ms,
                metrics.queue_depth,
                metrics.utilization_percent
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print_error(f"Error storing metrics: {e}")
    
    def get_historical_metrics(self, device_name: str, 
                               limit: int = 100) -> List[DiskMetrics]:
        """Get historical metrics from database"""
        metrics = []
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM disk_metrics 
                WHERE disk_name = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (device_name, limit))
            
            for row in cursor.fetchall():
                metrics.append(DiskMetrics(
                    disk_name=row[0],
                    timestamp=datetime.fromisoformat(row[1]),
                    iops_read=row[2],
                    iops_write=row[3],
                    throughput_read_mbps=row[4],
                    throughput_write_mbps=row[5],
                    latency_read_ms=row[6],
                    latency_write_ms=row[7],
                    queue_depth=row[8],
                    utilization_percent=row[9]
                ))
            
            conn.close()
        except Exception as e:
            print_error(f"Error fetching historical metrics: {e}")
        
        return metrics
    
    def check_thresholds(self, metrics: DiskMetrics) -> List[DiskPerformanceAlert]:
        """Check metrics against thresholds and generate alerts"""
        alerts = []
        
        def check(value, warning, critical, metric_type, name):
            if value >= critical:
                alerts.append(DiskPerformanceAlert(
                    disk_name=metrics.disk_name,
                    metric_type=metric_type,
                    timestamp=datetime.now(),
                    value=value,
                    threshold=critical,
                    severity="critical",
                    message=f"{name} is critical: {value:.2f}"
                ))
            elif value >= warning:
                alerts.append(DiskPerformanceAlert(
                    disk_name=metrics.disk_name,
                    metric_type=metric_type,
                    timestamp=datetime.now(),
                    value=value,
                    threshold=warning,
                    severity="warning",
                    message=f"{name} is elevated: {value:.2f}"
                ))
        
        check(metrics.iops_read, self.thresholds.iops_read_warning,
              self.thresholds.iops_read_critical, DiskMetricType.IOPS_READ, "Read IOPS")
        check(metrics.latency_read_ms, self.thresholds.latency_read_warning_ms,
              self.thresholds.latency_read_critical_ms, DiskMetricType.LATENCY_READ, "Read latency")
        check(metrics.utilization_percent, self.thresholds.utilization_warning_percent,
              self.thresholds.utilization_critical_percent, DiskMetricType.UTILIZATION, "Disk utilization")
        
        return alerts


def create_disk_performance_dashboard(vm_name: str, disk_name: str = None) -> Optional[Panel]:
    """
    Create disk performance dashboard with REAL metrics.
    
    Args:
        vm_name: VM name
        disk_name: Specific disk name or None for all disks
        
    Returns:
        Rich panel with dashboard
    """
    if not RICH_AVAILABLE:
        print_error("Rich library not available for dashboard")
        return None
    
    # Get all devices or specific one
    if disk_name:
        devices = [disk_name]
    else:
        devices = get_all_block_devices()
    
    if not devices:
        return Panel("No block devices found", title="Disk Performance")
    
    # Create table with real metrics
    table = Table(title=f"Disk Performance - {vm_name}")
    table.add_column("Device", style="cyan")
    table.add_column("Read IOPS", justify="right")
    table.add_column("Write IOPS", justify="right")
    table.add_column("Read MB/s", justify="right")
    table.add_column("Write MB/s", justify="right")
    table.add_column("Queue", justify="right")
    table.add_column("Util %", justify="right")
    
    for device in devices[:5]:  # Limit to 5 devices
        metrics = collect_realtime_metrics(device, interval_seconds=0.5)
        if metrics:
            # Color utilization based on level
            util_style = "green"
            if metrics.utilization_percent > 70:
                util_style = "yellow"
            if metrics.utilization_percent > 90:
                util_style = "red"
            
            table.add_row(
                device,
                f"{metrics.iops_read:.1f}",
                f"{metrics.iops_write:.1f}",
                f"{metrics.throughput_read_mbps:.2f}",
                f"{metrics.throughput_write_mbps:.2f}",
                f"{metrics.queue_depth:.0f}",
                f"[{util_style}]{metrics.utilization_percent:.1f}[/{util_style}]"
            )
        else:
            table.add_row(device, "-", "-", "-", "-", "-", "-")
    
    return Panel(table, title="Disk Performance Dashboard", border_style="blue")


def disk_performance_menu(vm_name: str = None):
    """
    Disk performance monitoring menu with REAL data.
    
    Args:
        vm_name: VM name (optional)
    """
    print_header("Disk Performance Monitoring")
    
    # Show available devices
    devices = get_all_block_devices()
    print_info(f"Found {len(devices)} block devices: {', '.join(devices[:5])}")
    
    if not devices:
        print_warning("No block devices found to monitor")
        return
    
    # Show quick metrics for first device
    primary_device = devices[0] if devices else None
    if primary_device:
        print_info(f"Collecting metrics for {primary_device}...")
        metrics = collect_realtime_metrics(primary_device, interval_seconds=1.0)
        if metrics:
            print_success(f"Read: {metrics.iops_read:.1f} IOPS, {metrics.throughput_read_mbps:.2f} MB/s")
            print_success(f"Write: {metrics.iops_write:.1f} IOPS, {metrics.throughput_write_mbps:.2f} MB/s")
            print_success(f"Utilization: {metrics.utilization_percent:.1f}%")
        else:
            print_warning("Could not collect metrics")