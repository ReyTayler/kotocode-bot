"""
Управление меню команд в Telegram.
Логика какие команды кому показывать — в RoleService.
Здесь только вызовы Bot API.
"""
import logging
from telegram import Bot, BotCommandScopeChat, BotCommandScopeAllGroupChats
from bot import database as db
from bot.services.role_service import get_role_service

logger = logging.getLogger(__name__)


async def set_commands_for_user(bot: Bot, telegram_id: int) -> None:
    """Устанавливает список команд для конкретного пользователя."""
    commands = get_role_service().get_commands(telegram_id)
    try:
        await bot.set_my_commands(
            commands=commands,
            scope=BotCommandScopeChat(chat_id=telegram_id),
        )
        logger.info("Команды установлены для user_id=%s (%d команд)", telegram_id, len(commands))
    except Exception as e:
        logger.warning("Не удалось установить команды для user_id=%s: %s", telegram_id, e)


async def set_commands_for_all_users(bot: Bot) -> None:
    """Устанавливает команды для всех пользователей при старте бота."""
    # Очищаем команды в группах
    try:
        await bot.set_my_commands(commands=[], scope=BotCommandScopeAllGroupChats())
        logger.info("Команды в групповых чатах очищены")
    except Exception as e:
        logger.warning("Не удалось очистить команды в группах: %s", e)

    # Дефолтные команды для незарегистрированных
    try:
        rs = get_role_service()
        default_commands = rs.get_commands(0)  # 0 — несуществующий id, вернёт COMMANDS_COMMON
        await bot.set_my_commands(commands=default_commands)
        logger.info("Дефолтные команды установлены")
    except Exception as e:
        logger.warning("Не удалось установить дефолтные команды: %s", e)

    # Персональные команды для каждого пользователя в БД
    for role in [db.ROLE_SUPERADMIN, db.ROLE_ADMIN, db.ROLE_MANAGER, db.ROLE_TEACHER]:
        for user in db.get_users_by_role(role):
            await set_commands_for_user(bot, user["telegram_id"])
