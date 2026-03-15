import os
import logging
import sqlite3
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("ЗАПУСК НОВОЙ ВЕРСИИ БОТА")

# ===== НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", 0))

# Проверка наличия токена
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в переменных окружения")
if not ADMIN_CHAT_ID:
    raise ValueError("ADMIN_CHAT_ID не задан в переменных окружения")

# Состояния для разговора (FSM)
NAME, ITEMS, QUANTITY, COMMENT = range(4)

# Клавиатура главного меню
main_keyboard = ReplyKeyboardMarkup([["📝 Сделать заказ"]], resize_keyboard=True)

# ===== ЛОГИРОВАНИЕ =====
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== БАЗА ДАННЫХ SQLite =====
def init_db():
    conn = sqlite3.connect("orders.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            items TEXT,
            quantity INTEGER,
            comment TEXT,
            payment TEXT,
            status TEXT DEFAULT 'новый',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_order(user_id, user_name, items, quantity, comment):
    conn = sqlite3.connect("orders.db")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders (user_id, user_name, items, quantity, comment, payment)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, user_name, items, quantity, comment, "наличные"))
    order_id = cur.lastrowid
    conn.commit()
    conn.close()
    return order_id

# ===== ОБРАБОТЧИКИ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать! Я бот для приёма заказов.\nНажмите кнопку ниже, чтобы начать.",
        reply_markup=main_keyboard
    )
    return ConversationHandler.END

async def make_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите ваше имя и фамилию:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Введите позиции заказа (например: Пицца Маргарита, Лазанья):")
    return ITEMS

async def get_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["items"] = update.message.text
    await update.message.reply_text("Введите количество порций (число):")
    return QUANTITY

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
        await update.message.reply_text("Пожалуйста, введите число.")
        return QUANTITY
    context.user_data["quantity"] = int(update.message.text)
    await update.message.reply_text("Есть комментарии к заказу? (если нет, отправьте 'нет')")
    return COMMENT

async def get_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text if update.message.text.lower() != "нет" else ""

    # Сохраняем в базу
    order_id = save_order(
        update.effective_user.id,
        context.user_data["name"],
        context.user_data["items"],
        context.user_data["quantity"],
        comment
    )

    # Уведомление администратору
    staff_msg = (
        f"🆕 НОВЫЙ ЗАКАЗ #{order_id}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👤 От: {context.user_data['name']}\n"
        f"📋 Позиции: {context.user_data['items']}\n"
        f"🔢 Количество: {context.user_data['quantity']}\n"
        f"💬 Комментарий: {comment or '—'}\n"
        f"💰 Оплата: наличные\n"
        f"━━━━━━━━━━━━━━━━"
    )
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=staff_msg)

    # Ответ пользователю
    await update.message.reply_text(
        f"✅ Заказ принят!\nНомер вашего заказа: #{order_id}\nСпасибо! Оплата наличными при получении.",
        reply_markup=main_keyboard
    )

    # Очищаем данные
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Заказ отменён.", reply_markup=main_keyboard)
    context.user_data.clear()
    return ConversationHandler.END

# ===== ЗАПУСК =====
def main():
    # Инициализация БД
    init_db()
    logger.info("База данных инициализирована")

    # Создаём приложение
    app = Application.builder().token(BOT_TOKEN).build()

    # Диалог заказа
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 Сделать заказ$"), make_order)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ITEMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_items)],
            QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity)],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_comment)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    # Запускаем бота (polling)
    logger.info("Бот запускается...")
    app.run_polling()

if __name__ == "__main__":
    main()