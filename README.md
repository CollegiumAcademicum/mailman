# mm_mailman
This is a simple mattermost Bot that relays messages to channels


[![Automatic Dependency Submission](https://github.com/CollegiumAcademicum/mailman/actions/workflows/dependency-graph/auto-submission/badge.svg)](https://github.com/CollegiumAcademicum/mailman/actions/workflows/dependency-graph/auto-submission)
[![CodeQL](https://github.com/CollegiumAcademicum/mailman/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/CollegiumAcademicum/mailman/actions/workflows/github-code-scanning/codeql)
[![Python Unit Tests](https://github.com/CollegiumAcademicum/mailman/actions/workflows/tests.yml/badge.svg)](https://github.com/CollegiumAcademicum/mailman/actions/workflows/tests.yml)
## Example .env file:
Must have the following variables:
```dotenv
MATTERMOST_URL=mattermost.yourdomain.com
BOT_TOKEN=your_bot_access_token
TEAM_NAME=your-team-name
```
Following variables have standard values if not set:
```dotenv
SESSION_TIMEOUT_SECONDS=300
CLEANUP_INTERVAL_SECONDS=60

LOGGING_LEVEL=INFO
CONSOLE_LOGGING_LEVEL=WARNING
LOG_FILE=logs/bot.log

CHANNELS_JSON_PATH=channels.json
DB_PATH=broadcast_log.db
```

## Installation

### As a GitHub Submodule

To use this bot in another project:
1. Add it as a submodule: `git submodule add https://github.com/CollegiumAcademicum/mailman.git`
2. Ensure you have the `.env` and `channels.json` files in the `mailman` directory.
3. Import and run it from your parent project:
```python
import sys
from pathlib import Path

# Add submodule to sys.path
submodule_path = Path("./mailman").resolve()
sys.path.append(str(submodule_path))

from main import main
if __name__ == "__main__":
    main()
```

### Local / Dev
```bash
pip install uv
uv run main.py
```

### Running Tests
To run the unit tests, use `pytest`:
```bash
uv run pytest
```
Alternatively, if not using `uv`:
```bash
pip install pytest
pytest
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