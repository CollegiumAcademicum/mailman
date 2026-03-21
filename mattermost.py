from mattermostdriver import Driver
from config import MATTERMOST_URL, BOT_TOKEN, TEAM_NAME, WHITELIST, CHANNEL_GROUPS
from state import bot_info

# Initialize the Mattermost driver
driver = Driver({
    'url': MATTERMOST_URL,
    'token': BOT_TOKEN,
    'scheme': 'https',
    'port': 443
})

def initialize_driver():
    """Logs the bot in and fetches essential IDs for operation."""
    print("Connecting to Mattermost...")
    driver.login()
    bot_info["bot_id"] = driver.users.get_user('me')['id']
    
    try:
        bot_info["team_id"] = driver.teams.get_team_by_name(TEAM_NAME)['id']
        print(f"Bot connected. Bot ID: {bot_info['bot_id']} | Team ID: {bot_info['team_id']}")
    except Exception as e:
        print(f"ERROR: Could not find team '{TEAM_NAME}'. Please check TEAM_NAME in your .env file.")
        print(f"Details: {e}")
        exit() # Exit if the team can't be found, as the bot can't function.

def resolve_targets(requested_inputs):
    """
    Resolves user inputs (channel names, IDs, or groups) into a list of valid channel IDs and names.

    - Channels from groups (visible or secret) are automatically approved and bypass the whitelist.
    - Direct inputs (channel names or IDs) are validated against the whitelist.
    - Fetches the display name for each valid channel ID.
    """
    valid_ids = set()
    invalid_inputs = set()
    
    # 1. Expand groups and separate direct inputs
    group_channel_ids = set()
    direct_inputs = set()

    for item in requested_inputs:
        clean_item = item.strip().lower().strip('#')
        if clean_item in CHANNEL_GROUPS:
            group_channel_ids.update(CHANNEL_GROUPS[clean_item])
        else:
            direct_inputs.add(clean_item)

    # Group channels are pre-approved
    valid_ids.update(group_channel_ids)

    # 2. Validate direct inputs against the whitelist
    for target in direct_inputs:
        channel_id = None
        # First, try resolving the input as a channel name
        try:
            channel = driver.channels.get_channel_by_name(bot_info["team_id"], target)
            channel_id = channel['id']
        except Exception:
            # If that fails, assume the input is already a channel ID
            channel_id = target

        # Check if the resolved/assumed ID is in the whitelist
        if channel_id in WHITELIST:
            valid_ids.add(channel_id)
        else:
            invalid_inputs.add(target)

    # 3. Fetch display names for all valid IDs
    valid_names = []
    for cid in valid_ids:
        try:
            channel_info = driver.channels.get_channel(cid)
            valid_names.append(channel_info['display_name'])
        except Exception:
            valid_names.append(cid)  # Fallback to ID if name fetch fails

    return list(valid_ids), valid_names, list(invalid_inputs)