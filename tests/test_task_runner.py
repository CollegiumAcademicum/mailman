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
