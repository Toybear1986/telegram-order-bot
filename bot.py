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
 VIEW_CART, EDITING_CART, CHOOSING_EDIT_ACTION, ENTERING_NEW_QUANTITY, ENTERING_COMMENT) = range(9)

# Инициализация БД при старте
init_db()

async def get_menu():
    try:
        return load_menu_from_csv(config.MENU_CSV_URL)
    except Exception as e:
        logging.error(f"Ошибка загрузки меню: {e}")
        return {}

async def load_menu_and_build_index(context: ContextTypes.DEFAULT_TYPE):
    menu = await get_menu()
    if not menu:
        return None
    items_by_id = {}
    for cat, items in menu.items():
        for itm in items:
            if 'id' in itm:
                items_by_id[itm['id']] = (cat, itm)
    context.bot_data['menu'] = menu
    context.bot_data['items_by_id'] = items_by_id
    return menu

def format_items_list(items):
    lines = []
    for item in items:
        name = item['name']
        weight = item.get('weight', '')
        price = item.get('price', 0)
        desc = item.get('description', '')
        if len(desc) > 50:
            desc = desc[:50] + '…'
        line = f"• {name}"
        if weight:
            line += f" ({weight})"
        line += f" — {price}₽"
        if desc:
            line += f"\n  _{desc}_"
        lines.append(line)
    return "\n".join(lines)

def categories_keyboard(menu):
    buttons = []
    for category in menu.keys():
        buttons.append([InlineKeyboardButton(category, callback_data=f"cat_{category}")])
    return InlineKeyboardMarkup(buttons)

def items_keyboard(category, items, user_id):
    buttons = []
    for item in items:
        buttons.append([InlineKeyboardButton(item['name'], callback_data=f"item_{item['id']}")])
    # Кнопка "Назад в главное меню"
    back_button = [InlineKeyboardButton("◀ Назад в главное меню", callback_data="back_to_cats")]
    # Если корзина не пуста, добавляем кнопку "Перейти в корзину"
    if get_cart(user_id):
        buttons.append([InlineKeyboardButton("🛒 Перейти в корзину", callback_data="view_cart")])
    buttons.append(back_button)
    return InlineKeyboardMarkup(buttons)

def after_add_keyboard(category):
    buttons = [
        [InlineKeyboardButton(f"➕ Посмотреть еще раз {category}", callback_data=f"cat_{category}")],
        [InlineKeyboardButton("📋 В главное меню", callback_data="back_to_cats")],
        [InlineKeyboardButton("🛒 Перейти в корзину", callback_data="view_cart")]
    ]
    return InlineKeyboardMarkup(buttons)

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

def edit_item_keyboard(item_name):
    buttons = [
        [InlineKeyboardButton("❌ Удалить из заказа", callback_data=f"delete_{item_name}")],
        [InlineKeyboardButton("✏️ Изменить количество", callback_data=f"change_qty_{item_name}")],
        [InlineKeyboardButton("◀ Назад", callback_data="back_to_cart")]
    ]
    return InlineKeyboardMarkup(buttons)

