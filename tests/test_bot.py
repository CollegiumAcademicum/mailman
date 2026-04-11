"""Comprehensive tests for PostBot and DMOnlyMiddleware."""

from __future__ import annotations

import asyncio
import toml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot import DMOnlyMiddleware, GroupEntry, PostBot, WhitelistEntry
from config import PostBotConfig
from mmbot_framework import ParsedMessage


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config(channels_file: Path, tmp_path: Path) -> PostBotConfig:
    return PostBotConfig(
        url="mm.example.com",
        token="test-token",
        team_name="test-team",
        channels_toml_path=channels_file,
        db_path=tmp_path / "test.db",
        bot_log_channel_id="",
        console_log_level="WARNING",
        log_file=None,
    )


@pytest.fixture
def mock_driver() -> MagicMock:
    return MagicMock()


@pytest.fixture
def bot(config: PostBotConfig, mock_driver: MagicMock) -> PostBot:
    with patch("mmbot_framework.core.driver.DriverFactory.create", return_value=mock_driver):
        b = PostBot(config)
    b._team_id = "test-team-id"
    b._bot_username = "testbot"
    b._visible_groups = {"TestGroup": GroupEntry(channels=["ch_id_1", "ch_id_2"], aliases=["tg"])}
    b._private_groups = {"PrivateGroup": GroupEntry(channels=["ch_id_3"], aliases=[])}
    b._whitelist = {
        "ch-id-1": WhitelistEntry(id="ch_id_1", label="ch-id-1", aliases=[]),
        "ch-id-2": WhitelistEntry(id="ch_id_2", label="ch-id-2", aliases=[]),
        "ch-id-3": WhitelistEntry(id="ch_id_3", label="ch-id-3", aliases=[]),
        "whitelisted": WhitelistEntry(id="whitelisted_id", label="whitelisted", aliases=[]),
    }
    b._whitelist_ids = {"ch_id_1", "ch_id_2", "ch_id_3", "whitelisted_id"}
    b._alias_map = {"tg": "TestGroup"}
    return b


# ---------------------------------------------------------------------------
# Helper: extract the most-recently posted message text / channel
# ---------------------------------------------------------------------------


def _last_post(bot: PostBot) -> str:
    call_args = bot.driver.posts.create_post.call_args_list[-1]
    return call_args[0][0]["message"]


# ---------------------------------------------------------------------------
# TestDMOnlyMiddleware
# ---------------------------------------------------------------------------


class TestDMOnlyMiddleware:
    def test_dm_passes_through(self, make_msg):
        middleware = DMOnlyMiddleware()
        msg = make_msg(text="hello", channel_type="D")
        call_next = AsyncMock()
        asyncio.run(middleware(msg, call_next))
        call_next.assert_called_once()

    def test_non_dm_dropped(self, make_msg):
        middleware = DMOnlyMiddleware()
        msg = make_msg(text="hello", channel_type="O")
        call_next = AsyncMock()
        asyncio.run(middleware(msg, call_next))
        call_next.assert_not_called()


# ---------------------------------------------------------------------------
# TestHandleHelp
# ---------------------------------------------------------------------------


class TestHandleHelp:
    def test_help_triggers(self, bot: PostBot, make_msg):
        for trigger in ["!help", "help", "--help", "man"]:
            bot.driver.posts.create_post.reset_mock()
            asyncio.run(bot._dispatcher.dispatch(make_msg(text=trigger)))
            assert bot.driver.posts.create_post.called, (
                f"Expected post for trigger {trigger!r}"
            )
            msg_text = bot.driver.posts.create_post.call_args[0][0]["message"]
            assert "Usage" in msg_text, (
                f"Expected 'Usage' in help text for trigger {trigger!r}"
            )


# ---------------------------------------------------------------------------
# TestHandleId
# ---------------------------------------------------------------------------


class TestHandleId:
    def test_id_returns_channel_id(self, bot: PostBot, make_msg):
        bot.driver.channels.get_channel_by_name.return_value = {"id": "found_ch_id"}
        asyncio.run(bot._handle_id(make_msg(text="!id town-square")))
        assert "found_ch_id" in _last_post(bot)

    def test_id_empty_name(self, bot: PostBot, make_msg):
        asyncio.run(bot._handle_id(make_msg(text="!id")))
        assert "Please provide a channel name" in _last_post(bot)

    def test_id_channel_not_found(self, bot: PostBot, make_msg):
        bot.driver.channels.get_channel_by_name.side_effect = Exception("not found")
        asyncio.run(bot._handle_id(make_msg(text="!id missing")))
        assert "Could not find" in _last_post(bot)


