from config import MATTERMOST_URL, BOT_TOKEN, TEAM_NAME, WHITELIST, CHANNEL_GROUPS
from state import bot_info
from mattermostdriver import Driver

# Define driver as a global variable, but do not initialize it yet.
driver: Driver = None


def initialize_driver():
    """Initializes the Mattermost driver, logs the bot in, and fetches essential IDs."""
    global driver
    print("Connecting to Mattermost...")

    driver = Driver(
        {"url": MATTERMOST_URL, "token": BOT_TOKEN, "scheme": "https", "port": 443}
    )

    driver.login()
    bot_info["bot_id"] = driver.users.get_user("me")["id"]
    bot_info["bot_username"] = driver.users.get_user("me")["username"]

    try:
        bot_info["team_id"] = driver.teams.get_team_by_name(TEAM_NAME)["id"]
        print(
            f"Bot connected. Bot ID: {bot_info['bot_id']} | Team ID: {bot_info['team_id']}"
        )
    except Exception as e:
        print(
            f"ERROR: Could not find team '{TEAM_NAME}'. Please check TEAM_NAME in your .env file."
        )
        print(f"Details: {e}")
        exit()


def resolve_targets(requested_inputs):
    """
    Resolves user inputs (channel names, IDs, or groups) into a list of valid channel IDs and names.
    """
    valid_ids = set()
    invalid_inputs = set()

    group_channel_ids = set()
    direct_inputs = set()

    for item in requested_inputs:
        clean_item = item.strip().lower().strip("#")
        if clean_item in CHANNEL_GROUPS:
            group_channel_ids.update(CHANNEL_GROUPS[clean_item])
        else:
            direct_inputs.add(clean_item)

    valid_ids.update(group_channel_ids)

    for target in direct_inputs:
        try:
            channel = driver.channels.get_channel_by_name(bot_info["team_id"], target)
            channel_id = channel["id"]
        except Exception:
            channel_id = target

        if channel_id in WHITELIST:
            valid_ids.add(channel_id)
        else:
            invalid_inputs.add(target)

    valid_names = []
    for cid in valid_ids:
        try:
            channel_info = driver.channels.get_channel(cid)
            valid_names.append(channel_info["display_name"])
        except Exception:
            valid_names.append(cid)

    return list(valid_ids), valid_names, list(invalid_inputs)
