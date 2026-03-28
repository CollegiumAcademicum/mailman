import sys

from mattermostdriver import Driver

MATTERMOST_URL = sys.argv[1]
BOT_TOKEN = sys.argv[2]
TEAM_NAME = sys.argv[3]
branch = sys.argv[4] # ${{ github.ref_name }}
author = sys.argv[5] # ${{ github.actor }}
short_sha = sys.argv[6] # $(git rev-parse --short ${{ github.sha }})
commit_url = sys.argv[7] # "${{ github.server_url }}/${{ github.repository }}/commit/${{ github.sha }}"
commit_message = sys.argv[8] # $(git log -1 --pretty=format:'%s' ${{ github.sha }} | sed 's/"/\\"/g')


driver = Driver(
    {"url": MATTERMOST_URL, "token": BOT_TOKEN, "scheme": "https", "port": 443}
)

driver.login()
bot_id = driver.users.get_user("me")["id"]
bot_username = driver.users.get_user("me")["username"]
team_id = driver.teams.get_team_by_name(TEAM_NAME)["id"]


print(f"Bot connected. Bot ID: {bot_id} | Team ID: {team_id}")

#(f"✅ **Unit Tests Passed!**\n"
 #f"**Repository:** [${{ github.repository }}](${{ github.server_url }}/${{ github.repository }})\n"
 #f"**Branch:** {branch}\n"
 #f"**Author:** {author}\n"
 #f"**Commit:** [{short_sha}]({commit_url})\n"
 #f"**Message:** {commit_message}")



driver.posts.create_post(
            {
                "channel_id": "14d9s71is3fh3duwj9a6u9k4jr",
                "message": "unit test completed"
                           f"✅ **Unit Tests Passed!**\n"
                           f"**Repository:** [${{ github.repository }}](${{ github.server_url }}/${{ github.repository }})\n"
                           f"**Branch:** {branch}\n"
                           f"**Author:** {author}\n"
                           f"**Commit:** [{short_sha}]({commit_url})\n"
                           f"**Message:** {commit_message}"
                ,
            }
        )


driver.logout()
