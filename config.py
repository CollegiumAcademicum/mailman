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
CHANNEL_GROUPS = {**VISIBLE_CHANNEL_GROUPS, **PRIVATE_CHANNEL_GROUPS}

WHITELIST = set(channel_data.get("whitelist", []))