import json
import logging
import time

from scripts.config import (
    BOT_LOG_CHANNEL_ID,
    CHANNELS_JSON_PATH,
    PRIVATE_CHANNEL_GROUPS,
    VISIBLE_CHANNEL_GROUPS,
    WHITELIST,
)
from scripts.database import log_broadcast
from scripts.mattermost import driver, resolve_targets
from scripts.state import bot_info, known_users, sessions


def handle_id_lookup(channel_name, dm_channel_id):
    """Looks up and returns the ID of a given channel name."""
    logging.info(f"Handling ID lookup for channel: {channel_name}")
    try:
        channel = driver.channels.get_channel_by_name(bot_info["team_id"], channel_name)
        response = f"The ID for channel `{channel_name}` is: `{channel['id']}`"
        logging.info(f"Found channel ID {channel['id']} for name {channel_name}")
    except Exception as e:
        response = f"⚠️ Could not find a channel named `{channel_name}`."
        logging.error(f"Could not find channel {channel_name}: {e}")

    driver.posts.create_post({"channel_id": dm_channel_id, "message": response})


def handle_channels_command(dm_channel_id):
    logging.info("Handling !channels command.")
    lines = ["| display_name | name  | ID | team_name |",
             "| :------------ |:---------------| :-----| :-----|"]
    try:
        mm_teams = driver.teams.get_user_teams("me")
        logging.debug(f"Retrieved {len(mm_teams)} teams for bot")
        # 2. Iterate through teams and fetch the associated channels
        for team in mm_teams:
            channels = driver.channels.get_channels_for_user("me", team["id"])
            logging.debug(f"Retrieved {len(channels)} channels for team {team['display_name']}")
            for channel in channels:
                # display_name is the UI name, name is the system URL name
                if channel["team_id"]:
                    team_name = driver.teams.get_team(channel["team_id"]).get(
                        "display_name", "N/A"
                    )

                    lines.append(
                        f"| `{channel['display_name']}` | {channel['name']} | `{channel['id']}` | {team_name} | "
                    )
    except Exception as e:
        logging.error(f"Error fetching channels: {e}")
        lines.append("Error fetching channels.")

    message = "\n".join(lines)
    driver.posts.create_post({"channel_id": dm_channel_id, "message": message})


def handle_new_user(sender_id, dm_channel_id):
    """Sends a welcome message to a first-time user."""
    logging.info(f"Handling new user: {sender_id}")
    known_users.add(sender_id)
    driver.posts.create_post(
        {
            "channel_id": dm_channel_id,
            "message": (
                "👋 **Welcome, I'm the Postbot**\n\n"
                "To send a broadcast, just send me the message you want to share (you can attach files too!). "
                "I will then ask you to specify the target channels or groups.\n\n"
                "Your message will *not* be sent until you confirm.\n\n"
                "**TYPE YOUR MESSAGE AND/OR ATTACH FILES NOW:**"
            ),
        }
    )


def handle_new_session(sender_id, dm_channel_id, text, file_ids):
    """Starts a new broadcast session with the user's message and files."""
    logging.info(f"Handling new session for user: {sender_id}")
    sessions[sender_id] = {
        "state": "AWAITING_CHANNELS",
        "message": text,
        "file_ids": file_ids,
        "timestamp": time.time(),
        "dm_channel_id": dm_channel_id,
    }

    allowed_channels = []
    for channel_id in WHITELIST:
        try:
            channel_info = driver.channels.get_channel(channel_id)
            if channel_info["team_id"]:
                team_name = driver.teams.get_team(channel_info["team_id"]).get(
                    "display_name", "N/A"
                )
                logging.debug(
                    f"team_name: {team_name}, display_name: {channel_info['display_name']}, name: {channel_info['name']}"
                )
                allowed_channels.append(
                    f"- name: `{channel_info['name']}`    (display_name `{channel_info['display_name']}`- ID `{channel_id}` - Team name: `{team_name}`)"
                )
        except Exception as e:
            logging.error(f"Error fetching info for channel {channel_id}: {e}")
            allowed_channels.append(f"- `(ID not found)` (`{channel_id}`)")
    allowed_channels.sort()

    file_notice = (
        "\n_You have attached {} file(s)._".format(len(file_ids)) if file_ids else ""
    )

    group_str: str = ""
    for group in VISIBLE_CHANNEL_GROUPS.keys():
        group_str += f"- `{group}`\n"

    driver.posts.create_post(
        {
            "channel_id": dm_channel_id,
            "message": (
                f"I've captured your message.{file_notice}\n  \n"
                f"Reply with the **channel names** or **groups** you want to send it to, separated by commas.\n\n"
                f"### **Available Groups:** \n"
                f"{group_str}"
                f"**Available Channels:**\n"
                f"{'\n'.join(allowed_channels)}"
            ),
        }
    )


