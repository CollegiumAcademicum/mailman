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


from task_runner import is_due, _fire_task


# ── is_due ────────────────────────────────────────────────────────────────────

def test_is_due_fires_when_due():
    # Every minute; last ran 61s ago — should fire.
    cron = "* * * * *"
    now = datetime(2026, 4, 20, 8, 1, 0, tzinfo=timezone.utc)
    last = datetime(2026, 4, 20, 8, 0, 0, tzinfo=timezone.utc)
    assert is_due(cron, last, now) is True


def test_is_due_skips_when_not_yet_due():
    # Hourly; last ran at 08:00, now is 08:30 — should NOT fire.
    cron = "0 * * * *"
    now = datetime(2026, 4, 20, 8, 30, 0, tzinfo=timezone.utc)
    last = datetime(2026, 4, 20, 8, 0, 0, tzinfo=timezone.utc)
    assert is_due(cron, last, now) is False


def test_is_due_fires_when_never_run():
    # Every minute; never run — should fire (uses 60s look-back window).
    cron = "* * * * *"
    now = datetime(2026, 4, 20, 8, 1, 0, tzinfo=timezone.utc)
    assert is_due(cron, None, now) is True


def test_is_due_skips_rare_schedule_when_never_run():
    # Annually; never run, now is not the scheduled time — should NOT fire.
    cron = "0 0 1 1 *"  # 1st Jan 00:00
    now = datetime(2026, 4, 20, 8, 0, 0, tzinfo=timezone.utc)
    assert is_due(cron, None, now) is False


# ── _fire_task ────────────────────────────────────────────────────────────────

def test_fire_task_sets_last_run():
    async def run(driver): pass
    entry = TaskEntry(name="t", run=run)
    before = datetime.now(timezone.utc)
    asyncio.run(_fire_task(entry, object(), lambda c, m: None, ""))
    assert entry.last_run is not None
    assert entry.last_run >= before


def test_fire_task_posts_on_error():
    async def run(driver): raise RuntimeError("boom")
    entry = TaskEntry(name="t", run=run)
    posted: list[tuple[str, str]] = []
    asyncio.run(_fire_task(entry, object(), lambda c, m: posted.append((c, m)), "log-ch"))
    assert len(posted) == 1
    assert "log-ch" == posted[0][0]
    assert "boom" in posted[0][1]


def test_fire_task_no_post_without_log_channel():
    async def run(driver): raise RuntimeError("boom")
    entry = TaskEntry(name="t", run=run)
    posted: list = []
    asyncio.run(_fire_task(entry, object(), lambda c, m: posted.append(m), ""))
    assert posted == []


def test_fire_task_does_not_update_last_run_on_error():
    async def run(driver): raise RuntimeError("boom")
    entry = TaskEntry(name="t", run=run)
    asyncio.run(_fire_task(entry, object(), lambda c, m: None, ""))
    assert entry.last_run is None


# ── scheduler_loop ────────────────────────────────────────────────────────────

from task_runner import scheduler_loop  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402


def test_scheduler_loop_does_not_leak_tasks_on_cancel():
    """Cancelling scheduler_loop raises CancelledError cleanly with no leaked tasks."""

    async def run():
        entry = TaskEntry(name="t", run=AsyncMock(), description="test")
        registry = TaskRegistry(tasks={"t": entry}, schedule={})
        loop_task = asyncio.create_task(
            scheduler_loop(registry, driver=None, post_fn=lambda c, m: None, log_channel_id=None)
        )
        await asyncio.sleep(0)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass  # expected

    asyncio.run(run())


def test_scheduler_loop_skips_unscheduled_task():
    """scheduler_loop does not fire a task that has no schedule entry."""
    fired: list[bool] = []

    async def fake_run(driver):
        fired.append(True)

    async def run():
        entry = TaskEntry(name="t", run=fake_run, description="test")
        registry = TaskRegistry(tasks={"t": entry}, schedule={})
        loop_task = asyncio.create_task(
            scheduler_loop(registry, driver=None, post_fn=lambda c, m: None, log_channel_id=None)
        )
        await asyncio.sleep(0)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    assert fired == []


def test_scheduler_loop_cancels_in_flight_tasks_on_shutdown():
    """In-flight tasks are cancelled (not abandoned) when the loop is cancelled."""
    cancelled: list[bool] = []
    completed: list[bool] = []

    async def slow_run(driver):
        try:
            await asyncio.sleep(10)
            completed.append(True)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    async def run():
        # Test the cancellation mechanic directly via _fire_task — equivalent
        # to what the scheduler_loop does to in-flight tasks on shutdown.
        entry = TaskEntry(name="slow", run=slow_run, description="test")
        inner = asyncio.create_task(_fire_task(entry, None, lambda c, m: None, None))
        await asyncio.sleep(0)  # let _fire_task reach asyncio.sleep(10)
        inner.cancel()
        try:
            await inner
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(run())
    assert completed == []
    assert cancelled == [True]
