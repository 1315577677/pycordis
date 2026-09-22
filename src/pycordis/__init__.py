"""A small, dependency-aware and reversible plugin kernel."""

from .core import Context, Plugin, PluginHandle, PluginState
from .errors import DuplicateServiceError, PluginActivationError

__all__ = [
    "Context",
    "DuplicateServiceError",
    "Plugin",
    "PluginActivationError",
    "PluginHandle",
    "PluginState",
]

