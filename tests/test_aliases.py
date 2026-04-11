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


# ---------------------------------------------------------------------------
# TestResolveTargetsWithAliases
# ---------------------------------------------------------------------------


class TestResolveTargetsWithAliases:
    """_resolve_targets should resolve group and whitelist aliases."""

    @pytest.fixture
    def bot(self, tmp_path):
        import time
        from mmbot_framework.core.cache import CacheManager
        bot = _make_bot(tmp_path, _VALID_TOML)
        bot._load_channel_data()
        bot._team_id = "team1"
        bot.driver = MagicMock()
        bot.cache = CacheManager()
        bot.cache.register("channels", lambda: {}, ttl=3600)
        entry = bot.cache._entries["channels"]
        entry.data = {
            "by_id": {
                "ch_id_1": {"display_name": "Channel 1", "name": "ch-1"},
                "ch_id_2": {"display_name": "Channel 2", "name": "ch-2"},
            },
            "by_name": {"ch-1": "ch_id_1", "ch-2": "ch_id_2"},
            "all_rows": [],
        }
        entry.loaded_at = time.time()
        return bot

    def test_group_alias_expands_to_channel_ids(self, bot):
        valid_ids, valid_names, invalid = bot._resolve_targets({"tg"})
        assert "ch_id_1" in valid_ids
        assert "ch_id_2" in valid_ids
        assert invalid == []

    def test_group_alias_case_insensitive(self, bot):
        valid_ids, _, _ = bot._resolve_targets({"TG"})
        assert "ch_id_1" in valid_ids

    def test_whitelist_alias_resolves_to_channel_id(self, bot):
        valid_ids, _, invalid = bot._resolve_targets({"c1"})
        assert "ch_id_1" in valid_ids
        assert invalid == []

    def test_canonical_group_name_still_works(self, bot):
        valid_ids, _, invalid = bot._resolve_targets({"TestGroup"})
        assert "ch_id_1" in valid_ids
        assert "ch_id_2" in valid_ids

    def test_unknown_input_ends_up_invalid(self, bot):
        bot.driver.channels.get_channel_by_name.side_effect = Exception("not found")
        _, _, invalid = bot._resolve_targets({"totally-unknown"})
        assert "totally-unknown" in invalid


# ---------------------------------------------------------------------------
# TestHandleChannelsAliasesColumn
# ---------------------------------------------------------------------------


class TestHandleChannelsAliasesColumn:
    @pytest.fixture
    def bot(self, tmp_path):
        import time
        from mmbot_framework.core.cache import CacheManager
        content = {
            "whitelist": {
                "ch-id-1": {"id": "ch_id_1", "aliases": ["shortname", "sn"]},
                "ch-id-2": {"id": "ch_id_2", "aliases": []},
            },
            "groups": {},
            "private_groups": {},
        }
        bot = _make_bot(tmp_path, content)
        bot._load_channel_data()
        bot._team_id = "team1"
        bot.driver = MagicMock()
        bot.cache = CacheManager()
        bot.cache.register("channels", lambda: {}, ttl=3600)
        entry = bot.cache._entries["channels"]
        entry.data = {
            "by_id": {
                "ch_id_1": {
                    "display_name": "Channel One",
                    "name": "channel-one",
                    "team_name": "Team",
                    "team_id": "t1",
                },
                "ch_id_2": {
                    "display_name": "Channel Two",
                    "name": "channel-two",
                    "team_name": "Team",
                    "team_id": "t1",
                },
            },
            "by_name": {},
            "all_rows": [],
        }
        entry.loaded_at = time.time()
        return bot

    @pytest.mark.anyio
    async def test_aliases_column_present_in_header(self, bot, make_msg):
        msg = make_msg(text="!channels")
        await bot._handle_channels(msg)
        reply = bot.driver.posts.create_post.call_args_list[-1][0][0]["message"]
        assert "aliases" in reply

    @pytest.mark.anyio
    async def test_aliases_populated_for_whitelisted_channel(self, bot, make_msg):
        msg = make_msg(text="!channels")
        await bot._handle_channels(msg)
        reply = bot.driver.posts.create_post.call_args_list[-1][0][0]["message"]
        assert "shortname" in reply
        assert "sn" in reply

    @pytest.mark.anyio
    async def test_no_aliases_shows_empty_cell(self, bot, make_msg):
        msg = make_msg(text="!channels")
        await bot._handle_channels(msg)
        reply = bot.driver.posts.create_post.call_args_list[-1][0][0]["message"]
        assert "Channel Two" in reply
