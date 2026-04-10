"""PostBot — broadcast relay bot built on mmbot_framework.

Usage::

    from config import PostBotConfig
    from bot import PostBot, DMOnlyMiddleware
    from mmbot_framework import IgnoreSelfMiddleware

    config = PostBotConfig.load(".env")
    bot = PostBot(config)
    bot.add_middleware(IgnoreSelfMiddleware(bot))
    bot.add_middleware(DMOnlyMiddleware())
    bot.run()
"""

from __future__ import annotations

import asyncio
import toml
import json
import logging
import logging.handlers
import time
from pathlib import Path
from typing import Callable

from mmbot_framework import BaseBot, ParsedMessage, Session

from config import PostBotConfig
from database import close_db_connection, initialize_database, log_broadcast
from patches import apply_ssl_patch

logger = logging.getLogger(__name__)


# ── Middleware ────────────────────────────────────────────────────────────────


class DMOnlyMiddleware:
    """Drop any message that did not arrive in a direct-message channel.

    Postbot only acts on DMs (``channel_type == "D"``).  Messages from public
    channels, private groups, or any other channel type are silently discarded
    here so that none of the command handlers ever see them.

    Example::

        bot.add_middleware(DMOnlyMiddleware())
    """

    async def __call__(self, msg: ParsedMessage, call_next: Callable) -> None:
        """Pass DMs down the pipeline; drop everything else.

        Args:
            msg: The parsed incoming message.
            call_next: Coroutine that continues the middleware chain.
        """
        if msg.channel_type != "D":
            logger.debug(
                f"DMOnlyMiddleware: dropping message from non-DM channel {msg.channel_id!r}."
            )
            return
        await call_next(msg)


# ── Help text ─────────────────────────────────────────────────────────────────

_HELP_MESSAGE = (
    "### Usage\n"
    "**DM me with the message you want delivered — I'll guide you through the process.**\n\n"
    "**Other commands:**\n"
    "- `!id <channel>` — return the channel ID for `<channel>` "
    "(use the system name, not the display name)\n"
    "- `!channels` — list all channels the bot has access to\n"
    "- `!get_groups` — list all available groups and their channels\n"
    "- `!get_private_groups` — same as above but for private groups\n"
    '- `!add_group <toml>` — add public group(s): `"GroupName" = ["id1", "id2"]`\n'
    "- `!add_private_group <toml>` — add private group(s): same toml format\n"
    "- `!refresh_channels` — force-reload the channel list cache"
)


# ── Bot ───────────────────────────────────────────────────────────────────────