# Предварительная клавиатура для подтверждения заказа
def pre_checkout_keyboard(has_comment):
    buttons = [
        [InlineKeyboardButton("✅ Подтвердить заказ", callback_data="confirm_order")],
        [InlineKeyboardButton("💬 Добавить комментарий", callback_data="add_comment")]
    ]
    # Если комментарий уже есть, можно показать его в тексте, но кнопка всё равно нужна для редактирования
    if has_comment:
        buttons.append([InlineKeyboardButton("✏️ Изменить комментарий", callback_data="add_comment")])
    buttons.append([InlineKeyboardButton("📋 В меню", callback_data="back_to_cats")])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu = context.bot_data.get('menu')
    if not menu:
        menu = await load_menu_and_build_index(context)
    if not menu:
        await update.message.reply_text("Меню временно недоступно. Попробуйте позже.")
        return ConversationHandler.END
    await update.message.reply_text(
        "Добро пожаловать в меню мероприятия \"Пар да Мёд\"! Выбирайте:",
        reply_markup=categories_keyboard(menu)
    )
    return CHOOSING_CATEGORY

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back_to_cats":
        menu = context.bot_data.get('menu')
        if not menu:
            menu = await load_menu_and_build_index(context)
        # Получаем базовую клавиатуру категорий
        base_markup = categories_keyboard(menu)
        # Извлекаем список кнопок (может быть кортежем, поэтому преобразуем в список)
        base_keyboard = list(base_markup.inline_keyboard)
        # Создаем копию, чтобы не изменять исходный объект
        new_buttons = base_keyboard.copy()
        # Проверяем корзину и добавляем кнопку "Перейти в корзину" при необходимости
        cart = get_cart(update.effective_user.id)
        if cart:
            new_buttons.append([InlineKeyboardButton("🛒 Перейти в корзину", callback_data="view_cart")])
        reply_markup = InlineKeyboardMarkup(new_buttons)
        await query.edit_message_text(
            "Выбирайте:",
            reply_markup=reply_markup
        )
        return CHOOSING_CATEGORY

    elif data.startswith("cat_"):
        category = data[4:]
        menu = context.bot_data.get('menu')
        if not menu:
            menu = await load_menu_and_build_index(context)
        items = menu.get(category, [])
        if not items:
            # Добавляем кнопку для возврата в главное меню
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📋 В главное меню", callback_data="back_to_cats")]])
            await query.edit_message_text(
                "Здесь пока ничего нет, но мы уже работаем над этим",
                reply_markup=keyboard
            )
            return CHOOSING_CATEGORY
        context.user_data['current_category'] = category
        items_text = format_items_list(items)
        text = f"*{category}*\n\n{items_text}\n\nЧто вас заинтересовало?"
        await query.edit_message_text(
            text, parse_mode='Markdown',
            reply_markup=items_keyboard(category, items, update.effective_user.id)
        )
        return CHOOSING_ITEM

    elif data.startswith("item_"):
        try:
            item_id = int(data.split('_')[1])
        except:
            await query.answer("Ошибка в данных кнопки", show_alert=True)
            return CHOOSING_CATEGORY

        items_by_id = context.bot_data.get('items_by_id')
        if not items_by_id:
            await load_menu_and_build_index(context)
            items_by_id = context.bot_data.get('items_by_id')
            if not items_by_id:
                await query.edit_message_text("Ошибка загрузки меню. Попробуйте позже.")
                return ConversationHandler.END

        if item_id in items_by_id:
            category, item = items_by_id[item_id]
            context.user_data['selected_category'] = category
            context.user_data['selected_item_obj'] = item

            text = f"*{item['name']}*\n"
            if item.get('weight'):
                text += f"Вес: {item['weight']}\n"
            text += f"Цена: {item['price']}₽\n\n"
            text += f"_{item.get('description', '')}_\n\n"
            text += "Сколько добавить в заказ? (введите число)"

            # Формируем клавиатуру: всегда есть кнопка "Назад к списку"
            back_button = InlineKeyboardButton("◀ Назад к списку", callback_data=f"cat_{category}")
            # Если корзина не пуста, добавляем кнопку "Перейти в корзину"
            cart = get_cart(update.effective_user.id)
            if cart:
                checkout_button = InlineKeyboardButton("🛒 Перейти в корзину", callback_data="view_cart")
                keyboard = InlineKeyboardMarkup([[back_button], [checkout_button]])
            else:
                keyboard = InlineKeyboardMarkup([[back_button]])

            await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
            logging.info(f"Переходим в состояние ENTERING_QUANTITY для user {update.effective_user.id}")
            return ENTERING_QUANTITY
        else:
            await query.answer("Товар не найден", show_alert=True)
            return CHOOSING_CATEGORY

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
        update_cart_quantity(user_id, item_name, 0)
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
        # Переходим к предварительному оформлению
        return await pre_checkout(update, context)

    elif data == "add_comment":
        await query.edit_message_text(
            "Введите ваш комментарий к заказу:"
        )
        return ENTERING_COMMENT

    elif data == "confirm_order":
        return await confirm_order(update, context)

    else:
        await query.edit_message_text("Неизвестная команда.")
        return ConversationHandler.END

