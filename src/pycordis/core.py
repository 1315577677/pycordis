"""Core lifecycle primitives for the Python Cordis implementation."""

from __future__ import annotations

from collections import defaultdict
import asyncio
import inspect
from collections.abc import AsyncIterable, Callable, Iterable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, TypeAlias

from .errors import ConfigValidationError, DuplicateServiceError, PluginActivationError

Cleanup: TypeAlias = Callable[[], object]
Listener: TypeAlias = Callable[..., Any]
PluginApply: TypeAlias = Callable[["Context"], object]


class PluginState(Enum):
    """Lifecycle state for a plugin mount."""

    PENDING = auto()
    ACTIVE = auto()
    FAILED = auto()
    DISPOSED = auto()


class FiberState(Enum):
    """Cordis-style lifecycle states for a registry-managed plugin instance."""

    PENDING = auto()
    LOADING = auto()
    ACTIVE = auto()
    FAILED = auto()
    DISPOSED = auto()
    UNLOADING = auto()


@dataclass(frozen=True, slots=True)
class FiberDiagnostics:
    """A stable, read-only snapshot of a Fiber's observable lifecycle state."""

    name: str
    state: FiberState
    dependencies: tuple[str, ...]
    config: object
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class Plugin:
    """A named unit of behavior that can require services from a context."""

    name: str
    apply: PluginApply
    inject: tuple[str, ...] = ()


