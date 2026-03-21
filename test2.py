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

channel_names = set()
channel_names.add("A")
channel_names.add("B")

# 1. Define the event handler
async def my_event_handler(message):
    try:
        data = json.loads(message)
        if data.get('event') == 'posted':
            post = json.loads(data['data']['post'])
            sender = data['data'].get('sender_name', 'Unknown')
            print(f"data: {data['data']}")
            text = post.get('message', '')
            if text.startswith('!channel'):
                for channel_name in channel_names:
                    channel_id = driver.channels.get_channel_by_name("j88fqucc8iyfmkc93r849kibwc", channel_name)
                    print(f"channel_id: {channel_id}")
                    stats = driver.channels.get_channel_statistics(channel_id["id"])
                    print(f"stats: {stats}")
                    driver.posts.create_post({
                        'channel_id': channel_id["id"],
                        'message': text[8:]
                    })
            elif text.startswith('!dm'):
                dm_channel_id = post.get('channel_id')
                driver.posts.create_post({
                    'channel_id': dm_channel_id,
                    'message': text[3:]
                })
            print(f"[{sender}]: {text}")

    except json.JSONDecodeError:
        pass


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
    print(f"Success! Connected to Mattermost as: {me['username']}")

    print("Listening for new messages via WebSocket...")
    driver.init_websocket(my_event_handler)