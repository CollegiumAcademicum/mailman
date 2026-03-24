import asyncio
import json
import unittest
from unittest.mock import MagicMock, mock_open, patch

from main import message_handler
from state import known_users, sessions


class TestBot(unittest.TestCase):
    def setUp(self):
        """Clear state before each test."""
        sessions.clear()
        known_users.clear()

    @staticmethod
    def create_message(
        text,
        user_id="user_id_1",
        channel_id="dm_channel_id_1",
        sender_name="@testuser",
        file_ids=None,
    ):
        if file_ids is None:
            file_ids = []
        return json.dumps(
            {
                "event": "posted",
                "data": {
                    "channel_type": "D",
                    "post": json.dumps(
                        {
                            "user_id": user_id,
                            "channel_id": channel_id,
                            "message": text,
                            "file_ids": file_ids,
                        }
                    ),
                    "sender_name": sender_name,
                },
            }
        )

    @patch("main.driver", new_callable=MagicMock)
    def test_help_command(self, mock_driver):
        message = self.create_message("!help")
        asyncio.run(message_handler(message))
        self.assertIn("Usage", mock_driver.posts.create_post.call_args[0][0]["message"])

    @patch("handlers.driver", new_callable=MagicMock)
    @patch("handlers.bot_info", {"team_id": "test_team_id"})
    def test_id_command_found(self, mock_driver):
        mock_driver.channels.get_channel_by_name.return_value = {
            "id": "channel_id_found"
        }
        message = self.create_message("!id test-channel")
        asyncio.run(message_handler(message))
        mock_driver.posts.create_post.assert_called_with(
            {
                "channel_id": "dm_channel_id_1",
                "message": "The ID for channel `test-channel` is: `channel_id_found`",
            }
        )

    @patch("main.driver", new_callable=MagicMock)
    def test_channels_command(self, mock_driver):
        mock_driver.teams.get_user_teams.return_value = [{"id": "team_id_1"}]
        mock_driver.channels.get_channels_for_user.return_value = [
            {"display_name": "Channel 1", "name": "channel-1", "id": "channel_id_1"}
        ]
        message = self.create_message("!channels")
        asyncio.run(message_handler(message))
        mock_driver.posts.create_post.assert_called_with(
            {
                "channel_id": "dm_channel_id_1",
                "message": "Channel 1 (channel-1) | ID: channel_id_1",
            }
        )

    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data='{"groups": {}, "private_groups": {}}',
    )
    @patch("handlers.driver", new_callable=MagicMock)
    @patch("handlers.VISIBLE_CHANNEL_GROUPS", {})
    def test_add_group_command(self, mock_driver, m_open):
        mock_driver.channels.get_channel.return_value = {}
        message = self.create_message('!add_group {"new_group": ["id1"]}')
        asyncio.run(message_handler(message))
        mock_driver.posts.create_post.assert_called_with(
            {"channel_id": "dm_channel_id_1", "message": "✅ Group added successfully!"}
        )

    @patch("handlers.driver", new_callable=MagicMock)
    def test_new_user_flow(self, mock_driver):
        self.assertNotIn("new_user", known_users)
        message = self.create_message("Hello", user_id="new_user")
        asyncio.run(message_handler(message))
        self.assertIn("new_user", known_users)
        self.assertIn(
            "Welcome, I'm the Mailman",
            mock_driver.posts.create_post.call_args[0][0]["message"],
        )

    @patch("handlers.driver", new_callable=MagicMock)
    @patch("handlers.WHITELIST", ["channel_id_1"])
    @patch("handlers.VISIBLE_CHANNEL_GROUPS", {"Group 1": ["id1"]})
    def test_conversation_flow(self, mock_driver):
        # -- Step 1: Start a new session ---
        known_users.add("user_id_1")
        mock_driver.channels.get_channel.return_value = {
            "name": "channel-1",
            "display_name": "Channel 1",
        }

        message1 = self.create_message("My broadcast message")
        asyncio.run(message_handler(message1))

        self.assertIn("user_id_1", sessions)
        self.assertEqual(sessions["user_id_1"]["state"], "AWAITING_CHANNELS")
        self.assertIn(
            "I've captured your message",
            mock_driver.posts.create_post.call_args[0][0]["message"],
        )

        # -- Step 2: User provides channel -> moves to confirmation ---
        mock_driver.reset_mock()
        with patch(
            "handlers.resolve_targets",
            return_value=(["target_id_1"], ["target_name_1"], []),
        ):
            message2 = self.create_message("target_name_1")
            asyncio.run(message_handler(message2))

        self.assertEqual(sessions["user_id_1"]["state"], "CONFIRMATION")
        self.assertIn(
            "Preview:", mock_driver.posts.create_post.call_args[0][0]["message"]
        )

        # -- Step 3: User confirms -> broadcast is sent and session is cleared ---
        mock_driver.reset_mock()
        with (
            patch("handlers.bot_info", {"bot_username": "testbot"}),
            patch("handlers.log_broadcast") as mock_log,
        ):
            message3 = self.create_message("yes")
            asyncio.run(message_handler(message3))

        self.assertNotIn("user_id_1", sessions)

        broadcast_message = "📢 **Message from @testuser**\n \n \nMy broadcast message\n \n \n \n*--- END of Message ---*\n*If YOU want to use the services of me (@testbot) just DM me*"
        mock_driver.posts.create_post.assert_any_call(
            {"channel_id": "target_id_1", "message": broadcast_message, "file_ids": []}
        )
        self.assertIn(
            "Broadcast sent successfully",
            mock_driver.posts.create_post.call_args[0][0]["message"],
        )
        mock_log.assert_called_once()

    @patch("handlers.driver", new_callable=MagicMock)
    def test_conversation_cancellation(self, mock_driver):
        known_users.add("user_id_1")
        sessions["user_id_1"] = {"state": "CONFIRMATION"}
        message = self.create_message("no")
        asyncio.run(message_handler(message))
        self.assertNotIn("user_id_1", sessions)
        mock_driver.posts.create_post.assert_called_with(
            {"channel_id": "dm_channel_id_1", "message": "❌ **Broadcast canceled.**"}
        )

    @patch("handlers.driver", new_callable=MagicMock)
    def test_file_attachment_flow(self, mock_driver):
        known_users.add("user_id_1")
        sessions["user_id_1"] = {
            "state": "CONFIRMATION",
            "message": "Test with file",
            "file_ids": ["file_id_1"],
            "target_ids": ["channel_id_1"],
            "valid_names": ["channel-1"],
            "dm_channel_id": "dm_channel_id_1",
        }
        mock_driver.files.get_file.return_value.content = b"file_content"
        mock_driver.files.get_file_metadata.return_value = {"name": "test_file.txt"}
        mock_driver.files.upload_file.return_value = {
            "file_infos": [{"id": "new_file_id"}]
        }

        with patch("handlers.bot_info", {"bot_username": "testbot"}):
            message = self.create_message("yes")
            asyncio.run(message_handler(message))

        mock_driver.files.get_file.assert_called_with("file_id_1")
        mock_driver.files.upload_file.assert_called_with(
            channel_id="channel_id_1",
            files={"files": ("test_file.txt", b"file_content")},
        )
        self.assertIn(
            "new_file_id",
            mock_driver.posts.create_post.call_args_list[0].args[0]["file_ids"],
        )

    @patch("main.driver", new_callable=MagicMock)
    def test_invalid_id_command(self, mock_driver):
        message = self.create_message("!id")
        asyncio.run(message_handler(message))
        mock_driver.posts.create_post.assert_called_with(
            {
                "channel_id": "dm_channel_id_1",
                "message": "Please provide a channel name after `!id!`.",
            }
        )

    @patch("handlers.driver", new_callable=MagicMock)
    def test_invalid_channel_selection(self, mock_driver):
        known_users.add("user_id_1")
        sessions["user_id_1"] = {"state": "AWAITING_CHANNELS"}
        with patch(
            "handlers.resolve_targets", return_value=([], [], ["invalid1", "invalid2"])
        ):
            message = self.create_message("invalid1, invalid2")
            asyncio.run(message_handler(message))

        mock_driver.posts.create_post.assert_called_with(
            {
                "channel_id": "dm_channel_id_1",
                "message": "⚠️ No valid channels found. Please try again.",
            }
        )
        self.assertEqual(sessions["user_id_1"]["state"], "AWAITING_CHANNELS")


if __name__ == "__main__":
    unittest.main()
