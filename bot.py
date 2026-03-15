import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from config import BOT_TOKEN, ADMIN_CHAT_ID
from database import init_db, add_to_cart, get_cart, update_cart_quantity, clear_cart, save_order_to_db
from menu import load_menu_from_csv
from sheets import append_order_to_sheet
import config

# Состояния для FSM
(CHOOSING_CATEGORY, CHOOSING_ITEM, ENTERING_QUANTITY, CONFIRM_ADD,
 VIEW_CART, EDITING_CART, CHOOSING_EDIT_ACTION, ENTERING_NEW_QUANTITY) = range(8)

# Инициализация БД при старте
init_db()

# Загружаем меню (можно кешировать, но при каждом запросе лучше перезагружать для актуальности)
async def get_menu():
    try:
        return load_menu_from_csv(config.MENU_CSV_URL)
    except Exception as e:
        logging.error(f"Ошибка загрузки меню: {e}")
        return {}

# Клавиатура категорий
def categories_keyboard(menu):
    buttons = []
    for category in menu.keys():
        buttons.append([InlineKeyboardButton(category, callback_data=f"cat_{category}")])
    return InlineKeyboardMarkup(buttons)

# Клавиатура товаров в категории
def items_keyboard(category, items):
    buttons = []
    for item in items:
        buttons.append([InlineKeyboardButton(item['name'], callback_data=f"item_{category}_{item['name']}")])
    buttons.append([InlineKeyboardButton("◀ Назад к категориям", callback_data="back_to_cats")])
    return InlineKeyboardMarkup(buttons)

# Клавиатура для действий после добавления в корзину
def after_add_keyboard(category):
    buttons = [
        [InlineKeyboardButton(f"➕ Ещё из {category}", callback_data=f"cat_{category}")],
        [InlineKeyboardButton("📋 Посмотреть меню", callback_data="back_to_cats")],
        [InlineKeyboardButton("🛒 Сделать/завершить заказ", callback_data="view_cart")]
    ]
    return InlineKeyboardMarkup(buttons)

# Клавиатура корзины
def cart_keyboard(user_id):
    cart = get_cart(user_id)
    if not cart:
        return None
    buttons = []
    for item_name, qty, price in cart:
        buttons.append([InlineKeyboardButton(f"{item_name} x{qty} — {qty*price}₽", callback_data=f"edit_{item_name}")])
    buttons.append([InlineKeyboardButton("✅ Заказать", callback_data="checkout")])
    buttons.append([InlineKeyboardButton("📋 В меню", callback_data="back_to_cats")])
    buttons.append([InlineKeyboardButton("✏️ Редактировать заказ", callback_data="edit_cart")])
    return InlineKeyboardMarkup(buttons)

# Клавиатура редактирования позиции
def edit_item_keyboard(item_name):
    buttons = [
        [InlineKeyboardButton("❌ Удалить из заказа", callback_data=f"delete_{item_name}")],
        [InlineKeyboardButton("✏️ Изменить количество", callback_data=f"change_qty_{item_name}")],
        [InlineKeyboardButton("◀ Назад", callback_data="back_to_cart")]
    ]
    return InlineKeyboardMarkup(buttons)

# Старт
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu = await get_menu()
    if not menu:
        await update.message.reply_text("Меню временно недоступно. Попробуйте позже.")
        return ConversationHandler.END
    context.user_data['menu'] = menu
    await update.message.reply_text(
        "Добро пожаловать! Выберите категорию:",
        reply_markup=categories_keyboard(menu)
    )
    return CHOOSING_CATEGORY

