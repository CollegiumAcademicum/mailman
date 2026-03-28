import sys
import datetime

from mattermostdriver import Driver

MATTERMOST_URL = sys.argv[1]
BOT_TOKEN = sys.argv[2]
TEAM_NAME = sys.argv[3]
branch = sys.argv[4]  # ${{ github.ref_name }}
author = sys.argv[5]  # ${{ github.actor }}
short_sha = sys.argv[6]  # $(git rev-parse --short ${{ github.sha }})
commit_url = sys.argv[7]  # "${{ github.server_url }}/${{ github.repository }}/commit/${{ github.sha }}"
commit_message = sys.argv[8]  # $(git log -1 --pretty=format:'%s' ${{ github.sha }} | sed 's/"/\\"/g')
repo_name = sys.argv[9]  # ${{ github.repository }}
github_server_url = sys.argv[10]  # ${{ github.server_url }}

if sys.argv[11] == "True":
    test_status = "Passed"
    badge_emoji = "✅"
else:
    test_status = "Failed"
    badge_emoji = "❌"




driver = Driver(
    {"url": MATTERMOST_URL, "token": BOT_TOKEN, "scheme": "https", "port": 443}
)

driver.login()
bot_id = driver.users.get_user("me")["id"]
bot_username = driver.users.get_user("me")["username"]
team_id = driver.teams.get_team_by_name(TEAM_NAME)["id"]

channel = driver.channels.get_channel_by_name_and_team_name(TEAM_NAME, "bot-status")

print(f"Bot connected. Bot ID: {bot_id} | Team ID: {team_id}")

driver.posts.create_post(
    {
        "channel_id": channel["id"],
        "message": f"### {badge_emoji} **Unit Tests {test_status}!**\n"
        f"--- {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n\n"
        f"**Repository:** [{repo_name}]({github_server_url}/{repo_name})\n"
        f"**Branch:** {branch}\n"
        f"**Author:** {author}\n"
        f"**Commit:** [{short_sha}]({commit_url})\n"
        f"**Message:** {commit_message}\n"
        f"**Bot ID:** {bot_id}\n"
        f"**Bot Username:** {bot_username}\n"
        f"**Team ID:** {team_id}\n",
    }
)


driver.logout()
