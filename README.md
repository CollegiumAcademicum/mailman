# mm_mailman

A Mattermost bot that relays messages to multiple channels via a guided two-step broadcast wizard. Users interact with the bot exclusively via direct messages.

[![Automatic Dependency Submission](https://github.com/CollegiumAcademicum/mailman/actions/workflows/dependency-graph/auto-submission/badge.svg)](https://github.com/CollegiumAcademicum/mailman/actions/workflows/dependency-graph/auto-submission)
[![CodeQL](https://github.com/CollegiumAcademicum/mailman/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/CollegiumAcademicum/mailman/actions/workflows/github-code-scanning/codeql)
[![Python Unit Tests](https://github.com/CollegiumAcademicum/mailman/actions/workflows/tests.yml/badge.svg)](https://github.com/CollegiumAcademicum/mailman/actions/workflows/tests.yml)

---

## Architecture

The bot is built on [mmbot_framework](../mmbot_framework/), a shared library that handles the WebSocket lifecycle, session management, middleware, and command routing. `postbot` adds only the broadcast-relay logic on top.

```
postbot/
  main.py        # Entry point: load config, build bot, run
  bot.py         # PostBot(BaseBot) — all command handlers and broadcast wizard
  config.py      # PostBotConfig(BotConfig) — env var loading and validation
  database.py    # SQLite broadcast log
  patches.py     # SSL workaround
  channels.json  # Channel group definitions (visible groups, private groups, whitelist)
```

**Message flow:**

```
Mattermost WebSocket event
  → IgnoreSelfMiddleware     (drop own messages)
  → DMOnlyMiddleware         (drop non-DM messages)
  → CommandDispatcher        (route to handler by trigger prefix)
  → handler / broadcast wizard (PostBot.on_message)
```

---

## Configuration

Create a `.env` file in the `postbot/` directory:

```dotenv
# Required
URL=mattermost.yourdomain.com
TOKEN=your_bot_access_token
TEAM_NAME=your-team-name

# Optional — shown with their defaults
SESSION_TTL_SECONDS=300
SESSION_CLEANUP_INTERVAL_SECONDS=60

# Logging
LOG_LEVEL=INFO                  # File log level
CONSOLE_LOG_LEVEL=WARNING   # Console (stdout) log level — set to INFO to see startup messages
LOG_FILE=logs/bot.log

# Postbot-specific
BOT_LOG_CHANNEL_ID=             # Channel ID for broadcast audit messages (empty = disabled)
CHANNELS_JSON_PATH=channels.json
DB_PATH=broadcast_log.db
```

> **Tip:** Set `CONSOLE_LOGGING_LEVEL=INFO` to see WebSocket connection and startup messages in the terminal.

---

## channels.toml

Defines the channel groups the bot can broadcast to. Loaded at startup and extendable at runtime via `!add_group` / `!add_private_group`.

```toml
whitelist = [ "14d9s71is3fh3duwj9a6u9k4jr",]

[groups]
"name1" = [ "id1", "id2",]
"name2" = [ "id3", "id4", "id5",]


[private_groups]
"name3" = [ "id6", "id7", "id8",]

```

- **groups** — visible to all users via `!get_groups`
- **private_groups** — visible only via `!get_private_groups`
- **whitelist** — channel IDs that may be targeted individually by name or ID, outside of groups

---

## Installation

### Local / Dev

Requires Python 3.14+ and [`uv`](https://github.com/astral-sh/uv).

```bash
cd postbot
uv sync
# create and fill in .env (see Configuration section above)
uv run main.py
```

### Running Tests

```bash
cd postbot
uv run pytest -v
```

### Container (Podman / Docker)

```bash
cd postbot
podman build -f Containerfile -t mailman-bot .
podman run --env-file .env -v ./channels.json:/app/channels.json:ro mailman-bot
```

---

## Bot Commands

All interaction happens via **direct message** to the bot. Messages in channels or group chats are ignored.

| Command                             | Description |
|-------------------------------------|---|
| `!help` / `help` / `--help` / `man` | Show usage instructions |
| `!channels`                         | List all channels the bot has access to in the current team |
| `!id <channel name>`                | Look up a channel's ID by name |
| `!get_groups`                       | List all visible channel groups |
| `!get_private_groups`               | List all private channel groups |
| `!add_group <TOML>`                 | Add one or more public groups at runtime |
| `!add_private_group <TOML>`         | Add one or more private groups at runtime |
| *(any other message)*               | Start the broadcast wizard |

### Broadcast Wizard

Sending any message that isn't a command starts a two-step broadcast:

1. **Target selection** — the bot asks which channels or groups to send to. Accepted formats:
   - Group names (from `!get_groups` / `!get_private_groups`)
   - Individual channel names (must be on the whitelist)
   - Channel IDs directly
   - Comma-separated combinations: `Group A, Group B, some-channel-name`

2. **Confirmation** — the bot shows a preview of recipients. Reply `yes` to send, `no` to cancel.

Files attached to your original message are relayed alongside the text.

Sessions expire after `SESSION_TTL_SECONDS` (default 5 minutes). If your session expires before you confirm, the bot sends a DM notification.

### Adding Groups at Runtime

```
!add_group {"New Group Name": ["channel_id_1", "channel_id_2"]}
```

Multiple groups in one command:

```
!add_group {"Floor 1": ["id_a", "id_b"], "Floor 2": ["id_c", "id_d"]}
```

Changes are persisted to `channels.json` immediately.

---

## Broadcast Log

Every successful broadcast is recorded in a SQLite database (`broadcast_log.db` by default), including sender, timestamp, target channels, and message content.

If `BOT_LOG_CHANNEL_ID` is set, a summary is also posted to that channel after each broadcast.