def handle_channel_selection(session, text, dm_channel_id):
    """Processes the user's channel selection and asks for confirmation."""
    logging.info(f"Handling channel selection: {text}")
    requested_inputs = text.split(",")
    valid_ids, valid_names, invalid_names = resolve_targets(requested_inputs)

    if not valid_ids:
        logging.warning(f"No valid channels found for input: {text}")
        driver.posts.create_post(
            {
                "channel_id": dm_channel_id,
                "message": "⚠️ No valid channels found. Please try again.",
            }
        )
        return

    session.update(
        {
            "target_ids": valid_ids,
            "valid_names": valid_names,
            "state": "CONFIRMATION",
            "timestamp": time.time(),
        }
    )
    logging.info(f"Channels selected for broadcast: {valid_names}")

    file_notice = (
        "\n**Files Attached:** {}".format(len(session.get("file_ids", [])))
        if session.get("file_ids")
        else ""
    )
    warning_text = (
        f"\n⚠️ *Ignored invalid inputs: {', '.join(invalid_names)}*"
        if invalid_names
        else ""
    )
    preview_text = (
        f"**Preview:**\n{session['message']}\n \n"
        f"**Targets:** \n{'\n'.join(valid_names)}{file_notice}{warning_text}\n \n"
        "Reply with **yes** to send or **no** to cancel."
    )
    driver.posts.create_post({"channel_id": dm_channel_id, "message": preview_text})


def handle_confirmation(user_id, session, text, sender_name, dm_channel_id):
    """Handles the final 'yes' or 'no' confirmation and ends the session."""
    logging.info(f"Handling confirmation from {sender_name}: {text}")
    if text.lower() == "yes":
        logging.info(f"User {sender_name} confirmed broadcast.")
        message = (
            f"📢 **Message from @{sender_name}**\n \n \n{session['message']}"
            f"\n \n \n \n*--- END of Message ---*\n"
            f"*To use my services (@{bot_info['bot_username']}) just DM me*"
        )
        original_file_ids = session.get("file_ids", [])
        logging.info(f"Original file IDs: {original_file_ids}")
        files = {}
        for original_id in original_file_ids:
            try:
                response = driver.files.get_file(original_id)
                metadata = driver.files.get_file_metadata(original_id)
                filename = metadata.get("name", "relayed_file.dat")
                # Extract bytes safely
                if isinstance(response, dict):
                    # It was a JSON file; convert the parsed dict back to raw bytes
                    files[filename] = json.dumps(response).encode("utf-8")
                else:
                    # It was a standard file; access the .content attribute of the Response object
                    files[filename] = response.content
            except Exception as e:
                logging.error(f"Failed to fetch file {original_id}: {e}")
        logging.info(f"Files to upload: {list(files.keys())}")
        all_file_ids = []
        for channel_id in session["target_ids"]:
            file_ids = []
            # upload file to channel:
            for filename, content in files.items():
                try:
                    file_info = driver.files.upload_file(
                        channel_id=channel_id, files={"files": (filename, content)}
                    )
                    logging.info(f"File uploaded successfully: {file_info}")
                    file_ids.append(file_info["file_infos"][0]["id"])
                except Exception as e:
                    logging.error(f"Failed to upload file to {channel_id}: {e}")
            all_file_ids.extend(file_ids)
            try:
                post_options: dict[str, str | list[str]] = {
                    "channel_id": channel_id,
                    "message": message,
                    "file_ids": file_ids,
                }

                driver.posts.create_post(post_options)
                logging.info(f"Posted message to channel {channel_id}")
            except Exception as e:
                logging.error(f"Failed to post to {channel_id}: {e}")

        # Log the broadcast to DB
        log_broadcast(
            sender_name=sender_name,
            message_content=session["message"],
            target_channels=session["valid_names"],
            file_ids=all_file_ids,
        )

        # Send User confirmation Message
        driver.posts.create_post(
            {
                "channel_id": dm_channel_id,
                "message": "✅ **Broadcast sent successfully.**\n\n"
                "Thank you for using the Broadcast Bot!\n\n\n"
                "**If You want to send another Broadcast, SEND THE MESSAGE AND/OR ATTACH FILES NOW:**\n"
                "If not, just do nothing :feuervoigl:",
            }
        )

        # Send metadata-only audit post to the configured bot log channel (if set)
        if BOT_LOG_CHANNEL_ID:
            driver.posts.create_post(
                {
                    "channel_id": BOT_LOG_CHANNEL_ID,
                    "message": (
                        f"Sender *{sender_name}* sent a broadcast. "
                        f"Timestamp (UTC): {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}. "
                        f"Target channel count: {len(session.get('valid_names', []))}. "
                        f"Attached file count: {len(all_file_ids)}."
                    ),
                }
            )

    elif text.lower() == "no":
        logging.info(f"User {sender_name} canceled broadcast.")
        driver.posts.create_post(
            {"channel_id": dm_channel_id, "message": "❌ **Broadcast canceled.**"}
        )

    else:
        logging.warning(f"Invalid confirmation from {sender_name}: {text}")
        driver.posts.create_post(
            {
                "channel_id": dm_channel_id,
                "message": "Invalid response. Please reply with **yes** or **no**.",
            }
        )
        return

    del sessions[user_id]
    logging.info(f"Session for user {user_id} deleted.")


