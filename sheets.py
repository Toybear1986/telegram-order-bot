import gspread
from config import GOOGLE_CREDENTIALS_INFO, ORDERS_SPREADSHEET_ID, MENU_SPREADSHEET_ID
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger(__name__)

def append_order_to_sheet(order_data):
    """
    order_data: dict with keys:
        order_id, user_id, user_name, username, items_str, total_amount, comment
    """
    logger.info("=== Попытка записи заказа в Google Sheets ===")
    logger.info(f"Полученные данные: {order_data}")

    if not GOOGLE_CREDENTIALS_INFO or not ORDERS_SPREADSHEET_ID:
        logger.error("❌ GOOGLE_CREDENTIALS_INFO отсутствует или равен None")
        return False

    try:
        client = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_INFO)
        logger.info("✅ Авторизация через service_account_from_dict успешна")

        sheet = client.open_by_key(ORDERS_SPREADSHEET_ID).sheet1
        logger.info("✅ Таблица открыта, выбран первый лист")

        # Используем московское время
        moscow_tz = ZoneInfo("Europe/Moscow")
        current_time = datetime.now(moscow_tz).strftime("%Y-%m-%d %H:%M:%S")

        row = [
            current_time,                     # A: Дата
            order_data["order_id"],            # B: Номер заказа
            order_data["user_id"],             # C: ID пользователя
            order_data["user_name"],           # D: Имя
            order_data.get("username", ""),    # E: Username
            order_data["items_str"],           # F: Состав заказа
            order_data["total_amount"],        # G: Сумма
            order_data["comment"],             # H: Комментарий
            "новый"                            # I: Статус
        ]
        logger.info(f"Подготовлена строка для записи: {row}")

        sheet.append_row(row)
        logger.info("✅ Заказ успешно записан в Google Sheets")
        return True

    except Exception as e:
        logger.exception(f"❌ Ошибка при записи в Google Sheets: {e}")
        return False

def update_order_status(order_id: int, new_status: str, updated_by: str):
    try:
        client = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_INFO)
        sheet = client.open_by_key(ORDERS_SPREADSHEET_ID).sheet1

        # Ищем ячейку с order_id во второй колонке (B)
        cell = sheet.find(str(order_id), in_column=2)  # колонка B
        if not cell:
            logger.error(f"Заказ №{order_id} не найден")
            return False

        # Определяем индексы колонок по заголовкам
        headers = sheet.row_values(1)
        try:
            status_col = headers.index("Статус") + 1
            updated_by_col = headers.index("status_updated_by") + 1
            updated_at_col = headers.index("status_updated_at") + 1
        except ValueError as e:
            logger.error(f"Не найдены необходимые колонки: {e}")
            return False

        moscow_tz = ZoneInfo("Europe/Moscow")
        now = datetime.now(moscow_tz).strftime("%Y-%m-%d %H:%M:%S")
        sheet.update_cell(cell.row, status_col, new_status)
        sheet.update_cell(cell.row, updated_by_col, updated_by)
        sheet.update_cell(cell.row, updated_at_col, now)
        logger.info(f"Заказ №{order_id} обновлён: статус={new_status}, кем={updated_by}")
        return True
    except Exception as e:
        logger.exception(f"Ошибка обновления статуса заказа №{order_id}: {e}")
        return False

def get_orders_by_status(status: str):
    """Возвращает список заказов с заданным статусом."""
    try:
        client = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_INFO)
        sheet = client.open_by_key(ORDERS_SPREADSHEET_ID).sheet1
        records = sheet.get_all_records()
        # Фильтруем по статусу (предполагаем, что колонка называется "Статус")
        filtered = [rec for rec in records if rec.get("Статус") == status]
        # Возвращаем список словарей (каждый содержит все поля)
        return filtered
    except Exception as e:
        logger.exception(f"Ошибка получения заказов по статусу {status}: {e}")
        return []

def increment_tip_sent(order_id: int) -> int:
    """Увеличивает счётчик отправленных фраз о чаевых, возвращает новый номер (1-based)."""
    try:
        client = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_INFO)
        sheet = client.open_by_key(ORDERS_SPREADSHEET_ID).sheet1
        headers = sheet.row_values(1)
        try:
            tip_col = headers.index("tip_sent") + 1
        except ValueError:
            logger.error("Колонка tip_sent не найдена")
            return 0

        cell = sheet.find(str(order_id), in_column=2) # ИСПРАВЛЕНО
        if not cell:
            return 0

        current = int(sheet.cell(cell.row, tip_col).value or 0)
        new_val = current + 1
        sheet.update_cell(cell.row, tip_col, new_val)
        return new_val
    except Exception as e:
        logger.exception(f"Ошибка обновления tip_sent для заказа {order_id}: {e}")
        return 0

def update_item_availability(item_id: int, status: str):
    """
    Устанавливает статус доступности товара в таблице меню.
    status: "Да" или "Нет"
    """
    if not GOOGLE_CREDENTIALS_INFO or not MENU_SPREADSHEET_ID:
        logger.error("❌ Нет credentials или ID таблицы меню")
        return False

    try:
        client = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_INFO)
        # Открываем таблицу меню по её ID
        sheet = client.open_by_key(MENU_SPREADSHEET_ID).sheet1

        # Получаем заголовки, чтобы найти колонку "Доступно"
        headers = sheet.row_values(1)
        try:
            col_index = headers.index("Доступно") + 1  # +1 для gspread (индексация с 1)
        except ValueError:
            logger.error("❌ Не найдена колонка 'Доступно' в таблице меню")
            return False

        # Ищем ячейку с ID (предполагаем, что ID в первой колонке)
        cell = sheet.find(str(item_id))
        if not cell:
            logger.error(f"❌ Товар с ID {item_id} не найден в таблице меню")
            return False

        # Обновляем ячейку в той же строке, в колонке "Доступно"
        sheet.update_cell(cell.row, col_index, status)
        logger.info(f"✅ Статус товара ID {item_id} изменён на {status}")
        return True
    except Exception as e:
        logger.exception(f"❌ Ошибка при обновлении доступности: {e}")
        return False