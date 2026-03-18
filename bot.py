import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from config import BOT_TOKEN, ADMIN_CHAT_ID, GROUP_CHAT_ID
from database import init_db, add_to_cart, get_cart, update_cart_quantity, clear_cart, save_order_to_db
from menu import load_menu_from_csv
from sheets import append_order_to_sheet, update_item_availability
import config

# Список фраз о чаевых
TIP_MESSAGES = [
    "Благодарность не знает обязательств, она живёт в сердце. Вознаграждение за труд — всегда на ваше усмотрение.",
    "Ваше спасибо для нас уже награда. Всё, что сверху — исключительно от чистого сердца и по вашему желанию.",
    "Для нас главное, чтобы вы ушли с улыбкой. Чаевые — это лишь вопрос вашей доброй воли и щедрости души.",
    "Чаевые не обязательны, но всегда приятны. Решение остаётся за вами.",
    "Вознаграждение персоналу — это не долг, а право гостя.",
    "Чай — исключительно по велению души, а не по обязанности.",
    "Наша работа — это знак внимания к вам. Ваши чаевые — знак внимания к нам, и они ценны лишь тогда, когда искренни.",
    "В счёт включена только наша забота. Ваша благодарность не имеет цены и остаётся на ваше усмотрение.",
    "Благодарность не терпит принуждения.",
    "Искренность не знает тарифов. Всё исключительно на ваше усмотрение."
]

