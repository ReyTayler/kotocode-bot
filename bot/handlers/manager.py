import logging
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, CallbackQueryHandler, filters,
)

from bot import database as db
from bot.config import GENERAL_CHAT_ID, TIMEZONE
from bot.middlewares.role_check import require_role, is_manager_or_above
from bot.scheduler import schedule_reminders, cancel_reminders
from bot.states.forms import (
    DOPROVED_WAITING_TEMPLATE, DOPROVED_WAITING_CONFIRM,
    PERENOS_WAITING_TEMPLATE, PERENOS_WAITING_CONFIRM,
    EDIT_CHOOSING_FIELD, EDIT_WAITING_VALUE,
)
from bot.utils.parser import parse_template, ParseError, _parse_date, _validate_future
from bot.utils.formatters import (
    DOPROVED_TEMPLATE, PERENOS_TEMPLATE,
    fmt_preview, fmt_event_announce, fmt_event_cancelled,
    fmt_event_list_item, fmt_event_card, fmt_event_updated,
)

logger = logging.getLogger(__name__)

# ─── Ключи для хранения данных в context.user_data ───────────────────────────
_PARSED_KEY = "pending_event_parsed"
_TYPE_KEY = "pending_event_type"
_EDIT_EVENT_ID_KEY = "edit_event_id"
_EDIT_FIELD_KEY = "edit_field"


# ─── Шаблонные сообщения ──────────────────────────────────────────────────────

TEMPLATE_PROMPT = (
    "Скопируй и заполни шаблон:\n\n"
    "<code>{template}</code>\n\n"
    "После заполнения — отправь сообщением сюда.\n"
    "Для отмены — /cancel_input"
)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Сохранить", callback_data="event_confirm"),
            InlineKeyboardButton("❌ Отмена", callback_data="event_cancel"),
        ]
    ])


# ─── /add_doproved ────────────────────────────────────────────────────────────

@require_role(is_manager_or_above)
async def add_doproved_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    await update.message.reply_text(
        TEMPLATE_PROMPT.format(template=DOPROVED_TEMPLATE),
        parse_mode="HTML",
    )
    return DOPROVED_WAITING_TEMPLATE


