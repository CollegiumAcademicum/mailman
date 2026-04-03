if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(".env")
import asyncio
import json
import logging

import threading
import time

from scripts import handlers as h
import scripts.config as config
from scripts.database import close_db_connection, initialize_database
from scripts.mattermost import driver, initialize_driver
from scripts.patches import apply_ssl_patch
from scripts.state import bot_info, known_users, sessions

#TODO add standard broadcast channel every broadcast the bot emits gets send to, too

# --- Main WebSocket Event Handler ---


async def message_handler(message):
    """The main entry point for processing incoming WebSocket messages."""
    logging.debug("Received message from WebSocket.")
    try:
        msg_data = json.loads(message)
    except json.JSONDecodeError:
        logging.error(f"Could not decode message: {message}")
        return

    if msg_data.get("event") != "posted":
        logging.debug(f"Ignoring non-post event: {msg_data.get('event')}")
        return

    data = msg_data.get("data", {})
    if data.get("channel_type") != "D":
        logging.debug("Ignoring message not in a direct message channel.")
        return

    post = json.loads(data.get("post", "{}"))
    sender_id = post.get("user_id")
    dm_channel_id = post.get("channel_id")
    text = post.get("message", "").strip()
    file_ids = post.get("file_ids", [])
    sender_name = data.get("sender_name", "").strip("@")

    if not all([sender_id, dm_channel_id, sender_name]) or sender_id == bot_info.get(
        "bot_id"
    ):
        logging.debug("Ignoring message from bot or with missing data.")
        return

    if not text and not file_ids:  # Ignore messages with no content
        logging.debug("Ignoring message with no content.")
        return

    logging.info(f"Processing message from {sender_name} (ID: {sender_id}).")

    if text.lower().startswith(("help", "!help", "--help", "man")):
        logging.info(f"User {sender_name} requested help.")
        driver.posts.create_post(
            {"channel_id": dm_channel_id, "message": config.HELP_MESSAGE}
        )
    elif text.lower().startswith("!id"):
        channel_name = text.strip().lstrip("!id").strip()
        if channel_name:
            logging.info(f"User {sender_name} requested ID for channel '{channel_name}'.")
            h.handle_id_lookup(channel_name, dm_channel_id)
        else:
            logging.warning(f"User {sender_name} used !id without a channel name.")
            driver.posts.create_post(
                {
                    "channel_id": dm_channel_id,
                    "message": "Please provide a channel name after `!id!`.",
                },
            )
        return
    elif text.lower().startswith("!channels"):
        logging.info(f"User {sender_name} requested channel list.")
        h.handle_channels_command(dm_channel_id)
    elif text.lower().startswith("!get_private_groups"):
        logging.info(f"User {sender_name} requested private groups.")
        lines = []
        for name, channel_list in config.PRIVATE_CHANNEL_GROUPS.items():
            lines.append(
                f"{name}: {[driver.channels.get_channel(i)['name'] for i in channel_list]}\n \n"
            )
        message = "\n".join(lines)
        driver.posts.create_post({"channel_id": dm_channel_id, "message": message})
    elif text.lower().startswith("!get_groups"):
        logging.info(f"User {sender_name} requested visible groups.")
        lines = []
        for name, channel_list in config.VISIBLE_CHANNEL_GROUPS.items():
            try:
                lines.append(
                    f"{name}: {[driver.channels.get_channel(i)['name'] for i in channel_list]}\n \n"
                )
            except Exception as e:
                logging.error(f"Error fetching channel name for group {name}: {e}")
                lines.append(f"{name}: [ID not found]\n \n")
        message = f"{'\n'.join(lines)}"
        driver.posts.create_post({"channel_id": dm_channel_id, "message": message})
    elif text.lower().startswith("!add_group"):
        logging.info(f"User {sender_name} is adding a group.")
        h.handle_add_group(text, dm_channel_id)
    elif text.lower().startswith("!add_private_group"):
        logging.info(f"User {sender_name} is adding a private group.")
        h.handle_add_group(text, dm_channel_id, private=True)
    else:
        if sender_id not in known_users:
            logging.info(f"New user detected: {sender_name} (ID: {sender_id}).")
            h.handle_new_user(sender_id, dm_channel_id)
            return
        session = sessions.get(sender_id)
        if not session:
            logging.info(f"Creating new session for user {sender_name}.")
            h.handle_new_session(sender_id, dm_channel_id, text, file_ids)
        elif session.get("state") == "AWAITING_CHANNELS":
            logging.info(f"Handling channel selection for user {sender_name}.")
            h.handle_channel_selection(session, text, dm_channel_id)
        elif session.get("state") == "CONFIRMATION":
            logging.info(f"Handling confirmation for user {sender_name}.")
            h.handle_confirmation(
                sender_id, session, text, sender_name, dm_channel_id
            )
        else:
            logging.warning(
                f"User {sender_name} in unknown session state: {session.get('state')}"
            )
            pass


# --- Background Tasks ---


async def session_cleanup_task():
    """Periodically cleans up expired user sessions."""
    while True:
        await asyncio.sleep(config.CLEANUP_INTERVAL_SECONDS)
        logging.debug("Running session cleanup task.")
        current_time = time.time()
        expired_users = [
            uid
            for uid, sess in sessions.items()
            if current_time - sess["timestamp"] > config.SESSION_TIMEOUT_SECONDS
        ]

        if expired_users:
            logging.info(f"Found {len(expired_users)} expired sessions to clean up.")
        for user_id in expired_users:
            expired_session = sessions.pop(user_id, None)
            if expired_session:
                logging.info(f"Session for user {user_id} expired and was removed.")
                try:
                    driver.posts.create_post(
                        {
                            "channel_id": expired_session["dm_channel_id"],
                            "message": "⏱️ **Session expired.** You took too long to confirm. Send a new message to start over.",
                        },
                    )
                except Exception as e:
                    logging.error(f"Failed to send timeout notice for user {user_id}: {e}")


def run_websocket_listener():
    """Sets up and runs the WebSocket listener in its own event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    logging.info("Starting session cleanup task.")
    loop.create_task(session_cleanup_task())

    logging.info("Initializing WebSocket listener.")
    driver.init_websocket(message_handler)


# --- Main Execution ---
def main():
    logging.info("Starting bot.")
    apply_ssl_patch()
    initialize_driver()
    initialize_database()

    logging.info("Starting WebSocket listener thread.")
    ws_thread = threading.Thread(target=run_websocket_listener, daemon=True)
    ws_thread.start()

    try:
        ws_thread.join()
    finally:
        close_db_connection()
        logging.info("Bot shutting down.")


if __name__ == "__main__":
    main()
