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

    '''
    In this project i added the commands inside the bots __init__ function.
    Here you can see an example on how to add a command to the bot outside the __init__ function.
    There are other ways that are possible.
    '''
    @bot.command("!ping")
    async def ping(msg):
        await bot.reply(msg, "pong")



    # Middleware is applied in registration order.
    # 1. Drop the bot's own messages first (cheapest check).
    # 2. Then drop any messages not from a DM channel.
    bot.add_middleware(DMOnlyMiddleware())
    bot.add_middleware(IgnoreSelfMiddleware(bot))

    bot.run()


if __name__ == "__main__":
    main()
