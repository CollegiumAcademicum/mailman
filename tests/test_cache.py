# postbot/tests/test_cache.py
"""Tests for PostBot channel caching: loader, on_start, !refresh_channels."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot import PostBot
from config import PostBotConfig
from mmbot_framework.core.cache import CacheManager


# ---------------------------------------------------------------------------
# Shared cache data used across multiple tests
# ---------------------------------------------------------------------------

_CACHE_DATA = {
    "by_id": {
        "ch_id_1": {
            "name": "test-channel-1",
            "display_name": "Test Channel 1",
            "team_name": "Test Team",
            "team_id": "team1",
        },
        "ch_id_2": {
            "name": "test-channel-2",
            "display_name": "Test Channel 2",
            "team_name": "Test Team",
            "team_id": "team1",
        },
        "ch_id_3": {
            "name": "private-channel",
            "display_name": "Private Channel",
            "team_name": "Test Team",
            "team_id": "team1",
        },
        "whitelisted_id": {
            "name": "whitelisted",
            "display_name": "Whitelisted",
            "team_name": "Test Team",
            "team_id": "team1",
        },
    },
    "by_name": {
        "test-channel-1": "ch_id_1",
        "test-channel-2": "ch_id_2",
        "private-channel": "ch_id_3",
        "whitelisted": "whitelisted_id",
    },
    "all_rows": [
        "| `Test Channel 1` | test-channel-1 | `ch_id_1` | Test Team |",
        "| `Test Channel 2` | test-channel-2 | `ch_id_2` | Test Team |",
    ],
}


def _seed_cache(bot: PostBot) -> None:
    """Pre-populate bot.cache with _CACHE_DATA so handlers can read from it."""
    loader = AsyncMock(return_value=_CACHE_DATA)
    bot.cache.register("channels", loader, ttl=3600)
    asyncio.run(bot.cache.refresh("channels"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config(channels_file, tmp_path):
    from pathlib import Path
    return PostBotConfig(
        url="mm.example.com",
        token="test-token",
        team_name="test-team",
        channels_toml_path=channels_file,
        db_path=tmp_path / "test.db",
        bot_log_channel_id="",
        console_log_level="WARNING",
        log_file=None,
        channel_cache_ttl_seconds=3600,
    )


@pytest.fixture
def mock_driver():
    return MagicMock()


@pytest.fixture
def bot(config, mock_driver):
    with patch("mmbot_framework.core.driver.DriverFactory.create", return_value=mock_driver):
        b = PostBot(config)
    b._team_id = "test-team-id"
    b._bot_username = "testbot"
    b._visible_groups = {"TestGroup": ["ch_id_1", "ch_id_2"]}
    b._private_groups = {"PrivateGroup": ["ch_id_3"]}
    b._whitelist = {"ch_id_1", "ch_id_2", "ch_id_3", "whitelisted_id"}
    return b


def _last_post(bot: PostBot) -> str:
    return bot.driver.posts.create_post.call_args_list[-1][0][0]["message"]


# ---------------------------------------------------------------------------
# Tests for _load_channel_cache
# ---------------------------------------------------------------------------


class TestLoadChannelCache:
    @pytest.mark.anyio
    async def test_builds_by_id_and_by_name(self, bot):
        bot.driver.teams.get_user_teams.return_value = [
            {"id": "team1", "display_name": "Test Team"}
        ]
        bot.driver.channels.get_channels_for_user.return_value = [
            {
                "id": "ch1",
                "name": "general",
                "display_name": "General",
                "team_id": "team1",
            },
            {
                "id": "ch2",
                "name": "random",
                "display_name": "Random",
                "team_id": "team1",
            },
        ]

        result = await bot._load_channel_cache()

        assert result["by_id"]["ch1"] == {
            "name": "general",
            "display_name": "General",
            "team_name": "Test Team",
            "team_id": "team1",
        }
        assert result["by_name"]["general"] == "ch1"
        assert result["by_name"]["random"] == "ch2"
        assert len(result["all_rows"]) == 2

    @pytest.mark.anyio
    async def test_skips_channels_without_team_id(self, bot):
        """DM and group-message channels have an empty team_id and must be excluded."""
        bot.driver.teams.get_user_teams.return_value = [
            {"id": "team1", "display_name": "Test Team"}
        ]
        bot.driver.channels.get_channels_for_user.return_value = [
            {
                "id": "dm1",
                "name": "dm-channel",
                "display_name": "DM",
                "team_id": "",
            },
        ]

        result = await bot._load_channel_cache()

        assert "dm1" not in result["by_id"]
        assert "dm-channel" not in result["by_name"]
        assert result["all_rows"] == []

    @pytest.mark.anyio
    async def test_covers_multiple_teams(self, bot):
        bot.driver.teams.get_user_teams.return_value = [
            {"id": "t1", "display_name": "Team A"},
            {"id": "t2", "display_name": "Team B"},
        ]
        bot.driver.channels.get_channels_for_user.side_effect = [
            [{"id": "c1", "name": "alpha", "display_name": "Alpha", "team_id": "t1"}],
            [{"id": "c2", "name": "beta", "display_name": "Beta", "team_id": "t2"}],
        ]

        result = await bot._load_channel_cache()

        assert result["by_id"]["c1"]["team_name"] == "Team A"
        assert result["by_id"]["c2"]["team_name"] == "Team B"


# ---------------------------------------------------------------------------
# Tests for !refresh_channels command
# ---------------------------------------------------------------------------


class TestRefreshChannelsCommand:
    @pytest.mark.anyio
    async def test_refresh_channels_calls_cache_refresh(self, bot, make_msg):
        bot.cache.refresh = AsyncMock()
        msg = make_msg(text="!refresh_channels")
        await bot._handle_refresh_channels(msg)
        bot.cache.refresh.assert_awaited_once_with("channels")

    @pytest.mark.anyio
    async def test_refresh_channels_replies_with_timestamp(self, bot, make_msg):
        bot.cache.refresh = AsyncMock()
        msg = make_msg(text="!refresh_channels")
        await bot._handle_refresh_channels(msg)
        reply = _last_post(bot)
        assert "✅" in reply
        assert "UTC" in reply

    @pytest.mark.anyio
    async def test_refresh_channels_driver_not_called_directly(self, bot, make_msg):
        """The handler must delegate to cache.refresh, not call the driver itself."""
        bot.cache.refresh = AsyncMock()
        msg = make_msg(text="!refresh_channels")
        await bot._handle_refresh_channels(msg)
        bot.driver.teams.get_user_teams.assert_not_called()