# Обработка нажатий на кнопки (callback_query)
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back_to_cats":
        menu = await get_menu()
        await query.edit_message_text(
            "Выберите категорию:",
            reply_markup=categories_keyboard(menu)
        )
        return CHOOSING_CATEGORY

    elif data.startswith("cat_"):
        category = data[4:]
        menu = context.user_data.get('menu')
        if not menu or category not in menu:
            menu = await get_menu()
            context.user_data['menu'] = menu
        items = menu.get(category, [])
        if not items:
            await query.edit_message_text("В этой категории пока нет доступных позиций.")
            return CHOOSING_CATEGORY
        context.user_data['current_category'] = category
        text = f"*{category}*\n\nВыберите позицию:"
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=items_keyboard(category, items)
        )
        return CHOOSING_ITEM

    elif data.startswith("item_"):
        parts = data.split('_', 2)
        category = parts[1]
        item_name = parts[2]
        context.user_data['selected_category'] = category
        context.user_data['selected_item'] = item_name
        # Запросить количество
        await query.edit_message_text(
            f"Сколько *{item_name}* добавить в заказ? (введите число)",
            parse_mode='Markdown'
        )
        return ENTERING_QUANTITY

    elif data == "view_cart":
        return await show_cart(update, context)

    elif data == "edit_cart":
        return await show_cart_for_edit(update, context)

    elif data.startswith("edit_"):
        item_name = data[5:]
        context.user_data['editing_item'] = item_name
        await query.edit_message_text(
            f"Редактирование *{item_name}*",
            parse_mode='Markdown',
            reply_markup=edit_item_keyboard(item_name)
        )
        return EDITING_CART

    elif data.startswith("delete_"):
        item_name = data[7:]
        user_id = update.effective_user.id
        update_cart_quantity(user_id, item_name, 0)  # удалить
        await query.answer(f"{item_name} удалён")
        return await show_cart(update, context)

    elif data.startswith("change_qty_"):
        item_name = data[11:]
        context.user_data['editing_item'] = item_name
        await query.edit_message_text(
            f"Введите новое количество для *{item_name}*:",
            parse_mode='Markdown'
        )
        return ENTERING_NEW_QUANTITY

    elif data == "back_to_cart":
        return await show_cart(update, context)

    elif data == "checkout":
        return await checkout(update, context)

    else:
        await query.edit_message_text("Неизвестная команда.")
        return ConversationHandler.END

# Показать корзину
async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    cart = get_cart(user_id)
    if not cart:
        await query.edit_message_text(
            "Ваша корзина пуста.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 В меню", callback_data="back_to_cats")]])
        )
        return CHOOSING_CATEGORY
    total = sum(qty * price for _, qty, price in cart)
    lines = [f"{name} x{qty} — {qty*price}₽" for name, qty, price in cart]
    text = "Ваш заказ:\n\n" + "\n".join(lines) + f"\n\n*Итого: {total}₽*"
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=cart_keyboard(user_id)
    )
    return VIEW_CART

# Показать корзину для редактирования (то же, но с акцентом)
async def show_cart_for_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    cart = get_cart(user_id)
    if not cart:
        await query.edit_message_text(
            "Корзина пуста.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 В меню", callback_data="back_to_cats")]])
        )
        return CHOOSING_CATEGORY
    total = sum(qty * price for _, qty, price in cart)
    lines = [f"{name} x{qty} — {qty*price}₽" for name, qty, price in cart]
    text = "Ваш заказ:\n\n" + "\n".join(lines) + f"\n\n*Итого: {total}₽*\n\nВыберите позицию для редактирования:"
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=cart_keyboard(user_id)
    )
    return VIEW_CART

# Обработка ввода количества (первый раз)
async def quantity_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text)
        if qty <= 0:
            raise ValueError
    except:
        await update.message.reply_text("Пожалуйста, введите положительное число.")
        return ENTERING_QUANTITY

    category = context.user_data.get('selected_category')
    item_name = context.user_data.get('selected_item')
    menu = context.user_data.get('menu')
    if not menu or category not in menu:
        menu = await get_menu()
        context.user_data['menu'] = menu

    # Найти цену товара
    price = None
    for item in menu.get(category, []):
        if item['name'] == item_name:
            price = item['price']
            break
    if price is None:
        await update.message.reply_text("Ошибка: товар не найден.")
        return CHOOSING_CATEGORY

    user_id = update.effective_user.id
    add_to_cart(user_id, item_name, qty, price)

    # Предложить дальнейшие действия
    keyboard = after_add_keyboard(category)
    await update.message.reply_text(
        f"Добавлено: {item_name} x{qty}",
        reply_markup=keyboard
    )
    return CONFIRM_ADD

