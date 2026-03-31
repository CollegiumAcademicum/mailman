import logging
from scripts.config import MATTERMOST_URL, BOT_TOKEN, TEAM_NAME, WHITELIST, CHANNEL_GROUPS
from scripts.state import bot_info
from mattermostdriver import Driver

# Define driver as a global variable, but do not initialize it yet.
driver = Driver(
    {"url": MATTERMOST_URL, "token": BOT_TOKEN, "scheme": "https", "port": 443}
)


def initialize_driver():
    """Initializes the Mattermost driver, logs the bot in, and fetches essential IDs."""
    logging.info("Connecting to Mattermost...")
    driver.login()
    bot_info["bot_id"] = driver.users.get_user("me")["id"]
    bot_info["bot_username"] = driver.users.get_user("me")["username"]

    try:
        bot_info["team_id"] = driver.teams.get_team_by_name(TEAM_NAME)["id"]
        logging.info(
            f"Bot connected. Bot ID: {bot_info['bot_id']} | Team ID: {bot_info['team_id']}"
        )
    except Exception as e:
        logging.critical(
            f"ERROR: Could not find team '{TEAM_NAME}'. Please check TEAM_NAME in your .env file."
        )
        logging.critical(f"Details: {e}")
        exit()


def resolve_targets(requested_inputs):
    """
    Resolves user inputs (channel names, IDs, or groups) into a list of valid channel IDs and names.
    """
    logging.info(f"Resolving targets for inputs: {requested_inputs}")
    valid_ids = set()
    invalid_inputs = set()

    group_channel_ids = set()
    direct_inputs = set()

    for item in requested_inputs:
        stripped_item = item.strip()
        if stripped_item in CHANNEL_GROUPS:
            group_channel_ids.update(CHANNEL_GROUPS[stripped_item])
            logging.debug(f"Resolved group '{stripped_item}' to IDs: {CHANNEL_GROUPS[stripped_item]}")
        else:
            clean_item = stripped_item.lower().strip("#")
            direct_inputs.add(clean_item)

    valid_ids.update(group_channel_ids)

    for target in direct_inputs:
        try:
            channel = driver.channels.get_channel_by_name(bot_info["team_id"], target)
            channel_id = channel["id"]
            logging.debug(f"Resolved channel name '{target}' to ID: {channel_id}")
        except Exception:
            channel_id = target
            logging.debug(f"Could not resolve '{target}' as a name, treating as ID.")

        if channel_id in WHITELIST:
            valid_ids.add(channel_id)
            logging.debug(f"Channel ID '{channel_id}' is in the whitelist.")
        else:
            invalid_inputs.add(target)
            logging.warning(f"Channel '{target}' (resolved to {channel_id}) is not in the whitelist.")

    valid_names = []
    for cid in valid_ids:
        try:
            channel_info = driver.channels.get_channel(cid)
            valid_names.append(channel_info["display_name"])
        except Exception:
            valid_names.append(cid)
            logging.warning(f"Could not get display name for channel ID: {cid}")

    logging.debug(f"Resolved valid IDs: {list(valid_ids)}")
    logging.debug(f"Resolved valid names: {valid_names}")
    logging.info(f"Unresolved/invalid inputs: {list(invalid_inputs)}")
    return list(valid_ids), valid_names, list(invalid_inputs)
