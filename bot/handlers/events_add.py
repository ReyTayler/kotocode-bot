"""
FSM для добавления допроведов и переносов.
/add_doproved, /add_perenos
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, CallbackQueryHandler, filters,
)

from bot import database as db
from bot.config import GENERAL_CHAT_ID
from bot.middlewares.role_check import require_role, is_manager_or_above
from bot.scheduler import schedule_reminders
from bot.states.forms import (
    DOPROVED_WAITING_TEMPLATE, DOPROVED_WAITING_CONFIRM,
    PERENOS_WAITING_TEMPLATE, PERENOS_WAITING_CONFIRM,
)
from bot.utils.parser import parse_template, ParseError, validate_teacher
from bot.utils.formatters import (
    DOPROVED_TEMPLATE, PERENOS_TEMPLATE,
    fmt_preview, fmt_event_announce,
)
from bot.utils.notifications import notify_event_assigned

logger = logging.getLogger(__name__)

_PARSED_KEY = "pending_event_parsed"
_TYPE_KEY   = "pending_event_type"

TEMPLATE_PROMPT = (
    "Скопируй и заполни шаблон:\n\n"
    "<code>{template}</code>\n\n"
    "После заполнения — отправь сообщением сюда.\n"
    "Для отмены — /cancel_input"
)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Сохранить", callback_data="event_confirm"),
        InlineKeyboardButton("❌ Отмена",    callback_data="event_cancel"),
    ]])


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


# ─── Общая логика ─────────────────────────────────────────────────────────────

async def _receive_template(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    event_type: str,
    confirm_state: str,
) -> str:
    text = update.message.text.strip()
    try:
        parsed = parse_template(text)
        validate_teacher(parsed.teacher_username)
    except ParseError as e:
        await update.message.reply_text(
            f"⚠️ Ошибка в шаблоне:\n{e}\n\nИсправь и отправь снова, или /cancel_input для отмены.",
            parse_mode="HTML",
        )
        return DOPROVED_WAITING_TEMPLATE if event_type == db.TYPE_DOPROVED else PERENOS_WAITING_TEMPLATE

    context.user_data[_PARSED_KEY] = parsed
    context.user_data[_TYPE_KEY]   = event_type

    await update.message.reply_text(
        fmt_preview(parsed, event_type),
        parse_mode="HTML",
        reply_markup=_confirm_keyboard(),
    )
    return confirm_state


async def event_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not is_manager_or_above(update.effective_user.id):
        await query.edit_message_text("⛔ У вас нет прав для этого действия.")
        return ConversationHandler.END

    parsed    = context.user_data.get(_PARSED_KEY)
    event_type = context.user_data.get(_TYPE_KEY)

    if not parsed or not event_type:
        await query.edit_message_text("⚠️ Данные потеряны. Начни заново.")
        return ConversationHandler.END

    teacher_user  = db.get_user_by_username(parsed.teacher_username)
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
        created_by=update.effective_user.id,
    )

    event = db.get_event(event_id)
    schedule_reminders(event_id, parsed.scheduled_at)

    await context.bot.send_message(
        chat_id=GENERAL_CHAT_ID,
        text=fmt_event_announce(event),
        parse_mode="HTML",
    )

    if teacher_tg_id:
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
    context.user_data.pop(_PARSED_KEY, None)
    context.user_data.pop(_TYPE_KEY, None)
    await update.message.reply_text("❌ Ввод отменён.")
    return ConversationHandler.END


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
                CallbackQueryHandler(event_cancel_callback,  pattern="^event_cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel_input",  cancel_input,       filters=filters.ChatType.PRIVATE),
            CommandHandler("add_doproved",  add_doproved_start, filters=filters.ChatType.PRIVATE),
            CommandHandler("add_perenos",   add_perenos_start,  filters=filters.ChatType.PRIVATE),
        ],
        per_user=True, per_chat=True, per_message=False,
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
                CallbackQueryHandler(event_cancel_callback,  pattern="^event_cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel_input",  cancel_input,       filters=filters.ChatType.PRIVATE),
            CommandHandler("add_doproved",  add_doproved_start, filters=filters.ChatType.PRIVATE),
            CommandHandler("add_perenos",   add_perenos_start,  filters=filters.ChatType.PRIVATE),
        ],
        per_user=True, per_chat=True, per_message=False,
    )
