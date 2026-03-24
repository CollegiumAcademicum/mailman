import unittest
import json
from unittest.mock import patch, AsyncMock, call, mock_open
from main import message_handler
import handlers as h

class TestBot(unittest.TestCase):
    @patch('main.driver')
    def test_bot_responds_to_help_command(self, mock_driver):
        # Configure the mock to be an AsyncMock
        mock_driver.posts.create_post = AsyncMock()

        # Mock the websocket message
        message = json.dumps({
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "user_id": "user_id_1",
                    "channel_id": "dm_channel_id_1",
                    "message": "!help",
                    "file_ids": []
                }),
                "sender_name": "@testuser"
            }
        })

        # Call the message handler
        import asyncio
        asyncio.run(message_handler(message))

        # Assert that the driver's create_post method was called with the help message
        expected_message = ("### Usage\n"
                   "**DM me with the message you want delivered, I'll guide you through the process**\n \n "
                   "**Other Commands:** \n"
                   "!id <channel> : return channel id for <channel> the name must **NOT** be the display_name\n"
                   "!channels : list all channels the bot has access to \n"
                   "!get_groups : list all available groups and their channels\n"
                   "!get_private_groups : same as above but with private groups\n"
                   '!add_group <json dict> : add public group(s) scheme: {"name1" : ["id1", "id2", ...], "name2" : ["id1", "id2", ...]}\n'
                   "!add_private_group <json dict> : add private group(s) scheme: same as for public groups"
                   )
        mock_driver.posts.create_post.assert_called_with({
            "channel_id": "dm_channel_id_1",
            "message": expected_message
        })

    @patch('handlers.driver')
    @patch('main.bot_info', {'team_id': 'test_team_id'})
    def test_id_command_found(self, mock_driver):
        mock_driver.channels.get_channel_by_name.return_value = {'id': 'channel_id_found'}
        mock_driver.posts.create_post = AsyncMock()

        message = json.dumps({
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "user_id": "user_id_1",
                    "channel_id": "dm_channel_id_1",
                    "message": "!id test-channel",
                    "file_ids": []
                }),
                "sender_name": "@testuser"
            }
        })

        import asyncio
        asyncio.run(message_handler(message))

        mock_driver.posts.create_post.assert_called_with({
            "channel_id": "dm_channel_id_1",
            "message": "The ID for channel `test-channel` is: `channel_id_found`"
        })

    @patch('handlers.driver')
    @patch('main.bot_info', {'team_id': 'test_team_id'})
    def test_id_command_not_found(self, mock_driver):
        mock_driver.channels.get_channel_by_name.side_effect = Exception("Channel not found")
        mock_driver.posts.create_post = AsyncMock()

        message = json.dumps({
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "user_id": "user_id_1",
                    "channel_id": "dm_channel_id_1",
                    "message": "!id non-existent-channel",
                    "file_ids": []
                }),
                "sender_name": "@testuser"
            }
        })

        import asyncio
        asyncio.run(message_handler(message))

        mock_driver.posts.create_post.assert_called_with({
            "channel_id": "dm_channel_id_1",
            "message": "⚠️ Could not find a channel named `non-existent-channel`."
        })

    @patch('main.driver')
    def test_channels_command(self, mock_driver):
        mock_driver.teams.get_user_teams.return_value = [{'id': 'team_id_1'}]
        mock_driver.channels.get_channels_for_user.return_value = [
            {'display_name': 'Channel 1', 'name': 'channel-1', 'id': 'channel_id_1'},
            {'display_name': 'Channel 2', 'name': 'channel-2', 'id': 'channel_id_2'}
        ]
        mock_driver.posts.create_post = AsyncMock()

        message = json.dumps({
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "user_id": "user_id_1",
                    "channel_id": "dm_channel_id_1",
                    "message": "!channels",
                    "file_ids": []
                }),
                "sender_name": "@testuser"
            }
        })

        import asyncio
        asyncio.run(message_handler(message))

        expected_message = "Channel 1 (channel-1) | ID: channel_id_1\nChannel 2 (channel-2) | ID: channel_id_2"
        mock_driver.posts.create_post.assert_called_with({
            "channel_id": "dm_channel_id_1",
            "message": expected_message
        })

    @patch('main.driver')
    @patch('main.VISIBLE_CHANNEL_GROUPS', {'Group 1': ['id1', 'id2']})
    def test_get_groups_command(self, mock_driver):
        mock_driver.channels.get_channel.side_effect = lambda id: {'name': f'name-for-{id}'}
        mock_driver.posts.create_post = AsyncMock()

        message = json.dumps({
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "user_id": "user_id_1",
                    "channel_id": "dm_channel_id_1",
                    "message": "!get_groups",
                    "file_ids": []
                }),
                "sender_name": "@testuser"
            }
        })

        import asyncio
        asyncio.run(message_handler(message))

        expected_message = "Group 1: ['name-for-id1', 'name-for-id2']\n \n"
        mock_driver.posts.create_post.assert_called_with({
            "channel_id": "dm_channel_id_1",
            "message": expected_message
        })

    @patch('main.driver')
    @patch('main.PRIVATE_CHANNEL_GROUPS', {'Private Group 1': ['p_id1', 'p_id2']})
    def test_get_private_groups_command(self, mock_driver):
        mock_driver.channels.get_channel.side_effect = lambda id: {'name': f'name-for-{id}'}
        mock_driver.posts.create_post = AsyncMock()

        message = json.dumps({
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "user_id": "user_id_1",
                    "channel_id": "dm_channel_id_1",
                    "message": "!get_private_groups",
                    "file_ids": []
                }),
                "sender_name": "@testuser"
            }
        })

        import asyncio
        asyncio.run(message_handler(message))

        expected_message = "Private Group 1: ['name-for-p_id1', 'name-for-p_id2']\n \n"
        mock_driver.posts.create_post.assert_called_with({
            "channel_id": "dm_channel_id_1",
            "message": expected_message
        })

    @patch('builtins.open', new_callable=mock_open, read_data='{"groups": {}, "private_groups": {}}')
    @patch('handlers.driver')
    @patch('main.VISIBLE_CHANNEL_GROUPS', {})
    def test_add_group_command(self, mock_driver, m_open):
        mock_driver.channels.get_channel.return_value = {}
        mock_driver.posts.create_post = AsyncMock()

        message = json.dumps({
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "user_id": "user_id_1",
                    "channel_id": "dm_channel_id_1",
                    "message": '!add_group {"new_group": ["id1", "id2"]}',
                    "file_ids": []
                }),
                "sender_name": "@testuser"
            }
        })

        import asyncio
        asyncio.run(message_handler(message))

        m_open.assert_called_with('channels.json', 'w')
        handle = m_open()
        handle.write.assert_called()
        # Get the content that was written
        written_content = handle.write.call_args[0][0]
        written_data = json.loads(written_content)
        self.assertIn('new_group', written_data['groups'])
        self.assertEqual(written_data['groups']['new_group'], ['id1', 'id2'])

        mock_driver.posts.create_post.assert_called_with({
            "channel_id": "dm_channel_id_1",
            "message": "✅ Group added successfully!"
        })

    @patch('builtins.open', new_callable=mock_open, read_data='{"groups": {}, "private_groups": {}}')
    @patch('handlers.driver')
    @patch('main.PRIVATE_CHANNEL_GROUPS', {})
    def test_add_private_group_command(self, mock_driver, m_open):
        mock_driver.channels.get_channel.return_value = {}
        mock_driver.posts.create_post = AsyncMock()

        message = json.dumps({
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "user_id": "user_id_1",
                    "channel_id": "dm_channel_id_1",
                    "message": '!add_private_group {"new_private_group": ["p_id1", "p_id2"]}',
                    "file_ids": []
                }),
                "sender_name": "@testuser"
            }
        })

        import asyncio
        asyncio.run(message_handler(message))

        m_open.assert_called_with('channels.json', 'w')
        handle = m_open()
        handle.write.assert_called()
        # Get the content that was written
        written_content = handle.write.call_args[0][0]
        written_data = json.loads(written_content)
        self.assertIn('new_private_group', written_data['private_groups'])
        self.assertEqual(written_data['private_groups']['new_private_group'], ['p_id1', 'p_id2'])

        mock_driver.posts.create_post.assert_called_with({
            "channel_id": "dm_channel_id_1",
            "message": "✅ Group added successfully!"
        })

    @patch('main.driver')
    @patch('main.known_users', set())
    def test_new_user(self, mock_driver):
        mock_driver.posts.create_post = AsyncMock()

        message = json.dumps({
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "user_id": "new_user_id",
                    "channel_id": "dm_channel_id_1",
                    "message": "Hello",
                    "file_ids": []
                }),
                "sender_name": "@newuser"
            }
        })

        import asyncio
        asyncio.run(message_handler(message))

        mock_driver.posts.create_post.assert_called_with({
            "channel_id": "dm_channel_id_1",
            "message": (
                "👋 **Welcome, I'm the Mailman**\n\n"
                "To send a broadcast, just send me the message you want to share (you can attach files too!). "
                "I will then ask you to specify the target channels or groups.\n\n"
                "Your message will *not* be sent until you confirm.\n\n"
                "**TYPE YOUR MESSAGE AND/OR ATTACH FILES NOW:**"
            )
        })

    @patch('main.driver')
    @patch('main.sessions', {})
    @patch('main.known_users', {'user_id_1'})
    @patch('main.WHITELIST', ['channel_id_1'])
    @patch('main.VISIBLE_CHANNEL_GROUPS', {'Group 1': ['id1']})
    def test_new_session(self, mock_driver):
        mock_driver.channels.get_channel.return_value = {'name': 'channel-1', 'display_name': 'Channel 1'}
        mock_driver.posts.create_post = AsyncMock()

        message = json.dumps({
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "user_id": "user_id_1",
                    "channel_id": "dm_channel_id_1",
                    "message": "My broadcast message",
                    "file_ids": []
                }),
                "sender_name": "@testuser"
            }
        })

        import asyncio
        asyncio.run(message_handler(message))

        self.assertIn("user_id_1", h.sessions)
        self.assertEqual(h.sessions["user_id_1"]["state"], "AWAITING_CHANNELS")
        self.assertEqual(h.sessions["user_id_1"]["message"], "My broadcast message")

if __name__ == '__main__':
    unittest.main()
