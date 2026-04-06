"""PostBotConfig — extends BotConfig with postbot-specific configuration.

All fields are loaded from a ``.env`` file via :meth:`PostBotConfig.load`.
The base :class:`mmbot_framework.BotConfig` fields (``url``, ``token``,
``team_name``, etc.) are documented there.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

from mmbot_framework import BotConfig, ConfigError
from pydantic import field_validator


class PostBotConfig(BotConfig):
    """Configuration for the postbot broadcast relay bot.

    Extends :class:`mmbot_framework.BotConfig` with postbot-specific fields.
    All fields can be set via environment variables (or a ``.env`` file).

    Additional attributes:
        bot_log_channel_id: Mattermost channel ID for audit posts after each
            broadcast. Empty string disables audit logging.
        channels_json_path: Path to ``channels.json`` which defines channel
            groups and the broadcast whitelist.
        db_path: Path to the SQLite database used to log broadcasts.
        console_log_level: Log level for console (stderr) output. Independent
            of the file log level set by :attr:`~BotConfig.log_level`.
    """

    bot_log_channel_id: str = ""
    channels_json_path: Path = Path("channels.json")
    db_path: Path = Path("broadcast_log.db")
    console_log_level: str = "WARNING"

    @field_validator("console_log_level")
    @classmethod
    def _validate_console_log_level(cls, value: str) -> str:
        """Ensure ``console_log_level`` is a recognised Python log level name."""
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in valid:
            raise ValueError(
                f"console_log_level must be one of {sorted(valid)}, got {value!r}"
            )
        return upper

    @classmethod
    def load(cls, path: str | Path = ".env") -> "PostBotConfig":
        """Load configuration from a ``.env`` file.

        All keys are lowercased before validation so environment variable
        names are case-insensitive (e.g. ``BOT_TOKEN`` and ``bot_token``
        are equivalent).

        Args:
            path: Path to the ``.env`` file. Defaults to ``".env"`` in the
                current working directory.

        Returns:
            A validated :class:`PostBotConfig` instance.

        Raises:
            ConfigError: If the file does not exist or required fields are
                missing or invalid.
        """
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"Config file not found: {p}")
        raw = dict(dotenv_values(p))
        normalised = {k.lower(): v for k, v in raw.items()}
        try:
            return cls(**normalised)
        except Exception as exc:
            raise ConfigError(f"Invalid configuration: {exc}") from exc
