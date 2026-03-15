import gspread
from config import GOOGLE_CREDENTIALS_INFO, ORDERS_SPREADSHEET_ID
from datetime import datetime
from zoneinfo import ZoneInfo  # для Python 3.9+
import logging

logger = logging.getLogger(__name__)

def append_order_to_sheet(order_data):
    """
    order_data: dict with keys:
        user_id, user_name, username, items_str, total_amount, comment
    """
    logger.info("=== Попытка записи заказа в Google Sheets ===")
    logger.info(f"Полученные данные: {order_data}")

    if not GOOGLE_CREDENTIALS_INFO:
        logger.error("❌ GOOGLE_CREDENTIALS_INFO отсутствует или равен None")
        return False
    if not ORDERS_SPREADSHEET_ID:
        logger.error("❌ ORDERS_SPREADSHEET_ID отсутствует")
        return False

    try:
        client = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_INFO)
        logger.info("✅ Авторизация через service_account_from_dict успешна")

        sheet = client.open_by_key(ORDERS_SPREADSHEET_ID).sheet1
        logger.info("✅ Таблица открыта, выбран первый лист")

        # Используем московское время (UTC+3)
        moscow_tz = ZoneInfo("Europe/Moscow")
        current_time = datetime.now(moscow_tz).strftime("%Y-%m-%d %H:%M:%S")

        row = [
            current_time,
            order_data["user_id"],
            order_data["user_name"],
            order_data.get("username", ""),
            order_data["items_str"],
            order_data["total_amount"],
            order_data["comment"],
            "новый"
        ]
        logger.info(f"Подготовлена строка для записи: {row}")

        sheet.append_row(row)
        logger.info("✅ Заказ успешно записан в Google Sheets")
        return True

    except gspread.exceptions.SpreadsheetNotFound:
        logger.error("❌ Таблица с указанным ID не найдена. Проверьте ORDERS_SPREADSHEET_ID")
        return False
    except gspread.exceptions.APIError as e:
        logger.error(f"❌ Ошибка API Google Sheets: {e}")
        return False
    except Exception as e:
        logger.exception("❌ Непредвиденная ошибка при записи в Google Sheets")
        return False