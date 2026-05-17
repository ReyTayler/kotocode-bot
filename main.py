import asyncio
import logging

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from bot.config import BOT_TOKEN, SUPERADMIN_ID, setup_logging
from bot import database as db
from bot.scheduler import setup_scheduler, reschedule_all_active

from bot.handlers.common import start, help_cmd, unknown_command
from bot.handlers.manager import (
    get_doproved_conv_handler,
    get_perenos_conv_handler,
    cancel_event,
    cancel_event_by_id,
    list_events,
    my_events,
)
from bot.handlers.admin import (
    add_manager, remove_manager, list_managers,
    add_teacher, remove_teacher, list_teachers,
)
from bot.handlers.superadmin import (
    add_admin, remove_admin, list_admins,
    get_transfer_conv_handler,
)
from bot.utils.commands import set_commands_for_all_users

setup_logging()
logger = logging.getLogger(__name__)


def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Фильтр: только личные сообщения
    private = filters.ChatType.PRIVATE

    # ── Общие команды ──────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", start, filters=private))
    app.add_handler(CommandHandler("help", help_cmd, filters=private))

    # ── FSM: добавление событий ────────────────────────────────────────────────
    app.add_handler(get_doproved_conv_handler())
    app.add_handler(get_perenos_conv_handler())

    # ── FSM: передача прав ─────────────────────────────────────────────────────
    app.add_handler(get_transfer_conv_handler())

    # ── Команды менеджера ──────────────────────────────────────────────────────
    app.add_handler(CommandHandler("cancel", cancel_event, filters=private))
    app.add_handler(MessageHandler(filters.Regex(r"^/cancel_\d+$") & private, cancel_event_by_id))
    app.add_handler(CommandHandler("list", list_events, filters=private))
    app.add_handler(CommandHandler("my", my_events, filters=private))

    # ── Команды администратора ─────────────────────────────────────────────────
    app.add_handler(CommandHandler("addmanager", add_manager, filters=private))
    app.add_handler(CommandHandler("removemanager", remove_manager, filters=private))
    app.add_handler(CommandHandler("managers", list_managers, filters=private))
    app.add_handler(CommandHandler("addteacher", add_teacher, filters=private))
    app.add_handler(CommandHandler("removeteacher", remove_teacher, filters=private))
    app.add_handler(CommandHandler("teachers", list_teachers, filters=private))

    # ── Команды супер-админа ───────────────────────────────────────────────────
    app.add_handler(CommandHandler("addadmin", add_admin, filters=private))
    app.add_handler(CommandHandler("removeadmin", remove_admin, filters=private))
    app.add_handler(CommandHandler("admins", list_admins, filters=private))

    # ── Неизвестные команды — ВСЕГДА ПОСЛЕДНИМ ────────────────────────────────
    app.add_handler(MessageHandler(filters.COMMAND & private, unknown_command))

    return app


async def main():
    # Инициализация БД
    db.init_db()

    # Гарантируем что супер-админ из .env есть в БД
    # (имя/username появятся после первого /start)
    logger.info("Супер-админ из .env: telegram_id=%s", SUPERADMIN_ID)

    app = build_app()

    # Настраиваем планировщик
    scheduler = setup_scheduler(app.bot)
    scheduler.start()
    logger.info("Планировщик запущен")

    # Восстанавливаем напоминания для активных событий после перезапуска
    reschedule_all_active()
    logger.info("Бот запущен")

    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        # Устанавливаем команды для всех пользователей из БД
        await set_commands_for_all_users(app.bot)
        # Держим бот запущенным
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