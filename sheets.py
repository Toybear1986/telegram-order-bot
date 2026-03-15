import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import GOOGLE_CREDENTIALS_INFO, ORDERS_SPREADSHEET_ID
from datetime import datetime
import logging

# Настраиваем логгер для этого модуля
logger = logging.getLogger(__name__)

def append_order_to_sheet(order_data):
    """
    order_data: dict with keys:
        user_id, user_name, items_str, total_amount, comment
    """
    logger.info("=== Попытка записи заказа в Google Sheets ===")
    logger.info(f"Полученные данные: {order_data}")

    # Проверка наличия credentials и ID таблицы
    if not GOOGLE_CREDENTIALS_INFO:
        logger.error("❌ GOOGLE_CREDENTIALS_INFO отсутствует или равен None")
        return False
    if not ORDERS_SPREADSHEET_ID:
        logger.error("❌ ORDERS_SPREADSHEET_ID отсутствует")
        return False

    logger.info("✅ GOOGLE_CREDENTIALS_INFO и ORDERS_SPREADSHEET_ID присутствуют")

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

    try:
        # Авторизация
        logger.info("Попытка авторизации через сервисный аккаунт...")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_CREDENTIALS_INFO, scope)
        client = gspread.authorize(creds)
        logger.info("✅ Авторизация успешна")

        # Открытие таблицы
        logger.info(f"Открываем таблицу с ID: {ORDERS_SPREADSHEET_ID}")
        sheet = client.open_by_key(ORDERS_SPREADSHEET_ID).sheet1
        logger.info("✅ Таблица открыта, выбран первый лист")

        # Подготовка строки
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            order_data["user_id"],
            order_data["user_name"],
            order_data["items_str"],
            order_data["total_amount"],
            order_data["comment"],
            "новый"
        ]
        logger.info(f"Подготовлена строка для записи: {row}")

        # Запись
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