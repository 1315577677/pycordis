"""Structured, context-aware logging primitives for PyCordis."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Context


class LoggerLevel(IntEnum):
    """The severity levels supported by a PyCordis logger."""

    ERROR = 0
    WARN = 1
    INFO = 2
    DEBUG = 3


@dataclass(frozen=True, slots=True)
class LogRecord:
    """One structured log message emitted by a named logger."""

    sequence: int
    timestamp: float
    name: str
    level: LoggerLevel
    args: tuple[object, ...]
    fiber_name: str | None


LogExporter = Callable[[LogRecord], None]


@dataclass(frozen=True, slots=True)
class _Exporter:
    callback: LogExporter
    level: LoggerLevel


class Logger:
    """A named logger whose messages retain their structured arguments."""

    def __init__(
        self,
        service: LoggerService,
        name: str,
        level: LoggerLevel,
        fiber_name: str | None,
    ) -> None:
        self._service = service
        self.name = name
        self.level = level
        self.fiber_name = fiber_name

    def error(self, *args: object) -> None:
        """Emit an error-level record."""
        self._emit(LoggerLevel.ERROR, args)

    def warn(self, *args: object) -> None:
        """Emit a warning-level record."""
        self._emit(LoggerLevel.WARN, args)

    def info(self, *args: object) -> None:
        """Emit an informational record."""
        self._emit(LoggerLevel.INFO, args)

    def debug(self, *args: object) -> None:
        """Emit a debug-level record."""
        self._emit(LoggerLevel.DEBUG, args)

    def _emit(self, level: LoggerLevel, args: tuple[object, ...]) -> None:
        if level > self.level:
            return
        self._service._emit(self.name, level, args, self.fiber_name)


class _LoggerView:
    """A callable Logger service bound to one calling Context."""

    def __init__(self, service: LoggerService, context: Context) -> None:
        self._service = service
        self._context = context

    @property
    def records(self) -> tuple[LogRecord, ...]:
        """Return the root logger's bounded, immutable record buffer."""
        return self._service.records

    @property
    def buffer_size(self) -> int:
        """Return the maximum number of records kept in memory."""
        return self._service.buffer_size

    @buffer_size.setter
    def buffer_size(self, size: int) -> None:
        self._service.buffer_size = size

    def __call__(self, name: str | None = None) -> Logger:
        return self._service._logger_for(self._context, name)

    def error(self, *args: object) -> None:
        self().error(*args)

    def warn(self, *args: object) -> None:
        self().warn(*args)

    def info(self, *args: object) -> None:
        self().info(*args)

    def debug(self, *args: object) -> None:
        self().debug(*args)

    def exporter(self, callback: LogExporter, *, level: LoggerLevel = LoggerLevel.DEBUG) -> Callable[[], None]:
        """Register an exporter and bind it to the calling Context's active Fiber."""
        return self._context.effect(
            lambda: self._service._register_exporter(callback, _coerce_level(level))
        )


class LoggerService:
    """Shared logger state, in-memory records, and reversible exporters."""

    def __init__(self, *, buffer_size: int = 1_000, level: LoggerLevel = LoggerLevel.INFO) -> None:
        self._buffer_size = buffer_size
        self.default_level = level
        self._records: list[LogRecord] = []
        self._exporters: dict[int, _Exporter] = {}
        self._sequence = 0
        self._next_exporter = 0

    @property
    def records(self) -> tuple[LogRecord, ...]:
        """Return records currently retained by the bounded in-memory buffer."""
        return tuple(self._records)

    @property
    def buffer_size(self) -> int:
        return self._buffer_size

    @buffer_size.setter
    def buffer_size(self, size: int) -> None:
        if size < 0:
            raise ValueError("logger buffer_size must not be negative")
        self._buffer_size = size
        del self._records[: max(0, len(self._records) - size)]

    def view(self, context: Context) -> _LoggerView:
        """Create a Context-bound callable logger view."""
        return _LoggerView(self, context)

    def _logger_for(self, context: Context, name: str | None) -> Logger:
        config = context.resolve_config("logger")
        resolved_name = name or _string_config(config, "name") or _fiber_name(context) or "context"
        level = _coerce_level(config.get("level", self.default_level))
        return Logger(self, resolved_name, level, _fiber_name(context))

    def _emit(
        self,
        name: str,
        level: LoggerLevel,
        args: tuple[object, ...],
        fiber_name: str | None,
    ) -> None:
        self._sequence += 1
        record = LogRecord(
            sequence=self._sequence,
            timestamp=time.time(),
            name=name,
            level=level,
            args=args,
            fiber_name=fiber_name,
        )
        self._records.append(record)
        overflow = len(self._records) - self.buffer_size
        if overflow > 0:
            del self._records[:overflow]
        for exporter in tuple(self._exporters.values()):
            if level <= exporter.level:
                exporter.callback(record)

    def _register_exporter(self, callback: LogExporter, level: LoggerLevel) -> Callable[[], None]:
        self._next_exporter += 1
        identifier = self._next_exporter
        self._exporters[identifier] = _Exporter(callback, level)

        def dispose() -> None:
            self._exporters.pop(identifier, None)

        return dispose


def _coerce_level(value: object) -> LoggerLevel:
    """Normalize config values while rejecting unsupported log levels clearly."""
    if isinstance(value, LoggerLevel):
        return value
    if isinstance(value, str):
        try:
            return LoggerLevel[value.upper()]
        except KeyError as error:
            raise ValueError(f"unsupported logger level {value!r}") from error
    try:
        return LoggerLevel(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"unsupported logger level {value!r}") from error


def _string_config(config: dict[str, object], name: str) -> str | None:
    value = config.get(name)
    return value if isinstance(value, str) else None


def _fiber_name(context: Context) -> str | None:
    scope = context._active_scope.get()
    if scope is None and context._scope_stack:
        scope = context._scope_stack[-1]
    if scope is None:
        return None
    return getattr(scope, "name", getattr(scope.plugin, "name", None))
