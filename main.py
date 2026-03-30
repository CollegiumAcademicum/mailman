import asyncio
import json
import threading
import time

import handlers as h
import config
from database import close_db_connection, initialize_database
from mattermost import driver, initialize_driver
from patches import apply_ssl_patch
from state import bot_info, known_users, sessions


# --- Main WebSocket Event Handler ---


async def message_handler(message):
    """The main entry point for processing incoming WebSocket messages."""
    try:
        msg_data = json.loads(message)
    except json.JSONDecodeError:
        print(f"Could not decode message: {message}")
        return

    if msg_data.get("event") != "posted":
        return

    data = msg_data.get("data", {})
    if data.get("channel_type") != "D":
        return

    post = json.loads(data.get("post", "{}"))
    sender_id = post.get("user_id")
    dm_channel_id = post.get("channel_id")
    text = post.get("message", "").strip()
    file_ids = post.get("file_ids", [])
    sender_name = data.get("sender_name", "").strip("@")

    if not all([sender_id, dm_channel_id, sender_name]) or sender_id == bot_info.get("bot_id"):
        return

    if not text and not file_ids:  # Ignore messages with no content
        return

    if text.lower().startswith(("help", "!help", "--help", "man")):
        driver.posts.create_post({"channel_id": dm_channel_id, "message": config.help_message})
    elif text.lower().startswith("!id"):
        channel_name = text.strip().lstrip("!id").strip()
        if channel_name:
            h.handle_id_lookup(channel_name, dm_channel_id)
        else:
            driver.posts.create_post(
                {
                    "channel_id": dm_channel_id,
                    "message": "Please provide a channel name after `!id!`.",
                },
            )
        return
    elif text.lower().startswith("!channels"):
        h.handle_channels_command(dm_channel_id)
    elif text.lower().startswith("!get_private_groups"):
        lines = []
        for name, channel_list in config.PRIVATE_CHANNEL_GROUPS.items():
            lines.append(
                f"{name}: {[driver.channels.get_channel(i)['name'] for i in channel_list]}\n \n"
            )
        message = "\n".join(lines)
        driver.posts.create_post({"channel_id": dm_channel_id, "message": message})
    elif text.lower().startswith("!get_groups"):
        lines = []
        for name, channel_list in config.VISIBLE_CHANNEL_GROUPS.items():
            try:
                lines.append(
                    f"{name}: {[driver.channels.get_channel(i)['name'] for i in channel_list]}\n \n"
                )
            except Exception:
                lines.append(f"{name}: [ID not found]\n \n")
        message = f"{'\n'.join(lines)}"
        driver.posts.create_post({"channel_id": dm_channel_id, "message": message})
    elif text.lower().startswith("!add_group"):
        h.handle_add_group(text, dm_channel_id)
    elif text.lower().startswith("!add_private_group"):
        h.handle_add_group(text, dm_channel_id, private=True)
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
        else:
            pass


# --- Background Tasks ---


async def session_cleanup_task():
    """Periodically cleans up expired user sessions."""
    while True:
        await asyncio.sleep(config.CLEANUP_INTERVAL_SECONDS)
        current_time = time.time()
        expired_users = [
            uid
            for uid, sess in sessions.items()
            if current_time - sess["timestamp"] > config.SESSION_TIMEOUT_SECONDS
        ]

        for user_id in expired_users:
            expired_session = sessions.pop(user_id, None)
            if expired_session:
                try:
                    driver.posts.create_post(
                        {
                            "channel_id": expired_session["dm_channel_id"],
                            "message": "⏱️ **Session expired.** You took too long to confirm. Send a new message to start over.",
                        },
                    )
                except Exception as e:
                    print(f"Failed to send timeout notice for user {user_id}: {e}")


def run_websocket_listener():
    """Sets up and runs the WebSocket listener in its own event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.create_task(session_cleanup_task())

    driver.init_websocket(message_handler)


# --- Main Execution ---
def main():
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


if __name__ == "__main__":
    main()
