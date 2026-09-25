from __future__ import annotations

import asyncio

from pycordis import Context, LoggerLevel


def test_logger_records_structured_messages_and_honors_the_default_level() -> None:
    context = Context()

    context.logger("jobs").debug("skipped %s", "draft")
    context.logger("jobs").info("processed %s", "job-42")
    context.logger.warn("queue is slow")

    records = context.logger.records
    assert [(record.name, record.level, record.args) for record in records] == [
        ("jobs", LoggerLevel.INFO, ("processed %s", "job-42")),
        ("context", LoggerLevel.WARN, ("queue is slow",)),
    ]


def test_logger_uses_the_callers_intercepted_name_and_level() -> None:
    context = Context()
    worker = context.intercept(
        "logger", {"name": "worker", "level": LoggerLevel.DEBUG}
    )

    worker.logger.debug("connected")

    record = context.logger.records[-1]
    assert (record.name, record.level, record.args) == (
        "worker",
        LoggerLevel.DEBUG,
        ("connected",),
    )


def test_logger_uses_the_current_fiber_name_and_releases_scoped_exporters() -> None:
    context = Context()
    exported = []

    def worker_plugin(ctx: Context) -> None:
        ctx.logger.exporter(exported.append)
        ctx.logger.info("started")

    fiber = context.plugin(worker_plugin)

    assert context.logger.records[-1].name == "worker_plugin"
    assert [record.args for record in exported] == [("started",)]

    asyncio.run(fiber.dispose())
    context.logger.info("stopped")

    assert [record.args for record in exported] == [("started",)]
