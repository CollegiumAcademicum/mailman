import sys

from mattermostdriver import Driver

MATTERMOST_URL = sys.argv[1]
BOT_TOKEN = sys.argv[2]
TEAM_NAME = sys.argv[3]

driver = Driver(
    {"url": MATTERMOST_URL, "token": BOT_TOKEN, "scheme": "https", "port": 443}
)

driver.login()
bot_id = driver.users.get_user("me")["id"]
bot_username = driver.users.get_user("me")["username"]
team_id = driver.teams.get_team_by_name(TEAM_NAME)["id"]


print(f"Bot connected. Bot ID: {bot_id} | Team ID: {team_id}")

driver.posts.create_post(
    {
        "channel_id": "14d9s71is3fh3duwj9a6u9k4jr",
        "message": "unit test completed",
    }
)


driver.logout()