async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает предварительный экран с корзиной и опцией добавления комментария."""
    query = update.callback_query
    user_id = update.effective_user.id
    cart = get_cart(user_id)
    if not cart:
        await query.edit_message_text("Корзина пуста. Добавьте товары.")
        return CHOOSING_CATEGORY

    total = sum(qty * price for _, qty, price in cart)
    lines = [f"{name} x{qty} — {qty*price}₽" for name, qty, price in cart]
    items_str = "\n".join(lines)

    # Проверяем, есть ли уже сохранённый комментарий
    comment = context.user_data.get('order_comment', '')
    comment_text = f"\n\n💬 Комментарий: {comment}" if comment else ""

    text = f"Ваш заказ:\n\n{items_str}\n\n*Итого: {total}₽*{comment_text}"

    has_comment = bool(comment)
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=pre_checkout_keyboard(has_comment)
    )
    # Остаёмся в состоянии VIEW_CART, чтобы потом можно было вернуться
    return VIEW_CART

async def comment_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает текст комментария и возвращается к предварительному оформлению."""
    comment = update.message.text
    context.user_data['order_comment'] = comment

    # Возвращаемся к предварительному экрану, создавая новый callback_query
    # Для этого эмулируем вызов pre_checkout с новым сообщением
    user_id = update.effective_user.id
    cart = get_cart(user_id)
    total = sum(qty * price for _, qty, price in cart)
    lines = [f"{name} x{qty} — {qty*price}₽" for name, qty, price in cart]
    items_str = "\n".join(lines)

    text = f"Ваш заказ:\n\n{items_str}\n\n*Итого: {total}₽*\n\n💬 Комментарий: {comment}"

    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=pre_checkout_keyboard(True)
    )
    return VIEW_CART

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Финальное подтверждение заказа – сохранение в БД и Google Sheets."""
    query = update.callback_query
    user_id = update.effective_user.id
    cart = get_cart(user_id)
    if not cart:
        await query.edit_message_text("Корзина пуста. Добавьте товары.")
        return CHOOSING_CATEGORY

    total = sum(qty * price for _, qty, price in cart)
    lines = [f"{name} x{qty} — {qty*price}₽" for name, qty, price in cart]
    items_str = "\n".join(lines)

    user = update.effective_user
    user_name = user.full_name or user.username or str(user.id)
    username = user.username or ""  # может быть None
    comment = context.user_data.get('order_comment', '')

    # Сохраняем в локальную БД
    order_id = save_order_to_db(user_id, user_name, items_str, total, comment)

    order_data = {
        "user_id": user_id,
        "user_name": user_name,
        "username": username,
        "items_str": items_str,
        "total_amount": total,
        "comment": comment
    }
    sheet_ok = append_order_to_sheet(order_data)

    # Очищаем корзину и временные данные
    clear_cart(user_id)
    context.user_data.pop('order_comment', None)

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

async def quantity_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"===== quantity_received вызвана =====")
    logging.info(f"Текст сообщения: {update.message.text}")
    logging.info(f"user_data: {context.user_data}")
    try:
        qty = int(update.message.text)
        if qty <= 0:
            raise ValueError
    except:
        await update.message.reply_text("Пожалуйста, введите положительное число.")
        return ENTERING_QUANTITY

    item_obj = context.user_data.get('selected_item_obj')
    if not item_obj:
        await update.message.reply_text("Ошибка: товар не найден. Начните заново.")
        return CHOOSING_CATEGORY
    
    logging.info(f"Всё ок, сейчас вызову add_to_cart для {item_name}")

    item_name = item_obj['name']
    price = item_obj['price']
    category = context.user_data.get('selected_category')

    user_id = update.effective_user.id
    # add_to_cart(user_id, item_name, qty, price)
    await update.message.reply_text(f"Тест: {item_name} x{qty}")

    keyboard = after_add_keyboard(category)
    await update.message.reply_text(
        f"Добавлено: {item_name} x{qty}",
        reply_markup=keyboard
    )
    return CONFIRM_ADD

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

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Действие отменено.")
    return ConversationHandler.END

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_CATEGORY: [CallbackQueryHandler(button_handler)],
            CHOOSING_ITEM: [CallbackQueryHandler(button_handler)],
            ENTERING_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quantity_received),
                CallbackQueryHandler(button_handler)
            ],
            CONFIRM_ADD: [CallbackQueryHandler(button_handler)],
            VIEW_CART: [CallbackQueryHandler(button_handler)],
            EDITING_CART: [CallbackQueryHandler(button_handler)],
            ENTERING_NEW_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_quantity_received)],
            ENTERING_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, comment_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    # application.add_handler(CallbackQueryHandler(button_handler))

    logging.basicConfig(level=logging.INFO)
    application.run_polling()

if __name__ == "__main__":
    main()