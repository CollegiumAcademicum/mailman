from mattermost import driver, initialize_driver, resolve_targets
from state import sessions, known_users, bot_info
from config import WHITELIST, VISIBLE_CHANNEL_GROUPS, SESSION_TIMEOUT_SECONDS, CLEANUP_INTERVAL_SECONDS
from database import initialize_database, log_broadcast, close_db_connection


import time
import json




def handle_id_lookup(channel_name, dm_channel_id):
    """Looks up and returns the ID of a given channel name."""
    try:
        channel = driver.channels.get_channel_by_name(bot_info["team_id"], channel_name)
        response = f"The ID for channel `{channel_name}` is: `{channel['id']}`"
    except Exception:
        response = f"⚠️ Could not find a channel named `{channel_name}`."

    driver.posts.create_post({"channel_id": dm_channel_id, "message": response})

def handle_new_user(sender_id, dm_channel_id):
    """Sends a welcome message to a first-time user."""
    known_users.add(sender_id)
    driver.posts.create_post({
        "channel_id": dm_channel_id,
        "message": (
            "👋 **Welcome, I'm the Mailman**\n\n"
            "To send a broadcast, just send me the message you want to share (you can attach files too!). "
            "I will then ask you to specify the target channels or groups.\n\n"
            "Your message will *not* be sent until you confirm.\n\n"
            "**TYPE YOUR MESSAGE AND/OR ATTACH FILES NOW:**"
        )
    })

def handle_new_session(sender_id, dm_channel_id, text, file_ids):
    """Starts a new broadcast session with the user's message and files."""
    sessions[sender_id] = {
        "state": "AWAITING_CHANNELS",
        "message": text,
        "file_ids": file_ids,
        "timestamp": time.time(),
        "dm_channel_id": dm_channel_id
    }
    group_list = ", ".join(VISIBLE_CHANNEL_GROUPS.keys())

    allowed_channels = []
    allowed_channels_patch = {} #TODO match channel IDs to names
    for channel_id in WHITELIST:
        try:
            channel_info = driver.channels.get_channel(channel_id)
            allowed_channels.append(f"- `{channel_info['name']}`    (`{channel_info['display_name']}`- `{channel_id}`)")
        except Exception:
            allowed_channels.append(f"- `(ID not found)` (`{channel_id}`)")
    allowed_channels.sort()

    file_notice = "\n_You have attached {} file(s)._".format(len(file_ids)) if file_ids else ""
    driver.posts.create_post({
        "channel_id": dm_channel_id,
        "message": (
            f"I've captured your message.{file_notice}\n\n"
            f"Reply with the **channel names** or **groups** you want to send it to, separated by commas.\n\n"
            f"**Available Groups:** {group_list}\n\n"
            f"**Available Channels:**\n"
            f"{'\n'.join(allowed_channels)}"
        )
    })

def handle_channel_selection(session, text, dm_channel_id):
    """Processes the user's channel selection and asks for confirmation."""
    requested_inputs = text.split(",")
    valid_ids, valid_names, invalid_names = resolve_targets(requested_inputs)

    if not valid_ids:
        driver.posts.create_post \
            ({"channel_id": dm_channel_id, "message": "⚠️ No valid channels found. Please try again."})
        return

    session.update({
        "target_ids": valid_ids,
        "valid_names": valid_names,
        "state": "CONFIRMATION",
        "timestamp": time.time()
    })

    file_notice = "\n**Files Attached:** {}".format(len(session.get("file_ids", []))) if session.get("file_ids") else ""
    warning_text = f"\n⚠️ *Ignored invalid inputs: {', '.join(invalid_names)}*" if invalid_names else ""
    preview_text = (
        f"**Preview:**\n{session['message']}\n \n"
        f"**Targets:** {', '.join(valid_names)}{file_notice}{warning_text}\n \n"
        "Reply with **yes** to send or **no** to cancel."
    )
    driver.posts.create_post({"channel_id": dm_channel_id, "message": preview_text})

