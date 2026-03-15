import requests
import csv
from io import StringIO

def load_menu_from_csv(url):
    response = requests.get(url)
    response.raise_for_status()
    content = response.text
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