from pathlib import Path

from config import PostBotConfig


def _base_env() -> dict:
    """Minimal valid PostBotConfig kwargs."""
    return {
        "url": "chat.example.com",
        "token": "testtoken",
        "team_name": "testteam",
    }


def test_tasks_dir_default():
    config = PostBotConfig(**_base_env())
    assert config.tasks_dir == Path("tasks")


def test_tasks_dir_custom():
    config = PostBotConfig(**_base_env(), tasks_dir=Path("/custom/tasks"))
    assert config.tasks_dir == Path("/custom/tasks")


def test_scheduler_toml_path_default():
    config = PostBotConfig(**_base_env())
    assert config.scheduler_toml_path == Path("scheduler.toml")


def test_scheduler_toml_path_custom():
    config = PostBotConfig(**_base_env(), scheduler_toml_path=Path("/custom/scheduler.toml"))
    assert config.scheduler_toml_path == Path("/custom/scheduler.toml")


import asyncio
from datetime import datetime, timezone

import pytest

import task_runner
from task_runner import TaskEntry, TaskRegistry, load_tasks, load_schedule


# ── TaskEntry ────────────────────────────────────────────────────────────────

def test_task_entry_defaults():
    async def run(driver): pass
    entry = TaskEntry(name="foo", run=run)
    assert entry.description == "—"
    assert entry.last_run is None


# ── TaskRegistry ─────────────────────────────────────────────────────────────

def test_registry_get_known():
    async def run(driver): pass
    entry = TaskEntry(name="foo", run=run)
    registry = TaskRegistry({"foo": entry}, {})
    assert registry.get("foo") is entry


def test_registry_get_unknown():
    registry = TaskRegistry({}, {})
    assert registry.get("missing") is None


def test_registry_all_tasks():
    async def run(driver): pass
    a = TaskEntry(name="a", run=run)
    b = TaskEntry(name="b", run=run)
    registry = TaskRegistry({"a": a, "b": b}, {})
    names = {e.name for e in registry.all_tasks()}
    assert names == {"a", "b"}


# ── load_tasks ────────────────────────────────────────────────────────────────

def test_load_tasks_valid(tmp_path):
    (tmp_path / "my_task.py").write_text(
        'DESCRIPTION = "A test task"\n\nasync def run(driver):\n    pass\n'
    )
    tasks = load_tasks(tmp_path)
    assert "my_task" in tasks
    assert tasks["my_task"].description == "A test task"
    assert callable(tasks["my_task"].run)


def test_load_tasks_no_description(tmp_path):
    (tmp_path / "bare.py").write_text("async def run(driver):\n    pass\n")
    tasks = load_tasks(tmp_path)
    assert "bare" in tasks
    assert tasks["bare"].description == "—"


def test_load_tasks_skips_missing_run(tmp_path):
    (tmp_path / "bad.py").write_text('DESCRIPTION = "no run"\n')
    tasks = load_tasks(tmp_path)
    assert "bad" not in tasks


def test_load_tasks_skips_dunder_files(tmp_path):
    (tmp_path / "__init__.py").write_text("async def run(driver): pass\n")
    tasks = load_tasks(tmp_path)
    assert "__init__" not in tasks


def test_load_tasks_skips_bad_import(tmp_path):
    (tmp_path / "broken.py").write_text("raise ValueError('oops')\n")
    tasks = load_tasks(tmp_path)
    assert "broken" not in tasks


def test_load_tasks_missing_dir():
    tasks = load_tasks(Path("/nonexistent/tasks/dir"))
    assert tasks == {}


def test_load_tasks_empty_dir(tmp_path):
    tasks = load_tasks(tmp_path)
    assert tasks == {}


# ── load_schedule ─────────────────────────────────────────────────────────────

def test_load_schedule_valid(tmp_path):
    (tmp_path / "scheduler.toml").write_text(
        '[tasks]\nweekly = "0 7 * * 1"\nmonthly = "0 8 1 * *"\n'
    )
    schedule = load_schedule(tmp_path / "scheduler.toml")
    assert schedule == {"weekly": "0 7 * * 1", "monthly": "0 8 1 * *"}


def test_load_schedule_missing_file(tmp_path):
    schedule = load_schedule(tmp_path / "nonexistent.toml")
    assert schedule == {}


def test_load_schedule_empty_tasks_section(tmp_path):
    (tmp_path / "scheduler.toml").write_text("[tasks]\n")
    schedule = load_schedule(tmp_path / "scheduler.toml")
    assert schedule == {}
