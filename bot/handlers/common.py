import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import database as db
from bot.middlewares.role_check import _get_effective_role
from bot.utils.commands import set_commands_for_user

logger = logging.getLogger(__name__)

_SECTION_COMMON = """🤖 <b>Общие команды</b>
/start — приветствие и информация о роли
/help — список доступных команд
"""

_SECTION_TEACHER = """
👨‍🏫 <b>Преподаватель</b>
/my — мои назначенные события
"""

_SECTION_MANAGER = """
📋 <b>Менеджер</b>
/add_doproved — назначить допровед
/add_perenos — назначить перенос
/cancel ID — отменить событие по номеру
/list — все активные события
/list @username — события конкретного преподавателя
/teachers — список преподавателей
"""

_SECTION_ADMIN = """
🔧 <b>Администратор</b>
/addmanager @username — назначить менеджера
/removemanager @username — снять менеджера
/managers — список менеджеров
/addteacher @username — зарегистрировать преподавателя
/removeteacher @username — снять преподавателя
/users — все пользователи бота по ролям
/admins — список администраторов
"""

_SECTION_SUPERADMIN = """
👑 <b>Супер-админ</b>
/addadmin @username — назначить администратора
/removeadmin @username — снять администратора
/transfer @username — передать права супер-админа
"""

HELP_BY_ROLE = {
    db.ROLE_SUPERADMIN: (
        _SECTION_COMMON
        + _SECTION_MANAGER
        + _SECTION_ADMIN
        + _SECTION_SUPERADMIN
    ),
    db.ROLE_ADMIN: (
        _SECTION_COMMON
        + _SECTION_MANAGER
        + _SECTION_ADMIN
    ),
    db.ROLE_MANAGER: (
        _SECTION_COMMON
        + _SECTION_MANAGER
    ),
    db.ROLE_TEACHER: (
        _SECTION_COMMON
        + _SECTION_TEACHER
    ),
    db.ROLE_BLOCKED: "⛔ У вас нет доступа к боту.\nОбратитесь к администратору школы Котокод.",
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.full_name)

    # Если это супер-админ из .env — гарантируем корректную запись в БД
    from bot.config import SUPERADMIN_ID
    if user.id == SUPERADMIN_ID:
        db.ensure_superadmin(user.id, user.username, user.full_name)

    role = _get_effective_role(user.id)

    # Собираем список всех активных ролей пользователя
    db_user = db.get_user(user.id)
    roles_active = []
    if db_user:
        if db_user["is_superadmin"]: roles_active.append("Супер-админ 👑")
        if db_user["is_admin"]:      roles_active.append("Администратор 🔧")
        if db_user["is_manager"]:    roles_active.append("Менеджер 📋")
        if db_user["is_teacher"]:    roles_active.append("Преподаватель 👨‍🏫")
    if not roles_active:
        roles_active = ["Нет доступа ⛔"]

    roles_str = ", ".join(roles_active)
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
    role = _get_effective_role(user.id)

    # Для пользователей с несколькими ролями — показываем все доступные секции
    db_user = db.get_user(user.id)
    if db_user:
        sections = [_SECTION_COMMON]
        # Добавляем секции по всем активным ролям
        if db_user["is_teacher"] and not (db_user["is_admin"] or db_user["is_manager"] or db_user["is_superadmin"]):
            sections.append(_SECTION_TEACHER)
        if db_user["is_manager"] or db_user["is_admin"] or db_user["is_superadmin"]:
            sections.append(_SECTION_MANAGER)
        if db_user["is_admin"] or db_user["is_superadmin"]:
            sections.append(_SECTION_ADMIN)
        if db_user["is_superadmin"]:
            sections.append(_SECTION_SUPERADMIN)
        text = "".join(sections)
    else:
        text = HELP_BY_ROLE.get(role, HELP_BY_ROLE[db.ROLE_BLOCKED])

    await update.message.reply_text(text.strip(), parse_mode="HTML")


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Реакция на любую неизвестную команду."""
    command = update.message.text.split()[0] if update.message.text else "?"
    await update.message.reply_text(
        f"Команда <code>{command}</code> не найдена.\n"
        f"Используй /help для списка доступных команд.",
        parse_mode="HTML",
    )
