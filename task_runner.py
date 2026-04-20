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
