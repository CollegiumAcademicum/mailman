# mm_mailman
This is a simple mattermost Bot that relays messages to channels


[![Automatic Dependency Submission](https://github.com/CollegiumAcademicum/mailman/actions/workflows/dependency-graph/auto-submission/badge.svg)](https://github.com/CollegiumAcademicum/mailman/actions/workflows/dependency-graph/auto-submission)
[![CodeQL](https://github.com/CollegiumAcademicum/mailman/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/CollegiumAcademicum/mailman/actions/workflows/github-code-scanning/codeql)
[![Python Unit Tests](https://github.com/CollegiumAcademicum/mailman/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/CollegiumAcademicum/mailman/actions/workflows/unit-tests.yml)

## Example .env file:
Must have the following variables:
```dotenv
MATTERMOST_URL=mattermost.yourdomain.com
BOT_TOKEN=your_bot_access_token
TEAM_NAME=your-team-name
SESSION_TIMEOUT_SECONDS=300
CLEANUP_INTERVAL_SECONDS=60
```
Can have the following variables:
```dotenv
DEBUG_LEVEL=INFO
LOG_FILE=bot.log
```

## Installation
## local / dev
```
pip install uv
uv run main.py
```
## Podman
```
git clone <repo>
<build image from Containerfile>
<run image>
```


## Use
- the bot can send messages into all channels when defined through a group
- When cherrypicked directly, the bot can only send messages into channels of its current team (TEAM_NAME in .env)