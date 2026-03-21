import json
from mattermost import get_driver, initialize_driver
from state import bot_info

def convert_channel_names_to_ids():
    """
    Reads channels.json, converts channel names to IDs, and overwrites the file.
    """
    initialize_driver()
    driver = get_driver()
    team_id = bot_info.get("team_id")

    if not team_id:
        print("Could not get team ID. Aborting.")
        return

    with open('channels.json', 'r') as f:
        data = json.load(f)

    new_data = {
        "groups": {},
        "whitelist": []
    }

    # Convert whitelist
    for channel_name in data.get("whitelist", []):
        try:
            channel = driver.channels.get_channel_by_name(team_id, channel_name)
            new_data["whitelist"].append(channel['id'])
        except Exception as e:
            print(f"Could not find channel '{channel_name}'. Skipping. Error: {e}")

    # Convert groups
    for group_name, channel_names in data.get("groups", {}).items():
        new_data["groups"][group_name] = []
        for channel_name in channel_names:
            try:
                channel = driver.channels.get_channel_by_name(team_id, channel_name)
                new_data["groups"][group_name].append(channel['id'])
            except Exception as e:
                print(f"Could not find channel '{channel_name}' in group '{group_name}'. Skipping. Error: {e}")

    with open('channels.json', 'w') as f:
        json.dump(new_data, f, indent=2)

    print("channels.json has been updated with channel IDs.")

if __name__ == "__main__":
    convert_channel_names_to_ids()