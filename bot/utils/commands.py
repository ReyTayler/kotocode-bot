import logging
from telegram import Bot, BotCommand, BotCommandScopeChat
from bot import database as db
from bot.middlewares.role_check import _get_effective_role

logger = logging.getLogger(__name__)

# ─── Команды по ролям ────────────────────────────────────────────────────────
# Каждая роль видит свои команды + все команды ролей ниже

COMMANDS_COMMON = [
    BotCommand("start", "Приветствие и информация о роли"),
    BotCommand("help", "Список доступных команд"),
]

COMMANDS_TEACHER = [
    BotCommand("my", "Мои назначенные события"),
]

COMMANDS_MANAGER = [
    BotCommand("add_doproved", "Назначить допровед"),
    BotCommand("add_perenos", "Назначить перенос"),
    BotCommand("cancel", "Отменить событие — /cancel ID"),
    BotCommand("list", "Все активные события"),
    BotCommand("teachers", "Список преподавателей"),
]

COMMANDS_ADMIN = [
    BotCommand("addmanager", "Назначить менеджера"),
    BotCommand("removemanager", "Снять менеджера"),
    BotCommand("managers", "Список менеджеров"),
    BotCommand("addteacher", "Зарегистрировать преподавателя"),
    BotCommand("removeteacher", "Снять преподавателя"),
    BotCommand("users", "Все пользователи бота по ролям"),
    BotCommand("admins", "Список администраторов"),
]

COMMANDS_SUPERADMIN = [
    BotCommand("addadmin", "Назначить администратора"),
    BotCommand("removeadmin", "Снять администратора"),
    BotCommand("transfer", "Передать права супер-админа"),
]


def _get_commands_for_role(role: str) -> list[BotCommand]:
    """Возвращает полный список команд для роли (включая команды ролей ниже)."""
    if role == db.ROLE_SUPERADMIN:
        return (
            COMMANDS_COMMON
            + COMMANDS_MANAGER
            + COMMANDS_ADMIN
            + COMMANDS_SUPERADMIN
        )
    elif role == db.ROLE_ADMIN:
        return (
            COMMANDS_COMMON
            + COMMANDS_MANAGER
            + COMMANDS_ADMIN
        )
    elif role == db.ROLE_MANAGER:
        return COMMANDS_COMMON + COMMANDS_MANAGER
    elif role == db.ROLE_TEACHER:
        return COMMANDS_COMMON + COMMANDS_TEACHER
    else:
        return COMMANDS_COMMON


async def set_commands_for_user(bot: Bot, telegram_id: int) -> None:
    """Устанавливает список команд для конкретного пользователя."""
    role = _get_effective_role(telegram_id)
    commands = _get_commands_for_role(role)
    try:
        await bot.set_my_commands(
            commands=commands,
            scope=BotCommandScopeChat(chat_id=telegram_id),
        )
        logger.info("Команды установлены для user_id=%s role=%s", telegram_id, role)
    except Exception as e:
        logger.warning("Не удалось установить команды для user_id=%s: %s", telegram_id, e)


async def set_commands_for_all_users(bot: Bot) -> None:
    """
    Устанавливает команды для всех известных пользователей при старте бота.
    Также устанавливает дефолтные команды (для незарегистрированных).
    Очищает команды во всех групповых чатах.
    """
    # Очищаем команды для всех типов групповых чатов
    from telegram import BotCommandScopeAllGroupChats
    try:
        await bot.set_my_commands(commands=[], scope=BotCommandScopeAllGroupChats())
        logger.info("Команды в групповых чатах очищены")
    except Exception as e:
        logger.warning("Не удалось очистить команды в группах: %s", e)

    # Дефолтные команды для личных чатов (незарегистрированные)
    try:
        await bot.set_my_commands(commands=COMMANDS_COMMON)
        logger.info("Дефолтные команды установлены")
    except Exception as e:
        logger.warning("Не удалось установить дефолтные команды: %s", e)

    # Персональные команды для каждого пользователя в БД
    roles = [db.ROLE_SUPERADMIN, db.ROLE_ADMIN, db.ROLE_MANAGER, db.ROLE_TEACHER]
    for role in roles:
        users = db.get_users_by_role(role)
        for user in users:
            await set_commands_for_user(bot, user["telegram_id"])
