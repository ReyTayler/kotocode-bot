import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.base import JobLookupError

from bot.config import TIMEZONE, GENERAL_CHAT_ID
from bot import database as db
from bot.utils.formatters import fmt_event_reminder

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_bot = None  # глобальная ссылка, не сериализуется


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    return _scheduler


# ─── Отправка напоминания ─────────────────────────────────────────────────────

async def _send_reminder(event_id: int, reminder_type: str) -> None:
    """Вызывается планировщиком точно в нужное время."""
    if _bot is None:
        logger.error("_send_reminder: bot не инициализирован")
        return

    event = db.get_event(event_id)

    # Событие могли отменить пока ждали напоминания
    if not event or event["status"] != db.STATUS_ACTIVE:
        logger.info(
            "Напоминание %s для события #%s пропущено — статус: %s",
            reminder_type, event_id,
            event["status"] if event else "не найдено",
        )
        return

    # Защита от дублей
    col = "reminded_24h" if reminder_type == "24h" else "reminded_1h"
    if event[col]:
        logger.info("Напоминание %s для #%s уже отправлено — пропускаем", reminder_type, event_id)
        return

    hours = 24 if reminder_type == "24h" else 1
    try:
        text = fmt_event_reminder(event, hours)
        # Отправляем в общий чат
        await _bot.send_message(
            chat_id=GENERAL_CHAT_ID,
            text=text,
            parse_mode="HTML",
        )
        # Отправляем в личку преподавателю если он есть в БД
        if event["teacher_telegram_id"]:
            from bot.utils.notifications import notify_reminder_dm
            await notify_reminder_dm(_bot, event["teacher_telegram_id"], event, hours)

        db.mark_reminded(event_id, reminder_type)
        logger.info(
            "Напоминание %s отправлено для события #%s (@%s)",
            reminder_type, event_id, event["teacher_username"],
        )
    except Exception as e:
        logger.error(
            "Ошибка при отправке напоминания %s для события #%s: %s",
            reminder_type, event_id, e,
        )


# ─── Планирование напоминаний для одного события ─────────────────────────────

def schedule_reminders(event_id: int, scheduled_at: datetime) -> None:
    """
    Планирует напоминания за 24ч и за 1ч для события.
    Безопасно вызывать повторно — replace_existing=True.
    Если время уже прошло — молча пропускает.
    """
    scheduler = get_scheduler()
    now = datetime.now(TIMEZONE)

    reminders = [
        ("24h", scheduled_at - timedelta(hours=24)),
        ("1h",  scheduled_at - timedelta(hours=1)),
    ]

    for reminder_type, run_at in reminders:
        job_id = f"remind_{reminder_type}_{event_id}"

        # Проверяем флаг в БД — вдруг уже напомнили до перезапуска
        event = db.get_event(event_id)
        if event:
            col = "reminded_24h" if reminder_type == "24h" else "reminded_1h"
            if event[col]:
                logger.debug(
                    "Событие #%s: напоминание %s уже отправлено, пропускаем",
                    event_id, reminder_type,
                )
                continue

        if run_at <= now:
            logger.info(
                "Событие #%s: время напоминания %s уже прошло (%s), пропускаем",
                event_id, reminder_type, run_at.strftime("%d.%m %H:%M"),
            )
            continue

        scheduler.add_job(
            _send_reminder,
            trigger="date",
            run_date=run_at,
            args=[event_id, reminder_type],
            id=job_id,
            replace_existing=True,
            name=f"Напоминание {reminder_type} для события #{event_id}",
            misfire_grace_time=600,  # если бот был недоступен до 10 минут — всё равно отправит
        )
        logger.info(
            "Запланировано напоминание %s для события #%s на %s",
            reminder_type, event_id, run_at.strftime("%d.%m %H:%M"),
        )


def cancel_reminders(event_id: int) -> None:
    """Удаляет запланированные напоминания при отмене события."""
    scheduler = get_scheduler()
    for reminder_type in ("24h", "1h"):
        job_id = f"remind_{reminder_type}_{event_id}"
        try:
            scheduler.remove_job(job_id)
            logger.info(
                "Напоминание %s для события #%s удалено из планировщика",
                reminder_type, event_id,
            )
        except JobLookupError:
            pass  # джоб уже сработал или не существовал — норма


# ─── Восстановление после перезапуска ────────────────────────────────────────

def reschedule_all_active() -> None:
    """
    Вызывается при старте бота.
    Пересоздаёт задачи для всех активных событий у которых
    напоминания ещё не были отправлены.
    """
    events = db.get_active_events()
    count = 0
    for event in events:
        if event["reminded_24h"] and event["reminded_1h"]:
            continue
        try:
            scheduled_at = TIMEZONE.localize(
                datetime.strptime(event["scheduled_at"], "%Y-%m-%d %H:%M:%S")
            )
            schedule_reminders(event["id"], scheduled_at)
            count += 1
        except Exception as e:
            logger.error(
                "Ошибка при восстановлении напоминаний для события #%s: %s",
                event["id"], e,
            )
    logger.info("Восстановлено напоминаний для %d активных событий", count)


# ─── Настройка планировщика ───────────────────────────────────────────────────

def setup_scheduler(bot) -> AsyncIOScheduler:
    global _bot
    _bot = bot

    scheduler = get_scheduler()

    # Раз в час помечаем прошедшие события как выполненные
    scheduler.add_job(
        db.mark_done_past_events,
        trigger="interval",
        hours=1,
        id="mark_done",
        replace_existing=True,
        name="Архивирование прошедших событий",
    )

    logger.info("Планировщик настроен")
    return scheduler