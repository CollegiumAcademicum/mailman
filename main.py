"""Entry point for the postbot broadcast relay bot.

Loads configuration from ``.env``, constructs a :class:`~bot.PostBot`
instance, attaches middleware, and starts the bot.

Run with::

    uv run main.py

Or via the installed script (see ``pyproject.toml``)::

    mailman-bot
"""

from __future__ import annotations

from mmbot_framework import IgnoreSelfMiddleware

from bot import DMOnlyMiddleware, PostBot
from config import PostBotConfig


def main() -> None:
    """Load configuration, build the bot, and run it until interrupted."""
    config = PostBotConfig.load(".env")

    bot = PostBot(config)

    # Middleware is applied in registration order.
    # 1. Drop the bot's own messages first (cheapest check).
    # 2. Then drop any messages not from a DM channel.
    bot.add_middleware(IgnoreSelfMiddleware(bot))
    bot.add_middleware(DMOnlyMiddleware())

    bot.run()


if __name__ == "__main__":
    main()
