"""Tests for PostBotConfig."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from config import PostBotConfig
from mmbot_framework import ConfigError


# ---------------------------------------------------------------------------
# Direct construction
# ---------------------------------------------------------------------------


def test_direct_construction_minimal():
    config = PostBotConfig(url="mm.example.com", token="tok", team_name="myteam")

    assert config.url == "mm.example.com"
    assert config.token == "tok"
    assert config.team_name == "myteam"
    # postbot-specific defaults
    assert config.console_log_level == "WARNING"
    assert config.bot_log_channel_id == ""
    assert config.db_path == Path("broadcast_log.db")


def test_direct_construction_all_fields():
    config = PostBotConfig(
        url="mm.example.com",
        token="tok",
        team_name="myteam",
        console_log_level="DEBUG",
        bot_log_channel_id="ch123",
        db_path=Path("/tmp/test.db"),
        channels_toml_path=Path("/tmp/channels.toml"),
    )

    assert config.url == "mm.example.com"
    assert config.token == "tok"
    assert config.team_name == "myteam"
    assert config.console_log_level == "DEBUG"
    assert config.bot_log_channel_id == "ch123"
    assert config.db_path == Path("/tmp/test.db")
    assert config.channels_toml_path == Path("/tmp/channels.toml")


def test_console_log_level_uppercased():
    config = PostBotConfig(url="mm.example.com", token="tok", team_name="myteam", console_log_level="debug")
    assert config.console_log_level == "DEBUG"


def test_console_log_level_invalid():
    with pytest.raises(ValidationError):
        PostBotConfig(url="mm.example.com", token="tok", team_name="myteam", console_log_level="VERBOSE")


def test_invalid_port():
    with pytest.raises(ValidationError):
        PostBotConfig(url="mm.example.com", token="tok", team_name="myteam", port=99999)


# ---------------------------------------------------------------------------
# PostBotConfig.load()
# ---------------------------------------------------------------------------


def test_load_from_env_file(tmp_path):
    # Keys must match PostBotConfig field names exactly (load() just lowercases them).
    env_file = tmp_path / ".env"
    env_file.write_text(
        "URL=mm.example.com\n"
        "TOKEN=test-token-123\n"
        "TEAM_NAME=myteam\n"
        "CONSOLE_LOG_LEVEL=INFO\n"
        "BOT_LOG_CHANNEL_ID=log_ch\n"
    )

    config = PostBotConfig.load(env_file)

    assert config.url == "mm.example.com"
    assert config.token == "test-token-123"
    assert config.team_name == "myteam"
    assert config.console_log_level == "INFO"
    assert config.bot_log_channel_id == "log_ch"


def test_load_missing_file():
    with pytest.raises(ConfigError):
        PostBotConfig.load("/nonexistent/.env")


def test_load_missing_required_field(tmp_path):
    # Only url provided; token and team_name are missing.
    env_file = tmp_path / ".env"
    env_file.write_text("URL=mm.example.com\n")

    with pytest.raises(ConfigError):
        PostBotConfig.load(env_file)


def test_load_case_insensitive_keys(tmp_path):
    # load() lowercases all keys, so uppercase env var names work too.
    env_file = tmp_path / ".env"
    env_file.write_text(
        "URL=mm.example.com\n"
        "TOKEN=tok\n"
        "TEAM_NAME=t\n"
    )

    config = PostBotConfig.load(env_file)

    assert config.url == "mm.example.com"
    assert config.token == "tok"
    assert config.team_name == "t"


# ---------------------------------------------------------------------------
# Channel cache TTL
# ---------------------------------------------------------------------------


class TestChannelCacheTTL:
    def test_default_ttl_is_3600(self, minimal_config_kwargs):
        config = PostBotConfig(**minimal_config_kwargs)
        assert config.channel_cache_ttl_seconds == 3600

    def test_custom_ttl_is_accepted(self, minimal_config_kwargs):
        config = PostBotConfig(**minimal_config_kwargs, channel_cache_ttl_seconds=600)
        assert config.channel_cache_ttl_seconds == 600
