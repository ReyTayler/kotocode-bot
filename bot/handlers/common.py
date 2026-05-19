import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import database as db
from bot.config import SUPERADMIN_ID
from bot.services.role_service import get_role_service
from bot.utils.commands import set_commands_for_user

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.full_name)

    if user.id == SUPERADMIN_ID:
        db.ensure_superadmin(user.id, user.username, user.full_name)

    rs = get_role_service()
    roles_str = ", ".join(rs.get_role_labels(user.id))

    greeting = (
        f"Привет, {user.first_name}!\n"
        f"Я - Бот школы <b>Котокод</b>\n"
        f"Ваши роли: <b>{roles_str}</b>\n\n"
        f"Используй /help для списка команд."
    )
    await update.message.reply_text(greeting, parse_mode="HTML")
    await set_commands_for_user(context.bot, user.id)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.full_name)

    text = get_role_service().get_help_text(user.id)
    await update.message.reply_text(text, parse_mode="HTML")


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    command = update.message.text.split()[0] if update.message.text else "?"
    await update.message.reply_text(
        f"Команда <code>{command}</code> не найдена.\n"
        f"Используй /help для списка доступных команд.",
        parse_mode="HTML",
    )
