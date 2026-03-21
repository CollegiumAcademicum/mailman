import ssl
import json

# --- START PATCH FOR MATTERMOSTDRIVER BUG ---
# Intercepts the faulty SSL call and forces SERVER_AUTH for Python 3.10+
orig_create_default_context = ssl.create_default_context


def patched_create_default_context(*args, **kwargs):
    kwargs["purpose"] = ssl.Purpose.SERVER_AUTH
    return orig_create_default_context(*args, **kwargs)


ssl.create_default_context = patched_create_default_context
# --- END PATCH ---

from mattermostdriver import Driver


# 2. Configure the driver
driver = Driver({
    'url': 'chat.collegiumacademicum.de',
    'token': 'x9xfy88aqty19kdww3m53xspno',
    'scheme': 'https',
    'port': 443
})

# 3. Authenticate and initialize the listener
if __name__ == "__main__":
    driver.login()
    me = driver.users.get_user('me')
    print(f"Success! Connected to Mattermost as: {me}")
    print(driver.teams.get_team_by_name("Testing"))
    channel_id = driver.channels.get_channel_by_name("j88fqucc8iyfmkc93r849kibwc", "A")
    print(f"channel_id: {channel_id}")
    stats = driver.channels.get_channel_statistics(channel_id["id"])
    print(f"stats: {stats}")
    driver.posts.create_post({
        'channel_id': channel_id["id"],
        'message': 'Hello from the bot!'
    })
    channels = driver.channels.get_channels_for_user('me', "j88fqucc8iyfmkc93r849kibwc")
    print("me:" , driver.channels.get_channels_for_user('me', "j88fqucc8iyfmkc93r849kibwc"))
    for i in channels:
        print(driver.channels.get_channel(i["id"])["display_name"], "  :  ", i["id"])

