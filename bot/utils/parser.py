import re
import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from bot.config import TIMEZONE

logger = logging.getLogger(__name__)


@dataclass
class ParsedEvent:
    teacher_username: str       # без @
    group_name: str
    lesson_number: str
    scheduled_at: datetime      # timezone-aware
    children: str
    comment: str


class ParseError(Exception):
    """Ошибка парсинга шаблона с понятным сообщением для пользователя."""
    pass


def parse_template(text: str) -> ParsedEvent:
    """
    Парсит заполненный шаблон вида:
        @username
        Название группы/индива
        Урок №
        Дата проведения - дд.мм чч:мм
        Дети на это время
        Комментарий

    Возвращает ParsedEvent или бросает ParseError.
    """
    lines = [line.strip() for line in text.strip().splitlines()]
    lines = [l for l in lines if l]  # убираем пустые строки

    if len(lines) < 5:
        raise ParseError(
            "Не хватает строк в шаблоне.\n"
            "Шаблон должен содержать минимум 5 заполненных строк."
        )

    # Строка 1 — @username
    username_raw = lines[0]
    if not username_raw.startswith("@"):
        raise ParseError(
            f"Первая строка должна быть @username преподавателя.\n"
            f"Получено: <code>{username_raw}</code>"
        )
    teacher_username = username_raw.lstrip("@").strip()
    if not teacher_username:
        raise ParseError("Username преподавателя не может быть пустым.")

    # Строка 2 — группа
    group_name = lines[1]
    if not group_name:
        raise ParseError("Название группы не может быть пустым.")

    # Строка 3 — номер урока
    lesson_number = lines[2]
    # Убираем префикс "Урок №" и проверяем что осталось число
    lesson_clean = re.sub(r"^урок\s*[№#]?\s*", "", lesson_number, flags=re.IGNORECASE).strip()
    if not lesson_clean or not re.search(r"\d", lesson_clean):
        raise ParseError(
            f"Номер урока не заполнен или не содержит числа.\n"
            f"Получено: <code>{lesson_number}</code>\n"
            f"Пример правильного заполнения: <code>Урок №12</code>"
        )

    # Строка 4 — дата (ищем паттерн дд.мм чч:мм или дд.мм.гггг чч:мм)
    date_line = lines[3]
    scheduled_at = _parse_date(date_line)
    _validate_future(scheduled_at)

    # Строка 5 — дети
    children_line = lines[4]
    # убираем возможные префиксы типа "Дети:" "Дети на это время:"
    children = re.sub(r"^дети[^:]*:\s*", "", children_line, flags=re.IGNORECASE).strip()
    if not children:
        children = children_line

    # Строка 6 — комментарий (опционально)
    comment = lines[5] if len(lines) >= 6 else ""
    comment = re.sub(r"^комментарий[^:]*:\s*", "", comment, flags=re.IGNORECASE).strip()

    return ParsedEvent(
        teacher_username=teacher_username,
        group_name=group_name,
        lesson_number=lesson_number,
        scheduled_at=scheduled_at,
        children=children,
        comment=comment,
    )


def _validate_future(scheduled_at: datetime) -> None:
    """Проверяет что дата события в будущем."""
    now = datetime.now(TIMEZONE)
    if scheduled_at <= now:
        raise ParseError(
            f"Дата проведения уже в прошлом: <b>{scheduled_at.strftime('%d.%m.%Y %H:%M')}</b>\n"
            "Укажи будущую дату и время."
        )


def validate_teacher(teacher_username: str) -> None:
    """
    Проверяет что преподаватель с таким username есть в БД и имеет роль teacher.
    Бросает ParseError если не найден.
    """
    from bot import database as db
    user = db.get_user_by_username(teacher_username)
    if not user:
        raise ParseError(
            f"Преподаватель @{teacher_username} не найден в системе.\n"
            "Попроси его написать боту /start, затем повтори."
        )
    if user["role"] not in (db.ROLE_TEACHER, db.ROLE_ADMIN, db.ROLE_SUPERADMIN):
        raise ParseError(
            f"Пользователь @{teacher_username} не является преподавателем.\n"
            "Проверь правильность username."
        )


def _parse_date(date_line: str) -> datetime:
    """
    Поддерживаемые форматы:
        20.01 15:00
        20.01.2025 15:00
        Дата проведения - 20.01 15:00
        Дата проведения - 20.01.2025 15:00
    """
    # Убираем всё до дефиса если есть
    clean = re.sub(r"^[^-]+-\s*", "", date_line).strip()

    now = datetime.now(TIMEZONE)
    year = now.year

    # Пробуем дд.мм.гггг чч:мм
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})", clean)
    if m:
        day, month, year, hour, minute = map(int, m.groups())
        return _make_dt(day, month, year, hour, minute)

    # Пробуем дд.мм чч:мм
    m = re.search(r"(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})", clean)
    if m:
        day, month, hour, minute = map(int, m.groups())
        dt = _make_dt(day, month, year, hour, minute)
        return dt

    raise ParseError(
        f"Не удалось распознать дату в строке:\n<code>{date_line}</code>\n\n"
        "Используй формат: <b>дд.мм чч:мм</b> или <b>дд.мм.гггг чч:мм</b>\n"
        "Например: <code>20.01 15:00</code>"
    )


def _make_dt(day: int, month: int, year: int, hour: int, minute: int) -> datetime:
    try:
        return TIMEZONE.localize(datetime(year, month, day, hour, minute))
    except ValueError as e:
        raise ParseError(f"Некорректная дата: {day:02d}.{month:02d}.{year} {hour:02d}:{minute:02d}\n{e}")
