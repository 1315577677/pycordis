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
)
from .errors import ConfigValidationError, DuplicateServiceError, PluginActivationError

__all__ = [
    "Context",
    "ConfigValidationError",
    "DuplicateServiceError",
    "Fiber",
    "FiberDiagnostics",
    "FiberState",
    "Plugin",
    "PluginActivationError",
    "PluginHandle",
    "PluginRegistry",
    "PluginState",
    "Service",
]