# ---------------------------------------------------------------------------
# TestHandleChannels
# ---------------------------------------------------------------------------


class TestHandleChannels:
    def test_channels_returns_table(self, bot: PostBot, make_msg):
        # Seed the cache so _handle_channels reads from it instead of the driver.
        from mmbot_framework.core.cache import CacheManager
        from unittest.mock import AsyncMock as _AsyncMock

        cache_data = {
            "by_id": {
                "ch123": {
                    "name": "general",
                    "display_name": "General",
                    "team_name": "My Team",
                    "team_id": "t1",
                }
            },
            "by_name": {"general": "ch123"},
            "all_rows": ["| `General` | general | `ch123` | My Team |"],
        }
        loader = _AsyncMock(return_value=cache_data)
        bot.cache.register("channels", loader, ttl=3600)
        asyncio.run(bot.cache.refresh("channels"))

        asyncio.run(bot._handle_channels(make_msg(text="!channels")))
        text = _last_post(bot)
        assert "general" in text
        assert "ch123" in text

    def test_channels_warns_when_cache_empty(self, bot: PostBot, make_msg):
        # No cache seeded — should get a warning message.
        asyncio.run(bot._handle_channels(make_msg(text="!channels")))
        text = _last_post(bot)
        assert "⚠️" in text


# ---------------------------------------------------------------------------
# TestHandleGetGroups
# ---------------------------------------------------------------------------


class TestHandleGetGroups:
    def test_get_groups_lists_groups(self, bot: PostBot, make_msg):
        bot.driver.channels.get_channel.return_value = {"name": "general"}
        asyncio.run(bot._handle_get_groups(make_msg(text="!get_groups")))
        assert "TestGroup" in _last_post(bot)

    def test_get_groups_empty(self, bot: PostBot, make_msg):
        bot._visible_groups = {}
        asyncio.run(bot._handle_get_groups(make_msg(text="!get_groups")))
        assert _last_post(bot) == "No groups configured."


# ---------------------------------------------------------------------------
# TestHandleGetPrivateGroups
# ---------------------------------------------------------------------------


class TestHandleGetPrivateGroups:
    def test_get_private_groups_lists_groups(self, bot: PostBot, make_msg):
        bot.driver.channels.get_channel.return_value = {"name": "private-ch"}
        asyncio.run(bot._handle_get_private_groups(make_msg(text="!get_private_groups")))
        assert "PrivateGroup" in _last_post(bot)


# ---------------------------------------------------------------------------
# TestHandleAddGroup
# ---------------------------------------------------------------------------


class TestHandleAddGroup:
    def test_add_group_valid_json(self, bot: PostBot, make_msg):
        bot.driver.channels.get_channel.return_value = {"id": "new_ch"}
        asyncio.run(
            bot._handle_add_group(make_msg(text='!add_group NewGroup = ["new_ch"]'))
        )
        assert "NewGroup" in bot._visible_groups
        assert "✅ Group added successfully!" in _last_post(bot)

        # Verify group was written to disk
        saved_data = toml.loads(bot.config.channels_toml_path.read_text())
        assert "NewGroup" in saved_data["groups"]

    def test_add_group_invalid_json(self, bot: PostBot, make_msg):
        asyncio.run(bot._handle_add_group(make_msg(text="!add_group not json")))
        assert "Invalid JSON" in _last_post(bot)

    def test_add_group_empty_payload(self, bot: PostBot, make_msg):
        asyncio.run(bot._handle_add_group(make_msg(text="!add_group")))
        assert "Please provide a JSON payload" in _last_post(bot)

    def test_add_group_all_invalid_channels(self, bot: PostBot, make_msg):
        bot.driver.channels.get_channel.side_effect = Exception("not found")
        asyncio.run(
            bot._handle_add_group(make_msg(text='!add_group BadGroup = ["bad_id"]'))
        )
        text = _last_post(bot)
        assert "No valid groups to add" in text or "no valid channels" in text.lower()

    def test_add_private_group(self, bot: PostBot, make_msg):
        bot.driver.channels.get_channel.return_value = {"id": "priv_ch"}
        asyncio.run(
            bot._handle_add_private_group(
                make_msg(text='!add_private_group NewPrivate = ["priv_ch"]')
            )
        )
        assert "NewPrivate" in bot._private_groups

    def test_add_group_payload_parsing_no_lstrip_bug(self, bot: PostBot, make_msg):
        """Verify that JSON payload is parsed correctly without character-stripping bug.

        The old code used lstrip("!_add_group") which strips individual characters
        {!, _, a, d, g, r, o, u, p} from the left. A group name starting with any of
        these chars (like "purple_group" which starts with 'p') would be mangled if the
        lstrip was applied to the group name. The fix uses text[len("!add_group"):]
        which removes exactly the trigger prefix, preserving all group names.
        """
        bot.driver.channels.get_channel.return_value = {"id": "ch_id_1"}
        asyncio.run(
            bot._handle_add_group(make_msg(text='!add_group purple_group = ["ch_id_1"]'))
        )
        assert "purple_group" in bot._visible_groups