# Функция проверки прав (staff)
def is_staff(user_id: int) -> bool:
    staff_ids = [int(id.strip()) for id in config.STAFF_IDS.split(",") if id.strip()]
    return user_id in staff_ids

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
    logging.info("load_menu_and_build_index: started")
    menu = await get_menu()
    if not menu:
        logging.error("load_menu_and_build_index: get_menu returned empty or None")
        return None
    logging.info(f"load_menu_and_build_index: got menu with {len(menu)} categories")

    all_items_by_id = {}
    available_menu = {}

    for cat, items in menu.items():
        logging.info(f"Processing category '{cat}' with {len(items)} items")
        available_items = []
        for itm in items:
            if 'id' in itm:
                all_items_by_id[itm['id']] = (cat, itm)
                logging.debug(f"Item ID {itm['id']}: {itm['name']}, available={itm.get('available')}")
            if itm.get('available', False):
                available_items.append(itm)
        if available_items:
            available_menu[cat] = available_items

    context.bot_data['menu'] = available_menu
    context.bot_data['items_by_id'] = all_items_by_id
    logging.info(f"load_menu_and_build_index: built index with {len(all_items_by_id)} items, available categories: {len(available_menu)}")
    return available_menu

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
    logging.info(f"start called by user {update.effective_user.id}")
    try:
        menu = context.bot_data.get('menu')
        if not menu:
            menu = await load_menu_and_build_index(context)
        if not menu:
            await update.message.reply_text("Меню временно недоступно. Попробуйте позже.")
            return ConversationHandler.END
        welcome_text = (
        "Добро пожаловать в бот заказов «Пар да Мёд»!\n\n"
        "Здесь вы можете быстро и удобно выбрать любимые блюда и напитки, чтобы не ждать официанта и не толпиться у бара. Всё просто и весело!\n\n"
        "<b>Что умеет бот?</b>\n"
        "• 📜 Показывает всё наше меню с описаниями и ценами.\n"
        "• 🛒 Позволяет собрать корзину из нескольких позиций.\n"
        "• 💬 Добавить комментарий к заказу (например, «без лука» или «побольше остроты»).\n"
        "• ✅ Оформить заказ в один клик.\n\n"
        "<b>Как сделать заказ?</b>\n\n"
        "1. Выберите категорию (например, «Бургеры» или «Коктейли»).\n"
        "2. Тапайте на понравившиеся позиции, указывайте количество.\n"
        "3. Когда всё готово – загляните в корзину и нажмите «Заказать».\n"
        "4. По желанию оставьте комментарий.\n"
        "5. Готово! Ваш заказ уже у персонала, а вы получаете подтверждение.\n\n"
        "<b>Выберите категорию:</b>"
    )
        await update.message.reply_text(
            welcome_text,
            parse_mode='HTML',
            reply_markup=categories_keyboard(menu)
        )
        return CHOOSING_CATEGORY
    except Exception as e:
        logging.exception(f"Error in start: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")
        return ConversationHandler.END

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    logging.info(f"BUTTON_HANDLER: data={data}, user={update.effective_user.id}")
    await query.answer()

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
            
            cart = get_cart(update.effective_user.id)

            text = f"*{item['name']}*\n"
            if item.get('weight'):
                text += f"Вес: {item['weight']}\n"
            text += f"Цена: {item['price']}₽\n\n"
            text += f"_{item.get('description', '')}_\n\n"
            text += "Сколько добавить в заказ? (введите число)"

            # Формируем список кнопок
            buttons = [[InlineKeyboardButton("◀ Назад к списку", callback_data=f"cat_{category}")]]

            # Если в описании есть фраза про акции, добавляем кнопку "Акции"
            if "Обратите так же внимание на выгодные акции" in item.get('description', ''):
                buttons.append([InlineKeyboardButton("🔥 Акции", callback_data="cat_Акции")])

            # Если корзина не пуста, добавляем кнопку "Перейти в корзину"
            if cart:
                buttons.append([InlineKeyboardButton("🛒 Перейти в корзину", callback_data="view_cart")])

            keyboard = InlineKeyboardMarkup(buttons)

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
    
    elif data.startswith("order_"):
        # Формат: order_action_orderId
        parts = data.split('_')
        action = parts[1]
        order_id = int(parts[2])

        # Проверка прав
        if not is_staff(update.effective_user.id):
            await query.answer("⛔ У вас нет прав для этого действия.", show_alert=True)
            return

        # Определяем новый статус и следующую кнопку
        if action == "accept":
            new_status = "готовится"
            next_button = [InlineKeyboardButton("👨‍🍳 Готовится", callback_data=f"order_prepare_{order_id}")]
        elif action == "prepare":
            new_status = "готовится"  # здесь можно оставить тот же статус или изменить, но по логике это уже готовится
            # На самом деле после "Принять" мы уже перешли в готовится, поэтому следующая кнопка "Выдан"
            next_button = [InlineKeyboardButton("✅ Выдан", callback_data=f"order_done_{order_id}")]
        elif action == "done":
            new_status = "выдан"
            next_button = None  # финальный статус, кнопки убираем
        else:
            await query.answer("Неизвестное действие")
            return

        # Обновляем в Google Sheets
        username = update.effective_user.username or str(update.effective_user.id)
        success = update_order_status(order_id, new_status, username)
        if not success:
            await query.answer("❌ Не удалось обновить статус в таблице.", show_alert=True)
            return

        # Редактируем сообщение: убираем старые кнопки, добавляем новые (если есть)
        if next_button:
            new_markup = InlineKeyboardMarkup([next_button])
            await query.edit_message_reply_markup(reply_markup=new_markup)
        else:
            # Убираем все кнопки
            await query.edit_message_reply_markup(reply_markup=None)

        # Если статус "готовится" – отправляем клиенту случайную фразу о чаевых
        if new_status == "готовится":
            # Получаем следующий номер фразы
            tip_index = increment_tip_sent(order_id)
            if tip_index > 0:
                # Выбираем фразу по индексу (1-based, зацикливаем)
                msg = TIP_MESSAGES[(tip_index - 1) % len(TIP_MESSAGES)]
                try:
                    # Отправляем в личку клиенту (user_id есть в order_data? нужно передать)
                    # Для этого нужно сохранить user_id в контексте или получить из таблицы. Упростим: пока не делаем.
                    # Вместо этого отправим в группу? Но клиенту нужно отправить. 
                    # Пока пропустим – позже доработаем.
                    logging.info(f"Клиенту заказа {order_id} отправлена фраза: {msg}")
                    # await context.bot.send_message(chat_id=user_id, text=msg)
                except Exception as e:
                    logging.error(f"Не удалось отправить фразу клиенту {user_id}: {e}")

        # Если статус "выдан" – отправляем клиенту сообщение с предложением комментария
        elif new_status == "выдан":
            try:
                # Получаем user_id заказа (нужно хранить в контексте или получить из таблицы). Пока заглушка.
                # await context.bot.send_message(chat_id=user_id, 
                #    text="Ваш заказ исполнен, желаем вам приятного вечера! Если у вас есть комментарии, можете оставить их.",
                #    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Добавить комментарий", callback_data=f"comment_{order_id}")]])
                # )
                logging.info(f"Клиенту заказа {order_id} отправлено сообщение о выдаче")
            except Exception as e:
                logging.error(f"Ошибка отправки сообщения клиенту: {e}")

        await query.answer(f"Статус заказа №{order_id} изменён на {new_status}")

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
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📋 В главное меню", callback_data="back_to_cats")]])
        await query.edit_message_text(
            "Корзина пуста. Добавьте товары.",
            reply_markup=keyboard
        )
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

