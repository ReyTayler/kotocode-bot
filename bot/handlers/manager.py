import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, CallbackQueryHandler, filters,
)

from bot import database as db
from bot.config import GENERAL_CHAT_ID
from bot.middlewares.role_check import require_role, is_manager_or_above
from bot.scheduler import schedule_reminders, cancel_reminders
from bot.states.forms import (
    DOPROVED_WAITING_TEMPLATE, DOPROVED_WAITING_CONFIRM,
    PERENOS_WAITING_TEMPLATE, PERENOS_WAITING_CONFIRM,
)
from bot.utils.parser import parse_template, ParseError
from bot.utils.formatters import (
    DOPROVED_TEMPLATE, PERENOS_TEMPLATE,
    fmt_preview, fmt_event_announce, fmt_event_cancelled, fmt_event_list_item,
)

logger = logging.getLogger(__name__)

# ─── Ключи для хранения данных в context.user_data ───────────────────────────
_PARSED_KEY = "pending_event_parsed"
_TYPE_KEY = "pending_event_type"


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