def handle_add_group(text, dm_channel_id, private=False):
    group_type = "private" if private else "visible"
    logging.info(f"Handling add {group_type} group.")
    if private:
        targeted_groups = PRIVATE_CHANNEL_GROUPS
        incoming_message = text.strip().lstrip("!_add_private_group").strip()
        group = "private_groups"
    else:
        targeted_groups = VISIBLE_CHANNEL_GROUPS
        incoming_message = text.strip().lstrip("!_add_group").strip()
        group = "groups"

    # 1. Check if the user actually provided payload data
    if not incoming_message:
        logging.warning("!add_group command used without payload.")
        driver.posts.create_post(
            {
                "channel_id": dm_channel_id,
                "message": '❌ Please provide a JSON string. Example: `!_add_group! {"NewGroup": ["id1", "id2"]}`',
            }
        )
        return
    try:
        # 2. Attempt to parse the JSON
        new_groups_dict = json.loads(incoming_message)
        logging.debug(f"Parsed new groups: {new_groups_dict}")
        # 3. Validate that the parsed JSON is actually a dictionary
        if not isinstance(new_groups_dict, dict):
            raise ValueError("Input must be a JSON object (dictionary).")
        for key, channel_list in new_groups_dict.copy().items():
            logging.info(f"Validating channels for group {key}: {channel_list}")
            for channel_id in channel_list.copy():
                try:
                    driver.channels.get_channel(channel_id)
                except Exception:
                    channel_list.remove(channel_id)
                    logging.warning(
                        f"Removed invalid channel ID {channel_id} from group {key}"
                    )
            if len(channel_list) == 0:
                new_groups_dict.pop(key)
                logging.warning(f"Removed empty group {key}")

        logging.debug(f"Cleaned new groups: {new_groups_dict}")

        if len(new_groups_dict) != 0:
            # 4. Integrate the new group into your global state
            targeted_groups.update(new_groups_dict)
            logging.info("Updated groups in memory.")

            with open(CHANNELS_JSON_PATH, "r") as f:
                data = json.load(f)
            logging.debug("Loaded channels.json")

            data[group] = targeted_groups
            with open(CHANNELS_JSON_PATH, "w") as f:
                json.dump(data, f, indent=4)

            logging.info("Written updated groups to channels.json")
            driver.posts.create_post(
                {"channel_id": dm_channel_id, "message": "✅ Group added successfully!"}
            )
        else:
            logging.warning("No valid groups to add after cleaning.")
            driver.posts.create_post(
                {
                    "channel_id": dm_channel_id,
                    "message": "❌ Group could not be added. Check your JSON syntax and the channel IDs!",
                }
            )
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in !add_group command: {e}")
        driver.posts.create_post(
            {
                "channel_id": dm_channel_id,
                "message": "❌ Invalid JSON format. Please check your syntax.",
            }
        )
    except ValueError as e:
        logging.error(f"ValueError in !add_group command: {e}")
        driver.posts.create_post({"channel_id": dm_channel_id, "message": f"❌ {e}"})
    except Exception as e:
        # Catch-all for unexpected parsing or assignment issues
        logging.error(f"Unexpected error in !add_group: {e}")
        driver.posts.create_post(
            {
                "channel_id": dm_channel_id,
                "message": f"❌ An unexpected error occurred: {e}",
            }
        )
