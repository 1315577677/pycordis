from __future__ import annotations

import asyncio

import pytest

from pycordis import Context


def test_plugin_registry_accepts_function_and_exposes_its_fiber() -> None:
    context = Context()

    def answer_plugin(ctx: Context, answer: int) -> None:
        ctx.provide("answer", answer)

    fiber = context.plugin(answer_plugin, 42)

    assert fiber.name == "answer_plugin"
    assert context.registry.has(answer_plugin)
    assert context.get("answer") == 42

    asyncio.run(fiber.dispose())

    assert context.get("answer") is None
    assert context.registry.has(answer_plugin) is False


def test_isolated_context_can_override_a_service_without_affecting_parent() -> None:
    context = Context()
    context.provide("storage", "parent")
    isolated = context.isolate("storage")

    assert isolated.get("storage") is None

    isolated.provide("storage", "child")

    assert isolated.get("storage") == "child"
    assert context.get("storage") == "parent"


def test_once_listener_unregisters_after_its_first_dispatch() -> None:
    context = Context()
    received: list[str] = []
    context.once("message", received.append)

    context.emit("message", "first")
    context.emit("message", "second")

    assert received == ["first"]


def test_parallel_waits_for_all_async_listeners() -> None:
    context = Context()
    completed: list[str] = []

    async def first() -> None:
        await asyncio.sleep(0)
        completed.append("first")

    async def second() -> None:
        await asyncio.sleep(0)
        completed.append("second")

    context.on("work", first)
    context.on("work", second)

    asyncio.run(context.parallel("work"))

    assert set(completed) == {"first", "second"}


def test_serial_awaits_in_order_and_stops_at_the_first_bail_value() -> None:
    context = Context()
    calls: list[str] = []

    async def first() -> None:
        calls.append("first")

    async def second() -> str:
        await asyncio.sleep(0)
        calls.append("second")
        return "handled"

    async def third() -> None:
        calls.append("third")

    context.on("resolve", first)
    context.on("resolve", second)
    context.on("resolve", third)

    assert asyncio.run(context.serial("resolve")) == "handled"
    assert calls == ["first", "second"]


def test_bail_treats_false_as_a_non_bail_value() -> None:
    context = Context()
    context.on("authorize", lambda: False)
    context.on("authorize", lambda: "allowed")

    assert context.bail("authorize") == "allowed"


def test_plugin_effect_can_be_an_async_generator_of_disposers() -> None:
    context = Context()
    released: list[str] = []

    async def install() -> object:
        async def effects():
            yield lambda: released.append("first")
            yield lambda: released.append("second")

        return effects()

    fiber = context.plugin(lambda ctx: install())

    asyncio.run(fiber.dispose())

    assert released == ["second", "first"]