async def send_order_notification(context: ContextTypes.DEFAULT_TYPE, order_data: dict, order_id: int, sheet_ok: bool):
    if not GROUP_CHAT_ID:
        return

    sheet_url = f"https://docs.google.com/spreadsheets/d/{config.ORDERS_SPREADSHEET_ID}/edit"

    import html
    safe_items_str = html.escape(order_data['items_str'])
    safe_comment = html.escape(order_data['comment']) if order_data['comment'] else ""

    text = (
        f"<b>🆕 Новый заказ №{order_id}</b>\n"
        f"<b>👤 Пользователь:</b> {order_data['user_name']}\n"
        f"<b>🆔 ID:</b> {order_data['user_id']}\n"
        f"<b>📱 Username:</b> @{order_data['username']}\n"
        f"<b>📋 Состав заказа:</b>\n{safe_items_str}\n"
        f"<b>💰 Сумма:</b> {order_data['total_amount']}₽\n"
    )
    if safe_comment:
        text += f"<b>💬 Комментарий:</b> {safe_comment}\n"
    text += f"\n🔗 <a href='{sheet_url}'>Открыть таблицу</a>"

    # Кнопки для персонала
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Принять", callback_data=f"order_accept_{order_id}")]
    ])

    try:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=text, parse_mode='HTML', reply_markup=keyboard)
        logging.info(f"Уведомление о заказе №{order_id} отправлено в группу {GROUP_CHAT_ID}")
    except Exception as e:
        logging.error(f"Не удалось отправить уведомление в группу: {e}")

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Финальное подтверждение заказа – сохранение в БД и Google Sheets."""
    query = update.callback_query
    user_id = update.effective_user.id
    cart = get_cart(user_id)
    if not cart:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📋 В главное меню", callback_data="back_to_cats")]])
        await query.edit_message_text(
            "Корзина пуста. Добавьте товары.",
            reply_markup=keyboard
        )
        return CHOOSING_CATEGORY

    total = sum(qty * price for _, qty, price in cart)
    lines = [f"{name} x{qty} — {qty*price}₽" for name, qty, price in cart]
    items_str = "\n".join(lines)

    user = update.effective_user
    user_name = user.full_name or user.username or str(user.id)
    username = user.username or ""
    comment = context.user_data.get('order_comment', '')

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

    # Отправляем уведомление в группу
    await send_order_notification(context, order_data, order_id, sheet_ok)

    # Показываем главное меню
    menu = context.bot_data.get('menu')
    if not menu:
        menu = await load_menu_and_build_index(context)
    if sheet_ok:
        await query.edit_message_text(
            f"✅ Заказ №{order_id} оформлен!\n\n{items_str}\n\nИтого: {total}₽\n\n"
            "У нас камерный формат, поэтому мы принимаем только наличные. Большое спасибо, если расплатитесь без сдачи!\n\n"
            "Спасибо!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 В главное меню", callback_data="back_to_cats")]])
        )
    else:
        await query.edit_message_text(
            f"⚠️ Заказ №{order_id} сохранён локально, но возникла проблема с записью в Google Sheets.\n\n{items_str}\n\nИтого: {total}₽",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 В главное меню", callback_data="back_to_cats")]])
        )
    return CHOOSING_CATEGORY

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

    item_name = item_obj['name']
    price = item_obj['price']
    category = context.user_data.get('selected_category')

    # Логирование после определения переменной
    logging.info(f"Всё ок, сейчас вызову add_to_cart для {item_name}")

    user_id = update.effective_user.id
    add_to_cart(user_id, item_name, qty, price)

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

async def reload_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перезагружает меню из CSV (только для администратора)."""
    # Проверяем, что команду вызвал администратор
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return

    await update.message.reply_text("🔄 Перезагружаю меню из Google Sheets...")
    # Загружаем свежее меню и обновляем индексы
    menu = await load_menu_and_build_index(context)
    if menu:
        await update.message.reply_text("✅ Меню успешно перезагружено.")
    else:
        await update.message.reply_text("❌ Ошибка загрузки меню. Проверьте ссылку и доступность таблицы.")

