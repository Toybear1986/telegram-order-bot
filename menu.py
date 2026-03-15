import logging
import requests
import csv
from io import StringIO

logger = logging.getLogger(__name__)

def load_menu_from_csv(url):
    logger.info(f"Загрузка меню из {url}")
    try:
        response = requests.get(url, timeout=10)
        logger.info(f"Статус ответа: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"Ошибка HTTP {response.status_code}")
            return {}
        content = response.text
        logger.info(f"Длина содержимого: {len(content)} байт")
        logger.info(f"Первые 200 символов: {content[:200]}")
        
        reader = csv.DictReader(StringIO(content))
        logger.info(f"Заголовки CSV: {reader.fieldnames}")
        
        menu = {}
        for row in reader:
            category = row.get('Категория', '').strip()
            if not category:
                continue
            if category not in menu:
                menu[category] = []
            try:
                price = float(row.get('Цена', 0))
            except:
                price = 0
            item = {
                'name': row.get('Название', '').strip(),
                'description': row.get('Описание', '').strip(),
                'weight': row.get('Вес', '').strip(),
                'price': price,
                'available': row.get('Доступно', 'Да').strip().lower() == 'да'
            }
            if item['available'] and item['name']:
                menu[category].append(item)
        logger.info(f"Загружено категорий: {len(menu)}")
        return menu
    except Exception as e:
        logger.exception(f"Ошибка при загрузке меню: {e}")
        return {}