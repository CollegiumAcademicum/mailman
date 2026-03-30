import os
import json
from dotenv import load_dotenv

load_dotenv()

MATTERMOST_URL = os.getenv("MATTERMOST_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")
TEAM_NAME = os.getenv("TEAM_NAME")
SESSION_TIMEOUT_SECONDS = int(os.getenv("SESSION_TIMEOUT_SECONDS", 300))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", 60))

# Load channel definitions
with open("channels.json", "r") as f:
    channel_data = json.load(f)

# Public groups to be shown to the user
VISIBLE_CHANNEL_GROUPS = channel_data.get("groups", {})
PRIVATE_CHANNEL_GROUPS = channel_data.get("private_groups", {})

# Merge both for internal use
CHANNEL_GROUPS: dict[str, list[str]] = {**VISIBLE_CHANNEL_GROUPS, **PRIVATE_CHANNEL_GROUPS}

WHITELIST = set(channel_data.get("whitelist", []))

help_message: str = (
            "### Usage\n"
            "**DM me with the message you want delivered, I'll guide you through the process**\n \n "
            "**Other Commands:** \n"
            "!id <channel> : return channel id for <channel> the name must **NOT** be the display_name\n"
            "!channels : list all channels the bot has access to \n"
            "!get_groups : list all available groups and their channels\n"
            "!get_private_groups : same as above but with private groups\n"
            '!add_group <json dict> : add public group(s) scheme: {"name1" : ["id1", "id2", ...], "name2" : ["id1", "id2", ...]}\n'
            "!add_private_group <json dict> : add private group(s) scheme: same as for public groups"
        )
