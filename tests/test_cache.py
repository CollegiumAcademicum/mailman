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


async def _seed_cache(bot: PostBot) -> None:
    """Pre-populate bot.cache with _CACHE_DATA so handlers can read from it."""
    loader = AsyncMock(return_value=_CACHE_DATA)
    bot.cache.register("channels", loader, ttl=3600)
    await bot.cache.refresh("channels")


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


# ---------------------------------------------------------------------------
# Tests for cache-backed handlers
# ---------------------------------------------------------------------------


class TestHandleChannelsWithCache:
    @pytest.mark.anyio
    async def test_uses_cache_rows_no_driver_calls(self, bot, make_msg):
        await _seed_cache(bot)
        msg = make_msg(text="!channels")
        await bot._handle_channels(msg)
        bot.driver.teams.get_user_teams.assert_not_called()
        bot.driver.channels.get_channels_for_user.assert_not_called()

    @pytest.mark.anyio
    async def test_reply_contains_all_rows(self, bot, make_msg):
        await _seed_cache(bot)
        msg = make_msg(text="!channels")
        await bot._handle_channels(msg)
        reply = _last_post(bot)
        assert "Test Channel 1" in reply
        assert "Test Channel 2" in reply

    @pytest.mark.anyio
    async def test_warns_when_cache_empty(self, bot, make_msg):
        # cache not seeded — get("channels") returns None
        msg = make_msg(text="!channels")
        await bot._handle_channels(msg)
        reply = _last_post(bot)
        assert "⚠️" in reply


class TestHandleIdWithCache:
    @pytest.mark.anyio
    async def test_resolves_name_from_cache(self, bot, make_msg):
        await _seed_cache(bot)
        msg = make_msg(text="!id test-channel-1")
        await bot._handle_id(msg)
        bot.driver.channels.get_channel_by_name.assert_not_called()
        reply = _last_post(bot)
        assert "ch_id_1" in reply

    @pytest.mark.anyio
    async def test_falls_back_to_api_on_cache_miss(self, bot, make_msg):
        await _seed_cache(bot)
        bot.driver.channels.get_channel_by_name.return_value = {"id": "new_id"}
        msg = make_msg(text="!id brand-new-channel")
        await bot._handle_id(msg)
        bot.driver.channels.get_channel_by_name.assert_called_once()
        reply = _last_post(bot)
        assert "new_id" in reply
        assert "!refresh_channels" in reply  # stale-cache notice


class TestHandleGetGroupsWithCache:
    @pytest.mark.anyio
    async def test_resolves_channel_names_from_cache(self, bot, make_msg):
        await _seed_cache(bot)
        msg = make_msg(text="!get_groups")
        await bot._handle_get_groups(msg)
        bot.driver.channels.get_channel.assert_not_called()
        reply = _last_post(bot)
        assert "TestGroup" in reply

    @pytest.mark.anyio
    async def test_falls_back_to_api_on_cache_miss(self, bot, make_msg):
        # cache not seeded — IDs not in cache → fallback to driver
        bot.driver.channels.get_channel.return_value = {"name": "fallback-name"}
        msg = make_msg(text="!get_groups")
        await bot._handle_get_groups(msg)
        assert bot.driver.channels.get_channel.call_count > 0


class TestHandleGetPrivateGroupsWithCache:
    @pytest.mark.anyio
    async def test_resolves_channel_names_from_cache(self, bot, make_msg):
        await _seed_cache(bot)
        msg = make_msg(text="!get_private_groups")
        await bot._handle_get_private_groups(msg)
        bot.driver.channels.get_channel.assert_not_called()

    @pytest.mark.anyio
    async def test_falls_back_to_api_on_cache_miss(self, bot, make_msg):
        bot.driver.channels.get_channel.return_value = {"name": "fallback-name"}
        msg = make_msg(text="!get_private_groups")
        await bot._handle_get_private_groups(msg)
        assert bot.driver.channels.get_channel.call_count > 0


class TestHandleNewSessionWithCache:
    @pytest.mark.anyio
    async def test_whitelist_display_uses_cache(self, bot, make_msg):
        await _seed_cache(bot)
        msg = make_msg(text="Hello world broadcast")
        bot._known_users.add(msg.sender_id)
        await bot._handle_new_session(msg)
        bot.driver.channels.get_channel.assert_not_called()
        bot.driver.teams.get_team.assert_not_called()
        reply = _last_post(bot)
        assert "test-channel-1" in reply or "Test Channel 1" in reply

    @pytest.mark.anyio
    async def test_whitelist_falls_back_to_api_on_cache_miss(self, bot, make_msg):
        # cache not seeded
        bot.driver.channels.get_channel.return_value = {
            "name": "ch", "display_name": "Ch", "team_id": "t1"
        }
        bot.driver.teams.get_team.return_value = {"display_name": "T"}
        msg = make_msg(text="Hello world broadcast")
        bot._known_users.add(msg.sender_id)
        await bot._handle_new_session(msg)
        assert bot.driver.channels.get_channel.call_count > 0


class TestResolveTargetsWithCache:
    def test_resolves_channel_name_from_cache(self, bot):
        asyncio.run(_seed_cache(bot))
        valid_ids, valid_names, invalid = bot._resolve_targets({"test-channel-1"})
        bot.driver.channels.get_channel_by_name.assert_not_called()
        assert "ch_id_1" in valid_ids

    def test_falls_back_to_api_on_name_cache_miss(self, bot):
        asyncio.run(_seed_cache(bot))
        bot.driver.channels.get_channel_by_name.return_value = {"id": "whitelisted_id"}
        valid_ids, _, _ = bot._resolve_targets({"not-in-cache"})
        bot.driver.channels.get_channel_by_name.assert_called_once()

    def test_resolves_display_name_from_cache(self, bot):
        asyncio.run(_seed_cache(bot))
        _, valid_names, _ = bot._resolve_targets({"TestGroup"})
        bot.driver.channels.get_channel.assert_not_called()
        assert "Test Channel 1" in valid_names or "Test Channel 2" in valid_names