def handle_confirmation(user_id, session, text, sender_name, dm_channel_id):
    """Handles the final 'yes' or 'no' confirmation and ends the session."""
    if text.lower() == "yes":
        message = f"📢 **Message from @{sender_name}**\n \n \n{session['message']}\n \n \n \n*--- END of Message ---*\n*If YOU want to use the services of me (@{bot_info['bot_username']}) just DM me*"
        original_file_ids = session.get("file_ids", [])
        print(f"original_file_ids: {original_file_ids}")
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
                print(f"Failed to fetch file {original_id}: {e}")
        print(f"files.keys(): {files.keys()}")
        for channel_id in session["target_ids"]:
            file_ids = []
            # upload file to channel:
            for id, content in files.items():
                try:
                    file_info = driver.files.upload_file(
                        channel_id=channel_id,
                        files={"files": (id, content)}
                    )
                    print(f"File uploaded successfully: {file_info}")
                    print(file_ids.append(file_info["file_infos"][0]["id"]))
                except Exception as e:
                    print(f"Failed to upload file to {channel_id}: {e}")
            try:
                post_options = {"channel_id": channel_id}
                post_options["message"] = message
                post_options["file_ids"] = file_ids

                driver.posts.create_post(post_options)
            except Exception as e:
                print(f"Failed to post to {channel_id}: {e}")

        log_broadcast(
            sender_name=sender_name,
            message_content=session["message"],
            target_channels=session["valid_names"],
            file_ids=file_ids
        )

        driver.posts.create_post({
            "channel_id": dm_channel_id,
            "message": "✅ **Broadcast sent successfully.**\n\nThank you for using the Broadcast Bot!\n\n\n**If You want to send another Broadcast, SEND THE MESSAGE AND/OR ATTACH FILES NOW:**\nIf not, just do nothing :voigls:"
        })

    elif text.lower() == "no":
        driver.posts.create_post({"channel_id": dm_channel_id, "message": "❌ **Broadcast canceled.**"})

    else:
        driver.posts.create_post \
            ({"channel_id": dm_channel_id, "message": "Invalid response. Please reply with **yes** or **no**."})
        return

    del sessions[user_id]


def handle_add_group(text, dm_channel_id, private = False):
    if private:
        targeted_groups = PRIVATE_CHANNEL_GROUPS
        incoming_message = text.strip().lstrip("!_add_private_group").strip()
    else:
        targeted_groups = VISIBLE_CHANNEL_GROUPS
        incoming_message = text.strip().lstrip("!_add_group").strip()
    # 1. Check if the user actually provided payload data
    if not incoming_message:
        driver.posts.create_post({
                                     "channel_id": dm_channel_id,
                                     "message": "❌ Please provide a JSON string. Example: `!_add_group! {\"NewGroup\": [\"id1\", \"id2\"]}`"
                                 })
        return
    try:
        # 2. Attempt to parse the JSON
        new_groups_dict = json.loads(incoming_message)
        print(f"new_groups_dict pre cleaning: {new_groups_dict}")
        # 3. Validate that the parsed JSON is actually a dictionary
        if not isinstance(new_groups_dict, dict):
            raise ValueError("Input must be a JSON object (dictionary).")
        for key, list in new_groups_dict.copy().items():
            print(f"list {list}")
            for id in list.copy():
                print(f"id {id}")
                try:
                    driver.channels.get_channel(id)
                except Exception as e:
                    list.remove(id)
                    print(f"popped {id}")
            if len(list) == 0:
                new_groups_dict.pop(key)
                print(f"removed {key}")
                print(f"dict: {new_groups_dict}")

        print(f"new_groups_dict after cleaning: {new_groups_dict}")

        if len(new_groups_dict) != 0:


            # 4. Integrate the new group into your global state (assuming VISIBLE_CHANNEL_GROUPS)
            VISIBLE_CHANNEL_GROUPS.update(new_groups_dict)
            # 4. Integrate the new group into your global state
            print("updated")

            with open("channels.json", "r") as f:
                data = json.load(f)
            print("loaded")

            data["groups"] = targeted_groups
            with open("channels.json", "w") as f:
                json.dump(data, f, indent=4)

            print("written")
            driver.posts.create_post({
                "channel_id": dm_channel_id,
                "message": "✅ Group added successfully!"
            })
            print("done")
        else:
            driver.posts.create_post({
                "channel_id": dm_channel_id,
                "message": "❌ Group could not be added. Check your JSON syntax and the channel IDs!"
            })
    except json.JSONDecodeError:
        driver.posts.create_post({
            "channel_id": dm_channel_id, "message": "❌ Invalid JSON format. Please check your syntax."
        })
    except ValueError as e:
        driver.posts.create_post({
            "channel_id": dm_channel_id, "message": f"❌ {e}"
        })
    except Exception as e:
        # Catch-all for unexpected parsing or assignment issues
        driver.posts.create_post({"channel_id": dm_channel_id, "message": f"❌ An unexpected error occurred: {e}"})
