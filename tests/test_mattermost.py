from dotenv import load_dotenv

load_dotenv("tests/test.env")


import unittest
from unittest.mock import MagicMock, patch
from scripts.mattermost import resolve_targets


class TestMattermost(unittest.TestCase):

    @patch("scripts.mattermost.driver")
    def test_resolve_targets_mixed(self, mock_driver):
        # Mocking driver responses
        # group1 contains id1, id2 which are in whitelist
        # "name1" resolves to "name_id" which is in whitelist
        # "id3" is in whitelist
        # "invalid" is NOT in whitelist
        
        mock_driver.channels.get_channel_by_name.side_effect = lambda team_id, name: (
            {"id": "name_id"} if name == "name1" else Exception("Not found")
        )
        mock_driver.channels.get_channel.side_effect = lambda cid: (
            {"display_name": f"Display {cid}"}
        )

        with patch("scripts.mattermost.bot_info", {"team_id": "test_team_id"}), \
             patch("scripts.mattermost.CHANNEL_GROUPS", {"group1": ["id1", "id2"]}), \
             patch("scripts.mattermost.WHITELIST", {"id1", "id2", "id3", "name_id"}):

            inputs = ["group1", "name1", "id3", "invalid"]
            valid_ids, valid_names, invalid_inputs = resolve_targets(inputs)

            # valid_ids should contain id1, id2 (from group1), name_id (from name1), id3 (direct)
            self.assertCountEqual(valid_ids, ["id1", "id2", "name_id", "id3"])
            self.assertCountEqual(valid_names, ["Display id1", "Display id2", "Display name_id", "Display id3"])
            self.assertCountEqual(invalid_inputs, ["invalid"])

    @patch("scripts.mattermost.driver")
    def test_resolve_targets_empty_whitelist(self, mock_driver):
        with patch("scripts.mattermost.bot_info", {"team_id": "test_team_id"}), \
             patch("scripts.mattermost.CHANNEL_GROUPS", {}), \
             patch("scripts.mattermost.WHITELIST", set()):
            inputs = ["some_channel"]
            valid_ids, valid_names, invalid_inputs = resolve_targets(inputs)
            
            self.assertEqual(valid_ids, [])
            self.assertEqual(valid_names, [])
            self.assertEqual(invalid_inputs, ["some_channel"])

if __name__ == "__main__":
    unittest.main()