def main():
    async def list_orders_by_status(update: Update, context: ContextTypes.DEFAULT_TYPE, status: str):
        if not is_staff(update.effective_user.id):
            await update.message.reply_text("⛔ У вас нет прав.")
            return

        orders = get_orders_by_status(status)
        if not orders:
            await update.message.reply_text(f"Нет заказов со статусом '{status}'.")
            return

        # Формируем красивое сообщение
        lines = [f"<b>Заказы со статусом '{status}':</b>"]
        for ord in orders:
            # Предполагаем, что в записи есть поля: ID, user_name, total_amount, created_at, username и т.д.
            order_id = ord.get('ID')
            user = ord.get('user_name', 'Неизвестно')
            total = ord.get('total_amount', 0)
            time = ord.get('created_at', '')
            lines.append(f"• №{order_id} – {user} – {total}₽ ({time})")
        await update.message.reply_text("\n".join(lines), parse_mode='HTML')

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
    application.add_handler(CommandHandler("show", show))
    application.add_handler(CommandHandler("hide", hide))
    application.add_handler(CommandHandler("reloadmenu", reload_menu))
    application.add_handler(CommandHandler("new", lambda u,c: list_orders_by_status(u,c,"новый")))
    application.add_handler(CommandHandler("preparing", lambda u,c: list_orders_by_status(u,c,"готовится")))
    application.add_handler(CommandHandler("done", lambda u,c: list_orders_by_status(u,c,"выдан")))

    logging.basicConfig(level=logging.INFO)
    application.run_polling()

async def show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Включить товар (сделать доступным)"""
    await set_item_availability(update, context, "Да")

async def hide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выключить товар (сделать недоступным)"""
    await set_item_availability(update, context, "Нет")

async def set_item_availability(update: Update, context: ContextTypes.DEFAULT_TYPE, target_status: str):
    """Общая логика для включения/выключения товара с последующей перезагрузкой меню."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text(f"❌ Использование: /{context.command[0]} <id товара>")
        return

    try:
        item_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return

    # Ищем товар в текущем кеше
    items_by_id = context.bot_data.get('items_by_id')
    if not items_by_id:
        await update.message.reply_text("❌ Меню ещё не загружено. Попробуйте позже.")
        return

    if item_id not in items_by_id:
        await update.message.reply_text(f"❌ Товар с ID {item_id} не найден в меню.")
        return

    category, item = items_by_id[item_id]
    current_status = "Да" if item['available'] else "Нет"
    if current_status == target_status:
        await update.message.reply_text(f"ℹ️ Товар уже имеет статус '{target_status}'.")
        return

    # Обновляем в Google Sheets
    success = update_item_availability(item_id, target_status)
    if not success:
        await update.message.reply_text("❌ Не удалось обновить статус в таблице. Проверьте логи.")
        return

    # Обновляем локальный кеш
    item['available'] = (target_status == "Да")

    await update.message.reply_text(
        f"✅ Статус товара *{item['name']}* (ID {item_id}) изменён с '{current_status}' на '{target_status}'.",
        parse_mode='Markdown'
    )

    # Перезагружаем всё меню из CSV
    await update.message.reply_text("🔄 Перезагружаю меню из Google Sheets...")
    new_menu = await load_menu_and_build_index(context)
    if new_menu:
        # Отправляем новое главное меню, чтобы пользователь сразу видел изменения
        await update.message.reply_text(
            "✅ Меню обновлено. Выберите категорию:",
            reply_markup=categories_keyboard(new_menu)
        )
    else:
        await update.message.reply_text("⚠️ Не удалось загрузить меню, но статус товара уже изменён.")    

if __name__ == "__main__":
    main()