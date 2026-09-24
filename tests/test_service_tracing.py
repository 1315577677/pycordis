from __future__ import annotations

import asyncio

from pycordis import Context, Service


def test_service_method_uses_the_callers_intercepted_context() -> None:
    class Greeting(Service):
        def __init__(self, ctx: Context) -> None:
            super().__init__(ctx, "greeting")

        def greet(self, name: str) -> str:
            prefix = self.resolve_config({"prefix": "Hello"})["prefix"]
            return f"{prefix}, {name}!"

    root = Context()
    Greeting(root)
    spanish = root.intercept("greeting", {"prefix": "Hola"})

    assert root.greeting.greet("Ada") == "Hello, Ada!"
    assert spanish.greeting.greet("Ada") == "Hola, Ada!"


def test_async_service_method_keeps_the_callers_context_across_await() -> None:
    class DelayedGreeting(Service):
        def __init__(self, ctx: Context) -> None:
            super().__init__(ctx, "greeting")

        async def greet(self) -> str:
            await asyncio.sleep(0)
            return self.resolve_config({"prefix": "Hello"})["prefix"]

    async def scenario() -> None:
        root = Context()
        DelayedGreeting(root)
        spanish = root.intercept("greeting", {"prefix": "Hola"})

        assert await spanish.greeting.greet() == "Hola"

    asyncio.run(scenario())


def test_service_calls_are_recorded_with_member_and_calling_context() -> None:
    class Calculator(Service):
        def __init__(self, ctx: Context) -> None:
            super().__init__(ctx, "calculator")

        def add(self, left: int, right: int) -> int:
            return left + right

    root = Context()
    caller = root.child()
    Calculator(root)

    assert caller.calculator.add(2, 3) == 5

    trace = root.service_calls[-1]
    assert trace.service == "calculator"
    assert trace.member == "add"
    assert trace.context is caller
