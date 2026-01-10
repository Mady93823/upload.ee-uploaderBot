import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
except ValueError:
    ADMIN_ID = 0
    CHANNEL_ID = 0

MONGO_URI = os.getenv("MONGO_URI")
JOIN_CHANNELS = os.getenv("JOIN_CHANNELS", "")
FORCE_SUB_CHANNELS = [int(x) for x in JOIN_CHANNELS.split() if x.strip().lstrip('-').isdigit()]

# Toggles
MONITOR_ACTIVE = True
MAINTENANCE_MODE = False
FORCE_SUB_ACTIVE = True

# RSS Stats
RSS_STATS = {
    "last_check": "Never",
    "total_found": 0,
    "total_processed": 0
}
