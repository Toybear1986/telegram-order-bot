import sqlite3
import logging

logger = logging.getLogger(__name__)

DB_NAME = 'orders.db'

def init_db():
    """Создаёт таблицы, если их нет"""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    # Таблица для хранения оформленных заказов (история)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            items TEXT,
            total_amount INTEGER,
            comment TEXT,
            status TEXT DEFAULT 'новый',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Таблица для временной корзины пользователя
    cur.execute('''
        CREATE TABLE IF NOT EXISTS cart (
            user_id INTEGER,
            item_name TEXT,
            quantity INTEGER,
            price INTEGER,
            PRIMARY KEY (user_id, item_name)
        )
    ''')
    conn.commit()
    conn.close()

# ===== Работа с корзиной =====
def add_to_cart(user_id, item_name, quantity, price):
    logger.info(f"Добавление в корзину: user={user_id}, item={item_name}, qty={quantity}, price={price}")
    """Добавляет позицию в корзину или увеличивает количество, если уже есть"""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO cart (user_id, item_name, quantity, price)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, item_name) 
        DO UPDATE SET quantity = quantity + excluded.quantity
    ''', (user_id, item_name, quantity, price))
    conn.commit()
    conn.close()

def get_cart(user_id):
    """Возвращает список кортежей (item_name, quantity, price) для пользователя"""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('SELECT item_name, quantity, price FROM cart WHERE user_id = ?', (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def update_cart_quantity(user_id, item_name, new_quantity):
    """Обновляет количество позиции (если new_quantity <= 0 – удаляет)"""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if new_quantity <= 0:
        cur.execute('DELETE FROM cart WHERE user_id = ? AND item_name = ?', (user_id, item_name))
    else:
        cur.execute('UPDATE cart SET quantity = ? WHERE user_id = ? AND item_name = ?',
                    (new_quantity, user_id, item_name))
    conn.commit()
    conn.close()

def clear_cart(user_id):
    """Полностью очищает корзину пользователя"""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('DELETE FROM cart WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# ===== Сохранение заказа =====
def save_order_to_db(user_id, user_name, items_str, total_amount, comment):
    """Сохраняет оформленный заказ в таблицу orders и возвращает его id"""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO orders (user_id, user_name, items, total_amount, comment)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, user_name, items_str, total_amount, comment))
    order_id = cur.lastrowid
    conn.commit()
    conn.close()
    return order_id