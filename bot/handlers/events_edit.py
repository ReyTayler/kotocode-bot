"""
FSM для редактирования событий.
/edit_N
"""
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
from bot.states.forms import EDIT_CHOOSING_FIELD, EDIT_WAITING_VALUE
from bot.utils.parser import _parse_date, _validate_future
from bot.utils.formatters import fmt_event_card, fmt_event_updated
from bot.utils.notifications import notify_event_updated

logger = logging.getLogger(__name__)

_EDIT_EVENT_ID_KEY    = "edit_event_id"
_EDIT_FIELD_KEY       = "edit_field"
_EDIT_CHANGED_FIELDS  = "edit_changed_fields"

# field_key → (эмодзи, название, подсказка)
_EDIT_FIELDS = {
    "group_name":    ("📚", "Группа",          "Отправь новое название группы/индива:"),
    "lesson_number": ("📖", "Номер урока",      "Отправь новый номер урока (например: Урок №13):"),
    "scheduled_at":  ("📅", "Дата проведения",  "Отправь новую дату в формате: <code>дд.мм чч:мм</code>"),
    "children":      ("👦", "Дети",             "Отправь новый список детей:"),
    "comment":       ("💬", "Комментарий",      "Отправь новый комментарий (или <code>-</code> чтобы убрать):"),
}


def _edit_keyboard() -> InlineKeyboardMarkup:
    items = list(_EDIT_FIELDS.items())
    buttons = [
        [
            InlineKeyboardButton(f"{e} {name}", callback_data=f"edit_field:{key}")
            for key, (e, name, _) in items[i:i+2]
        ]
        for i in range(0, len(items), 2)
    ]
    buttons.append([InlineKeyboardButton("✅ Сохранить", callback_data="edit_done")])
    return InlineKeyboardMarkup(buttons)


@require_role(is_manager_or_above)
async def edit_event_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    match = re.search(r"/edit_(\d+)", update.message.text)
    if not match:
        return ConversationHandler.END

    event_id = int(match.group(1))
    event    = db.get_event(event_id)

    if not event:
        await update.message.reply_text(f"⚠️ Событие #{event_id} не найдено.")
        return ConversationHandler.END

    if event["status"] != db.STATUS_ACTIVE:
        await update.message.reply_text(f"⚠️ Событие #{event_id} не активно.")
        return ConversationHandler.END

    context.user_data[_EDIT_EVENT_ID_KEY]   = event_id
    context.user_data[_EDIT_CHANGED_FIELDS] = []

    await update.message.reply_text(
        fmt_event_card(event),
        parse_mode="HTML",
        reply_markup=_edit_keyboard(),
    )
    return EDIT_CHOOSING_FIELD


async def edit_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    query = update.callback_query
    await query.answer()

    if not is_manager_or_above(update.effective_user.id):
        await query.edit_message_text("⛔ У вас нет прав для этого действия.")
        return ConversationHandler.END

    field = query.data.split(":")[1]
    if field not in _EDIT_FIELDS:
        return EDIT_CHOOSING_FIELD

    context.user_data[_EDIT_FIELD_KEY] = field
    _, name, prompt = _EDIT_FIELDS[field]

    await query.edit_message_text(
        f"Редактирование поля <b>{name}</b>\n\n{prompt}\n\nДля отмены — /cancel_input",
        parse_mode="HTML",
    )
    return EDIT_WAITING_VALUE


