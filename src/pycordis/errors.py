"""Exceptions raised by the PyCordis kernel."""


class PyCordisError(Exception):
    """Base class for all PyCordis errors."""


class DuplicateServiceError(PyCordisError):
    """Raised when a context is asked to provide the same local service twice."""


class PluginActivationError(PyCordisError):
    """Raised when a plugin fails while its lifecycle is being activated."""


class ConfigValidationError(PyCordisError, ValueError):
    """Raised when a plugin's declared configuration validator rejects a value."""
