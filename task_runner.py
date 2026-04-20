"""Task runner — plugin discovery, schedule loading, and background scheduler."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import toml
from croniter import croniter

logger = logging.getLogger(__name__)


# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class TaskEntry:
    """A discovered task plugin."""

    name: str
    run: Callable  # async def run(driver) -> None
    description: str = "—"
    last_run: datetime | None = None


class TaskRegistry:
    """Holds all discovered tasks and their cron schedules."""

    def __init__(
        self,
        tasks: dict[str, TaskEntry],
        schedule: dict[str, str],
    ) -> None:
        self.tasks = tasks
        self.schedule = schedule  # task name → cron expression

    def get(self, name: str) -> TaskEntry | None:
        return self.tasks.get(name)

    def all_tasks(self) -> list[TaskEntry]:
        return list(self.tasks.values())


# ── Loaders ───────────────────────────────────────────────────────────────────


def load_tasks(tasks_dir: Path) -> dict[str, TaskEntry]:
    """Import all .py files in *tasks_dir* and return a name → TaskEntry dict.

    Files that fail to import or lack a callable ``run`` are skipped with a
    warning.  Dunder files (``__init__.py``, etc.) are always skipped.
    Returns an empty dict if the directory does not exist.
    """
    if not tasks_dir.exists():
        logger.warning(
            f"Tasks directory {str(tasks_dir)!r} does not exist; no tasks loaded."
        )
        return {}

    tasks: dict[str, TaskEntry] = {}
    for path in sorted(tasks_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        name = path.stem
        spec = importlib.util.spec_from_file_location(f"tasks.{name}", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            logger.warning(f"Failed to import task {name!r}: {exc}")
            continue
        if not hasattr(module, "run") or not callable(module.run):
            logger.warning(f"Task {name!r} has no callable 'run'; skipping.")
            continue
        description = getattr(module, "DESCRIPTION", "—")
        tasks[name] = TaskEntry(name=name, run=module.run, description=description)
        logger.info(f"Loaded task {name!r}.")
    return tasks


def load_schedule(path: Path) -> dict[str, str]:
    """Read *path* (a TOML file) and return a task-name → cron-expression dict.

    Returns an empty dict if the file does not exist.
    """
    if not path.exists():
        logger.info(
            f"No scheduler config at {str(path)!r}; no tasks will be scheduled."
        )
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = toml.load(fh)
    return dict(data.get("tasks", {}))


# ── Scheduling ────────────────────────────────────────────────────────────────


def is_due(cron_expr: str, last_run: datetime | None, now: datetime) -> bool:
    """Return True if *cron_expr* fires between *last_run* and *now*.

    If *last_run* is None (task never ran), uses a 60-second look-back window
    so the task fires on the first scheduler tick that matches the schedule.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start = last_run if last_run is not None else now - timedelta(seconds=60)
    cron = croniter(cron_expr, start)
    next_run = cron.get_next(datetime)
    return next_run <= now


async def _fire_task(
    entry: TaskEntry,
    driver,
    post_fn: Callable[[str, str], None],
    log_channel_id: str,
) -> None:
    """Run *entry.run(driver)*, update *entry.last_run*, and report errors.

    On success: updates ``entry.last_run`` to now.
    On exception: logs the error and, if *log_channel_id* is non-empty, posts
    an error notice via *post_fn*.  ``last_run`` is NOT updated on failure.
    """
    try:
        await entry.run(driver)
        entry.last_run = datetime.now(timezone.utc)
        logger.info(f"Task {entry.name!r} completed.")
    except Exception as exc:
        logger.error(f"Task {entry.name!r} failed: {exc}")
        if log_channel_id:
            post_fn(
                log_channel_id,
                f"⚠️ Scheduled task `{entry.name}` failed: {exc}",
            )


async def scheduler_loop(
    registry: TaskRegistry,
    driver,
    post_fn: Callable[[str, str], None],
    log_channel_id: str | None,
) -> None:
    """Background loop: wake every 60 s, fire any tasks that are due.

    Each due task runs as its own ``asyncio.Task`` so a slow task does not
    delay the next scheduler tick.  On cancellation all in-flight tasks are
    cancelled and awaited before the CancelledError is re-raised.
    """
    pending: set[asyncio.Task] = set()
    try:
        while True:
            await asyncio.sleep(60)
            now = datetime.now(timezone.utc)
            for name, entry in list(registry.tasks.items()):
                cron_expr = registry.schedule.get(name)
                if cron_expr is None:
                    continue
                if is_due(cron_expr, entry.last_run, now):
                    t = asyncio.create_task(
                        _fire_task(entry, driver, post_fn, log_channel_id)
                    )
                    pending.add(t)
                    t.add_done_callback(pending.discard)
                    logger.debug(f"Scheduled task {name!r} dispatched.")
    except asyncio.CancelledError:
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        raise
