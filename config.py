import os
import json
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0))
MENU_CSV_URL = os.getenv("MENU_CSV_URL")
ORDERS_SPREADSHEET_ID = os.getenv("ORDERS_SPREADSHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

if GOOGLE_CREDENTIALS_JSON:
    try:
        GOOGLE_CREDENTIALS_INFO = json.loads(GOOGLE_CREDENTIALS_JSON)
    except:
        GOOGLE_CREDENTIALS_INFO = None
else:
    GOOGLE_CREDENTIALS_INFO = None