# Обработка ввода нового количества при редактировании
async def new_quantity_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text)
        if qty < 0:
            raise ValueError
    except:
        await update.message.reply_text("Пожалуйста, введите неотрицательное число (0 для удаления).")
        return ENTERING_NEW_QUANTITY

    item_name = context.user_data.get('editing_item')
    user_id = update.effective_user.id
    update_cart_quantity(user_id, item_name, qty)

    if qty == 0:
        await update.message.reply_text(f"{item_name} удалён из заказа.")
    else:
        await update.message.reply_text(f"Количество {item_name} изменено на {qty}.")

    # Показываем обновлённую корзину
    return await show_cart_after_edit(update, context)

async def show_cart_after_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cart = get_cart(user_id)
    if not cart:
        await update.message.reply_text(
            "Корзина пуста.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 В меню", callback_data="back_to_cats")]])
        )
        return CHOOSING_CATEGORY
    total = sum(qty * price for _, qty, price in cart)
    lines = [f"{name} x{qty} — {qty*price}₽" for name, qty, price in cart]
    text = "Ваш заказ:\n\n" + "\n".join(lines) + f"\n\n*Итого: {total}₽*"
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=cart_keyboard(user_id)
    )
    return VIEW_CART

# Оформление заказа
async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    cart = get_cart(user_id)
    if not cart:
        await query.edit_message_text("Корзина пуста. Добавьте товары.")
        return CHOOSING_CATEGORY

    total = sum(qty * price for _, qty, price in cart)
    lines = [f"{name} x{qty} — {qty*price}₽" for name, qty, price in cart]
    items_str = "\n".join(lines)

    # Сохраняем в локальную БД
    user = update.effective_user
    user_name = user.full_name or user.username or str(user.id)
    order_id = save_order_to_db(user_id, user_name, items_str, total, "")

    # Сохраняем в Google Sheets
    order_data = {
        "user_id": user_id,
        "user_name": user_name,
        "items_str": items_str,
        "total_amount": total,
        "comment": ""
    }
    sheet_ok = append_order_to_sheet(order_data)

    # Очищаем корзину
    clear_cart(user_id)

    if sheet_ok:
        await query.edit_message_text(
            f"✅ Заказ №{order_id} оформлен!\n\n{items_str}\n\nИтого: {total}₽\n\nСпасибо! Оплата наличными при получении.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Новый заказ", callback_data="back_to_cats")]])
        )
    else:
        await query.edit_message_text(
            f"⚠️ Заказ №{order_id} сохранён локально, но возникла проблема с записью в Google Sheets. Мы уже работаем над этим.\n\n{items_str}\n\nИтого: {total}₽",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 В меню", callback_data="back_to_cats")]])
        )
    return ConversationHandler.END

# Отмена
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Действие отменено.")
    return ConversationHandler.END

# Основная функция запуска
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_CATEGORY: [CallbackQueryHandler(button_handler)],
            CHOOSING_ITEM: [CallbackQueryHandler(button_handler)],
            ENTERING_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, quantity_received)],
            CONFIRM_ADD: [CallbackQueryHandler(button_handler)],
            VIEW_CART: [CallbackQueryHandler(button_handler)],
            EDITING_CART: [CallbackQueryHandler(button_handler)],
            ENTERING_NEW_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_quantity_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    # Добавляем обработчик для кнопок, которые могут прийти вне состояний (например, после /start)
    application.add_handler(CallbackQueryHandler(button_handler))

    logging.basicConfig(level=logging.INFO)
    application.run_polling()

if __name__ == "__main__":
    main()