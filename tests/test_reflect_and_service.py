from __future__ import annotations

import asyncio

import pytest

from pycordis import Context, Service


def test_context_exposes_provided_service_as_an_attribute_and_allows_owner_set() -> None:
    context = Context()
    context.provide("settings", {"theme": "light"})

    assert context.settings == {"theme": "light"}

    context.set("settings", {"theme": "dark"})

    assert context.settings == {"theme": "dark"}


def test_child_context_cannot_replace_a_service_owned_by_its_parent() -> None:
    parent = Context()
    parent.provide("settings", {})

    with pytest.raises(PermissionError, match="settings"):
        parent.child().set("settings", {"theme": "dark"})


def test_accessor_exposes_computed_context_properties_and_is_reversible() -> None:
    context = Context()
    context.provide("release", "0.1.0")
    dispose = context.accessor("banner", get=lambda ctx: f"PyCordis {ctx.release}")

    assert context.banner == "PyCordis 0.1.0"

    dispose()

    with pytest.raises(AttributeError, match="banner"):
        _ = context.banner


def test_mixin_forwards_and_binds_selected_service_methods() -> None:
    class Calculator:
        def add(self, left: int, right: int) -> int:
            return left + right

    context = Context()
    context.provide("calculator", Calculator())
    context.mixin("calculator", ["add"])

    assert context.add(2, 3) == 5


def test_service_base_registers_class_plugins_under_a_stable_context_name() -> None:
    class Greeter(Service):
        def __init__(self, ctx: Context) -> None:
            super().__init__(ctx, "greeter")

        def greet(self, name: str) -> str:
            return f"Hello, {name}!"

    context = Context()
    fiber = context.plugin(Greeter)

    assert context.greeter.greet("Ada") == "Hello, Ada!"

    asyncio.run(fiber.dispose())

    assert context.get("greeter") is None


def test_intercept_merges_config_from_parent_to_child_scope() -> None:
    context = Context()
    intercepted = context.intercept("worker", {"retries": 2})
    nested = intercepted.intercept("worker", {"timeout": 10})

    assert nested.resolve_config("worker", {"retries": 1}) == {
        "retries": 2,
        "timeout": 10,
    }