# ---------------------------------------------------------------------------
# TestBroadcastWizard
# ---------------------------------------------------------------------------


class TestBroadcastWizard:
    def test_new_user_gets_welcome(self, bot: PostBot, make_msg):
        msg = make_msg(text="Hello", sender_id="user1")
        asyncio.run(bot.on_message(msg))
        assert "Welcome, I'm the Postbot" in _last_post(bot)
        assert "user1" in bot._known_users

    def test_known_user_no_session_creates_session(self, bot: PostBot, make_msg):
        bot._known_users.add("user1")
        bot.driver.channels.get_channel.return_value = {
            "name": "ch",
            "display_name": "Ch",
            "team_id": "t1",
        }
        bot.driver.teams.get_team.return_value = {"display_name": "Team"}
        asyncio.run(
            bot.on_message(make_msg(text="My broadcast message", sender_id="user1"))
        )
        session = bot.sessions.get("user1")
        assert session is not None
        assert session.data["state"] == "AWAITING_CHANNELS"
        assert session.data["message"] == "My broadcast message"

    def test_awaiting_channels_valid_targets(self, bot: PostBot, make_msg):
        bot._known_users.add("user1")
        session = bot.sessions.get_or_create("user1")
        session.data = {
            "state": "AWAITING_CHANNELS",
            "message": "hello",
            "file_ids": [],
            "dm_channel_id": "dm_ch_1",
        }
        bot.driver.channels.get_channel_by_name.return_value = {"id": "ch_id_1"}
        bot.driver.channels.get_channel.return_value = {"display_name": "General"}
        asyncio.run(bot.on_message(make_msg(text="ch_id_1", sender_id="user1")))
        assert session.data["state"] == "CONFIRMATION"
        assert "target_ids" in session.data
        assert "Preview" in _last_post(bot)

    def test_awaiting_channels_no_valid_targets(self, bot: PostBot, make_msg):
        bot._known_users.add("user1")
        session = bot.sessions.get_or_create("user1")
        session.data = {
            "state": "AWAITING_CHANNELS",
            "message": "hello",
            "file_ids": [],
            "dm_channel_id": "dm_ch_1",
        }
        bot.driver.channels.get_channel_by_name.side_effect = Exception("not found")
        bot._whitelist = set()
        asyncio.run(
            bot.on_message(make_msg(text="invalid-channel", sender_id="user1"))
        )
        # Session must still be AWAITING_CHANNELS (not cleared)
        current_session = bot.sessions.get("user1")
        assert current_session is not None
        assert current_session.data["state"] == "AWAITING_CHANNELS"
        assert "No valid channels found" in _last_post(bot)

    def test_confirmation_yes_sends_broadcast(self, bot: PostBot, make_msg):
        bot._known_users.add("user1")
        session = bot.sessions.get_or_create("user1")
        session.data = {
            "state": "CONFIRMATION",
            "message": "hello world",
            "file_ids": [],
            "dm_channel_id": "dm_ch_1",
            "target_ids": ["ch_id_1"],
            "valid_names": ["General"],
        }
        with patch("bot.log_broadcast") as mock_log:
            asyncio.run(
                bot.on_message(
                    make_msg(text="yes", sender_id="user1", channel_id="dm_ch_1")
                )
            )

        # Broadcast was sent to ch_id_1
        all_calls = bot.driver.posts.create_post.call_args_list
        broadcast_calls = [c for c in all_calls if c[0][0].get("channel_id") == "ch_id_1"]
        assert broadcast_calls, "Expected a post to ch_id_1"

        mock_log.assert_called_once()
        assert bot.sessions.get("user1") is None

        # Success message is the last post
        assert "✅ **Broadcast sent successfully.**" in _last_post(bot)

    def test_confirmation_no_cancels(self, bot: PostBot, make_msg):
        bot._known_users.add("user1")
        session = bot.sessions.get_or_create("user1")
        session.data = {
            "state": "CONFIRMATION",
            "message": "hello world",
            "file_ids": [],
            "dm_channel_id": "dm_ch_1",
            "target_ids": ["ch_id_1"],
            "valid_names": ["General"],
        }
        asyncio.run(bot.on_message(make_msg(text="no", sender_id="user1")))
        assert "❌ **Broadcast canceled.**" in _last_post(bot)
        assert bot.sessions.get("user1") is None

    def test_confirmation_invalid_keeps_session(self, bot: PostBot, make_msg):
        bot._known_users.add("user1")
        session = bot.sessions.get_or_create("user1")
        session.data = {
            "state": "CONFIRMATION",
            "message": "hello world",
            "file_ids": [],
            "dm_channel_id": "dm_ch_1",
            "target_ids": ["ch_id_1"],
            "valid_names": ["General"],
        }
        asyncio.run(bot.on_message(make_msg(text="maybe", sender_id="user1")))
        assert "Invalid response" in _last_post(bot)
        assert bot.sessions.get("user1") is not None

    def test_send_broadcast_with_files(self, bot: PostBot, make_msg):
        bot._known_users.add("user1")
        session = bot.sessions.get_or_create("user1")
        session.data = {
            "state": "CONFIRMATION",
            "message": "hello world",
            "file_ids": ["file_id_1"],
            "dm_channel_id": "dm_ch_1",
            "target_ids": ["ch_id_1"],
            "valid_names": ["General"],
        }
        file_response = MagicMock()
        file_response.content = b"binary_data"
        bot.driver.files.get_file.return_value = file_response
        bot.driver.files.get_file_metadata.return_value = {"name": "attachment.txt"}
        bot.driver.files.upload_file.return_value = {"file_infos": [{"id": "new_file_id"}]}

        with patch("bot.log_broadcast"):
            asyncio.run(bot.on_message(make_msg(text="yes", sender_id="user1")))

        bot.driver.files.upload_file.assert_called()

        # Verify the post to ch_id_1 includes the re-uploaded file ID
        all_calls = bot.driver.posts.create_post.call_args_list
        broadcast_calls = [c for c in all_calls if c[0][0].get("channel_id") == "ch_id_1"]
        assert broadcast_calls, "Expected a post to ch_id_1"
        assert "new_file_id" in broadcast_calls[0][0][0]["file_ids"]


