"""
Просмотр и отмена событий.
/list, /my, /cancel, /cancel_N
"""
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from bot import database as db
from bot.config import GENERAL_CHAT_ID
from bot.middlewares.role_check import require_role, is_manager_or_above
from bot.scheduler import cancel_reminders
from bot.utils.formatters import fmt_event_list_item, fmt_event_cancelled
from bot.utils.notifications import notify_event_cancelled

logger = logging.getLogger(__name__)


@require_role(is_manager_or_above)
async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    teacher_filter = context.args[0].lstrip("@") if context.args else None
    events = db.get_active_events(teacher_username=teacher_filter)

    if not events:
        msg = f"У @{teacher_filter} нет активных событий." if teacher_filter else "Активных событий нет."
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


async def my_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.full_name)

    db_user = db.get_user(user.id)
    if not db_user or not db_user["is_teacher"]:
        await update.message.reply_text("⛔ Эта команда только для преподавателей.")
        return

    if not user.username:
        await update.message.reply_text("⚠️ У тебя не задан username в Telegram. Обратись к менеджеру.")
        return

    events = db.get_active_events(teacher_username=user.username)

    if not events:
        await update.message.reply_text("У тебя нет активных назначений.")
        return

    lines = ["📋 <b>Твои назначения:</b>", ""]
    for i, event in enumerate(events, 1):
        lines.append(fmt_event_list_item(event, i, show_actions=False))
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@require_role(is_manager_or_above)
async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Укажи номер события.\nПример: <code>/cancel 42</code>",
            parse_mode="HTML",
        )
        return
    await _do_cancel(update, context, int(context.args[0]))


@require_role(is_manager_or_above)
async def cancel_event_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    await context.bot.send_message(
        chat_id=GENERAL_CHAT_ID,
        text=fmt_event_cancelled(event),
        parse_mode="HTML",
    )

    if event["teacher_telegram_id"]:
        await notify_event_cancelled(context.bot, event["teacher_telegram_id"], event)

    await update.message.reply_text(f"✅ Событие #{event_id} отменено.")
