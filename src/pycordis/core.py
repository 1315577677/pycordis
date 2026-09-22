"""The synchronous PyCordis kernel.

The kernel intentionally owns only lifecycle concerns. Everything useful to an
agent—models, tools, storage, schedulers, and UI—can be introduced as a plugin.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, TypeAlias

from .errors import DuplicateServiceError, PluginActivationError

Cleanup: TypeAlias = Callable[[], None]
Listener: TypeAlias = Callable[..., Any]
PluginApply: TypeAlias = Callable[["Context"], Cleanup | None]


class PluginState(Enum):
    """Lifecycle state for a plugin mount."""

    PENDING = auto()
    ACTIVE = auto()
    FAILED = auto()
    DISPOSED = auto()


@dataclass(frozen=True, slots=True)
class Plugin:
    """A named unit of behavior that can require services from a context."""

    name: str
    apply: PluginApply
    inject: tuple[str, ...] = ()


class PluginHandle:
    """The reversible mount of one plugin into one context."""

    def __init__(self, context: Context, plugin: Plugin) -> None:
        self._context = context
        self.plugin = plugin
        self.state = PluginState.PENDING
        self._cleanups: list[Cleanup] = []
        self.error: PluginActivationError | None = None

    def dispose(self) -> None:
        """Permanently remove this plugin and every registration it created."""
        if self.state is PluginState.DISPOSED:
            return

        self._dispose_registrations()
        self.state = PluginState.DISPOSED
        self._context._request_refresh()

    def _add_cleanup(self, cleanup: Cleanup) -> None:
        self._cleanups.append(cleanup)

    def _activate(self) -> None:
        if self.state is not PluginState.PENDING:
            return

        self.state = PluginState.ACTIVE
        self._context._scope_stack.append(self)
        try:
            cleanup = self.plugin.apply(self._context)
            if cleanup is not None:
                self._add_cleanup(_once(cleanup))
        except Exception as error:
            self._dispose_registrations()
            self.state = PluginState.FAILED
            self.error = PluginActivationError(
                f"Plugin {self.plugin.name!r} failed to activate"
            )
            raise self.error from error
        finally:
            self._context._scope_stack.pop()

    def _deactivate_for_missing_dependency(self) -> None:
        if self.state is not PluginState.ACTIVE:
            return

        self._dispose_registrations()
        self.state = PluginState.PENDING

    def _dispose_registrations(self) -> None:
        cleanups = self._cleanups
        self._cleanups = []
        for cleanup in reversed(cleanups):
            cleanup()


class Context:
    """A scope containing services, plugin mounts, effects, and event listeners."""

    def __init__(self, parent: Context | None = None) -> None:
        self._parent = parent
        self._children: list[Context] = []
        self._services: dict[str, object] = {}
        self._service_disposers: dict[str, Cleanup] = {}
        self._listeners: dict[str, list[Listener]] = defaultdict(list)
        self._handles: list[PluginHandle] = []
        self._scope_stack: list[PluginHandle] = []
        self._refreshing = False
        self._disposed = False

        if parent is not None:
            parent._children.append(self)

    def child(self) -> Context:
        """Create a nested context which can consume this context's services."""
        self._assert_open()
        return Context(parent=self)

    def mount(self, plugin: Plugin) -> PluginHandle:
        """Mount a plugin, activating it when all declared services are present."""
        self._assert_open()
        handle = PluginHandle(self, plugin)
        self._handles.append(handle)
        self._request_refresh()
        return handle

    def provide(self, name: str, service: object) -> Cleanup:
        """Expose a local service and return an idempotent disposer for it."""
        self._assert_open()
        if name in self._services:
            raise DuplicateServiceError(
                f"Service {name!r} is already provided by this context"
            )

        self._services[name] = service

        def remove() -> None:
            if self._services.get(name) is not service:
                return
            del self._services[name]
            self._service_disposers.pop(name, None)
            self._request_refresh()

        disposer = _once(remove)
        self._service_disposers[name] = disposer
        self._register_cleanup(disposer)
        self._request_refresh()
        return disposer

    def get(self, name: str) -> object:
        """Look up a service locally, then through ancestor contexts."""
        try:
            return self._services[name]
        except KeyError:
            if self._parent is not None:
                return self._parent.get(name)
            raise KeyError(f"Service {name!r} is not available") from None

    def has(self, name: str) -> bool:
        """Return whether a service is currently visible in this context."""
        try:
            self.get(name)
        except KeyError:
            return False
        return True

    def effect(self, setup: Callable[[], Cleanup | None]) -> Cleanup:
        """Run setup now and bind its optional cleanup to the current plugin scope."""
        self._assert_open()
        cleanup = _once(setup() or _noop)
        self._register_cleanup(cleanup)
        return cleanup

    def on(self, event: str, listener: Listener, *, prepend: bool = False) -> Cleanup:
        """Register an event listener and return an idempotent disposer."""
        self._assert_open()
        listeners = self._listeners[event]
        if prepend:
            listeners.insert(0, listener)
        else:
            listeners.append(listener)

        def remove() -> None:
            try:
                listeners.remove(listener)
            except ValueError:
                return

        disposer = _once(remove)
        self._register_cleanup(disposer)
        return disposer

    def emit(self, event: str, *args: object) -> None:
        """Notify all listeners in registration order and ignore their values."""
        for listener in self._listeners_for(event):
            listener(*args)

    def bail(self, event: str, *args: object) -> object | None:
        """Return the first non-None listener value, stopping dispatch at that point."""
        for listener in self._listeners_for(event):
            value = listener(*args)
            if value is not None:
                return value
        return None

    def waterfall(
        self,
        event: str,
        *args: object,
        terminal: Callable[..., object] | None = None,
    ) -> object | None:
        """Run around-middleware listeners, with each receiving a ``next_`` callable."""
        listeners = self._listeners_for(event)

        def dispatch(index: int, current_args: tuple[object, ...]) -> object | None:
            if index == len(listeners):
                return terminal(*current_args) if terminal is not None else None

            def next_(*next_args: object) -> object | None:
                return dispatch(index + 1, next_args or current_args)

            return listeners[index](*current_args, next_)

        return dispatch(0, args)

    def dispose(self) -> None:
        """Dispose this context, its children, plugin mounts, and local registrations."""
        if self._disposed:
            return

        for child in reversed(self._children.copy()):
            child.dispose()
        for handle in reversed(self._handles.copy()):
            handle.dispose()
        for disposer in reversed(list(self._service_disposers.values())):
            disposer()
        self._listeners.clear()
        self._disposed = True
        if self._parent is not None:
            self._parent._children.remove(self)

    def _listeners_for(self, event: str) -> list[Listener]:
        inherited = self._parent._listeners_for(event) if self._parent is not None else []
        return [*inherited, *self._listeners[event]]

    def _register_cleanup(self, cleanup: Cleanup) -> None:
        if self._scope_stack:
            self._scope_stack[-1]._add_cleanup(cleanup)

    def _request_refresh(self) -> None:
        root = self
        while root._parent is not None:
            root = root._parent
        root._refresh_tree()

    def _refresh_tree(self) -> None:
        if self._refreshing:
            return

        self._refreshing = True
        try:
            changed = True
            while changed:
                changed = False
                for context in self._walk():
                    for handle in context._handles:
                        if (
                            handle.state is PluginState.ACTIVE
                            and not context._dependencies_available(handle.plugin.inject)
                        ):
                            handle._deactivate_for_missing_dependency()
                            changed = True
                for context in self._walk():
                    for handle in context._handles:
                        if (
                            handle.state is PluginState.PENDING
                            and context._dependencies_available(handle.plugin.inject)
                        ):
                            handle._activate()
                            changed = True
        finally:
            self._refreshing = False

    def _walk(self) -> Iterable[Context]:
        yield self
        for child in self._children:
            yield from child._walk()

    def _dependencies_available(self, dependencies: tuple[str, ...]) -> bool:
        return all(self.has(name) for name in dependencies)

    def _assert_open(self) -> None:
        if self._disposed:
            raise RuntimeError("This context has already been disposed")


def _once(cleanup: Cleanup) -> Cleanup:
    """Wrap cleanup so it can safely be called more than once."""
    called = False

    def dispose_once() -> None:
        nonlocal called
        if called:
            return
        called = True
        cleanup()

    return dispose_once


def _noop() -> None:
    """Provide a common no-op cleanup function."""
