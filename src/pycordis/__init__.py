"""A small, dependency-aware and reversible plugin kernel."""

from .core import (
    Context,
    Fiber,
    FiberDiagnostics,
    FiberState,
    Plugin,
    PluginHandle,
    PluginRegistry,
    PluginState,
    Service,
    ServiceCall,
)
from .errors import ConfigValidationError, DuplicateServiceError, LoaderError, PluginActivationError
from .loader import Loader, LoaderEntry
from .logger import LogRecord, Logger, LoggerLevel, LoggerService

__all__ = [
    "Context",
    "ConfigValidationError",
    "DuplicateServiceError",
    "Fiber",
    "FiberDiagnostics",
    "FiberState",
    "LogRecord",
    "Logger",
    "LoggerLevel",
    "LoggerService",
    "Loader",
    "LoaderEntry",
    "LoaderError",
    "Plugin",
    "PluginActivationError",
    "PluginHandle",
    "PluginRegistry",
    "PluginState",
    "Service",
    "ServiceCall",
]