async def edit_receive_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    field    = context.user_data.get(_EDIT_FIELD_KEY)
    event_id = context.user_data.get(_EDIT_EVENT_ID_KEY)

    if not field or not event_id:
        await update.message.reply_text("⚠️ Что-то пошло не так. Начни заново.")
        return ConversationHandler.END

    raw   = update.message.text.strip()
    _, name, _ = _EDIT_FIELDS[field]

    if field == "scheduled_at":
        try:
            dt = _parse_date(raw)
            _validate_future(dt)
            db_value = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            await update.message.reply_text(
                f"⚠️ Ошибка: {e}\n\nПопробуй ещё раз или /cancel_input",
                parse_mode="HTML",
            )
            return EDIT_WAITING_VALUE

    elif field == "lesson_number":
        import re as _re
        clean = _re.sub(r"^урок\s*[№#]?\s*", "", raw, flags=_re.IGNORECASE).strip()
        if not clean or not _re.search(r"\d", clean):
            await update.message.reply_text(
                f"⚠️ Номер урока должен содержать число.\n"
                f"Получено: <code>{raw}</code>\n"
                f"Пример: <code>Урок №13</code>\n\n"
                f"Попробуй ещё раз или /cancel_input",
                parse_mode="HTML",
            )
            return EDIT_WAITING_VALUE
        db_value = raw

    elif field == "group_name":
        if not raw or raw == "-":
            await update.message.reply_text(
                "⚠️ Название группы не может быть пустым.\n\n"
                "Попробуй ещё раз или /cancel_input",
            )
            return EDIT_WAITING_VALUE
        db_value = raw

    elif field == "children":
        if not raw or raw == "-":
            await update.message.reply_text(
                "⚠️ Список детей не может быть пустым.\n\n"
                "Попробуй ещё раз или /cancel_input",
            )
            return EDIT_WAITING_VALUE
        db_value = raw

    elif field == "comment" and raw == "-":
        db_value = ""

    else:
        db_value = raw

    db.update_event_field(event_id, field, db_value)

    changed = context.user_data.setdefault(_EDIT_CHANGED_FIELDS, [])
    if field not in changed:
        changed.append(field)

    if field == "scheduled_at":
        cancel_reminders(event_id)
        schedule_reminders(
            event_id,
            TIMEZONE.localize(datetime.strptime(db_value, "%Y-%m-%d %H:%M:%S")),
        )

    event = db.get_event(event_id)
    await update.message.reply_text(
        f"✅ Поле <b>{name}</b> обновлено.\n\n" + fmt_event_card(event),
        parse_mode="HTML",
        reply_markup=_edit_keyboard(),
    )
    return EDIT_CHOOSING_FIELD


async def edit_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not is_manager_or_above(update.effective_user.id):
        await query.edit_message_text("⛔ У вас нет прав для этого действия.")
        return ConversationHandler.END

    event_id = context.user_data.get(_EDIT_EVENT_ID_KEY)
    if not event_id:
        await query.edit_message_text("⚠️ Что-то пошло не так.")
        return ConversationHandler.END

    event          = db.get_event(event_id)
    changed_by     = update.effective_user.username or str(update.effective_user.id)
    changed_fields = context.user_data.get(_EDIT_CHANGED_FIELDS, [])

    await context.bot.send_message(
        chat_id=GENERAL_CHAT_ID,
        text=fmt_event_updated(event, changed_fields, changed_by),
        parse_mode="HTML",
    )

    if event["teacher_telegram_id"]:
        await notify_event_updated(
            context.bot, event["teacher_telegram_id"], event, changed_fields
        )

    await query.edit_message_text(
        f"✅ Изменения по событию #{event_id} сохранены и отправлены в чат."
    )

    context.user_data.pop(_EDIT_EVENT_ID_KEY, None)
    context.user_data.pop(_EDIT_FIELD_KEY, None)
    context.user_data.pop(_EDIT_CHANGED_FIELDS, None)
    return ConversationHandler.END


async def _cancel_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(_EDIT_EVENT_ID_KEY, None)
    context.user_data.pop(_EDIT_FIELD_KEY, None)
    context.user_data.pop(_EDIT_CHANGED_FIELDS, None)
    await update.message.reply_text("❌ Редактирование отменено.")
    return ConversationHandler.END


def get_edit_conv_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(r"^/edit_\d+(@\w+)?$") & filters.ChatType.PRIVATE,
                edit_event_by_id
            ),
        ],
        states={
            EDIT_CHOOSING_FIELD: [
                CallbackQueryHandler(edit_field_callback, pattern=r"^edit_field:"),
                CallbackQueryHandler(edit_done_callback,  pattern="^edit_done$"),
            ],
            EDIT_WAITING_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, edit_receive_value),
            ],
        },
        fallbacks=[CommandHandler("cancel_input", _cancel_input, filters=filters.ChatType.PRIVATE)],
        per_user=True, per_chat=True, per_message=False,
    )
