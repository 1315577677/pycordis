"""A small, dependency-aware and reversible plugin kernel."""

from .core import Context, Fiber, FiberState, Plugin, PluginHandle, PluginRegistry, PluginState, Service
from .errors import DuplicateServiceError, PluginActivationError

__all__ = [
    "Context",
    "DuplicateServiceError",
    "Fiber",
    "FiberState",
    "Plugin",
    "PluginActivationError",
    "PluginHandle",
    "PluginRegistry",
    "PluginState",
    "Service",
]