# ---------------------------------------------------------------------------
# TestResolveTargets
# ---------------------------------------------------------------------------


class TestResolveTargets:
    def test_resolve_group_name(self, bot: PostBot):
        bot.driver.channels.get_channel.return_value = {"display_name": "General"}
        valid_ids, valid_names, invalid = bot._resolve_targets(["TestGroup"])
        assert "ch_id_1" in valid_ids
        assert "ch_id_2" in valid_ids
        assert len(invalid) == 0

    def test_resolve_channel_by_name(self, bot: PostBot):
        bot.driver.channels.get_channel_by_name.return_value = {"id": "whitelisted_id"}
        bot.driver.channels.get_channel.return_value = {"display_name": "Whitelisted Ch"}
        valid_ids, valid_names, invalid = bot._resolve_targets(["some-channel"])
        assert "whitelisted_id" in valid_ids

    def test_resolve_direct_channel_id_whitelisted(self, bot: PostBot):
        bot.driver.channels.get_channel_by_name.side_effect = Exception("not found")
        bot.driver.channels.get_channel.return_value = {"display_name": "Ch"}
        valid_ids, valid_names, invalid = bot._resolve_targets(["ch_id_1"])
        assert "ch_id_1" in valid_ids

    def test_resolve_non_whitelisted_is_invalid(self, bot: PostBot):
        bot.driver.channels.get_channel_by_name.side_effect = Exception("not found")
        valid_ids, valid_names, invalid = bot._resolve_targets(["not-in-whitelist"])
        assert len(valid_ids) == 0
        assert "not-in-whitelist" in invalid

    def test_resolve_mixed_inputs(self, bot: PostBot):
        bot.driver.channels.get_channel_by_name.side_effect = Exception()
        bot.driver.channels.get_channel.return_value = {"display_name": "Ch"}
        valid_ids, valid_names, invalid = bot._resolve_targets(
            ["TestGroup", "ch_id_1", "not-in-whitelist"]
        )
        assert "ch_id_1" in valid_ids
        assert "ch_id_2" in valid_ids
        assert "not-in-whitelist" in invalid