class PostBot(BaseBot):
    """Broadcast relay bot that lets authorised users send messages to many channels.

    Users interact exclusively via DM.  The bot guides them through a two-step
    wizard: composing a message, selecting target channels or groups, and
    confirming before the broadcast is sent.

    Infrastructure (WebSocket lifecycle, session management, driver login,
    logging) is inherited from :class:`mmbot_framework.BaseBot`.

    Attributes:
        config: The validated :class:`PostBotConfig` for this instance.
    """

    def __init__(self, config: PostBotConfig) -> None:
        """Initialise the bot and register all command triggers.

        Args:
            config: Validated postbot configuration.
        """
        super().__init__(config)
        self.config: PostBotConfig  # narrow the type hint for type-checkers

        # State populated at startup via on_start().
        self._team_id: str = ""
        self._bot_username: str = ""

        # In-memory set of users who have received the welcome message.
        # Resets on bot restart — this matches the original behaviour.
        self._known_users: set[str] = set()

        # Channel groups and whitelist loaded from channels.json at startup
        # and mutated in-place by !add_group / !add_private_group.
        self._visible_groups: dict[str, list[str]] = {}
        self._private_groups: dict[str, list[str]] = {}
        self._whitelist: set[str] = set()

        # Register all command triggers.  The @command decorator supports only
        # one trigger per method, so we use _dispatcher.register() directly.
        for trigger in ("help", "!help", "--help", "man"):
            self._dispatcher.register(trigger, self._handle_help)

        self._dispatcher.register("!id", self._handle_id)
        self._dispatcher.register("!channels", self._handle_channels)
        # Register !get_private_groups before !get_groups so the longer prefix
        # is checked first (the dispatcher matches on startswith, first wins).
        self._dispatcher.register("!get_private_groups", self._handle_get_private_groups)
        self._dispatcher.register("!get_groups", self._handle_get_groups)
        # Same ordering rationale for !add_private_group vs !add_group.
        self._dispatcher.register("!add_private_group", self._handle_add_private_group)
        self._dispatcher.register("!add_group", self._handle_add_group)
        self._dispatcher.register("!refresh_channels", self._handle_refresh_channels)

    # ── Lifecycle hooks ──────────────────────────────────────────────────────

    async def on_start(self) -> None:
        """Run setup tasks after driver login, before the WebSocket opens.

        Steps:
        1. Apply the SSL patch required by the installed mattermostdriver version.
        2. Initialise the SQLite broadcast-log database.
        3. Fetch the bot's Mattermost team ID and username.
        4. Load channel group definitions from the channels TOML file.
        5. Register and pre-warm the channel cache.
        """
        apply_ssl_patch()
        initialize_database(self.config.db_path)

        me = self.driver.users.get_user("me")
        self._bot_username = me["username"]

        try:
            team = self.driver.teams.get_team_by_name(self.config.team_name)
            self._team_id = team["id"]
            logger.info(
                f"Bot connected as @{self._bot_username} "
                f"(team_id={self._team_id!r})."
            )
        except Exception as exc:
            logger.critical(
                f"Could not find team {self.config.team_name!r}. "
                f"Check TEAM_NAME in your .env file. Details: {exc}"
            )
            raise

        self._load_channel_data()

        self.cache.register(
            "channels", self._load_channel_cache, ttl=self.config.channel_cache_ttl_seconds
        )
        await self.cache.refresh("channels")
        logger.info("Channel cache pre-warmed.")

    async def on_stop(self) -> None:
        """Close the SQLite connection on shutdown."""
        close_db_connection()
        logger.info("Database connection closed.")
        return

    def _setup_logging(self) -> None:
        """Configure logging with separate levels for console and file output.

        Extends :meth:`~mmbot_framework.BaseBot._setup_logging` to support a
        separate ``console_log_level`` for the stream handler, independent of
        the file log level (``log_level``).  This allows verbose file logging
        while keeping the console output concise.
        """
        file_level = getattr(logging, self.config.log_level, logging.INFO)
        console_level = getattr(
            logging, self.config.console_log_level, logging.WARNING
        )

        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(console_level)

        handlers: list[logging.Handler] = [stream_handler]
        if self.config.log_file:
            file_handler = logging.handlers.RotatingFileHandler(
                self.config.log_file,
                maxBytes=100 * 1024 * 1024,  # 100 MB, matching original postbot
                backupCount=5,
            )
            file_handler.setLevel(file_level)
            handlers.append(file_handler)

        logging.basicConfig(
            level=min(file_level, console_level),
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=handlers,
            force=True,
        )
        logger.debug(
            f"Logging configured — file_level={self.config.log_level} "
            f"console_level={self.config.console_log_level} "
            f"file={self.config.log_file}"
        )

    # ── Session cleanup with expiry notifications ─────────────────────────────

    async def _session_cleanup_loop(self) -> None:
        """Background task: notify users of expired sessions, then purge them.

        Overrides :meth:`~mmbot_framework.BaseBot._session_cleanup_loop` to
        send a DM to each user whose session has expired before the session is
        removed.  The base-class implementation silently purges without
        notifying the user.

        Session data must contain ``"dm_channel_id"`` for a notification to be
        sent; sessions without it are still purged but not notified.
        """
        interval = self.config.session_cleanup_interval_seconds
        while True:
            await asyncio.sleep(interval)
            logger.debug("Running session expiry check.")

            # Collect sessions that have expired and have a DM channel to
            # notify.  We iterate a snapshot (list) to avoid mutating the dict
            # during iteration.
            # TODO: Replace with a framework method once SessionManager exposes
            # pop_expired() → list[Session]. Direct access to _sessions is
            # required here because purge_expired() does not return the removed
            # sessions, so we cannot notify users after the fact.
            expired = [
                s
                for s in list(self.sessions._sessions.values())
                if s.is_expired() and "dm_channel_id" in s.data
            ]

            for session in expired:
                try:
                    self._post(
                        session.data["dm_channel_id"],
                        "⏱️ **Session expired.** You took too long to confirm. "
                        "Send a new message to start over.",
                    )
                    logger.info(
                        f"Sent expiry notice to user {session.sender_id!r}."
                    )
                    self._known_users.remove(session.sender_id) # remove user from known users once session ends. this is a workaround
                except Exception as exc:
                    logger.error(
                        f"Failed to send expiry notice to user "
                        f"{session.sender_id!r}: {exc}"
                    )

            removed = self.sessions.purge_expired()
            if removed:
                logger.info(
                    f"Session cleanup: removed {removed} expired session(s)."
                )

    # ── Broadcast wizard (on_message fallback) ────────────────────────────────

    async def on_message(self, msg: ParsedMessage) -> None:
        """Handle DMs that did not match any registered command.

        Implements the broadcast wizard state machine:

        - **New user** (first DM ever): show welcome message, wait for content.
        - **No active session**: user sends content — capture it, ask for targets.
        - **AWAITING_CHANNELS**: user specifies targets — validate and preview.
        - **CONFIRMATION**: user replies ``yes`` / ``no`` — relay or cancel.

        Args:
            msg: The unmatched parsed message (always a DM due to middleware).
        """
        sender_id = msg.sender_id

        if sender_id not in self._known_users:
            logger.info(f"New user: @{msg.sender_name} ({sender_id}).")
            await self._handle_new_user(msg)
            return

        session = self.sessions.get(sender_id)

        if session is None:
            logger.info(f"Starting new broadcast session for @{msg.sender_name}.")
            await self._handle_new_session(msg)
            return

        state = session.data.get("state")

        if state == "AWAITING_CHANNELS":
            logger.info(f"Handling channel selection for @{msg.sender_name}.")
            await self._handle_channel_selection(session, msg)
        elif state == "CONFIRMATION":
            logger.info(f"Handling broadcast confirmation for @{msg.sender_name}.")
            await self._handle_confirmation(session, msg)
        else:
            logger.warning(
                f"User @{msg.sender_name} is in unknown session state {state!r}."
            )

    # ── Command handlers ──────────────────────────────────────────────────────

    async def _handle_help(self, msg: ParsedMessage) -> None:
        """Respond with the usage help text.

        Triggered by: ``!help``, ``help``, ``--help``, ``man``.

        Args:
            msg: The incoming message.
        """
        logger.info(f"User @{msg.sender_name} requested help.")
        self._post(msg.channel_id, _HELP_MESSAGE)

    async def _handle_id(self, msg: ParsedMessage) -> None:
        """Look up and return the Mattermost channel ID for a given channel name.

        Usage: ``!id <channel-name>``

        The channel name must be the *system* name (e.g. ``town-square``), not
        the display name (e.g. ``Town Square``).

        Args:
            msg: The incoming message.  The channel name is the text after the
                ``!id`` prefix.
        """
        channel_name = msg.text[len("!id"):].strip()
        if not channel_name:
            logger.warning(
                f"User @{msg.sender_name} used !id without a channel name."
            )
            self._post(
                msg.channel_id,
                "Please provide a channel name after `!id`, "
                "e.g. `!id town-square`.",
            )
            return

        logger.info(
            f"User @{msg.sender_name} requested ID for channel {channel_name!r}."
        )
        try:
            channel = self.driver.channels.get_channel_by_name(
                self._team_id, channel_name
            )
            self._post(
                msg.channel_id,
                f"The ID for channel `{channel_name}` is: `{channel['id']}`",
            )
        except Exception as exc:
            logger.error(f"Could not find channel {channel_name!r}: {exc}")
            self._post(
                msg.channel_id,
                f"⚠️ Could not find a channel named `{channel_name}`.",
            )

    async def _handle_channels(self, msg: ParsedMessage) -> None:
        """List all Mattermost channels the bot has access to.

        Outputs a Markdown table with display name, system name, channel ID,
        and team name for every channel across all teams the bot belongs to.

        Args:
            msg: The incoming message.
        """
        logger.info(f"User @{msg.sender_name} requested the channel list.")
        lines = [
            "| display_name | name | ID | team_name |",
            "| :--- | :--- | :--- | :--- |",
        ]
        try:
            teams = self.driver.teams.get_user_teams("me")
            for team in teams:
                channels = self.driver.channels.get_channels_for_user(
                    "me", team["id"]
                )
                for channel in channels:
                    if channel["team_id"]:
                        team_name = self.driver.teams.get_team(
                            channel["team_id"]
                        ).get("display_name", "N/A")
                        lines.append(
                            f"| `{channel['display_name']}` | {channel['name']} "
                            f"| `{channel['id']}` | {team_name} |"
                        )
        except Exception as exc:
            logger.error(f"Error fetching channels: {exc}")
            lines.append("Error fetching channels.")

        self._post(msg.channel_id, "\n".join(lines))

    async def _handle_get_groups(self, msg: ParsedMessage) -> None:
        """List all visible channel groups and their resolved channel names.

        Args:
            msg: The incoming message.
        """
        logger.info(f"User @{msg.sender_name} requested visible groups.")
        lines: list[str] = []
        for name, channel_ids in self._visible_groups.items():
            try:
                resolved = [
                    self.driver.channels.get_channel(cid)["name"]
                    for cid in channel_ids
                ]
                lines.append(f"**{name}:** {resolved}\n")
            except Exception as exc:
                logger.error(
                    f"Error resolving channels for group {name!r}: {exc}"
                )
                lines.append(f"**{name}:** [error fetching channel names]\n")
        self._post(
            msg.channel_id,
            "\n".join(lines) if lines else "No groups configured.",
        )

    async def _handle_get_private_groups(self, msg: ParsedMessage) -> None:
        """List all private channel groups and their resolved channel names.

        Args:
            msg: The incoming message.
        """
        logger.info(f"User @{msg.sender_name} requested private groups.")
        lines: list[str] = []
        for name, channel_ids in self._private_groups.items():
            try:
                resolved = [
                    self.driver.channels.get_channel(cid)["name"]
                    for cid in channel_ids
                ]
                lines.append(f"**{name}:** {resolved}\n")
            except Exception as exc:
                logger.error(
                    f"Error resolving channels for private group {name!r}: {exc}"
                )
                lines.append(f"**{name}:** [error fetching channel names]\n")
        self._post(
            msg.channel_id,
            "\n".join(lines) if lines else "No private groups configured.",
        )

    async def _handle_add_group(self, msg: ParsedMessage) -> None:
        """Add one or more public channel groups from a JSON payload.

        Usage: ``!add_group {"GroupName": ["channel_id_1", "channel_id_2"]}``

        Invalid channel IDs are removed silently.  Groups where every ID is
        invalid are not added.  Valid groups are persisted to ``channels.json``
        and the in-memory state is updated immediately.

        Args:
            msg: The incoming message.
        """
        await self._add_group_impl(msg, private=False)

    async def _handle_add_private_group(self, msg: ParsedMessage) -> None:
        """Add one or more private channel groups from a JSON payload.

        Usage: ``!add_private_group {"GroupName": ["channel_id_1", "channel_id_2"]}``

        Private groups are only visible via ``!get_private_groups``, not
        ``!get_groups``.

        Args:
            msg: The incoming message.
        """
        await self._add_group_impl(msg, private=True)

    async def _handle_refresh_channels(self, msg: ParsedMessage) -> None:
        """Force-reload the channel cache immediately.

        Triggered by: ``!refresh_channels``

        Any user can trigger this.  Useful when channels have been created,
        renamed, or deleted since the last automatic refresh.

        Args:
            msg: The incoming message.
        """
        logger.info(f"User @{msg.sender_name} triggered channel cache refresh.")
        try:
            await self.cache.refresh("channels")
        except Exception as exc:
            logger.error(f"Channel cache refresh failed: {exc}")
            self._post(msg.channel_id, "⚠️ Channel cache refresh failed. Please try again later.")
            return
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        self._post(msg.channel_id, f"✅ Channel cache refreshed at **{ts} UTC**.")

    # ── Broadcast wizard helpers ──────────────────────────────────────────────

    async def _handle_new_user(self, msg: ParsedMessage) -> None:
        """Send the welcome message to a first-time user and register them.

        After the welcome, the user must send their broadcast content in a
        subsequent message before a session is created.

        Args:
            msg: The message that identified this user as new.

        Note:
            ``sender_id`` is added to ``_known_users`` *after* the welcome
            message is posted.  If the post fails, the user is not registered
            and will receive the welcome again on their next message.
        """
        self._post(
            msg.channel_id,
            "👋 **Welcome, I'm the Postbot**\n\n"
            "To send a broadcast, just send me the message you want to share "
            "(you can attach files too!). I'll then ask you to specify the "
            "target channels or groups.\n\n"
            "Your message will *not* be sent until you confirm.\n\n"
            "**TYPE YOUR MESSAGE AND/OR ATTACH FILES NOW:**",
        )
        self._known_users.add(msg.sender_id)

    async def _handle_new_session(self, msg: ParsedMessage) -> None:
        """Capture the user's broadcast content and ask for target channels.

        Creates a new session in the ``AWAITING_CHANNELS`` state.

        Args:
            msg: The message containing the broadcast content and optional files.
        """
        session = self.sessions.get_or_create(msg.sender_id)
        session.data.update(
            {
                "state": "AWAITING_CHANNELS",
                "message": msg.text,
                "file_ids": msg.file_ids,
                "dm_channel_id": msg.channel_id,
            }
        )

        # Build the displayed list of whitelisted channels.
        allowed_channels: list[str] = []
        for channel_id in self._whitelist:
            try:
                info = self.driver.channels.get_channel(channel_id)
                team_name = (
                    self.driver.teams.get_team(info["team_id"]).get(
                        "display_name", "N/A"
                    )
                    if info["team_id"]
                    else "N/A"
                )
                allowed_channels.append(
                    f"- name: `{info['name']}`    "
                    f"(display name: `{info['display_name']}` — "
                    f"ID: `{channel_id}` — team: `{team_name}`)"
                )
            except Exception as exc:
                logger.error(
                    f"Error fetching info for channel {channel_id!r}: {exc}"
                )
                allowed_channels.append(f"- `(ID not found)` (`{channel_id}`)")

        allowed_channels.sort()
        group_list = "".join(f"- `{g}`\n" for g in self._visible_groups)
        file_notice = (
            f"\n_You have attached {len(msg.file_ids)} file(s)._"
            if msg.file_ids
            else ""
        )

        self._post(
            msg.channel_id,
            f"I've captured your message.{file_notice}\n\n"
            f"Reply with the **channel names** or **groups** you want to send "
            f"it to, separated by commas.\n\n"
            f"### Available Groups:\n{group_list}"
            f"**Available Channels:**\n"
            + "\n".join(allowed_channels),
        )

    async def _handle_channel_selection(self, session: Session, msg: ParsedMessage) -> None:
        """Validate the user's target selection and show a confirmation preview.

        Updates the session state to ``CONFIRMATION`` on success.  If no valid
        channels are found the user is asked to try again (session is NOT
        cleared).

        Args:
            session: The active :class:`~mmbot_framework.Session` for this user.
            msg: The message containing the comma-separated channel/group targets.
        """
        requested_lines = [item.strip() for item in msg.text.split("\n")]
        logger.info(f"User @{msg.sender_name} requested channels: {requested_lines}")
        requested = set()
        for line in requested_lines:
            for item in line.split(","):
                requested.add(item.strip())
        valid_ids, valid_names, invalid_names = self._resolve_targets(requested)

        if not valid_ids:
            logger.warning(
                f"No valid channels found for input from @{msg.sender_name}."
            )
            self._post(
                msg.channel_id,
                "⚠️ No valid channels found. Please try again.",
            )
            return

        session.data.update(
            {
                "target_ids": valid_ids,
                "valid_names": valid_names,
                "state": "CONFIRMATION",
            }
        )

        file_notice = (
            f"\n**Files attached:** {len(session.data['file_ids'])}"
            if session.data.get("file_ids")
            else ""
        )
        warning = (
            f"\n⚠️ *Ignored invalid inputs: {', '.join(invalid_names)}*"
            if invalid_names
            else ""
        )
        self._post(
            msg.channel_id,
            f"**Preview:**\n{session.data['message']}\n\n"
            f"**Targets:**\n"
            + "\n".join(valid_names)
            + file_notice
            + warning
            + "\n\nReply with **yes** to send or **no** to cancel.",
        )

    async def _handle_confirmation(self, session: Session, msg: ParsedMessage) -> None:
        """Handle the user's final yes/no confirmation.

        - ``yes``: relay message and files to all target channels, log to DB,
          post audit entry (if configured), clear session.
        - ``no``: cancel and clear session.
        - anything else: ask again without clearing the session.

        Args:
            session: The active :class:`~mmbot_framework.Session` for this user.
            msg: The confirmation message.
        """
        text_lower = msg.text.lower()

        if text_lower == "yes":
            await self._send_broadcast(session, msg)
        elif text_lower == "no":
            logger.info(f"User @{msg.sender_name} canceled broadcast.")
            self._post(msg.channel_id, "❌ **Broadcast canceled.**")
        else:
            logger.warning(
                f"Invalid confirmation from @{msg.sender_name}: {msg.text!r}."
            )
            self._post(
                msg.channel_id,
                "Invalid response. Please reply with **yes** or **no**.",
            )
            return  # Keep the session alive — the user can still confirm.

        self.sessions.clear(msg.sender_id)
        logger.info(f"Session for @{msg.sender_name} cleared.")

    async def _send_broadcast(self, session: Session, msg: ParsedMessage) -> None:
        """Relay the broadcast message and files to all selected target channels.

        For each target channel:

        1. Download every attached file from Mattermost (once).
        2. Re-upload each file to the target channel.
        3. Post the broadcast message with the re-uploaded file IDs.

        After all channels are posted, persists the broadcast to SQLite and
        optionally posts an audit entry to the configured log channel.

        Args:
            session: The confirmed :class:`~mmbot_framework.Session`.
            msg: The ``yes`` confirmation message (provides sender metadata).
        """
        logger.info(f"User @{msg.sender_name} confirmed broadcast.")
        broadcast_text = (
            f"📢 **Message from @{msg.sender_name}**\n\n\n"
            f"{session.data['message']}"
            f"\n\n\n\n*--- END of Message ---*\n"
            f"*To use my services (@{self._bot_username}) just DM me*"
        )

        # Download all attached files once (they'll be re-uploaded per channel).
        files: dict[str, bytes] = {}
        for file_id in session.data.get("file_ids", []):
            try:
                response = self.driver.files.get_file(file_id)
                metadata = self.driver.files.get_file_metadata(file_id)
                filename = metadata.get("name", "relayed_file.dat")
                # get_file() returns a dict for JSON files, a Response otherwise.
                files[filename] = (
                    json.dumps(response).encode("utf-8")
                    if isinstance(response, dict)
                    else response.content
                )
            except Exception as exc:
                logger.error(f"Failed to fetch file {file_id!r}: {exc}")

        # Post to each target channel; re-upload files per channel.
        all_uploaded_ids: list[str] = []
        for channel_id in session.data["target_ids"]:
            channel_file_ids: list[str] = []
            for filename, content in files.items():
                try:
                    info = self.driver.files.upload_file(
                        channel_id=channel_id,
                        files={"files": (filename, content)},
                    )
                    channel_file_ids.append(info["file_infos"][0]["id"])
                except Exception as exc:
                    logger.error(
                        f"Failed to upload {filename!r} to channel "
                        f"{channel_id!r}: {exc}"
                    )
            all_uploaded_ids.extend(channel_file_ids)

            try:
                self.driver.posts.create_post(
                    {
                        "channel_id": channel_id,
                        "message": broadcast_text,
                        "file_ids": channel_file_ids,
                    }
                )
                logger.info(f"Posted broadcast to channel {channel_id!r}.")
            except Exception as exc:
                logger.error(
                    f"Failed to post to channel {channel_id!r}: {exc}"
                )

        # Persist to the SQLite broadcast log.
        log_broadcast(
            sender_name=msg.sender_name,
            message_content=session.data["message"],
            target_channels=session.data["valid_names"],
            file_ids=all_uploaded_ids,
        )

        # Optional audit post to the configured log channel.
        if self.config.bot_log_channel_id:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
            self._post(
                self.config.bot_log_channel_id,
                f"Sender *{msg.sender_name}* sent a broadcast. "
                f"Timestamp (UTC): {timestamp}. "
                f"Target channel count: {len(session.data['valid_names'])}. "
                f"Attached file count: {len(all_uploaded_ids)}.",
            )

        self._post(
            msg.channel_id,
            "✅ **Broadcast sent successfully.**\n\n"
            "Thank you for using the Broadcast Bot!\n\n\n"
            "**If you want to send another broadcast, SEND THE MESSAGE "
            "AND/OR ATTACH FILES NOW:**\n"
            "If not, just do nothing. The session will stop automatically :feuervoigl:",
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _post(self, channel_id: str, text: str) -> None:
        """Post a plain-text / Markdown message to a Mattermost channel.

        Thin wrapper over ``self.driver.posts.create_post`` that avoids
        repeating the dict-construction boilerplate throughout the handlers.

        Args:
            channel_id: The Mattermost channel ID to post to.
            text: The message body.  Mattermost renders Markdown.
        """
        self.driver.posts.create_post({"channel_id": channel_id, "message": text})

    def _resolve_targets(
        self, inputs: set[str]
    ) -> tuple[list[str], list[str], list[str]]:
        """Resolve user-supplied channel names, IDs, and group names to channel IDs.

        Each input is processed as follows:

        1. If it exactly matches a known group name (visible or private), the
           group's channel IDs are added directly.
        2. Otherwise it is treated as a channel name and resolved to an ID via
           the Mattermost API.  If the API call fails it is assumed to already
           be an ID.
        3. Any resolved ID **not** in :attr:`_whitelist` is rejected.

        Args:
            inputs: Raw user inputs, typically split on commas.

        Returns:
            A three-tuple of:

            - ``valid_ids``: Whitelisted channel IDs to broadcast to.
            - ``valid_names``: Display names corresponding to ``valid_ids``.
            - ``invalid_names``: Inputs that could not be resolved or are not
              whitelisted.
        """
        # TODO add Channel Caching
        # TODO add display name resolver
        all_groups: dict[str, list[str]] = {
            **self._visible_groups,
            **self._private_groups,
        }
        valid_ids: set[str] = set()
        invalid_inputs: set[str] = set()

        for item in inputs:
            stripped = item.strip()
            if stripped in all_groups:
                valid_ids.update(all_groups[stripped])
                logger.debug(
                    f"Resolved group {stripped!r} to {all_groups[stripped]}."
                )
            else:
                clean = stripped.lower().lstrip("#")
                try:
                    channel = self.driver.channels.get_channel_by_name(
                        self._team_id, clean
                    )
                    channel_id = channel["id"]
                except Exception:
                    channel_id = clean
                    logger.debug(
                        f"Could not resolve {clean!r} as a channel name; "
                        f"treating as raw ID."
                    )

                if channel_id in self._whitelist:
                    valid_ids.add(channel_id)
                else:
                    invalid_inputs.add(stripped)
                    logger.warning(
                        f"Channel {stripped!r} (resolved to {channel_id!r}) "
                        f"is not in the whitelist."
                    )

        valid_names: list[str] = []
        for cid in valid_ids:
            try:
                valid_names.append(
                    self.driver.channels.get_channel(cid)["display_name"]
                )
            except Exception:
                valid_names.append(cid)
                logger.warning(
                    f"Could not get display name for channel {cid!r}."
                )

        return list(valid_ids), valid_names, list(invalid_inputs)

    def _load_channel_data(self) -> None:
        """Read ``channels.json`` and populate in-memory group and whitelist data.

        Called at startup via :meth:`on_start` and after any successful
        ``!add_group`` or ``!add_private_group`` mutation.

        Raises:
            FileNotFoundError: If :attr:`~PostBotConfig.channels_toml_path`
                does not exist.
            json.JSONDecodeError: If the file contains invalid JSON.
        """
        # TODO add aliase
        path: Path = self.config.channels_toml_path
        logger.info(f"Loading channel data from {path}.")
        with path.open("r") as fh:
            data = toml.load(fh)
        self._visible_groups = data.get("groups", {})
        self._private_groups = data.get("private_groups", {})
        self._whitelist = set(data.get("whitelist", []))
        logger.debug(
            f"Loaded {len(self._visible_groups)} visible groups, "
            f"{len(self._private_groups)} private groups, "
            f"{len(self._whitelist)} whitelist entries."
        )

    async def _load_channel_cache(self) -> dict:
        """Fetch all channel data from the Mattermost API in one sweep.

        Called by :attr:`~mmbot_framework.BaseBot.cache` automatically on TTL
        expiry and on demand via ``!refresh_channels``.  Never call directly —
        use :meth:`~mmbot_framework.core.cache.CacheManager.refresh` instead.

        The returned dict has three keys:

        - ``"by_id"`` — maps channel ID → info dict with ``name``,
          ``display_name``, ``team_name``, and ``team_id``.
        - ``"by_name"`` — maps channel system name → channel ID.
        - ``"all_rows"`` — pre-formatted Markdown table rows for ``!channels``,
          built here so ``!channels`` is a zero-API-call string join.

        Returns:
            Dict with keys ``"by_id"``, ``"by_name"``, ``"all_rows"``.
        """
        by_id: dict[str, dict] = {}
        by_name: dict[str, str] = {}
        all_rows: list[str] = []

        teams = self.driver.teams.get_user_teams("me")
        for team in teams:
            team_name = team.get("display_name", "N/A")
            channels = self.driver.channels.get_channels_for_user("me", team["id"])
            for ch in channels:
                if not ch.get("team_id"):
                    continue  # skip DM / group-message channels
                cid = ch["id"]
                info = {
                    "name": ch["name"],
                    "display_name": ch["display_name"],
                    "team_name": team_name,
                    "team_id": ch["team_id"],
                }
                by_id[cid] = info
                by_name[ch["name"]] = cid
                all_rows.append(
                    f"| `{ch['display_name']}` | {ch['name']} "
                    f"| `{cid}` | {team_name} |"
                )

        logger.info(f"Channel cache loaded: {len(by_id)} channel(s).")
        return {"by_id": by_id, "by_name": by_name, "all_rows": all_rows}

    async def _add_group_impl(self, msg: ParsedMessage, *, private: bool) -> None:
        """Shared implementation for !add_group and !add_private_group.

        Parses the JSON payload from the message text, validates each channel
        ID against the Mattermost API, removes invalid IDs, and persists the
        cleaned result to ``channels.json``.  The in-memory state is updated
        immediately on success.

        Args:
            msg: The incoming message whose text contains the JSON payload
                after the command trigger.
            private: If ``True``, the group is written to ``private_groups``;
                otherwise to ``groups``.
        """
        trigger = "!add_private_group" if private else "!add_group"
        json_key = "private_groups" if private else "groups"
        target_dict = self._private_groups if private else self._visible_groups

        payload_str = msg.text[len(trigger):].strip()
        if not payload_str:
            self._post(
                msg.channel_id,
                f"❌ Please provide a JSON payload. "
                f'Example: `{trigger} {{"NewGroup": ["id1", "id2"]}}`',
            )
            return

        try:
            new_groups: dict = toml.loads(payload_str)
        except toml.TomlDecodeError as exc:
            logger.error(f"Invalid JSON in {trigger} command: {exc}")
            self._post(
                msg.channel_id,
                "❌ Invalid JSON format. Please check your syntax.",
            )
            return

        if not isinstance(new_groups, dict):
            self._post(
                msg.channel_id,
                "❌ Input must be a JSON object (dictionary).",
            )
            return

        # Validate each channel ID; drop those that don't exist in Mattermost.
        cleaned: dict[str, list[str]] = {}
        for group_name, channel_ids in new_groups.items():
            valid: list[str] = []
            for channel_id in channel_ids:
                try:
                    self.driver.channels.get_channel(channel_id)
                    valid.append(channel_id)
                except Exception:
                    logger.warning(
                        f"Removed invalid channel ID {channel_id!r} "
                        f"from group {group_name!r}."
                    )
            if valid:
                cleaned[group_name] = valid
            else:
                logger.warning(
                    f"Group {group_name!r} had no valid channels; skipped."
                )

        if not cleaned:
            self._post(
                msg.channel_id,
                "❌ No valid groups to add. "
                "Check your JSON syntax and channel IDs.",
            )
            return

        # Update in-memory state.
        target_dict.update(cleaned)

        # Persist to channels.json.
        path: Path = self.config.channels_toml_path
        with path.open("r", encoding="utf-8") as fh:
            data = toml.load(fh)
        data[json_key] = target_dict
        with path.open("w", encoding="utf-8") as fh:
            toml.dump(data, fh)

        logger.info(
            f"Persisted new groups to {path}: {list(cleaned.keys())}."
        )
        self._post(msg.channel_id, "✅ Group added successfully!")
