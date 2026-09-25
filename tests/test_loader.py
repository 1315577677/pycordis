from __future__ import annotations

import asyncio
from types import ModuleType
import sys

import pytest

from pycordis import Context, Loader, LoaderEntry


def test_loader_reconciles_config_rows_with_minimal_plugin_restarts() -> None:
    context = Context()
    calls: list[str] = []

    def worker(_: Context, config: dict[str, str]) -> object:
        label = config["label"]
        calls.append(f"start:{label}")
        return lambda: calls.append(f"stop:{label}")

    async def scenario() -> None:
        loader = Loader(context)
        first = LoaderEntry("worker", worker, {"label": "first"})

        await loader.reconcile([first])
        await loader.reconcile([first])
        await loader.reconcile([LoaderEntry("worker", worker, {"label": "second"})])
        await loader.reconcile([])

    asyncio.run(scenario())

    assert calls == ["start:first", "stop:first", "start:second", "stop:second"]


def test_loader_defers_disabled_entries_and_can_enable_them_later() -> None:
    context = Context()
    calls: list[str] = []

    def worker(_: Context) -> None:
        calls.append("started")

    async def scenario() -> None:
        loader = Loader(context)
        await loader.reconcile([LoaderEntry("worker", worker, disabled=True)])
        await loader.reconcile([LoaderEntry("worker", worker)])

    asyncio.run(scenario())

    assert calls == ["started"]


def test_loader_resolves_a_module_reference_to_a_plugin_callable() -> None:
    module_name = "_pycordis_loader_fixture"
    fixture = ModuleType(module_name)
    calls: list[str] = []

    def plugin(_: Context, config: str) -> None:
        calls.append(config)

    fixture.plugin = plugin
    sys.modules[module_name] = fixture

    async def scenario() -> None:
        loader = Loader(Context())
        await loader.reconcile([LoaderEntry("fixture", f"{module_name}:plugin", "loaded")])

    try:
        asyncio.run(scenario())
    finally:
        del sys.modules[module_name]

    assert calls == ["loaded"]


def test_loader_rejects_duplicate_entry_ids_before_reconciling() -> None:
    loader = Loader(Context())
    entry = LoaderEntry("duplicate", lambda _: None)

    with pytest.raises(ValueError, match="duplicate"):
        asyncio.run(loader.reconcile([entry, entry]))
