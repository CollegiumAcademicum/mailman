"""Tests for channel/group alias feature."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import toml

from bot import GroupEntry, PostBot, WhitelistEntry
from config import PostBotConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bot(tmp_path: Path, toml_content: dict) -> PostBot:
    """Write toml_content to a temp file and return a bot that uses it."""
    p = tmp_path / "channels.toml"
    p.write_text(toml.dumps(toml_content))
    cfg = PostBotConfig(
        url="mm.example.com",
        token="tok",
        team_name="team",
        channels_toml_path=p,
        db_path=tmp_path / "test.db",
        bot_log_channel_id="",
        console_log_level="WARNING",
        log_file=None,
    )
    with patch("mmbot_framework.core.driver.DriverFactory.create", return_value=MagicMock()):
        bot = PostBot(cfg)
    return bot


_VALID_TOML = {
    "whitelist": {
        "ch-id-1": {"id": "ch_id_1", "aliases": ["c1", "one"]},
        "ch-id-2": {"id": "ch_id_2"},  # no aliases key
    },
    "groups": {
        "TestGroup": {"channels": ["ch_id_1", "ch_id_2"], "aliases": ["tg", "test"]},
        "NoAliasGroup": {"channels": ["ch_id_2"]},  # no aliases key
    },
    "private_groups": {
        "PrivGroup": {"channels": ["ch_id_1"], "aliases": ["priv"]},
    },
}


# ---------------------------------------------------------------------------
# TestLoadChannelData
# ---------------------------------------------------------------------------


class TestLoadChannelData:
    def test_loads_group_entries(self, tmp_path):
        bot = _make_bot(tmp_path, _VALID_TOML)
        bot._load_channel_data()
        assert isinstance(bot._visible_groups["TestGroup"], GroupEntry)
        assert bot._visible_groups["TestGroup"].channels == ["ch_id_1", "ch_id_2"]
        assert bot._visible_groups["TestGroup"].aliases == ["tg", "test"]

    def test_missing_aliases_key_defaults_to_empty_list(self, tmp_path):
        bot = _make_bot(tmp_path, _VALID_TOML)
        bot._load_channel_data()
        assert bot._visible_groups["NoAliasGroup"].aliases == []

    def test_loads_whitelist_entries(self, tmp_path):
        bot = _make_bot(tmp_path, _VALID_TOML)
        bot._load_channel_data()
        assert isinstance(bot._whitelist["ch-id-1"], WhitelistEntry)
        assert bot._whitelist["ch-id-1"].id == "ch_id_1"
        assert bot._whitelist["ch-id-1"].aliases == ["c1", "one"]

    def test_whitelist_entry_no_aliases_defaults_empty(self, tmp_path):
        bot = _make_bot(tmp_path, _VALID_TOML)
        bot._load_channel_data()
        assert bot._whitelist["ch-id-2"].aliases == []

    def test_old_flat_whitelist_raises_value_error(self, tmp_path):
        old_format = {
            "whitelist": ["ch_id_1", "ch_id_2"],
            "groups": {},
            "private_groups": {},
        }
        bot = _make_bot(tmp_path, old_format)
        with pytest.raises(ValueError, match="old flat whitelist format"):
            bot._load_channel_data()

    def test_old_flat_group_value_raises_value_error(self, tmp_path):
        old_format = {
            "whitelist": {},
            "groups": {"OldGroup": ["ch_id_1"]},
            "private_groups": {},
        }
        bot = _make_bot(tmp_path, old_format)
        with pytest.raises(ValueError, match="old flat group format"):
            bot._load_channel_data()

    def test_builds_whitelist_ids_set(self, tmp_path):
        bot = _make_bot(tmp_path, _VALID_TOML)
        bot._load_channel_data()
        assert "ch_id_1" in bot._whitelist_ids
        assert "ch_id_2" in bot._whitelist_ids


# ---------------------------------------------------------------------------
# TestBuildAliasMap
# ---------------------------------------------------------------------------


class TestBuildAliasMap:
    def test_group_alias_registered(self, tmp_path):
        bot = _make_bot(tmp_path, _VALID_TOML)
        bot._load_channel_data()
        assert bot._alias_map["tg"] == "TestGroup"
        assert bot._alias_map["test"] == "TestGroup"

    def test_whitelist_alias_registered(self, tmp_path):
        bot = _make_bot(tmp_path, _VALID_TOML)
        bot._load_channel_data()
        assert bot._alias_map["c1"] == "ch-id-1"
        assert bot._alias_map["one"] == "ch-id-1"

    def test_private_group_alias_registered(self, tmp_path):
        bot = _make_bot(tmp_path, _VALID_TOML)
        bot._load_channel_data()
        assert bot._alias_map["priv"] == "PrivGroup"

    def test_collision_first_definition_wins(self, tmp_path, caplog):
        collision = {
            "whitelist": {},
            "groups": {
                "GroupA": {"channels": ["id1"], "aliases": ["dup"]},
                "GroupB": {"channels": ["id2"], "aliases": ["dup"]},
            },
            "private_groups": {},
        }
        bot = _make_bot(tmp_path, collision)
        import logging
        with caplog.at_level(logging.WARNING, logger="bot"):
            bot._load_channel_data()
        assert bot._alias_map["dup"] == "GroupA"
        assert "dup" in caplog.text
