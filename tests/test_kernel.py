from __future__ import annotations

import pytest

from pycordis import Context, DuplicateServiceError, Plugin, PluginState


def test_plugin_waits_for_its_injected_services_then_activates() -> None:
    context = Context()
    observed: list[object] = []

    handle = context.mount(
        Plugin(
            name="uses-database",
            inject=("database",),
            apply=lambda ctx: observed.append(ctx.get("database")),
        )
    )

    assert handle.state is PluginState.PENDING
    assert observed == []

    database = object()
    context.provide("database", database)

    assert handle.state is PluginState.ACTIVE
    assert observed == [database]


def test_plugin_disposal_reverses_its_services_and_event_handlers() -> None:
    context = Context()
    received: list[str] = []

    def install(ctx: Context) -> None:
        ctx.provide("formatter", str.upper)
        ctx.on("message", received.append)

    handle = context.mount(Plugin(name="messaging", apply=install))
    context.emit("message", "before")

    assert context.get("formatter")("hello") == "HELLO"
    assert received == ["before"]

    handle.dispose()
    context.emit("message", "after")

    assert context.has("formatter") is False
    assert received == ["before"]


def test_removing_a_dependency_deactivates_a_plugin_and_restoring_it_reactivates() -> None:
    context = Context()
    activations: list[int] = []

    handle = context.mount(
        Plugin(
            name="feature",
            inject=("settings",),
            apply=lambda ctx: activations.append(1),
        )
    )
    remove_settings = context.provide("settings", {"enabled": True})

    assert handle.state is PluginState.ACTIVE
    assert activations == [1]

    remove_settings()

    assert handle.state is PluginState.PENDING

    context.provide("settings", {"enabled": True})

    assert handle.state is PluginState.ACTIVE
    assert activations == [1, 1]


def test_child_context_can_consume_parent_services() -> None:
    parent = Context()
    child = parent.child()
    observed: list[str] = []

    handle = child.mount(
        Plugin(
            name="child-plugin",
            inject=("clock",),
            apply=lambda ctx: observed.append(ctx.get("clock")),
        )
    )

    parent.provide("clock", "parent-clock")

    assert child.get("clock") == "parent-clock"
    assert handle.state is PluginState.ACTIVE
    assert observed == ["parent-clock"]


def test_duplicate_service_names_in_the_same_context_are_rejected() -> None:
    context = Context()
    context.provide("storage", object())

    with pytest.raises(DuplicateServiceError, match="storage"):
        context.provide("storage", object())


def test_waterfall_wraps_next_and_allows_short_circuiting() -> None:
    context = Context()
    context.on("render", lambda value, next_: f"<{next_(value + '!')}>")
    context.on("render", lambda value, next_: value.upper())

    result = context.waterfall("render", "hello", terminal=lambda value: value + "?"
    )

    assert result == "<HELLO!>"


def test_bail_returns_the_first_non_none_result() -> None:
    context = Context()
    calls: list[str] = []
    context.on("authorize", lambda: calls.append("first"))
    context.on("authorize", lambda: "denied")
    context.on("authorize", lambda: calls.append("never"))

    assert context.bail("authorize") == "denied"
    assert calls == ["first"]

