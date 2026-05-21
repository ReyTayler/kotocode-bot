import asyncio
import logging
import traceback

from telegram import Update
from telegram.error import NetworkError, TimedOut, RetryAfter
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from bot.config import BOT_TOKEN, SUPERADMIN_ID, setup_logging
from bot import database as db
from bot.scheduler import setup_scheduler, reschedule_all_active
from bot.services.role_service import init_role_service

from bot.handlers.common import start, help_cmd, unknown_command
from bot.handlers.events_add import get_doproved_conv_handler, get_perenos_conv_handler
from bot.handlers.events_edit import get_edit_conv_handler
from bot.handlers.events_list import list_events, my_events, cancel_event, cancel_event_by_id
from bot.handlers.admin import (
    add_manager, remove_manager, list_managers,
    add_teacher, remove_teacher, list_teachers,
    list_all_users,
)
from bot.handlers.superadmin import (
    add_admin, remove_admin, list_admins,
    get_transfer_conv_handler,
)
from bot.utils.commands import set_commands_for_all_users

setup_logging()
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный обработчик ошибок."""
    error = context.error

    # Сетевые ошибки — временные, бот сам восстановится, просто логируем коротко
    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning("Сетевая ошибка (временная): %s", error)
        return

    # Flood limit — Telegram просит подождать
    if isinstance(error, RetryAfter):
        logger.warning("Flood limit: ждём %s секунд", error.retry_after)
        return

    # Всё остальное — логируем полный трейсбек
    logger.error("Необработанная ошибка: %s", error)
    logger.error(traceback.format_exc())

    # Уведомляем супер-админа о критической ошибке
    try:
        await context.bot.send_message(
            chat_id=SUPERADMIN_ID,
            text=f"⚠️ <b>Ошибка бота</b>\n<code>{type(error).__name__}: {error}</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass  # если не смогли уведомить — не падаем


def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    private = filters.ChatType.PRIVATE

    # ── Общие ──────────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", start, filters=private))
    app.add_handler(CommandHandler("help",  help_cmd, filters=private))

    # ── FSM: добавление событий ────────────────────────────────────────────────
    app.add_handler(get_doproved_conv_handler())
    app.add_handler(get_perenos_conv_handler())

    # ── FSM: редактирование событий ────────────────────────────────────────────
    app.add_handler(get_edit_conv_handler())

    # ── FSM: передача прав ─────────────────────────────────────────────────────
    app.add_handler(get_transfer_conv_handler())

    # ── События ────────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("cancel", cancel_event, filters=private))
    app.add_handler(MessageHandler(filters.Regex(r"^/cancel_\d+$") & private, cancel_event_by_id))
    app.add_handler(CommandHandler("list", list_events, filters=private))
    app.add_handler(CommandHandler("my",   my_events,   filters=private))

    # ── Администратор ──────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("addmanager",    add_manager,    filters=private))
    app.add_handler(CommandHandler("removemanager", remove_manager, filters=private))
    app.add_handler(CommandHandler("managers",      list_managers,  filters=private))
    app.add_handler(CommandHandler("addteacher",    add_teacher,    filters=private))
    app.add_handler(CommandHandler("removeteacher", remove_teacher, filters=private))
    app.add_handler(CommandHandler("teachers",      list_teachers,  filters=private))
    app.add_handler(CommandHandler("users",         list_all_users, filters=private))

    # ── Супер-админ ────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("addadmin",    add_admin,    filters=private))
    app.add_handler(CommandHandler("removeadmin", remove_admin, filters=private))
    app.add_handler(CommandHandler("admins",      list_admins,  filters=private))

    # ── Неизвестные команды — ВСЕГДА ПОСЛЕДНИМ ────────────────────────────────
    app.add_handler(MessageHandler(filters.COMMAND & private, unknown_command))

    # ── Глобальный обработчик ошибок ───────────────────────────────────────────
    app.add_error_handler(error_handler)

    return app


async def main():
    db.init_db()

    # Инициализируем RoleService — единственное место где знают про SUPERADMIN_ID
    init_role_service(SUPERADMIN_ID)
    logger.info("RoleService инициализирован, superadmin_id=%s", SUPERADMIN_ID)

    app = build_app()

    scheduler = setup_scheduler(app.bot)
    scheduler.start()
    logger.info("Планировщик запущен")

    reschedule_all_active()
    logger.info("Бот запущен")

    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await set_commands_for_all_users(app.bot)
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Бот остановлен вручную")
    finally:
        scheduler.shutdown(wait=False)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
