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
  main.py           # Entry point: load config, build bot, run
  bot.py            # PostBot(BaseBot) — all command handlers and broadcast wizard
  config.py         # PostBotConfig(BotConfig) — env var loading and validation
  database.py       # SQLite broadcast log
  patches.py        # SSL workaround
  task_runner.py    # Task plugin discovery, schedule loading, and scheduler loop
  channels.toml     # Channel group definitions (visible groups, private groups, whitelist)
  scheduler.toml    # Cron schedule for automated tasks
  tasks/            # Task plugin directory — one .py file per task
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
CHANNEL_CACHE_TTL_SECONDS=3600  # How long the channel cache stays fresh (seconds)

# Logging
LOG_LEVEL=INFO                  # File log level
CONSOLE_LOG_LEVEL=WARNING       # Console (stdout) log level — set to INFO to see startup messages
LOG_FILE=logs/bot.log

# Postbot-specific
BOT_LOG_CHANNEL_ID=             # Channel ID for broadcast audit messages and task failure alerts (empty = disabled)
CHANNELS_TOML_PATH=channels.toml
DB_PATH=broadcast_log.db

# Task scheduler
TASKS_DIR=tasks                 # Directory containing task plugin .py files
SCHEDULER_TOML_PATH=scheduler.toml  # Cron schedule config
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
podman run --env-file .env -v ./channels.toml:/app/channels.toml:ro mailman-bot
```

---

## Bot Commands

All interaction happens via **direct message** to the bot. Messages in channels or group chats are ignored.

| Command                            | Description                                                 |
|------------------------------------|-------------------------------------------------------------|
| `!help` / `help` / `--help` / `man` | Show usage instructions                                     |
| `!channels`                        | List all channels the bot has access to in the current team |
| `!id <channel name>`               | Look up a channel's ID by name                              |
| `!get_groups`                      | List all visible channel groups                             |
| `!get_private_groups`              | List all private channel groups                             |
| `!add_group <TOML>`                | Add one or more public groups at runtime                    |
| `!add_private_group <TOML>`        | Add one or more private groups at runtime                   |
| `!refresh_channels`                | Force-reload the channel cache immediately                  |
| `!add_alias <alias> <target>`      | Add a short alias for a group or whitelisted channel        |
| `!tasks`                           | List all task plugins with their schedule and last run time |
| `!run <task>`                      | Run a scheduled task immediately                            |
| *(any other message)*              | Start the broadcast wizard                                  |

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
!add_group "New Group Name" = ["channel_id_1", "channel_id_2"]
```

Multiple groups in one command:

```
!add_group "Floor 1" = ["id_a", "id_b"]
!add_group "Floor 2" = ["id_c", "id_d"]
```

Changes are persisted to `channels.toml` immediately.

### Adding Aliases at Runtime

```
!add_alias cluster "ALLE Cluster Briefkästen"
!add_alias wg "ALLE WG Briefkästen"
```

Aliases are case-insensitive and stored lowercase. They work in the broadcast wizard as shorthand for group names or whitelisted channels.

---

## Task Scheduler

The bot can run arbitrary Python tasks on a cron schedule or on demand via `!run`. This replaces the old standalone cron scripts.

### Writing a task

Create a `.py` file in the `tasks/` directory. The filename (without `.py`) becomes the task's name.

```python
# tasks/my_task.py

DESCRIPTION = "Posts the weekly maintenance plan"  # shown in !tasks (optional)

async def run(driver) -> None:
    """driver is the already-authenticated mattermostdriver.Driver."""
    driver.posts.create_post({
        "channel_id": "your_channel_id",
        "message": "Hello from the task scheduler!",
    })
```

The task is immediately available via `!run my_task` after a bot restart (or if the bot is already running, next restart). No registration code needed.

### Scheduling a task

Add an entry to `scheduler.toml` using standard 5-field cron syntax:

```toml
[tasks]
my_task = "0 7 * * 1"   # every Monday at 07:00
```

Tasks not listed in `scheduler.toml` can still be triggered manually via `!run`.

Schedule changes take effect on the next bot restart. The file is git-tracked, providing a natural audit trail.

### Error handling

- A task that fails to import at startup is skipped with a warning — the bot still starts.
- A task that raises an exception at runtime is logged and, if `BOT_LOG_CHANNEL_ID` is set, an alert is posted to that channel.
- A failing task never crashes the bot or blocks the scheduler.

---

## Broadcast Log

Every successful broadcast is recorded in a SQLite database (`broadcast_log.db` by default), including sender, timestamp, target channels, and message content.

If `BOT_LOG_CHANNEL_ID` is set, a summary is also posted to that channel after each broadcast.

---

## Channel Cache

At startup the bot fetches all channel and team data in one API sweep and stores
it in memory. All command handlers (`!channels`, `!id`, `!get_groups`,
`!get_private_groups`, and the broadcast wizard) read from this cache instead of
calling the Mattermost API on every request.

The cache is refreshed automatically in the background every
`CHANNEL_CACHE_TTL_SECONDS` seconds (default: 3600 / one hour). If a channel
has been created or renamed since the last refresh, any user can force an
immediate reload with `!refresh_channels`.

On a cache miss (a channel created after the last refresh), the bot falls back
to a live API call and appends a note suggesting `!refresh_channels`.
