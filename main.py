import json
import time
import asyncio
import threading

from patches import apply_ssl_patch
from config import WHITELIST, VISIBLE_CHANNEL_GROUPS, SESSION_TIMEOUT_SECONDS, CLEANUP_INTERVAL_SECONDS
from state import sessions, known_users, bot_info
from mattermost import driver, initialize_driver, resolve_targets
from database import initialize_database, log_broadcast, close_db_connection

# --- Command and State Handlers ---

def handle_id_lookup(channel_name, dm_channel_id):
    """Looks up and returns the ID of a given channel name."""
    try:
        channel = driver.channels.get_channel_by_name(bot_info["team_id"], channel_name)
        response = f"The ID for channel `{channel_name}` is: `{channel['id']}`"
    except Exception:
        response = f"⚠️ Could not find a channel named `{channel_name}`."
    
    driver.posts.create_post({'channel_id': dm_channel_id, 'message': response})

def handle_new_user(sender_id, dm_channel_id):
    """Sends a welcome message to a first-time user."""
    known_users.add(sender_id)
    driver.posts.create_post({
        'channel_id': dm_channel_id,
        'message': (
            "👋 **Welcome to the Broadcast Bot!**\n\n"
            "To send a broadcast, just send me the message you want to share. "
            "I will then ask you to specify the target channels or groups.\n\n"
            "Your message will *not* be sent until you confirm.\n\n"
            "**TYPE YOUR MESSAGE NOW:**"
        )
    })

def handle_new_session(sender_id, dm_channel_id, text):
    """Starts a new broadcast session with the user's message."""
    sessions[sender_id] = {
        "state": "AWAITING_CHANNELS",
        "message": text,
        "timestamp": time.time(),
        "dm_channel_id": dm_channel_id
    }
    group_list = ', '.join(VISIBLE_CHANNEL_GROUPS.keys())
    
    allowed_channels = []
    for channel_id in WHITELIST:
        try:
            channel_info = driver.channels.get_channel(channel_id)
            allowed_channels.append(f"- `{channel_info['display_name']}` (`{channel_id}`)")
        except Exception:
            allowed_channels.append(f"- `(ID not found)` (`{channel_id}`)")
    allowed_channels.sort()

    driver.posts.create_post({
        'channel_id': dm_channel_id,
        'message': (
            f"I've captured your message. Reply with the **channel names** or **groups** you want to send it to, separated by commas.\n\n"
            f"**Available Groups:** {group_list}\n\n"
            f"**Available Channels:**\n"
            f"{'\n'.join(allowed_channels)}"
        )
    })

def handle_channel_selection(session, text, dm_channel_id):
    """Processes the user's channel selection and asks for confirmation."""
    requested_inputs = text.split(',')
    valid_ids, valid_names, invalid_names = resolve_targets(requested_inputs)

    if not valid_ids:
        driver.posts.create_post({'channel_id': dm_channel_id, 'message': "⚠️ No valid channels found. Please try again."})
        return

    session.update({
        "target_ids": valid_ids,
        "valid_names": valid_names, # Store names for logging
        "state": "CONFIRMATION",
        "timestamp": time.time()
    })

    warning_text = f"\n⚠️ *Ignored invalid inputs: {', '.join(invalid_names)}*" if invalid_names else ""
    preview_text = (
        f"**Preview:**\n> {session['message']}\n\n"
        f"**Targets:** {', '.join(valid_names)}{warning_text}\n\n"
        "Reply with **yes** to send or **no** to cancel."
    )
    driver.posts.create_post({'channel_id': dm_channel_id, 'message': preview_text})

def handle_confirmation(user_id, session, text, sender_name, dm_channel_id):
    """Handles the final 'yes' or 'no' confirmation and ends the session."""
    if text.lower() == 'yes':
        for channel_id in session['target_ids']:
            try:
                driver.posts.create_post({
                    'channel_id': channel_id,
                    'message': f"📢 **Broadcast from @{sender_name}**\n\n> {session['message']}"
                })
            except Exception as e:
                print(f"Failed to post to {channel_id}: {e}")
        
        log_broadcast(
            sender_name=sender_name,
            message_content=session['message'],
            target_channels=session['valid_names']
        )
        
        driver.posts.create_post({'channel_id': dm_channel_id, 'message': "✅ **Broadcast sent successfully.**"})
    
    elif text.lower() == 'no':
        driver.posts.create_post({'channel_id': dm_channel_id, 'message': "❌ **Broadcast canceled.**"})
    
    else:
        driver.posts.create_post({'channel_id': dm_channel_id, 'message': "Invalid response. Please reply with **yes** or **no**."})
        return

    del sessions[user_id]

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
    sender_name = data.get('sender_name', '').strip('@')

    if not all([sender_id, dm_channel_id, text, sender_name]) or sender_id == bot_info.get("bot_id"):
        return

    # Handle !id! command
    if text.lower().startswith('!id!'):
        channel_name = text[5:].strip()
        if channel_name:
            handle_id_lookup(channel_name, dm_channel_id)
        else:
            driver.posts.create_post({'channel_id': dm_channel_id, 'message': "Please provide a channel name after `!id!`."})
        return

    if sender_id not in known_users:
        handle_new_user(sender_id, dm_channel_id)
        return

    session = sessions.get(sender_id)
    
    if not session:
        handle_new_session(sender_id, dm_channel_id, text)
    elif session.get("state") == "AWAITING_CHANNELS":
        handle_channel_selection(session, text, dm_channel_id)
    elif session.get("state") == "CONFIRMATION":
        handle_confirmation(sender_id, session, text, sender_name, dm_channel_id)

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