from __future__ import annotations

import asyncio

import pytest

from pycordis import ConfigValidationError, Context, FiberState


def test_invalid_plugin_config_fails_the_fiber_without_running_the_plugin() -> None:
    context = Context()
    calls: list[str] = []

    def worker(ctx: Context, config: dict[str, int]) -> None:
        calls.append("ran")

    class Config:
        @staticmethod
        def validate(value: object) -> dict[str, int]:
            if not isinstance(value, dict) or value.get("retries", 0) < 1:
                raise ConfigValidationError("retries must be at least one")
            return value

    worker.Config = Config  # type: ignore[attr-defined]
    fiber = context.plugin(worker, {"retries": 0})

    assert fiber.state is FiberState.FAILED
    assert isinstance(fiber.error, ConfigValidationError)
    assert calls == []

    with pytest.raises(ConfigValidationError, match="retries"):
        asyncio.run(fiber.wait())


def test_async_plugin_can_load_and_unload_inside_a_running_event_loop() -> None:
    async def scenario() -> None:
        context = Context()
        lifecycle: list[str] = []

        async def plugin(ctx: Context) -> object:
            await asyncio.sleep(0)
            ctx.provide("answer", 42)
            lifecycle.append("loaded")
            return lambda: lifecycle.append("unloaded")

        fiber = context.plugin(plugin)

        assert fiber.state is FiberState.LOADING

        await fiber.wait()
        assert fiber.state is FiberState.ACTIVE
        assert context.answer == 42

        await fiber.dispose()
        assert fiber.state is FiberState.DISPOSED
        assert context.get("answer") is None
        assert lifecycle == ["loaded", "unloaded"]

    asyncio.run(scenario())


def test_failed_async_plugin_exposes_its_original_error_in_diagnostics() -> None:
    async def scenario() -> None:
        context = Context()

        async def broken(ctx: Context) -> None:
            await asyncio.sleep(0)
            raise RuntimeError("connection refused")

        fiber = context.plugin(broken)

        with pytest.raises(RuntimeError, match="connection refused"):
            await fiber.wait()

        diagnostic = fiber.diagnostics
        assert fiber.state is FiberState.FAILED
        assert diagnostic.name == "broken"
        assert diagnostic.state is FiberState.FAILED
        assert diagnostic.error_type == "RuntimeError"
        assert diagnostic.error_message == "connection refused"

    asyncio.run(scenario())
