from __future__ import annotations

import asyncio

from pycordis import Context


def test_targeted_events_only_reach_listeners_in_the_same_isolation_scope() -> None:
    root = Context()
    left = root.isolate("channel")
    right = root.isolate("channel")
    received: list[str] = []

    left.on("message", lambda value: received.append(f"left:{value}"))
    right.on("message", lambda value: received.append(f"right:{value}"))

    root.emit("message", "hello", target=left)

    assert received == ["left:hello"]


def test_global_listener_receives_targeted_events_from_every_scope() -> None:
    root = Context()
    left = root.isolate("channel")
    right = root.isolate("channel")
    received: list[str] = []

    left.on("message", lambda value: received.append(f"left:{value}"))
    right.on(
        "message",
        lambda value: received.append(f"global:{value}"),
        global_=True,
    )

    root.emit("message", "hello", target=left)

    assert received == ["left:hello", "global:hello"]


def test_target_filter_applies_to_parallel_serial_and_waterfall_dispatch() -> None:
    async def scenario() -> None:
        root = Context()
        left = root.isolate("channel")
        right = root.isolate("channel")
        received: list[str] = []

        async def left_listener(value: str) -> None:
            received.append(f"left:{value}")

        async def right_listener(value: str) -> str:
            received.append(f"right:{value}")
            return "wrong-scope"

        left.on("parallel", left_listener)
        right.on("parallel", right_listener)
        left.on("serial", left_listener)
        right.on("serial", right_listener)
        left.on("render", lambda value, next_: f"<{next_(value)}>")
        right.on("render", lambda value, next_: "wrong-scope")

        await root.parallel("parallel", "p", target=left)
        assert await root.serial("serial", "s", target=left) is None
        assert root.waterfall("render", "w", target=left, terminal=lambda value: value) == "<w>"

        assert received == ["left:p", "left:s"]

    asyncio.run(scenario())


def test_once_global_listener_remains_global_until_its_first_delivery() -> None:
    root = Context()
    left = root.isolate("channel")
    right = root.isolate("channel")
    received: list[str] = []
    root.once("message", received.append, global_=True)

    root.emit("message", "first", target=left)
    root.emit("message", "second", target=right)

    assert received == ["first"]
