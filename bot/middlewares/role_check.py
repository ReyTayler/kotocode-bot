"""
Декораторы проверки прав доступа для хендлеров.
Вся логика ролей — в RoleService. Здесь только обёртка для PTB.
"""
import logging
from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from bot import database as db
from bot.services.role_service import get_role_service, Permission

logger = logging.getLogger(__name__)


# ─── Публичные функции проверки (используются в хендлерах напрямую) ───────────

def is_superadmin(telegram_id: int) -> bool:
    return get_role_service().is_superadmin(telegram_id)

def is_admin_or_above(telegram_id: int) -> bool:
    return get_role_service().is_admin(telegram_id)

def is_manager_or_above(telegram_id: int) -> bool:
    return get_role_service().is_manager(telegram_id)

def is_teacher_or_above(telegram_id: int) -> bool:
    return get_role_service().has_any_role(telegram_id)

def can_manage_events(telegram_id: int) -> bool:
    return get_role_service().has_permission(telegram_id, Permission.MANAGE_EVENTS)


# ─── Для обратной совместимости с common.py ───────────────────────────────────

def _get_effective_role(telegram_id: int) -> str:
    """Возвращает наивысшую роль. Используется только для /start приветствия."""
    from bot.config import SUPERADMIN_ID
    if telegram_id == SUPERADMIN_ID:
        return db.ROLE_SUPERADMIN
    user = db.get_user(telegram_id)
    if not user:
        return db.ROLE_BLOCKED
    return db.get_primary_role(user)


# ─── Декоратор ────────────────────────────────────────────────────────────────

def require_role(check_fn: Callable[[int], bool], deny_msg: str = None):
    """
    Декоратор для хендлеров. Проверяет права перед вызовом.

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
