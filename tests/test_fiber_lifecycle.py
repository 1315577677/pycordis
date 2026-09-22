from __future__ import annotations

import asyncio

import pytest

from pycordis import Context, FiberState


def test_fiber_reloads_when_an_injected_service_is_replaced() -> None:
    context = Context()
    context.provide("provider", "first")
    transitions: list[str] = []

    def consumer(ctx: Context) -> object:
        transitions.append(f"load:{ctx.provider}")
        return lambda: transitions.append(f"unload:{ctx.provider}")

    consumer.inject = ("provider",)  # type: ignore[attr-defined]
    fiber = context.plugin(consumer)

    context.set("provider", "second")

    assert transitions == ["load:first", "unload:second", "load:second"]
    assert fiber.state is FiberState.ACTIVE


def test_update_restarts_a_fiber_with_its_new_config() -> None:
    context = Context()
    calls: list[str] = []

    def configured(ctx: Context, config: str) -> object:
        calls.append(f"load:{config}")
        return lambda: calls.append(f"unload:{config}")

    fiber = context.plugin(configured, "first")
    fiber.update("second")

    assert calls == ["load:first", "unload:first", "load:second"]


def test_restart_releases_and_reapplies_an_active_plugin() -> None:
    context = Context()
    calls: list[str] = []

    def plugin(ctx: Context) -> object:
        calls.append("load")
        return lambda: calls.append("unload")

    fiber = context.plugin(plugin)
    fiber.restart()

    assert calls == ["load", "unload", "load"]


def test_disposed_fiber_cannot_restart_or_accept_updates() -> None:
    context = Context()
    fiber = context.plugin(lambda ctx: None)
    asyncio.run(fiber.dispose())

    with pytest.raises(RuntimeError, match="disposed"):
        fiber.restart()

    with pytest.raises(RuntimeError, match="disposed"):
        fiber.update(None)
