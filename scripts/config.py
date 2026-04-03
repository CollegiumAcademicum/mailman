import os
import json
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler


# Base directory for the project
BASE_DIR = Path(__file__).resolve().parent.parent

# These Environment Variables MUST be set.
# the Code will fail if they are not set.
# For more info --> README.md
MATTERMOST_URL = os.environ["MATTERMOST_URL"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
TEAM_NAME = os.environ["TEAM_NAME"]


# These Env Variables are optional:
# Bot log channel (if set, a metadata-only audit post is sent there after each broadcast)
BOT_LOG_CHANNEL_ID = os.getenv("BOT_LOG_CHANNEL_ID", "")
# Sessions
SESSION_TIMEOUT_SECONDS = int(os.getenv("SESSION_TIMEOUT_SECONDS", 300))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", 60))
# Logging
LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", "DEBUG")
CONSOLE_LOGGING_LEVEL = os.getenv("CONSOLE_LOGGING_LEVEL", "WARNING")
LOG_FILE = os.getenv("LOG_FILE", str(BASE_DIR / "logs" / "bot.log"))

# Paths for JSON and Database files
CHANNELS_JSON_PATH = Path(os.getenv("CHANNELS_JSON_PATH", str(BASE_DIR / "channels.json")))
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "broadcast_log.db")))

# Load channel definitions
with open(CHANNELS_JSON_PATH, "r") as f:
    channel_data = json.load(f)

# Public groups to be shown to the user
VISIBLE_CHANNEL_GROUPS = channel_data.get("groups", {})
PRIVATE_CHANNEL_GROUPS = channel_data.get("private_groups", {})

# Merge both for internal use
CHANNEL_GROUPS: dict[str, list[str]] = {**VISIBLE_CHANNEL_GROUPS, **PRIVATE_CHANNEL_GROUPS}

WHITELIST = set(channel_data.get("whitelist", []))

HELP_MESSAGE: str = (
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



def _logging_setup():
    if not os.path.exists(LOG_FILE):
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    # --- Logging Setup ---
    log_file = LOG_FILE
    max_log_size = 100 * 1024 * 1024  # 100 MB
    backup_count = 5

    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(LOGGING_LEVEL)

    # Create a rotating file handler
    file_handler = RotatingFileHandler(
    log_file, maxBytes=max_log_size, backupCount=backup_count
    )
    file_handler.setLevel(LOGGING_LEVEL)

    # Create a console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(CONSOLE_LOGGING_LEVEL)

    # Create a formatter and set it for both handlers
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

_logging_setup()
logging.critical("config setup finished")