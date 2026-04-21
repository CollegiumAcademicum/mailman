"""Example task — prints a greeting to the bot log channel.

Copy this file and rename it to create a new task.
The filename (without .py) becomes the task's name as shown in !tasks.

Required:
    async def run(driver, args: str = "") -> None   — called by the scheduler and !run

    ``args`` is the text that follows the task name in a ``!run`` command
    (e.g. ``!run example_task hello world`` → args = "hello world").
    It is always an empty string when the task is run on a cron schedule.

Optional:
    DESCRIPTION: str                — shown in !tasks output
"""

DESCRIPTION = "Example task: posts a test message to the bot log channel"


async def run(driver, args: str = "") -> None:
    """Post a test message.

    Replace this body with your actual task logic.
    ``driver`` is an authenticated mattermostdriver.Driver instance.
    ``args`` is any text passed after the task name via ``!run``.

    Example — post to a channel by ID:
        driver.posts.create_post({
            "channel_id": "your_channel_id_here",
            "message": f"Hello from the task scheduler! args={args!r}",
        })
    """
    # This example task does nothing — remove or replace this line.
    pass
