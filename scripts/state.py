# Maps user_id to their active draft and timeout metadata
sessions = {}

# Tracks users who have already seen the welcome message
known_users = set()

# Global variables populated at startup
bot_info = {"bot_id": None, "team_id": None, "bot_username": None}
