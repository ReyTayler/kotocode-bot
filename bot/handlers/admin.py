import logging
from telegram import Update
from telegram.ext import ContextTypes

from bot import database as db
from bot.middlewares.role_check import require_role, is_admin_or_above, is_manager_or_above
from bot.utils.commands import set_commands_for_user

logger = logging.getLogger(__name__)


def _fmt_users_list(users: list, role_label: str) -> str:
    if not users:
        return f"Список {role_label} пуст."
    lines = [f"<b>Список {role_label}:</b>", ""]
    for u in users:
        username = f"@{u['username']}" if u["username"] else "без username"
        lines.append(f"• {u['full_name']} ({username})")
    return "\n".join(lines)


async def _add_role(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    role: str,
    role_label: str,
) -> None:
    if not context.args:
        await update.message.reply_text(
            f"Укажи @username.\nПример: <code>/add{role} @username</code>",
            parse_mode="HTML",
        )
        return

    username = context.args[0].lstrip("@")
    user = db.get_user_by_username(username)

    if not user:
        await update.message.reply_text(
            f"⚠️ Пользователь @{username} не найден в системе.\n"
            "Попроси его написать боту /start, затем повтори команду."
        )
        return

    db.grant_role(user["telegram_id"], role, added_by=update.effective_user.id)
    await update.message.reply_text(
        f"✅ @{username} назначен как <b>{role_label}</b>.",
        parse_mode="HTML",
    )
    await set_commands_for_user(context.bot, user["telegram_id"])
    from bot.utils.notifications import notify_role_granted
    await notify_role_granted(context.bot, user["telegram_id"], role)


async def _remove_role(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    role: str,
    role_label: str,
    command: str,
) -> None:
    if not context.args:
        await update.message.reply_text(
            f"Укажи @username.\nПример: <code>/{command} @username</code>",
            parse_mode="HTML",
        )
        return

    username = context.args[0].lstrip("@")
    user = db.get_user_by_username(username)

    if not user:
        await update.message.reply_text(f"⚠️ Пользователь @{username} не найден.")
        return

    db.revoke_role(user["telegram_id"], role, added_by=update.effective_user.id)
    await update.message.reply_text(f"✅ У @{username} сняты права <b>{role_label}</b>.", parse_mode="HTML")
    await set_commands_for_user(context.bot, user["telegram_id"])
    from bot.utils.notifications import notify_role_revoked
    await notify_role_revoked(context.bot, user["telegram_id"], role_label)


# ─── Менеджеры ────────────────────────────────────────────────────────────────

@require_role(is_admin_or_above)
async def add_manager(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _add_role(update, context, db.ROLE_MANAGER, "Менеджер")


@require_role(is_admin_or_above)
async def remove_manager(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _remove_role(update, context, db.ROLE_MANAGER, "Менеджер", "removemanager")


@require_role(is_admin_or_above)
async def list_managers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = db.get_users_by_role(db.ROLE_MANAGER)
    await update.message.reply_text(_fmt_users_list(users, "менеджеров"), parse_mode="HTML")


# ─── Преподаватели ────────────────────────────────────────────────────────────

@require_role(is_admin_or_above)
async def add_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _add_role(update, context, db.ROLE_TEACHER, "Преподаватель")


@require_role(is_admin_or_above)
async def remove_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _remove_role(update, context, db.ROLE_TEACHER, "Преподаватель", "removeteacher")


@require_role(is_manager_or_above)
async def list_teachers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = db.get_users_by_role(db.ROLE_TEACHER)
    await update.message.reply_text(_fmt_users_list(users, "преподавателей"), parse_mode="HTML")


@require_role(is_admin_or_above)
async def list_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users_by_role = db.get_all_users_by_roles()

    role_labels = {
        db.ROLE_SUPERADMIN: "Супер-админы 👑",
        db.ROLE_ADMIN:      "Администраторы 🔧",
        db.ROLE_MANAGER:    "Менеджеры 📋",
        db.ROLE_TEACHER:    "Преподаватели 👨‍🏫",
        db.ROLE_BLOCKED:    "Без роли 👤",
    }

    if not users_by_role:
        await update.message.reply_text("В боте нет зарегистрированных пользователей.")
        return

    lines = ["<b>Список всех пользователей:</b>"]
    for role, label in role_labels.items():
        users = users_by_role.get(role)
        lines.append(f"\n<b>{label}</b>")
        if not users:
            lines.append("Нет пользователей в этой роли")
        else:
            for u in users:
                username = f" (@{u['username']})" if u["username"] else ""
                lines.append(f"{u['full_name']}{username}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")
