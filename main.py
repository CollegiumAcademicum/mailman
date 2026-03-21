import json
import time
import asyncio
import threading

from patches import apply_ssl_patch
from config import WHITELIST, VISIBLE_CHANNEL_GROUPS, SESSION_TIMEOUT_SECONDS, CLEANUP_INTERVAL_SECONDS
from state import sessions, known_users, bot_info
from mattermost import driver, initialize_driver, resolve_targets
from database import initialize_database, log_broadcast, close_db_connection
import handlers as h

# --- Main WebSocket Event Handler ---

async def message_handler(message):
    """The main entry point for processing incoming WebSocket messages."""
    try:
        msg_data = json.loads(message)
    except json.JSONDecodeError:
        print(f"Could not decode message: {message}")
        return

    if msg_data.get('event') != 'posted':
        return
    
    data = msg_data.get('data', {})
    if data.get('channel_type') != 'D':
        return

    post = json.loads(data.get('post', '{}'))
    sender_id = post.get('user_id')
    dm_channel_id = post.get('channel_id')
    text = post.get('message', '').strip()
    file_ids = post.get('file_ids', [])
    sender_name = data.get('sender_name', '').strip('@')

    if not all([sender_id, dm_channel_id, sender_name]) or sender_id == bot_info.get("bot_id"):
        return
    
    if not text and not file_ids: # Ignore messages with no content
        return

    if text.lower().startswith('!id!'):
        channel_name = text[5:].strip()
        if channel_name:
            h.handle_id_lookup(channel_name, dm_channel_id)
        else:
            driver.posts.create_post({'channel_id': dm_channel_id, 'message': "Please provide a channel name after `!id!`."})
        return
    elif text.lower().startswith("!channels!"):
        lines = []
        teams = driver.teams.get_user_teams('me')
        # 2. Iterate through teams and fetch the associated channels
        for team in teams:
            channels = driver.channels.get_channels_for_user('me', team['id'])
            for channel in channels:
                # display_name is the UI name, name is the system URL name
                lines.append(f"ID: {channel['id']} | Name: {channel['display_name']} ({channel['name']})")

                print(f"ID: {channel['id']} | Name: {channel['display_name']} ({channel['name']})")
        message = "\n".join(lines)
        driver.posts.create_post({'channel_id': dm_channel_id, 'message': message})
    else:
        if sender_id not in known_users:
            h.handle_new_user(sender_id, dm_channel_id)
            return

        session = sessions.get(sender_id)

        if not session:
            h.handle_new_session(sender_id, dm_channel_id, text, file_ids)
        elif session.get("state") == "AWAITING_CHANNELS":
            h.handle_channel_selection(session, text, dm_channel_id)
        elif session.get("state") == "CONFIRMATION":
            h.handle_confirmation(sender_id, session, text, sender_name, dm_channel_id)

# --- Background Tasks ---

async def session_cleanup_task():
    """Periodically cleans up expired user sessions."""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        current_time = time.time()
        expired_users = [uid for uid, sess in sessions.items() if
                         current_time - sess['timestamp'] > SESSION_TIMEOUT_SECONDS]

        for user_id in expired_users:
            expired_session = sessions.pop(user_id, None)
            if expired_session:
                try:
                    driver.posts.create_post({
                        'channel_id': expired_session['dm_channel_id'],
                        'message': "⏱️ **Session expired.** You took too long to confirm. Send a new message to start over."
                    })
                except Exception as e:
                    print(f"Failed to send timeout notice for user {user_id}: {e}")

def run_websocket_listener():
    """Sets up and runs the WebSocket listener in its own event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    loop.create_task(session_cleanup_task())
    
    driver.init_websocket(message_handler)

# --- Main Execution ---

if __name__ == "__main__":
    apply_ssl_patch()
    initialize_driver()
    initialize_database()
    
    ws_thread = threading.Thread(target=run_websocket_listener, daemon=True)
    ws_thread.start()
    
    try:
        ws_thread.join()
    finally:
        close_db_connection()
        print("Bot shutting down.")