async def doproved_receive_template(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    return await _receive_template(update, context, db.TYPE_DOPROVED, DOPROVED_WAITING_CONFIRM)


# ─── /add_perenos ─────────────────────────────────────────────────────────────

@require_role(is_manager_or_above)
async def add_perenos_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    await update.message.reply_text(
        TEMPLATE_PROMPT.format(template=PERENOS_TEMPLATE),
        parse_mode="HTML",
    )
    return PERENOS_WAITING_TEMPLATE


async def perenos_receive_template(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    return await _receive_template(update, context, db.TYPE_PERENOS, PERENOS_WAITING_CONFIRM)


# ─── Общая логика получения шаблона ──────────────────────────────────────────

async def _receive_template(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    event_type: str,
    confirm_state: str,
) -> str:
    text = update.message.text.strip()
    try:
        parsed = parse_template(text)
    except ParseError as e:
        await update.message.reply_text(
            f"⚠️ Ошибка в шаблоне:\n{e}\n\nИсправь и отправь снова, или /cancel_input для отмены.",
            parse_mode="HTML",
        )
        # Остаёмся в том же состоянии
        return DOPROVED_WAITING_TEMPLATE if event_type == db.TYPE_DOPROVED else PERENOS_WAITING_TEMPLATE

    context.user_data[_PARSED_KEY] = parsed
    context.user_data[_TYPE_KEY] = event_type

    preview = fmt_preview(parsed, event_type)
    await update.message.reply_text(
        preview,
        parse_mode="HTML",
        reply_markup=_confirm_keyboard(),
    )
    return confirm_state


# ─── Подтверждение / отмена через кнопки ─────────────────────────────────────

async def event_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # Явная проверка прав — CallbackQuery не проходит через @require_role
    from bot.middlewares.role_check import is_manager_or_above
    if not is_manager_or_above(update.effective_user.id):
        await query.edit_message_text("⛔ У вас нет прав для этого действия.")
        return ConversationHandler.END

    parsed = context.user_data.get(_PARSED_KEY)
    event_type = context.user_data.get(_TYPE_KEY)

    if not parsed or not event_type:
        await query.edit_message_text("⚠️ Данные потеряны. Начни заново.")
        return ConversationHandler.END

    user = update.effective_user

    # Ищем telegram_id преподавателя если он есть в БД
    teacher_user = db.get_user_by_username(parsed.teacher_username)
    teacher_tg_id = teacher_user["telegram_id"] if teacher_user else None

    event_id = db.add_event(
        event_type=event_type,
        teacher_username=parsed.teacher_username,
        teacher_telegram_id=teacher_tg_id,
        group_name=parsed.group_name,
        lesson_number=parsed.lesson_number,
        scheduled_at=parsed.scheduled_at,
        children=parsed.children,
        comment=parsed.comment,
        created_by=user.id,
    )

    event = db.get_event(event_id)
    announce_text = fmt_event_announce(event)

    # Планируем напоминания точно на нужное время
    schedule_reminders(event_id, parsed.scheduled_at)

    # Публикуем в общий чат
    await context.bot.send_message(
        chat_id=GENERAL_CHAT_ID,
        text=announce_text,
        parse_mode="HTML",
    )

    # Отправляем личное уведомление преподавателю если он есть в БД
    if teacher_tg_id:
        from bot.utils.notifications import notify_event_assigned
        await notify_event_assigned(context.bot, teacher_tg_id, event)

    await query.edit_message_text(
        f"✅ Сохранено и опубликовано в чат.\n🆔 #{event_id}",
        parse_mode="HTML",
    )

    context.user_data.pop(_PARSED_KEY, None)
    context.user_data.pop(_TYPE_KEY, None)
    return ConversationHandler.END


async def event_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.pop(_PARSED_KEY, None)
    context.user_data.pop(_TYPE_KEY, None)
    await query.edit_message_text("❌ Добавление отменено.")
    return ConversationHandler.END


async def cancel_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена FSM через /cancel_input."""
    context.user_data.pop(_PARSED_KEY, None)
    context.user_data.pop(_TYPE_KEY, None)
    await update.message.reply_text("❌ Ввод отменён.")
    return ConversationHandler.END


# ─── /cancel ID и /cancel_ID ──────────────────────────────────────────────────

@require_role(is_manager_or_above)
async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "Укажи номер события.\nПример: <code>/cancel 42</code>",
            parse_mode="HTML",
        )
        return
    await _do_cancel(update, context, int(args[0]))


@require_role(is_manager_or_above)
async def cancel_event_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает клик по /cancel_42 из списка событий."""
    import re
    match = re.search(r"/cancel_(\d+)", update.message.text)
    if match:
        await _do_cancel(update, context, int(match.group(1)))


async def _do_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    event = db.get_event(event_id)

    if not event:
        await update.message.reply_text(f"⚠️ Событие #{event_id} не найдено.")
        return

    if event["status"] != db.STATUS_ACTIVE:
        await update.message.reply_text(
            f"⚠️ Событие #{event_id} уже не активно (статус: {event['status']})."
        )
        return

    db.cancel_event(event_id)
    cancel_reminders(event_id)

    cancelled_text = fmt_event_cancelled(event)
    await context.bot.send_message(
        chat_id=GENERAL_CHAT_ID,
        text=cancelled_text,
        parse_mode="HTML",
    )

    # Уведомляем преподавателя в личку если он есть в БД
    if event["teacher_telegram_id"]:
        from bot.utils.notifications import notify_event_cancelled
        await notify_event_cancelled(context.bot, event["teacher_telegram_id"], event)

    await update.message.reply_text(f"✅ Событие #{event_id} отменено.")


# ─── /list ────────────────────────────────────────────────────────────────────

@require_role(is_manager_or_above)
async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    teacher_filter = None
    if context.args:
        teacher_filter = context.args[0].lstrip("@")

    events = db.get_active_events(teacher_username=teacher_filter)

    if not events:
        msg = "Активных событий нет."
        if teacher_filter:
            msg = f"У @{teacher_filter} нет активных событий."
        await update.message.reply_text(msg)
        return

    header = "📋 <b>Активные события</b>"
    if teacher_filter:
        header += f" — @{teacher_filter}"

    lines = [header, ""]
    for i, event in enumerate(events, 1):
        lines.append(fmt_event_list_item(event, i))
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── /my (для преподавателей) ─────────────────────────────────────────────────

async def my_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.full_name)

    from bot.middlewares.role_check import _get_effective_role
    from bot import database as db_module
    role = _get_effective_role(user.id)
    if role != db_module.ROLE_TEACHER:
        await update.message.reply_text("⛔ Эта команда только для преподавателей.")
        return

    if not user.username:
        await update.message.reply_text(
            "⚠️ У тебя не задан username в Telegram. Обратись к менеджеру."
        )
        return

    events = db.get_active_events(teacher_username=user.username)

    if not events:
        await update.message.reply_text("У тебя нет активных назначений.")
        return

    lines = ["📋 <b>Твои назначения:</b>", ""]
    for i, event in enumerate(events, 1):
        lines.append(fmt_event_list_item(event, i))
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── Редактирование события ───────────────────────────────────────────────────

# Описание полей: field_key → (эмодзи, название, подсказка для ввода)
_EDIT_FIELDS = {
    "group_name":    ("📚", "Группа",           "Отправь новое название группы/индива:"),
    "lesson_number": ("📖", "Номер урока",       "Отправь новый номер урока (например: Урок №13):"),
    "scheduled_at":  ("📅", "Дата проведения",   "Отправь новую дату в формате: <code>дд.мм чч:мм</code>"),
    "children":      ("👦", "Дети",              "Отправь новый список детей:"),
    "comment":       ("💬", "Комментарий",       "Отправь новый комментарий (или прочерк <code>-</code> чтобы убрать):"),
}


def _edit_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора поля для редактирования."""
    buttons = [
        [
            InlineKeyboardButton(f"{e} {name}", callback_data=f"edit_field:{key}")
            for key, (e, name, _) in list(_EDIT_FIELDS.items())[i:i+2]
        ]
        for i in range(0, len(_EDIT_FIELDS), 2)
    ]
    buttons.append([InlineKeyboardButton("✅ Сохранить", callback_data="edit_done")])
    return InlineKeyboardMarkup(buttons)


@require_role(is_manager_or_above)
async def edit_event_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Точка входа — /edit_42."""
    match = re.search(r"/edit_(\d+)", update.message.text)
    if not match:
        return ConversationHandler.END

    event_id = int(match.group(1))
    event = db.get_event(event_id)

    if not event:
        await update.message.reply_text(f"⚠️ Событие #{event_id} не найдено.")
        return ConversationHandler.END

    if event["status"] != db.STATUS_ACTIVE:
        await update.message.reply_text(f"⚠️ Событие #{event_id} не активно.")
        return ConversationHandler.END

    context.user_data[_EDIT_EVENT_ID_KEY] = event_id
    await update.message.reply_text(
        fmt_event_card(event),
        parse_mode="HTML",
        reply_markup=_edit_keyboard(),
    )
    return EDIT_CHOOSING_FIELD


async def edit_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Пользователь нажал кнопку поля."""
    query = update.callback_query
    await query.answer()

    # Проверка прав
    if not is_manager_or_above(update.effective_user.id):
        await query.edit_message_text("⛔ У вас нет прав для этого действия.")
        return ConversationHandler.END

    field = query.data.split(":")[1]
    if field not in _EDIT_FIELDS:
        return EDIT_CHOOSING_FIELD

    context.user_data[_EDIT_FIELD_KEY] = field
    _, name, prompt = _EDIT_FIELDS[field]

    await query.edit_message_text(
        f"Редактирование поля <b>{name}</b>\n\n{prompt}\n\n"
        f"Для отмены — /cancel_input",
        parse_mode="HTML",
    )
    return EDIT_WAITING_VALUE


async def edit_receive_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Получили новое значение поля от пользователя."""
    field = context.user_data.get(_EDIT_FIELD_KEY)
    event_id = context.user_data.get(_EDIT_EVENT_ID_KEY)

    if not field or not event_id:
        await update.message.reply_text("⚠️ Что-то пошло не так. Начни заново.")
        return ConversationHandler.END

    raw_value = update.message.text.strip()
    _, name, _ = _EDIT_FIELDS[field]

    # Обрабатываем дату отдельно — нужен парсинг и валидация
    if field == "scheduled_at":
        try:
            dt = _parse_date(raw_value)
            _validate_future(dt)
            db_value = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            await update.message.reply_text(
                f"⚠️ Ошибка: {e}\n\nПопробуй ещё раз или /cancel_input",
                parse_mode="HTML",
            )
            return EDIT_WAITING_VALUE
    elif field == "comment" and raw_value == "-":
        db_value = ""
    else:
        db_value = raw_value

    # Сохраняем в БД
    db.update_event_field(event_id, field, db_value)

    # Если изменилась дата — пересчитываем напоминания
    if field == "scheduled_at":
        cancel_reminders(event_id)
        schedule_reminders(event_id, TIMEZONE.localize(
            datetime.strptime(db_value, "%Y-%m-%d %H:%M:%S")
        ))

    # Показываем обновлённую карточку
    event = db.get_event(event_id)
    await update.message.reply_text(
        f"✅ Поле <b>{name}</b> обновлено.\n\n" + fmt_event_card(event),
        parse_mode="HTML",
        reply_markup=_edit_keyboard(),
    )
    return EDIT_CHOOSING_FIELD


async def edit_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь нажал Сохранить."""
    query = update.callback_query
    await query.answer()

    # Проверка прав
    if not is_manager_or_above(update.effective_user.id):
        await query.edit_message_text("⛔ У вас нет прав для этого действия.")
        return ConversationHandler.END

    event_id = context.user_data.get(_EDIT_EVENT_ID_KEY)
    if not event_id:
        await query.edit_message_text("⚠️ Что-то пошло не так.")
        return ConversationHandler.END

    event = db.get_event(event_id)
    changed_by = update.effective_user.username or str(update.effective_user.id)

    # Публикуем изменение в общий чат
    await query.bot.send_message(
        chat_id=GENERAL_CHAT_ID,
        text=fmt_event_updated(event, "general", changed_by),
        parse_mode="HTML",
    )

    # Уведомляем преподавателя в личку
    if event["teacher_telegram_id"]:
        from bot.utils.notifications import notify_event_updated
        await notify_event_updated(query.bot, event["teacher_telegram_id"], event, "general")

    await query.edit_message_text(
        f"✅ Изменения по событию #{event_id} сохранены и отправлены в чат."
    )

    context.user_data.pop(_EDIT_EVENT_ID_KEY, None)
    context.user_data.pop(_EDIT_FIELD_KEY, None)
    return ConversationHandler.END


def get_edit_conv_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^/edit_\d+$") & filters.ChatType.PRIVATE, edit_event_by_id)
        ],
        states={
            EDIT_CHOOSING_FIELD: [
                CallbackQueryHandler(edit_field_callback, pattern=r"^edit_field:"),
                CallbackQueryHandler(edit_done_callback, pattern="^edit_done$"),
            ],
            EDIT_WAITING_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, edit_receive_value),
            ],
        },
        fallbacks=[CommandHandler("cancel_input", cancel_input, filters=filters.ChatType.PRIVATE)],
        per_user=True,
        per_chat=True,
        per_message=False,
    )


# ─── ConversationHandler-ы ────────────────────────────────────────────────────

def get_doproved_conv_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("add_doproved", add_doproved_start, filters=filters.ChatType.PRIVATE)],
        states={
            DOPROVED_WAITING_TEMPLATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, doproved_receive_template),
            ],
            DOPROVED_WAITING_CONFIRM: [
                CallbackQueryHandler(event_confirm_callback, pattern="^event_confirm$"),
                CallbackQueryHandler(event_cancel_callback, pattern="^event_cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel_input", cancel_input, filters=filters.ChatType.PRIVATE)],
        per_user=True,
        per_chat=True,
        per_message=False,
    )


def get_perenos_conv_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("add_perenos", add_perenos_start, filters=filters.ChatType.PRIVATE)],
        states={
            PERENOS_WAITING_TEMPLATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, perenos_receive_template),
            ],
            PERENOS_WAITING_CONFIRM: [
                CallbackQueryHandler(event_confirm_callback, pattern="^event_confirm$"),
                CallbackQueryHandler(event_cancel_callback, pattern="^event_cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel_input", cancel_input, filters=filters.ChatType.PRIVATE)],
        per_user=True,
        per_chat=True,
        per_message=False,
    )
