import logging
from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from bot import database as db
from bot.config import SUPERADMIN_ID

logger = logging.getLogger(__name__)


def _get_effective_role(telegram_id: int) -> str:
    """
    Определяет роль пользователя.
    Приоритет: is_superadmin в БД > SUPERADMIN_ID в .env > роль из БД > blocked
    """
    # Проверяем супер-админа из БД (после передачи прав)
    sa = db.get_superadmin()
    if sa and sa["telegram_id"] == telegram_id:
        return db.ROLE_SUPERADMIN

    # Проверяем супер-админа из .env (первый запуск / аварийный доступ)
    if telegram_id == SUPERADMIN_ID:
        return db.ROLE_SUPERADMIN

    # Берём роль из БД
    user = db.get_user(telegram_id)
    if user:
        return user["role"]

    return db.ROLE_BLOCKED


def is_superadmin(telegram_id: int) -> bool:
    return _get_effective_role(telegram_id) == db.ROLE_SUPERADMIN


def is_admin_or_above(telegram_id: int) -> bool:
    return _get_effective_role(telegram_id) in (db.ROLE_SUPERADMIN, db.ROLE_ADMIN)


def is_manager_or_above(telegram_id: int) -> bool:
    return _get_effective_role(telegram_id) in (
        db.ROLE_SUPERADMIN, db.ROLE_ADMIN, db.ROLE_MANAGER
    )


def is_teacher_or_above(telegram_id: int) -> bool:
    return _get_effective_role(telegram_id) in (
        db.ROLE_SUPERADMIN, db.ROLE_ADMIN, db.ROLE_MANAGER, db.ROLE_TEACHER
    )


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

            # Обновляем данные пользователя при каждом взаимодействии
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
