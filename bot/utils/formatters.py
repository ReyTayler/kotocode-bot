import sqlite3
from datetime import datetime
from typing import Optional

from bot.config import TIMEZONE
from bot.database import TYPE_DOPROVED, TYPE_PERENOS

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}

TYPE_LABELS = {
    TYPE_DOPROVED: ("📌", "Допровед"),
    TYPE_PERENOS: ("🔄", "Перенос"),
}

DOPROVED_TEMPLATE = """@username
Название группы/индива
Урок №
Дата проведения - дд.мм чч:мм
Дети на это время
Комментарий"""

PERENOS_TEMPLATE = """@username
Название группы/индива
Урок №
Дата проведения - дд.мм чч:мм
Дети на это время
Комментарий"""


def fmt_dt(scheduled_at: str | datetime) -> str:
    """Форматирует дату в читаемый вид: 20 января в 15:00"""
    if isinstance(scheduled_at, str):
        dt = datetime.strptime(scheduled_at, "%Y-%m-%d %H:%M:%S")
        dt = TIMEZONE.localize(dt)
    else:
        dt = scheduled_at
    return f"{dt.day} {MONTHS_RU[dt.month]} в {dt.strftime('%H:%M')}"


def fmt_event_announce(event: sqlite3.Row) -> str:
    """Сообщение в общий чат при назначении события."""
    emoji, label = TYPE_LABELS.get(event["type"], ("📋", event["type"]))
    teacher = f"@{event['teacher_username']}"
    comment = f"\n💬 {event['comment']}" if event["comment"] else ""
    return (
        f"{emoji} <b>{label} назначен</b>\n"
        f"👨‍🏫 {teacher}\n"
        f"📚 {event['group_name']} | {event['lesson_number']}\n"
        f"📅 {fmt_dt(event['scheduled_at'])}\n"
        f"👦 Дети: {event['children']}"
        f"{comment}\n"
        f"🆔 #{event['id']}"
    )


def fmt_event_reminder(event: sqlite3.Row, hours: int) -> str:
    """Напоминание в общий чат."""
    emoji, label = TYPE_LABELS.get(event["type"], ("📋", event["type"]))
    teacher = f"@{event['teacher_username']}"
    if hours == 24:
        time_label = "⏰ Напоминание — <b>завтра</b>"
        time_detail = f"завтра в {datetime.strptime(event['scheduled_at'], '%Y-%m-%d %H:%M:%S').strftime('%H:%M')}"
    else:
        time_label = "🔔 Напоминание — <b>через 1 час</b>"
        time_detail = f"через час в {datetime.strptime(event['scheduled_at'], '%Y-%m-%d %H:%M:%S').strftime('%H:%M')}"

    comment = f"\n💬 {event['comment']}" if event["comment"] else ""
    return (
        f"{time_label}\n"
        f"{teacher}, {time_detail} — {label.lower()}\n"
        f"📚 {event['group_name']} | {event['lesson_number']}\n"
        f"👦 Дети: {event['children']}"
        f"{comment}\n"
        f"🆔 #{event['id']}"
    )


def fmt_event_cancelled(event: sqlite3.Row) -> str:
    """Сообщение об отмене в общий чат."""
    emoji, label = TYPE_LABELS.get(event["type"], ("📋", event["type"]))
    return (
        f"❌ <b>{label} отменён</b>\n"
        f"👨‍🏫 @{event['teacher_username']}\n"
        f"📅 {fmt_dt(event['scheduled_at'])}\n"
        f"📚 {event['group_name']} | {event['lesson_number']}\n"
        f"🆔 #{event['id']}"
    )


def fmt_event_list_item(event: sqlite3.Row, index: int, show_actions: bool = True) -> str:
    """Одна строка в списке событий."""
    emoji, label = TYPE_LABELS.get(event["type"], ("📋", event["type"]))
    comment = f"\n   💬 {event['comment']}" if event["comment"] else ""
    actions = (
        f"   ✖️ Отменить: /cancel_{event['id']}\n"
        f"   ✏️ Редактировать: /edit_{event['id']}"
    ) if show_actions else ""
    
    return (
        f"{index}. {emoji} <b>{label}</b> — @{event['teacher_username']}\n"
        f"   📅 {fmt_dt(event['scheduled_at'])}\n"
        f"   📚 {event['group_name']} | {event['lesson_number']}\n"
        f"   👦 {event['children']}"
        f"{comment}\n"
        f"   🆔 #{event['id']}\n"
        f"{actions}"
    )


def fmt_event_card(event: sqlite3.Row) -> str:
    """Карточка события для экрана редактирования."""
    emoji, label = TYPE_LABELS.get(event["type"], ("📋", event["type"]))
    comment = f"\n💬 {event['comment']}" if event["comment"] else ""
    return (
        f"{emoji} <b>{label} #{event['id']}</b>\n"
        f"👨‍🏫 @{event['teacher_username']}\n"
        f"📚 {event['group_name']} | {event['lesson_number']}\n"
        f"📅 {fmt_dt(event['scheduled_at'])}\n"
        f"👦 Дети: {event['children']}"
        f"{comment}\n\n"
        f"Выбери поле для редактирования или нажми <b>Сохранить</b>:"
    )


def fmt_event_updated(event: sqlite3.Row, changed_fields: list, changed_by: str) -> str:
    """Уведомление об изменении события в общий чат."""
    emoji, label = TYPE_LABELS.get(event["type"], ("📋", event["type"]))
    comment = f"\n💬 {event['comment']}" if event["comment"] else ""
    field_names = {
        "group_name":    "Группа",
        "lesson_number": "Номер урока",
        "scheduled_at":  "Дата проведения",
        "children":      "Дети",
        "comment":       "Комментарий",
    }
    if changed_fields:
        fields_str = ", ".join(field_names.get(f, f) for f in changed_fields)
    else:
        fields_str = "данные"
    return (
        f"✏️ <b>{label} #{event['id']} обновлён</b>\n"
        f"Изменено: <b>{fields_str}</b> "
        f"(менеджер @{changed_by})\n\n"
        f"👨‍🏫 @{event['teacher_username']}\n"
        f"📚 {event['group_name']} | {event['lesson_number']}\n"
        f"📅 {fmt_dt(event['scheduled_at'])}\n"
        f"👦 Дети: {event['children']}"
        f"{comment}\n"
        f"🆔 #{event['id']}"
    )


def fmt_preview(parsed, event_type: str) -> str:
    """Превью события перед сохранением."""
    emoji, label = TYPE_LABELS.get(event_type, ("📋", event_type))
    comment = f"\n💬 {parsed.comment}" if parsed.comment else ""
    return (
        f"<b>Проверь данные перед сохранением:</b>\n\n"
        f"{emoji} <b>{label}</b>\n"
        f"👨‍🏫 @{parsed.teacher_username}\n"
        f"📚 {parsed.group_name} | {parsed.lesson_number}\n"
        f"📅 {fmt_dt(parsed.scheduled_at)}\n"
        f"👦 Дети: {parsed.children}"
        f"{comment}\n\n"
        f"Всё верно?"
    )
