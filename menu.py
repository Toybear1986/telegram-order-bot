import requests
import csv
from io import StringIO

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
    except Exception as e:
        logger.exception(f"Ошибка при загрузке: {e}")
        return {}
    response = requests.get(url)
    response.raise_for_status()
    content = response.text
    # после получения content
    reader = csv.DictReader(StringIO(content))
    logger.info(f"Заголовки CSV: {reader.fieldnames}")
    first_row = next(reader)
    logger.info(f"Первая строка: {first_row}")
    reader = csv.DictReader(StringIO(content))
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
        
    return menu