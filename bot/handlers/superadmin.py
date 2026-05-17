import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, CallbackQueryHandler, filters,
)

from bot import database as db
from bot.middlewares.role_check import require_role, is_superadmin, is_admin_or_above
from bot.states.forms import TRANSFER_WAITING_CONFIRM
from bot.utils.commands import set_commands_for_user

logger = logging.getLogger(__name__)

_TRANSFER_TARGET_KEY = "transfer_target_id"


def _fmt_admins_list(users: list) -> str:
    if not users:
        return "Список администраторов пуст."
    lines = ["<b>Список администраторов:</b>", ""]
    for u in users:
        username = f"@{u['username']}" if u["username"] else "без username"
        lines.append(f"• {u['full_name']} ({username})")
    return "\n".join(lines)


# ─── Управление админами ──────────────────────────────────────────────────────

@require_role(is_superadmin)
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Укажи @username.\nПример: <code>/addadmin @username</code>",
            parse_mode="HTML",
        )
        return

    username = context.args[0].lstrip("@")
    user = db.get_user_by_username(username)

    if not user:
        await update.message.reply_text(
            f"⚠️ Пользователь @{username} не найден.\n"
            "Попроси его написать боту /start, затем повтори."
        )
        return

    db.set_role(user["telegram_id"], db.ROLE_ADMIN, added_by=update.effective_user.id)
    await update.message.reply_text(
        f"✅ @{username} назначен <b>Администратором</b>.",
        parse_mode="HTML",
    )
    await set_commands_for_user(context.bot, user["telegram_id"])
    from bot.utils.notifications import notify_role_granted
    await notify_role_granted(context.bot, user["telegram_id"], db.ROLE_ADMIN)


@require_role(is_superadmin)
async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Укажи @username.\nПример: <code>/removeadmin @username</code>",
            parse_mode="HTML",
        )
        return

    username = context.args[0].lstrip("@")
    user = db.get_user_by_username(username)

    if not user:
        await update.message.reply_text(f"⚠️ Пользователь @{username} не найден.")
        return

    # Нельзя снять права у супер-админа
    if user["is_superadmin"]:
        await update.message.reply_text("⛔ Нельзя снять права у супер-админа.")
        return

    db.set_role(user["telegram_id"], db.ROLE_BLOCKED, added_by=update.effective_user.id)
    await update.message.reply_text(f"✅ У @{username} сняты права администратора.")
    await set_commands_for_user(context.bot, user["telegram_id"])
    from bot.utils.notifications import notify_role_revoked
    await notify_role_revoked(context.bot, user["telegram_id"], "Администратор")


@require_role(is_admin_or_above)
async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = db.get_users_by_role(db.ROLE_ADMIN)
    await update.message.reply_text(_fmt_admins_list(users), parse_mode="HTML")


# ─── Передача прав супер-админа ───────────────────────────────────────────────

@require_role(is_superadmin)
async def transfer_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    if not context.args:
        await update.message.reply_text(
            "Укажи @username.\nПример: <code>/transfer @username</code>",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    username = context.args[0].lstrip("@")
    target = db.get_user_by_username(username)

    if not target:
        await update.message.reply_text(
            f"⚠️ Пользователь @{username} не найден.\n"
            "Попроси его написать боту /start, затем повтори."
        )
        return ConversationHandler.END

    if target["telegram_id"] == update.effective_user.id:
        await update.message.reply_text("⚠️ Нельзя передать права самому себе.")
        return ConversationHandler.END

    context.user_data[_TRANSFER_TARGET_KEY] = target["telegram_id"]

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, передать", callback_data="transfer_confirm"),
            InlineKeyboardButton("❌ Отмена", callback_data="transfer_cancel"),
        ]
    ])

    await update.message.reply_text(
        f"⚠️ <b>Внимание!</b>\n\n"
        f"Ты передаёшь права <b>супер-админа</b> пользователю @{username}.\n"
        f"Ты потеряешь права супер-админа и станешь обычным администратором.\n\n"
        f"Это действие необратимо через бота. Подтверждаешь?",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return TRANSFER_WAITING_CONFIRM


async def transfer_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # Явная проверка прав — CallbackQuery не проходит через @require_role
    if not is_superadmin(update.effective_user.id):
        await query.edit_message_text("⛔ У вас нет прав для этого действия.")
        return ConversationHandler.END

    from_id = update.effective_user.id
    to_id = context.user_data.get(_TRANSFER_TARGET_KEY)

    if not to_id:
        await query.edit_message_text("⚠️ Данные потеряны. Начни заново.")
        return ConversationHandler.END

    db.transfer_superadmin(from_id=from_id, to_telegram_id=to_id)

    await query.edit_message_text("✅ Права супер-админа переданы.")

    # Обновляем меню команд обоим
    await set_commands_for_user(context.bot, from_id)
    await set_commands_for_user(context.bot, to_id)

    # Уведомляем нового супер-админа
    try:
        await context.bot.send_message(
            chat_id=to_id,
            text="👑 Тебе переданы права <b>супер-админа</b> бота Котокод.",
            parse_mode="HTML",
        )
    except Exception:
        pass  # пользователь мог не начать диалог с ботом

    context.user_data.pop(_TRANSFER_TARGET_KEY, None)
    return ConversationHandler.END


async def transfer_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.pop(_TRANSFER_TARGET_KEY, None)
    await query.edit_message_text("❌ Передача прав отменена.")
    return ConversationHandler.END


def get_transfer_conv_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("transfer", transfer_start, filters=filters.ChatType.PRIVATE)],
        states={
            TRANSFER_WAITING_CONFIRM: [
                CallbackQueryHandler(transfer_confirm_callback, pattern="^transfer_confirm$"),
                CallbackQueryHandler(transfer_cancel_callback, pattern="^transfer_cancel$"),
            ],
        },
        fallbacks=[],
        per_user=True,
        per_chat=True,
        per_message=False,
    )