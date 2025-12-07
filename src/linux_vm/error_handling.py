# Made by trex099
# https://github.com/Trex099/Glint
"""
Error Handling and Messaging System for Linux VM Management

This module provides a comprehensive error classification, reporting, and recovery
system for Linux VM operations, with actionable error messages and troubleshooting
suggestions.
"""

import os
import sys
import logging
import traceback
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core_utils import print_error, print_warning, print_info, print_success

console = Console()
logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels for classification"""
    INFO = "info"           # Informational message, not an error
    WARNING = "warning"     # Warning that doesn't prevent operation
    ERROR = "error"         # Error that prevents current operation
    CRITICAL = "critical"   # Critical error that affects system stability


class ErrorCategory(Enum):
    """Error categories for systematic classification"""
    PERMISSION = "permission"       # Permission-related errors
    CONFIGURATION = "configuration" # Configuration-related errors
    RESOURCE = "resource"           # Resource availability errors
    HARDWARE = "hardware"           # Hardware-related errors
    NETWORK = "network"             # Network-related errors
    STORAGE = "storage"             # Storage-related errors
    PROCESS = "process"             # Process management errors
    VALIDATION = "validation"       # Input validation errors
    DEPENDENCY = "dependency"       # Missing dependency errors
    SYSTEM = "system"               # System-level errors
    INTERNAL = "internal"           # Internal application errors
    UNKNOWN = "unknown"             # Unclassified errors


@dataclass
class ErrorInfo:
    """Comprehensive error information structure"""
    message: str                            # User-friendly error message
    code: str                               # Unique error code
    severity: ErrorSeverity                 # Error severity level
    category: ErrorCategory                 # Error category
    details: Optional[str] = None           # Detailed error information
    suggestions: List[str] = None           # Troubleshooting suggestions
    recovery_options: List[str] = None      # Possible recovery options
    exception: Optional[Exception] = None   # Original exception if applicable
    context: Optional[Dict[str, Any]] = None # Additional context information
    
    def __post_init__(self):
        """Initialize default values for optional fields"""
        if self.suggestions is None:
            self.suggestions = []
        if self.recovery_options is None:
            self.recovery_options = []
        if self.context is None:
            self.context = {}


class GlintError(Exception):
    """Base exception class for all Glint errors"""
    def __init__(self, 
                 message: str,
                 code: str = "GLINT-E000",
                 severity: ErrorSeverity = ErrorSeverity.ERROR,
                 category: ErrorCategory = ErrorCategory.UNKNOWN,
                 details: Optional[str] = None,
                 suggestions: List[str] = None,
                 recovery_options: List[str] = None,
                 context: Dict[str, Any] = None,
                 original_exception: Exception = None):
        """
        Initialize a GlintError with comprehensive information
        
        Args:
            message: User-friendly error message
            code: Unique error code
            severity: Error severity level
            category: Error category
            details: Detailed error information
            suggestions: Troubleshooting suggestions
            recovery_options: Possible recovery options
            context: Additional context information
            original_exception: Original exception if applicable
        """
        self.error_info = ErrorInfo(
            message=message,
            code=code,
            severity=severity,
            category=category,
            details=details,
            suggestions=suggestions or [],
            recovery_options=recovery_options or [],
            exception=original_exception,
            context=context or {}
        )
        super().__init__(message)
    
    @property
    def code(self) -> str:
        """Get the error code"""
        return self.error_info.code
    
    @property
    def severity(self) -> ErrorSeverity:
        """Get the error severity"""
        return self.error_info.severity
    
    @property
    def category(self) -> ErrorCategory:
        """Get the error category"""
        return self.error_info.category
    
    @property
    def suggestions(self) -> List[str]:
        """Get troubleshooting suggestions"""
        return self.error_info.suggestions
    
    @property
    def recovery_options(self) -> List[str]:
        """Get recovery options"""
        return self.error_info.recovery_options
    
    @property
    def details(self) -> Optional[str]:
        """Get detailed error information"""
        return self.error_info.details
    
    @property
    def context(self) -> Dict[str, Any]:
        """Get additional context information"""
        return self.error_info.context


# Specific error classes for different categories
class PermissionError(GlintError):
    """Permission-related errors"""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault('category', ErrorCategory.PERMISSION)
        kwargs.setdefault('code', 'GLINT-E100')
        super().__init__(message, **kwargs)


class ConfigurationError(GlintError):
    """Configuration-related errors"""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault('category', ErrorCategory.CONFIGURATION)
        kwargs.setdefault('code', 'GLINT-E200')
        super().__init__(message, **kwargs)


class ResourceError(GlintError):
    """Resource availability errors"""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault('category', ErrorCategory.RESOURCE)
        kwargs.setdefault('code', 'GLINT-E300')
        super().__init__(message, **kwargs)


class HardwareError(GlintError):
    """Hardware-related errors"""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault('category', ErrorCategory.HARDWARE)
        kwargs.setdefault('code', 'GLINT-E400')
        super().__init__(message, **kwargs)


class NetworkError(GlintError):
    """Network-related errors"""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault('category', ErrorCategory.NETWORK)
        kwargs.setdefault('code', 'GLINT-E500')
        super().__init__(message, **kwargs)


class StorageError(GlintError):
    """Storage-related errors"""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault('category', ErrorCategory.STORAGE)
        kwargs.setdefault('code', 'GLINT-E600')
        super().__init__(message, **kwargs)


class ProcessError(GlintError):
    """Process management errors"""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault('category', ErrorCategory.PROCESS)
        kwargs.setdefault('code', 'GLINT-E700')
        super().__init__(message, **kwargs)


class ValidationError(GlintError):
    """Input validation errors"""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault('category', ErrorCategory.VALIDATION)
        kwargs.setdefault('code', 'GLINT-E800')
        super().__init__(message, **kwargs)


class DependencyError(GlintError):
    """Missing dependency errors"""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault('category', ErrorCategory.DEPENDENCY)
        kwargs.setdefault('code', 'GLINT-E900')
        super().__init__(message, **kwargs)


class SystemError(GlintError):
    """System-level errors"""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault('category', ErrorCategory.SYSTEM)
        kwargs.setdefault('code', 'GLINT-E1000')
        super().__init__(message, **kwargs)


class SecurityError(GlintError):
    """Security-related errors"""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault('category', ErrorCategory.SYSTEM)
        kwargs.setdefault('code', 'GLINT-E1200')
        super().__init__(message, **kwargs)


class InternalError(GlintError):
    """Internal application errors"""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault('category', ErrorCategory.INTERNAL)
        kwargs.setdefault('code', 'GLINT-E1100')
        super().__init__(message, **kwargs)


class ErrorHandler:
    """
    Centralized error handling system for Linux VM management
    
    This class provides methods for handling errors, displaying error information,
    and implementing recovery mechanisms.
    """
    
    def __init__(self):
        """Initialize the error handler"""
        self.logger = logging.getLogger('glint.error_handler')
        self.recovery_handlers: Dict[str, Callable] = {}
        self.error_history: List[ErrorInfo] = []
        self.max_history_size = 100
    
    def register_recovery_handler(self, error_code: str, handler: Callable):
        """
        Register a recovery handler for a specific error code
        
        Args:
            error_code: The error code to handle
            handler: The recovery handler function
        """
        self.recovery_handlers[error_code] = handler
        self.logger.debug(f"Registered recovery handler for error code {error_code}")
    
    def handle_error(self, error: Exception, context: Dict[str, Any] = None) -> bool:
        """
        Handle an exception with appropriate error display and recovery
        
        Args:
            error: The exception to handle
            context: Additional context information
            
        Returns:
            bool: True if error was handled successfully
        """
        try:
            # Convert to GlintError if it's not already
            if not isinstance(error, GlintError):
                error = self._convert_exception_to_glint_error(error, context)
            
            # Add context if provided
            if context:
                error.error_info.context.update(context)
            
            # Log the error
            self._log_error(error)
            
            # Add to error history
            self._add_to_error_history(error.error_info)
            
            # Display error information
            self.display_error(error)
            
            # Attempt recovery if available
            if error.code in self.recovery_handlers:
                return self._attempt_recovery(error)
            
            return False
            
        except Exception as e:
            # Fallback error handling if something goes wrong in the error handler
            self.logger.error(f"Error in error handler: {e}")
            print_error(f"An error occurred while handling another error: {e}")
            return False
    
    def _convert_exception_to_glint_error(self, 
                                         exception: Exception, 
                                         context: Dict[str, Any] = None) -> GlintError:
        """Convert a standard exception to a GlintError"""
        # Determine error category based on exception type
        category = ErrorCategory.UNKNOWN
        code = "GLINT-E000"
        severity = ErrorSeverity.ERROR
        
        if isinstance(exception, PermissionError) or (isinstance(exception, OSError) and exception.errno == 13):
            category = ErrorCategory.PERMISSION
            code = "GLINT-E101"
            message = "Permission denied"
            suggestions = [
                "Check if you have the necessary permissions to access the resource",
                "Try running the command with elevated privileges",
                "Verify file and directory permissions"
            ]
        elif isinstance(exception, FileNotFoundError) or (isinstance(exception, OSError) and exception.errno == 2):
            category = ErrorCategory.RESOURCE
            code = "GLINT-E301"
            message = "File or resource not found"
            suggestions = [
                "Verify the file path is correct",
                "Check if the resource exists",
                "Ensure required dependencies are installed"
            ]
        elif isinstance(exception, ValueError) or isinstance(exception, TypeError):
            category = ErrorCategory.VALIDATION
            code = "GLINT-E801"
            message = "Invalid input or parameter"
            suggestions = [
                "Check the input values and formats",
                "Verify parameter types match expected types",
                "Refer to documentation for correct usage"
            ]
        elif isinstance(exception, ImportError) or isinstance(exception, ModuleNotFoundError):
            category = ErrorCategory.DEPENDENCY
            code = "GLINT-E901"
            message = "Missing dependency or module"
            suggestions = [
                "Install required dependencies",
                "Check Python environment and installed packages",
                "Verify module paths and imports"
            ]
        elif isinstance(exception, TimeoutError):
            category = ErrorCategory.SYSTEM
            code = "GLINT-E1001"
            message = "Operation timed out"
            suggestions = [
                "Check system resources and network connectivity",
                "Increase timeout value if applicable",
                "Verify the target system is responsive"
            ]
        elif isinstance(exception, KeyboardInterrupt):
            category = ErrorCategory.PROCESS
            code = "GLINT-E701"
            message = "Operation cancelled by user"
            suggestions = [
                "Restart the operation if needed"
            ]
            severity = ErrorSeverity.WARNING
        else:
            # Generic error handling
            message = str(exception) or "An unknown error occurred"
            suggestions = [
                "Check logs for more details",
                "Report this issue if it persists"
            ]
        
        return GlintError(
            message=message,
            code=code,
            severity=severity,
            category=category,
            details=traceback.format_exc(),
            suggestions=suggestions,
            original_exception=exception,
            context=context
        )
    
    def _log_error(self, error: GlintError):
        """Log error information to the logger"""
        log_message = f"[{error.code}] {error.severity.value.upper()}: {str(error)}"
        
        if error.severity == ErrorSeverity.CRITICAL:
            self.logger.critical(log_message, exc_info=error.error_info.exception)
        elif error.severity == ErrorSeverity.ERROR:
            self.logger.error(log_message, exc_info=error.error_info.exception)
        elif error.severity == ErrorSeverity.WARNING:
            self.logger.warning(log_message)
        else:
            self.logger.info(log_message)
    
    def _add_to_error_history(self, error_info: ErrorInfo):
        """Add error to history, maintaining maximum size"""
        self.error_history.append(error_info)
        if len(self.error_history) > self.max_history_size:
            self.error_history.pop(0)
    
    def _attempt_recovery(self, error: GlintError) -> bool:
        """
        Attempt to recover from an error using registered handlers
        
        Returns:
            bool: True if recovery was successful
        """
        try:
            handler = self.recovery_handlers[error.code]
            self.logger.info(f"Attempting recovery for error {error.code}")
            
            result = handler(error)
            
            if result:
                self.logger.info(f"Recovery successful for error {error.code}")
                print_success("✅ Recovery successful")
                return True
            else:
                self.logger.warning(f"Recovery failed for error {error.code}")
                print_warning("⚠️ Recovery attempt failed")
                return False
                
        except Exception as e:
            self.logger.error(f"Error during recovery attempt: {e}")
            print_error(f"Recovery attempt failed: {e}")
            return False
    
    def display_error(self, error: GlintError):
        """Display error information to the user"""
        if error.severity == ErrorSeverity.INFO:
            self._display_info(error)
        elif error.severity == ErrorSeverity.WARNING:
            self._display_warning(error)
        elif error.severity == ErrorSeverity.ERROR:
            self._display_error(error)
        elif error.severity == ErrorSeverity.CRITICAL:
            self._display_critical(error)
    
    def _display_info(self, error: GlintError):
        """Display informational message"""
        print_info(f"{error}")
        
        if error.suggestions:
            for suggestion in error.suggestions:
                print_info(f"  • {suggestion}")
    
    def _display_warning(self, error: GlintError):
        """Display warning message"""
        print_warning(f"⚠️  {error}")
        
        if error.suggestions:
            console.print("[yellow]Suggestions:[/]")
            for suggestion in error.suggestions:
                console.print(f"  • {suggestion}")
    
    def _display_error(self, error: GlintError):
        """Display error message with rich formatting"""
        # Create error panel
        error_panel = f"[bold red]Error {error.code}:[/] {error}\n"
        
        if error.details:
            error_panel += f"\n[dim]{error.details}[/]"
        
        if error.suggestions:
            error_panel += "\n\n[yellow]Suggested Solutions:[/]"
            for suggestion in error.suggestions:
                error_panel += f"\n  • {suggestion}"
        
        if error.recovery_options:
            error_panel += "\n\n[green]Recovery Options:[/]"
            for option in error.recovery_options:
                error_panel += f"\n  • {option}"
        
        console.print(Panel(
            error_panel,
            title=f"[red]{error.category.value.upper()} ERROR[/]",
            border_style="red"
        ))
    
    def _display_critical(self, error: GlintError):
        """Display critical error message with rich formatting"""
        # Create error panel with more emphasis
        error_panel = f"[bold red]CRITICAL ERROR {error.code}:[/] {error}\n"
        
        if error.details:
            error_panel += f"\n[dim]{error.details}[/]"
        
        if error.suggestions:
            error_panel += "\n\n[yellow]Suggested Solutions:[/]"
            for suggestion in error.suggestions:
                error_panel += f"\n  • {suggestion}"
        
        if error.recovery_options:
            error_panel += "\n\n[green]Recovery Options:[/]"
            for option in error.recovery_options:
                error_panel += f"\n  • {option}"
        
        console.print(Panel(
            error_panel,
            title="[white on red]CRITICAL SYSTEM ERROR[/]",
            border_style="red"
        ))
    
    def get_error_history(self, limit: int = None) -> List[ErrorInfo]:
        """
        Get error history
        
        Args:
            limit: Maximum number of errors to return (newest first)
            
        Returns:
            List[ErrorInfo]: List of error information
        """
        if limit:
            return self.error_history[-limit:]
        return self.error_history
    
    def display_error_history(self, limit: int = 10):
        """
        Display error history in a table
        
        Args:
            limit: Maximum number of errors to display
        """
        history = self.get_error_history(limit)
        
        if not history:
            print_info("No errors in history")
            return
        
        table = Table(title=f"Error History (Last {min(limit, len(history))} Errors)")
        table.add_column("Time", style="cyan")
        table.add_column("Code", style="yellow")
        table.add_column("Severity", style="bold")
        table.add_column("Category", style="magenta")
        table.add_column("Message", style="white")
        
        for error in reversed(history):
            timestamp = error.context.get('timestamp', 'Unknown')
            table.add_row(
                str(timestamp),
                error.code,
                error.severity.value.upper(),
                error.category.value.capitalize(),
                error.message
            )
        
        console.print(table)
    
    def clear_error_history(self):
        """Clear the error history"""
        self.error_history = []
        self.logger.info("Error history cleared")


# Singleton instance for global access
_error_handler = None

def get_error_handler() -> ErrorHandler:
    """
    Get the global error handler instance
    
    Returns:
        ErrorHandler: The global error handler
    """
    global _error_handler
    if _error_handler is None:
        _error_handler = ErrorHandler()
    return _error_handler


def safe_operation(func):
    """
    Decorator for safely executing operations with error handling
    
    Example:
        @safe_operation
        def some_function(arg1, arg2):
            # Function body
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            handler = get_error_handler()
            handler.handle_error(e, {
                'function': func.__name__,
                'args': args,
                'kwargs': kwargs,
                'timestamp': datetime.now()
            })
            return None
    return wrapper


