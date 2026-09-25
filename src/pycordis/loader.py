"""Declarative plugin loading from configuration-like entry rows."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import importlib
from typing import TypeAlias

from .core import Context, Fiber, Service
from .errors import LoaderError


PluginReference: TypeAlias = str | object


@dataclass(frozen=True, slots=True)
class LoaderEntry:
    """One declarative plugin row managed by :class:`Loader`."""

    id: str
    plugin: PluginReference
    config: object = None
    disabled: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("loader entry id must not be empty")


@dataclass(slots=True)
class _LoadedEntry:
    entry: LoaderEntry
    fiber: Fiber | None = None


class Loader(Service):
    """Reconcile declarative rows into reversible plugin Fiber instances."""

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx, "loader")
        self._context = ctx
        self._entries: dict[str, _LoadedEntry] = {}

    @property
    def entries(self) -> tuple[LoaderEntry, ...]:
        """Return the rows currently managed by this loader."""
        return tuple(runtime.entry for runtime in self._entries.values())

    def get(self, entry_id: str) -> LoaderEntry | None:
        """Return a configured row by ID, if it is currently managed."""
        runtime = self._entries.get(entry_id)
        return runtime.entry if runtime is not None else None

    def fiber(self, entry_id: str) -> Fiber | None:
        """Return the active Fiber for a row, or ``None`` when it is disabled."""
        runtime = self._entries.get(entry_id)
        return runtime.fiber if runtime is not None else None

    async def reconcile(self, entries: Iterable[LoaderEntry]) -> None:
        """Converge loaded plugins with the supplied entry rows.

        Unchanged rows preserve their Fiber. A configuration-only change updates
        that Fiber, while replacement, disabling, and removal dispose the old
        registrations before a new plugin can be activated.
        """
        desired = tuple(entries)
        self._validate_entries(desired)
        desired_by_id = {entry.id: entry for entry in desired}

        for entry_id in tuple(self._entries):
            if entry_id not in desired_by_id:
                await self._remove(entry_id)

        for entry in desired:
            runtime = self._entries.get(entry.id)
            if runtime is None:
                runtime = _LoadedEntry(entry)
                self._entries[entry.id] = runtime
                await self._apply(runtime)
                continue
            if runtime.entry == entry:
                continue
            await self._update(runtime, entry)

    async def dispose(self) -> None:
        """Unload every managed entry and remove the Loader service itself."""
        await self.reconcile(())
        self._dispose()

    def resolve(self, reference: PluginReference) -> object:
        """Resolve ``module:attribute`` references without additional dependencies."""
        if not isinstance(reference, str):
            return reference
        module_name, separator, attribute = reference.partition(":")
        if not module_name:
            raise LoaderError("plugin module reference must not be empty")
        try:
            module = importlib.import_module(module_name)
        except ImportError as error:
            raise LoaderError(f"cannot import plugin module {module_name!r}") from error
        target: object = module
        for part in (attribute if separator else "plugin").split("."):
            try:
                target = getattr(target, part)
            except AttributeError as error:
                raise LoaderError(
                    f"plugin reference {reference!r} has no attribute {part!r}"
                ) from error
        return target

    async def _update(self, runtime: _LoadedEntry, entry: LoaderEntry) -> None:
        previous = runtime.entry
        runtime.entry = entry
        if entry.disabled:
            if runtime.fiber is not None:
                await runtime.fiber.dispose()
                runtime.fiber = None
            return
        if runtime.fiber is None:
            await self._apply(runtime)
            return
        if previous.plugin != entry.plugin:
            await runtime.fiber.dispose()
            runtime.fiber = None
            await self._apply(runtime)
            return
        if previous.config != entry.config or previous.disabled:
            runtime.fiber.update(entry.config)
            await runtime.fiber.wait()

    async def _apply(self, runtime: _LoadedEntry) -> None:
        if runtime.entry.disabled:
            return
        fiber = self._context.plugin(self.resolve(runtime.entry.plugin), runtime.entry.config)
        runtime.fiber = fiber
        await fiber.wait()

    async def _remove(self, entry_id: str) -> None:
        runtime = self._entries.pop(entry_id)
        if runtime.fiber is not None:
            await runtime.fiber.dispose()

    @staticmethod
    def _validate_entries(entries: tuple[LoaderEntry, ...]) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for entry in entries:
            if entry.id in seen:
                duplicates.add(entry.id)
            seen.add(entry.id)
        if duplicates:
            duplicate_ids = ", ".join(sorted(duplicates))
            raise ValueError(f"duplicate loader entry ids: {duplicate_ids}")