class Service:
    """Base class for plugins that provide a stable named context service."""

    def __init__(self, ctx: Context, name: str) -> None:
        self.ctx = ctx
        self.name = name
        self._dispose = ctx.provide(name, self)

    def resolve_config(
        self, base: Mapping[str, object] | None = None, head: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        """Resolve this service's intercepted configuration for the current context."""
        return self.ctx.resolve_config(self.name, base, head)


class PluginRegistry:
    """Owns the live fibers for each normalized plugin callback."""

    def __init__(self) -> None:
        self._fibers: dict[object, list[Fiber]] = {}

    def has(self, plugin: object) -> bool:
        return bool(self._fibers.get(_plugin_key(plugin)))

    def get(self, plugin: object) -> tuple[Fiber, ...]:
        return tuple(self._fibers.get(_plugin_key(plugin), ()))

    def _add(self, fiber: Fiber) -> None:
        self._fibers.setdefault(fiber.key, []).append(fiber)

    def _remove(self, fiber: Fiber) -> None:
        fibers = self._fibers.get(fiber.key)
        if fibers is None:
            return
        fibers.remove(fiber)
        if not fibers:
            del self._fibers[fiber.key]


class Fiber:
    """One reversible application of a function, class, object, or ``Plugin``."""

    def __init__(self, context: Context, plugin: object, config: object = None) -> None:
        self._context = context
        self.plugin = plugin
        self.key = _plugin_key(plugin)
        self.name = _plugin_name(plugin)
        self.raw_config = config
        self.config = config
        self.inject = _plugin_inject(plugin)
        self.state = FiberState.PENDING
        self.error: BaseException | None = None
        self._cleanups: list[Cleanup] = []
        self._activation_task: asyncio.Task[None] | None = None

    async def dispose(self) -> None:
        """Unload the fiber, awaiting any in-flight startup and cleanup work."""
        if self.state is FiberState.DISPOSED:
            return
        if self._activation_task is not None:
            await self._activation_task
        self.state = FiberState.UNLOADING
        await self._dispose_registrations_async()
        self.state = FiberState.DISPOSED
        self._context.registry._remove(self)
        self._context._request_refresh()

    async def wait(self) -> Fiber:
        """Wait for current asynchronous loading work and re-raise any startup error."""
        if self._activation_task is not None:
            await self._activation_task
        if self.error is not None:
            raise self.error
        return self

    @property
    def diagnostics(self) -> FiberDiagnostics:
        """Return the Fiber state needed by an inspector or operations console."""
        return FiberDiagnostics(
            name=self.name,
            state=self.state,
            dependencies=self.inject,
            config=self.config,
            error_type=type(self.error).__name__ if self.error is not None else None,
            error_message=str(self.error) if self.error is not None else None,
        )

    def restart(self) -> None:
        """Unload and immediately reapply this fiber with its current config."""
        self._assert_not_disposed()
        self._restart_sync()

    def update(self, config: object) -> None:
        """Store a new config and restart the plugin lifecycle."""
        self._assert_not_disposed()
        self.raw_config = config
        self._restart_sync()

    def _add_cleanup(self, cleanup: Cleanup) -> None:
        self._cleanups.append(cleanup)

    def _activate(self) -> None:
        if self.state is not FiberState.PENDING:
            return
        self.state = FiberState.LOADING
        self._context._scope_stack.append(self)
        try:
            effect = self._invoke()
            if _requires_async_collection(effect) and _has_running_loop():
                self._activation_task = asyncio.create_task(self._activate_async(effect))
                return
            _collect_effect(effect, self._add_cleanup)
            self.state = FiberState.ACTIVE
        except Exception as error:
            self._fail(error)
        finally:
            self._context._scope_stack.pop()

    async def _activate_async(self, effect: object) -> None:
        token = self._context._active_scope.set(self)
        try:
            await _collect_effect_async(effect, self._add_cleanup)
            if self.state is FiberState.LOADING:
                self.state = FiberState.ACTIVE
        except Exception as error:
            self._fail(error)
        finally:
            self._context._active_scope.reset(token)

    def _invoke(self) -> object:
        self.config = _validate_plugin_config(self.plugin, self.raw_config)
        if isinstance(self.plugin, Plugin):
            return self.plugin.apply(self._context)
        if inspect.isclass(self.plugin):
            instance = _invoke_with_config(self.plugin, self._context, self.config)
            initializer = getattr(instance, "init", None)
            return initializer() if callable(initializer) else None
        apply = getattr(self.plugin, "apply", None)
        callback = apply if callable(apply) else self.plugin
        if not callable(callback):
            raise TypeError("plugin must be a function, class, or object with apply()")
        return _invoke_with_config(callback, self._context, self.config)

    def _deactivate_for_missing_dependency(self) -> None:
        if self.state is not FiberState.ACTIVE:
            return
        self.state = FiberState.UNLOADING
        self._dispose_registrations()
        self.state = FiberState.PENDING

    def _dispose_sync(self) -> None:
        if self.state is FiberState.DISPOSED:
            return
        self.state = FiberState.UNLOADING
        self._dispose_registrations()
        self.state = FiberState.DISPOSED
        self._context.registry._remove(self)
        self._context._request_refresh()

    def _restart_sync(self) -> None:
        self.state = FiberState.UNLOADING
        self._dispose_registrations()
        self.state = FiberState.PENDING
        self._context._request_refresh()

    def _dispose_registrations(self) -> None:
        cleanups = self._cleanups
        self._cleanups = []
        for cleanup in reversed(cleanups):
            _collect_effect(cleanup(), lambda _: None)

    async def _dispose_registrations_async(self) -> None:
        cleanups = self._cleanups
        self._cleanups = []
        for cleanup in reversed(cleanups):
            await _collect_effect_async(cleanup(), lambda _: None)

    def _fail(self, error: BaseException) -> None:
        self._dispose_registrations()
        self.state = FiberState.FAILED
        self.error = error

    def _assert_not_disposed(self) -> None:
        if self.state is FiberState.DISPOSED:
            raise RuntimeError(f"Plugin fiber {self.name!r} has been disposed")


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
        self._accessors: dict[str, tuple[Callable[[Context], object], Callable[[object], bool] | None]] = {}
        self._intercepts: dict[str, dict[str, object]] = {}
        self._handles: list[PluginHandle] = []
        self._fibers: list[Fiber] = []
        self._scope_stack: list[PluginHandle | Fiber] = []
        self._active_scope: ContextVar[PluginHandle | Fiber | None] = ContextVar(
            f"pycordis-active-scope-{id(self)}", default=None
        )
        self._isolated: set[str] = set()
        self._refreshing = False
        self._disposed = False
        self.registry = parent.registry if parent is not None else PluginRegistry()

        if parent is not None:
            parent._children.append(self)

    def child(self) -> Context:
        """Create a nested context which can consume this context's services."""
        self._assert_open()
        return Context(parent=self)

    def extend(self) -> Context:
        """Create a child context; the Python equivalent of ``ctx.extend()``."""
        return self.child()

    def isolate(self, name: str) -> Context:
        """Create a child whose service scope for ``name`` does not inherit upward."""
        isolated = self.child()
        isolated._isolated.add(name)
        return isolated

    def intercept(self, name: str, config: Mapping[str, object]) -> Context:
        """Create a child context with configuration overlaid for one service."""
        intercepted = self.child()
        intercepted._intercepts[name] = dict(config)
        return intercepted

    def resolve_config(
        self,
        name: str,
        base: Mapping[str, object] | None = None,
        head: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Merge a service's intercept config from root to this context."""
        contexts: list[Context] = []
        current: Context | None = self
        while current is not None:
            contexts.append(current)
            current = current._parent
        result = dict(base or {})
        for context in reversed(contexts):
            result.update(context._intercepts.get(name, {}))
        result.update(head or {})
        return result

    def mount(self, plugin: Plugin) -> PluginHandle:
        """Mount a plugin, activating it when all declared services are present."""
        self._assert_open()
        handle = PluginHandle(self, plugin)
        self._handles.append(handle)
        self._request_refresh()
        return handle

    def plugin(self, plugin: object, config: object = None) -> Fiber:
        """Register a Cordis plugin function, class, object, or ``Plugin`` instance."""
        self._assert_open()
        fiber = Fiber(self, plugin, config)
        self._fibers.append(fiber)
        self.registry._add(fiber)
        self._request_refresh()
        return fiber

    def inject(self, dependencies: Iterable[str], callback: PluginApply) -> Fiber:
        """Run a callback whenever its declared service dependencies are available."""
        return self.plugin(
            Plugin(
                name=getattr(callback, "__name__", "injected-callback"),
                inject=tuple(dependencies),
                apply=callback,
            )
        )

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

    def set(self, name: str, service: object | None) -> None:
        """Replace a service only when it is owned by this context."""
        if name in self._services:
            self._services[name] = service
            self._request_refresh({name})
            return
        if self._parent is not None and self._parent.has(name):
            raise PermissionError(
                f"Service {name!r} is provided by another context and cannot be replaced here"
            )
        raise KeyError(f"Service {name!r} has not been provided")

    def get(self, name: str, strict: bool = True) -> object | None:
        """Look up a service locally, then through ancestor contexts."""
        if name in self._services:
            return self._services[name]
        if name in self._isolated or self._parent is None:
            return None
        return self._parent.get(name, strict=strict)

    def has(self, name: str) -> bool:
        """Return whether a service is currently visible in this context."""
        if name in self._services:
            return True
        if name in self._isolated or self._parent is None:
            return False
        return self._parent.has(name)

    def accessor(
        self,
        name: str,
        *,
        get: Callable[[Context], object],
        set: Callable[[object], bool] | None = None,
    ) -> Cleanup:
        """Define a computed context property and return a disposer for it."""
        if name in self._accessors or name in self._services:
            raise DuplicateServiceError(f"Context property {name!r} is already declared")
        self._accessors[name] = (get, set)

        def remove() -> None:
            self._accessors.pop(name, None)

        disposer = _once(remove)
        self._register_cleanup(disposer)
        return disposer

    def mixin(
        self, source: str | object, mixins: Iterable[str] | Mapping[str, str]
    ) -> Cleanup:
        """Expose selected source members as reversible Context accessors."""
        entries = ((name, name) for name in mixins) if not isinstance(mixins, Mapping) else mixins.items()
        disposers: list[Cleanup] = []
        for source_name, target_name in entries:
            def getter(ctx: Context, member: str = source_name) -> object:
                target = ctx.get(source) if isinstance(source, str) else source
                if target is None:
                    return None
                return getattr(target, member)

            disposers.append(self.accessor(target_name, get=getter))

        def remove() -> None:
            for disposer in reversed(disposers):
                disposer()

        return _once(remove)

    def effect(self, setup: Callable[[], object]) -> Cleanup:
        """Run setup now and bind its optional cleanup to the current plugin scope."""
        self._assert_open()
        cleanups: list[Cleanup] = []
        _collect_effect(setup(), cleanups.append)

        def dispose() -> None:
            for cleanup in reversed(cleanups):
                _collect_effect(cleanup(), lambda _: None)

        cleanup = _once(dispose)
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

    def once(self, event: str, listener: Listener, *, prepend: bool = False) -> Cleanup:
        """Register a listener that removes itself before its first invocation."""
        disposer: Cleanup

        def wrapped(*args: object) -> object:
            disposer()
            return listener(*args)

        disposer = self.on(event, wrapped, prepend=prepend)
        return disposer

    def emit(self, event: str, *args: object) -> None:
        """Notify all listeners in registration order and ignore their values."""
        for listener in self._listeners_for(event):
            listener(*args)

    def bail(self, event: str, *args: object) -> object | None:
        """Return the first Cordis bail value (anything except ``None`` or ``False``)."""
        for listener in self._listeners_for(event):
            value = listener(*args)
            if _is_bailed(value):
                return value
        return None

    async def parallel(self, event: str, *args: object) -> None:
        """Await all listeners concurrently, raising an exception group on failure."""
        results = await asyncio.gather(
            *(_await_result(listener(*args)) for listener in self._listeners_for(event)),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            raise ExceptionGroup(f"Errors while dispatching {event!r}", errors)

    async def serial(self, event: str, *args: object) -> object | None:
        """Await listeners in order and return the first Cordis bail value."""
        for listener in self._listeners_for(event):
            value = await _await_result(listener(*args))
            if _is_bailed(value):
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
        for fiber in reversed(self._fibers.copy()):
            fiber._dispose_sync()
        for disposer in reversed(list(self._service_disposers.values())):
            disposer()
        self._listeners.clear()
        self._accessors.clear()
        self._disposed = True
        if self._parent is not None:
            self._parent._children.remove(self)

    def _listeners_for(self, event: str) -> list[Listener]:
        inherited = self._parent._listeners_for(event) if self._parent is not None else []
        return [*inherited, *self._listeners[event]]

    def _register_cleanup(self, cleanup: Cleanup) -> None:
        scope = self._active_scope.get()
        if scope is not None:
            scope._add_cleanup(cleanup)
        elif self._scope_stack:
            self._scope_stack[-1]._add_cleanup(cleanup)

    def _request_refresh(self, changed_services: set[str] | None = None) -> None:
        root = self
        while root._parent is not None:
            root = root._parent
        root._refresh_tree(changed_services or set())

    def _refresh_tree(self, changed_services: set[str]) -> None:
        if self._refreshing:
            return

        self._refreshing = True
        try:
            changed = True
            force_restart = changed_services.copy()
            while changed:
                changed = False
                for context in self._walk():
                    for handle in context._handles:
                        if (
                            handle.state is PluginState.ACTIVE
                            and (
                                not context._dependencies_available(handle.plugin.inject)
                                or bool(set(handle.plugin.inject) & force_restart)
                            )
                        ):
                            handle._deactivate_for_missing_dependency()
                            changed = True
                    for fiber in context._fibers:
                        if (
                            fiber.state is FiberState.ACTIVE
                            and (
                                not context._dependencies_available(fiber.inject)
                                or bool(set(fiber.inject) & force_restart)
                            )
                        ):
                            fiber._deactivate_for_missing_dependency()
                            changed = True
                force_restart.clear()
                for context in self._walk():
                    for handle in context._handles:
                        if (
                            handle.state is PluginState.PENDING
                            and context._dependencies_available(handle.plugin.inject)
                        ):
                            handle._activate()
                            changed = True
                    for fiber in context._fibers:
                        if (
                            fiber.state is FiberState.PENDING
                            and context._dependencies_available(fiber.inject)
                        ):
                            fiber._activate()
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

    def __getattr__(self, name: str) -> object:
        """Resolve declared accessors and currently visible services like Cordis's proxy."""
        if name.startswith("_"):
            raise AttributeError(name)
        accessor = self._find_accessor(name)
        if accessor is not None:
            return accessor[0](self)
        if self.has(name):
            return self.get(name)
        raise AttributeError(f"Context has no declared property {name!r}")

    def _find_accessor(
        self, name: str
    ) -> tuple[Callable[[Context], object], Callable[[object], bool] | None] | None:
        if name in self._accessors:
            return self._accessors[name]
        if self._parent is None:
            return None
        return self._parent._find_accessor(name)


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


def _plugin_key(plugin: object) -> object:
    """Normalize supported plugin forms to their executable identity."""
    if isinstance(plugin, Plugin):
        return plugin.apply
    apply = getattr(plugin, "apply", None)
    return apply if callable(apply) and not inspect.isclass(plugin) else plugin


def _plugin_name(plugin: object) -> str:
    if isinstance(plugin, Plugin):
        return plugin.name
    name = getattr(plugin, "__name__", None)
    if name and name != "apply":
        return name
    apply = getattr(plugin, "apply", None)
    return getattr(apply, "__name__", None) or type(plugin).__name__


def _plugin_inject(plugin: object) -> tuple[str, ...]:
    inject = getattr(plugin, "inject", ())
    if isinstance(inject, Mapping):
        return tuple(inject)
    return tuple(inject or ())


def _validate_plugin_config(plugin: object, config: object) -> object:
    """Apply the optional Python ``Config`` validator declared by a plugin."""
    validator = getattr(plugin, "Config", None)
    if validator is None:
        return config
    validate = getattr(validator, "validate", validator)
    if not callable(validate):
        raise TypeError("plugin Config must be callable or expose validate()")
    try:
        return validate(config)
    except ConfigValidationError:
        raise
    except Exception as error:
        raise ConfigValidationError(str(error)) from error


def _invoke_with_config(callback: Callable[..., object], context: Context, config: object) -> object:
    """Call a Python plugin with config only when its signature accepts it."""
    try:
        inspect.signature(callback).bind(context, config)
    except TypeError:
        return callback(context)
    return callback(context, config)


def _is_bailed(value: object) -> bool:
    return value is not None and value is not False


async def _await_result(value: object) -> object:
    return await value if inspect.isawaitable(value) else value


def _requires_async_collection(value: object) -> bool:
    return inspect.isawaitable(value) or isinstance(value, AsyncIterable)


def _has_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _collect_effect(result: object, collect: Callable[[Cleanup], None]) -> None:
    """Normalize the Cordis effect shapes accepted by the Python port."""
    if result is None:
        return
    if callable(result):
        collect(result)
        return
    if inspect.isawaitable(result):
        _collect_effect(_run_awaitable(result), collect)
        return
    if isinstance(result, AsyncIterable):
        async def consume() -> list[object]:
            return [value async for value in result]

        for value in _run_awaitable(consume()):
            _collect_effect(value, collect)
        return
    if isinstance(result, Iterable) and not isinstance(result, (bytes, str, Mapping)):
        for value in result:
            _collect_effect(value, collect)
        return
    raise TypeError("effect must return a cleanup, iterable, async iterable, or awaitable")


async def _collect_effect_async(result: object, collect: Callable[[Cleanup], None]) -> None:
    """Asynchronously normalize Cordis effect shapes without nesting event loops."""
    if result is None:
        return
    if callable(result):
        collect(result)
        return
    if inspect.isawaitable(result):
        await _collect_effect_async(await result, collect)
        return
    if isinstance(result, AsyncIterable):
        async for value in result:
            await _collect_effect_async(value, collect)
        return
    if isinstance(result, Iterable) and not isinstance(result, (bytes, str, Mapping)):
        for value in result:
            await _collect_effect_async(value, collect)
        return
    raise TypeError("effect must return a cleanup, iterable, async iterable, or awaitable")


def _run_awaitable(awaitable: object) -> object:
    """Synchronously settle lifecycle work when the public API is used synchronously."""
    if not inspect.isawaitable(awaitable):
        return awaitable
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError(
        "Synchronous lifecycle activation cannot await inside a running event loop; "
        "use the asynchronous Fiber API."
    )
