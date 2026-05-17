"""
Утилиты для отправки уведомлений пользователям в личку.
Все функции graceful — если пользователь не начал диалог с ботом,
ошибка логируется и игнорируется.
"""
import logging
from telegram import Bot
from bot.utils.formatters import fmt_event_announce, fmt_event_reminder

logger = logging.getLogger(__name__)


async def notify_user(bot: Bot, telegram_id: int, text: str) -> bool:
    """
    Отправляет личное сообщение пользователю.
    Возвращает True если успешно, False если пользователь не начал диалог.
    """
    try:
        await bot.send_message(chat_id=telegram_id, text=text, parse_mode="HTML")
        return True
    except Exception as e:
        logger.warning("Не удалось отправить личное сообщение user_id=%s: %s", telegram_id, e)
        return False


async def notify_event_assigned(bot: Bot, teacher_telegram_id: int, event) -> None:
    """Уведомление преподавателю о назначении допровода/переноса."""
    from bot.utils.formatters import TYPE_LABELS, fmt_dt
    emoji, label = TYPE_LABELS.get(event["type"], ("📋", event["type"]))
    comment = f"\n💬 {event['comment']}" if event["comment"] else ""
    text = (
        f"{emoji} <b>Тебе назначен {label.lower()}</b>\n\n"
        f"📚 {event['group_name']} | {event['lesson_number']}\n"
        f"📅 {fmt_dt(event['scheduled_at'])}\n"
        f"👦 Дети: {event['children']}"
        f"{comment}\n"
        f"🆔 #{event['id']}"
    )
    await notify_user(bot, teacher_telegram_id, text)


async def notify_event_cancelled(bot: Bot, teacher_telegram_id: int, event) -> None:
    """Уведомление преподавателю об отмене допровода/переноса."""
    from bot.utils.formatters import TYPE_LABELS, fmt_dt
    emoji, label = TYPE_LABELS.get(event["type"], ("📋", event["type"]))
    text = (
        f"❌ <b>{label} отменён</b>\n\n"
        f"📚 {event['group_name']} | {event['lesson_number']}\n"
        f"📅 {fmt_dt(event['scheduled_at'])}\n"
        f"🆔 #{event['id']}"
    )
    await notify_user(bot, teacher_telegram_id, text)


async def notify_reminder_dm(bot: Bot, teacher_telegram_id: int, event, hours: int) -> None:
    """Напоминание преподавателю в личку."""
    text = fmt_event_reminder(event, hours)
    await notify_user(bot, teacher_telegram_id, text)


async def notify_role_granted(bot: Bot, telegram_id: int, role: str) -> None:
    """Уведомление пользователю о выдаче роли."""
    from bot.database import ROLE_ADMIN, ROLE_MANAGER, ROLE_TEACHER
    messages = {
        ROLE_ADMIN:   "🔧 Тебе выданы права <b>Администратора</b> бота Котокод.\nНапиши /help для списка команд.",
        ROLE_MANAGER: "📋 Тебе выданы права <b>Менеджера</b> бота Котокод.\nНапиши /help для списка команд.",
        ROLE_TEACHER: "👨‍🏫 Ты добавлен как <b>Преподаватель</b> в бота Котокод.\nНапиши /help для списка команд.",
    }
    text = messages.get(role)
    if text:
        await notify_user(bot, telegram_id, text)


async def notify_role_revoked(bot: Bot, telegram_id: int, role_label: str) -> None:
    """Уведомление пользователю о снятии роли."""
    text = f"⛔ Твои права <b>{role_label}</b> в боте Котокод были сняты."
    await notify_user(bot, telegram_id, text)