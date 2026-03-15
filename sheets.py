import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import GOOGLE_CREDENTIALS_INFO, ORDERS_SPREADSHEET_ID
from datetime import datetime

def append_order_to_sheet(order_data):
    """
    order_data: dict with keys:
        user_id, user_name, items_str, total_amount, comment
    """
    if not GOOGLE_CREDENTIALS_INFO or not ORDERS_SPREADSHEET_ID:
        print("Google Sheets credentials or spreadsheet ID missing")
        return False

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_CREDENTIALS_INFO, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(ORDERS_SPREADSHEET_ID).sheet1

    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        order_data["user_id"],
        order_data["user_name"],
        order_data["items_str"],
        order_data["total_amount"],
        order_data["comment"],
        "новый"
    ]
    sheet.append_row(row)
    return True