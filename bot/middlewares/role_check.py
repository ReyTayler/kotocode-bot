import logging
from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from bot import database as db
from bot.config import SUPERADMIN_ID

logger = logging.getLogger(__name__)


def _get_user_with_fallback(telegram_id: int):
    """
    Возвращает строку пользователя из БД.
    Для супер-админа из .env гарантирует наличие записи.
    """
    return db.get_user(telegram_id)


def _get_effective_role(telegram_id: int) -> str:
    """
    Возвращает наивысшую роль пользователя.
    Приоритет: is_superadmin в БД > SUPERADMIN_ID в .env > флаги > blocked
    """
    # Аварийный доступ через .env
    if telegram_id == SUPERADMIN_ID:
        return db.ROLE_SUPERADMIN

    user = db.get_user(telegram_id)
    if not user:
        return db.ROLE_BLOCKED

    return db.get_primary_role(user)


def is_superadmin(telegram_id: int) -> bool:
    if telegram_id == SUPERADMIN_ID:
        return True
    user = db.get_user(telegram_id)
    return bool(user and user["is_superadmin"])


def is_admin_or_above(telegram_id: int) -> bool:
    if telegram_id == SUPERADMIN_ID:
        return True
    user = db.get_user(telegram_id)
    return bool(user and (user["is_superadmin"] or user["is_admin"]))


def is_manager_or_above(telegram_id: int) -> bool:
    if telegram_id == SUPERADMIN_ID:
        return True
    user = db.get_user(telegram_id)
    return bool(user and (user["is_superadmin"] or user["is_admin"] or user["is_manager"]))


def is_teacher_or_above(telegram_id: int) -> bool:
    if telegram_id == SUPERADMIN_ID:
        return True
    user = db.get_user(telegram_id)
    return bool(user and (
        user["is_superadmin"] or user["is_admin"] or
        user["is_manager"]    or user["is_teacher"]
    ))


def require_role(check_fn: Callable[[int], bool], deny_msg: str = None):
    """
    Декоратор для хендлеров.
    Пример:
        @require_role(is_manager_or_above)
        async def my_handler(update, context): ...
    """
    def decorator(handler: Callable):
        @wraps(handler)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user = update.effective_user
            if not user:
                return

            db.upsert_user(user.id, user.username, user.full_name)

            if not check_fn(user.id):
                msg = deny_msg or "⛔ У вас нет доступа к этой команде."
                await update.message.reply_text(msg)
                logger.warning(
                    "Отказ в доступе: user_id=%s username=%s команда=%s",
                    user.id, user.username,
                    update.message.text if update.message else "?",
                )
                return

            return await handler(update, context)
        return wrapper
    return decorator