# Common error codes and messages for reference
ERROR_CODES = {
    # Permission errors (100-199)
    "GLINT-E100": "Generic permission error",
    "GLINT-E101": "File permission denied",
    "GLINT-E102": "Insufficient privileges for operation",
    "GLINT-E103": "Cannot access device or resource",
    
    # Configuration errors (200-299)
    "GLINT-E200": "Generic configuration error",
    "GLINT-E201": "Invalid configuration file",
    "GLINT-E202": "Missing configuration parameter",
    "GLINT-E203": "Configuration value out of range",
    
    # Resource errors (300-399)
    "GLINT-E300": "Generic resource error",
    "GLINT-E301": "Resource not found",
    "GLINT-E302": "Resource already exists",
    "GLINT-E303": "Resource temporarily unavailable",
    
    # Hardware errors (400-499)
    "GLINT-E400": "Generic hardware error",
    "GLINT-E401": "Device not found",
    "GLINT-E402": "Device already in use",
    "GLINT-E403": "Device not compatible",
    
    # Network errors (500-599)
    "GLINT-E500": "Generic network error",
    "GLINT-E501": "Network connection failed",
    "GLINT-E502": "Port already in use",
    "GLINT-E503": "Network timeout",
    
    # Storage errors (600-699)
    "GLINT-E600": "Generic storage error",
    "GLINT-E601": "Disk full",
    "GLINT-E602": "File system error",
    "GLINT-E603": "I/O error",
    
    # Process errors (700-799)
    "GLINT-E700": "Generic process error",
    "GLINT-E701": "Process terminated unexpectedly",
    "GLINT-E702": "Process timeout",
    "GLINT-E703": "Process already running",
    
    # Validation errors (800-899)
    "GLINT-E800": "Generic validation error",
    "GLINT-E801": "Invalid input parameter",
    "GLINT-E802": "Required parameter missing",
    "GLINT-E803": "Parameter out of range",
    
    # Dependency errors (900-999)
    "GLINT-E900": "Generic dependency error",
    "GLINT-E901": "Missing required dependency",
    "GLINT-E902": "Incompatible dependency version",
    "GLINT-E903": "Dependency configuration error",
    
    # System errors (1000-1099)
    "GLINT-E1000": "Generic system error",
    "GLINT-E1001": "System call failed",
    "GLINT-E1002": "System resource limit reached",
    "GLINT-E1003": "System state invalid",
    
    # Internal errors (1100-1199)
    "GLINT-E1100": "Generic internal error",
    "GLINT-E1101": "Internal assertion failed",
    "GLINT-E1102": "Unexpected internal state",
    "GLINT-E1103": "Internal component failure"
}


# Import datetime here to avoid circular imports in the decorator
from datetime import datetime