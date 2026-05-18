import sqlite3
import logging
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

from bot.config import DB_PATH, TIMEZONE

logger = logging.getLogger(__name__)

# ─── Роли ────────────────────────────────────────────────────────────────────
ROLE_SUPERADMIN = "superadmin"
ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_TEACHER = "teacher"
ROLE_BLOCKED = "blocked"

# ─── Типы событий ─────────────────────────────────────────────────────────────
TYPE_DOPROVED = "doproved"
TYPE_PERENOS = "perenos"

# ─── Статусы событий ──────────────────────────────────────────────────────────
STATUS_ACTIVE = "active"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # безопасная конкурентная запись
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── Инициализация БД ─────────────────────────────────────────────────────────

def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id  INTEGER UNIQUE NOT NULL,
                username     TEXT,
                full_name    TEXT,
                role         TEXT NOT NULL DEFAULT 'blocked',
                is_superadmin BOOLEAN NOT NULL DEFAULT 0,
                added_by     INTEGER,
                created_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                type              TEXT NOT NULL,
                teacher_username  TEXT NOT NULL,
                teacher_telegram_id INTEGER,
                group_name        TEXT NOT NULL,
                lesson_number     TEXT NOT NULL,
                scheduled_at      TEXT NOT NULL,
                children          TEXT NOT NULL,
                comment           TEXT,
                created_by        INTEGER NOT NULL,
                created_at        TEXT NOT NULL,
                status            TEXT NOT NULL DEFAULT 'active',
                reminded_24h      INTEGER NOT NULL DEFAULT 0,
                reminded_1h       INTEGER NOT NULL DEFAULT 0
            );
        """)
    logger.info("БД инициализирована: %s", DB_PATH)


# ─── Пользователи ─────────────────────────────────────────────────────────────

def get_user(telegram_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()


def get_user_by_username(username: str) -> Optional[sqlite3.Row]:
    """username без @"""
    username = username.lstrip("@")
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


def upsert_user(telegram_id: int, username: Optional[str], full_name: str) -> None:
    """Создаёт пользователя если не существует, обновляет username/full_name."""
    now = _now_str()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE users SET username = ?, full_name = ? WHERE telegram_id = ?",
                (username, full_name, telegram_id),
            )
        else:
            conn.execute(
                """INSERT INTO users (telegram_id, username, full_name, role, created_at)
                   VALUES (?, ?, ?, 'blocked', ?)""",
                (telegram_id, username, full_name, now),
            )


VALID_ROLES = {ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_MANAGER, ROLE_TEACHER, ROLE_BLOCKED}


def set_role(telegram_id: int, role: str, added_by: int) -> bool:
    """Возвращает True если пользователь найден и роль обновлена."""
    if role not in VALID_ROLES:
        raise ValueError(f"Недопустимая роль: {role}")
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE users SET role = ?, added_by = ? WHERE telegram_id = ?",
            (role, added_by, telegram_id),
        )
        return cur.rowcount > 0


def set_role_by_username(username: str, role: str, added_by: int) -> bool:
    username = username.lstrip("@")
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE users SET role = ?, added_by = ? WHERE username = ?",
            (role, added_by, username),
        )
        return cur.rowcount > 0


def get_superadmin() -> Optional[sqlite3.Row]:
    """Возвращает супер-админа из БД (после передачи прав)."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE is_superadmin = 1"
        ).fetchone()


def transfer_superadmin(from_id: int, to_telegram_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET is_superadmin = 0 WHERE telegram_id = ?", (from_id,))
        conn.execute(
            "UPDATE users SET is_superadmin = 1, role = ? WHERE telegram_id = ?",
            (ROLE_ADMIN, to_telegram_id),
        )


def get_users_by_role(role: str) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE role = ? ORDER BY full_name", (role,)
        ).fetchall()


def ensure_superadmin(telegram_id: int, username: Optional[str], full_name: str) -> None:
    """Гарантирует что супер-админ из .env есть в БД."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        now = _now_str()
        if existing:
            conn.execute(
                "UPDATE users SET role = ?, is_superadmin = 1, username = ?, full_name = ? WHERE telegram_id = ?",
                (ROLE_ADMIN, username, full_name, telegram_id),
            )
        else:
            conn.execute(
                """INSERT INTO users (telegram_id, username, full_name, role, is_superadmin, created_at)
                   VALUES (?, ?, ?, ?, 1, ?)""",
                (telegram_id, username, full_name, ROLE_ADMIN, now),
            )


# ─── События ──────────────────────────────────────────────────────────────────

def add_event(
    event_type: str,
    teacher_username: str,
    teacher_telegram_id: Optional[int],
    group_name: str,
    lesson_number: str,
    scheduled_at: datetime,
    children: str,
    comment: str,
    created_by: int,
) -> int:
    now = _now_str()
    teacher_username = teacher_username.lstrip("@")
    scheduled_str = scheduled_at.strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO events
               (type, teacher_username, teacher_telegram_id, group_name, lesson_number,
                scheduled_at, children, comment, created_by, created_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            (
                event_type, teacher_username, teacher_telegram_id,
                group_name, lesson_number, scheduled_str,
                children, comment, created_by, now,
            ),
        )
        return cur.lastrowid


def get_event(event_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()


# Допустимые поля для редактирования
EDITABLE_FIELDS = {"group_name", "lesson_number", "scheduled_at", "children", "comment"}


def update_event_field(event_id: int, field: str, value: str) -> bool:
    """Обновляет одно поле активного события. Возвращает True если успешно."""
    if field not in EDITABLE_FIELDS:
        raise ValueError(f"Поле {field} не доступно для редактирования")
    with get_conn() as conn:
        if field == "scheduled_at":
            # Сбрасываем флаги напоминаний — дата изменилась, нужно напомнить заново
            cur = conn.execute(
                "UPDATE events SET scheduled_at = ?, reminded_24h = 0, reminded_1h = 0 "
                "WHERE id = ? AND status = 'active'",
                (value, event_id),
            )
        else:
            cur = conn.execute(
                f"UPDATE events SET {field} = ? WHERE id = ? AND status = 'active'",
                (value, event_id),
            )
        return cur.rowcount > 0


def cancel_event(event_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE events SET status = 'cancelled' WHERE id = ? AND status = 'active'",
            (event_id,),
        )
        return cur.rowcount > 0


def get_active_events(teacher_username: Optional[str] = None) -> list:
    teacher_username = (teacher_username or "").lstrip("@") or None
    with get_conn() as conn:
        if teacher_username:
            return conn.execute(
                "SELECT * FROM events WHERE status = 'active' AND teacher_username = ? ORDER BY scheduled_at",
                (teacher_username,),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM events WHERE status = 'active' ORDER BY scheduled_at"
        ).fetchall()


def get_events_needing_reminder(reminder_type: str) -> list:
    """
    reminder_type: '24h' или '1h'
    Возвращает активные события, для которых ещё не было напоминания
    и время подошло.
    """
    import pytz
    from datetime import timedelta

    tz = TIMEZONE
    now = datetime.now(tz)

    if reminder_type == "24h":
        window_start = now + timedelta(hours=23, minutes=50)
        window_end = now + timedelta(hours=24, minutes=10)
        col = "reminded_24h"
    else:
        window_start = now + timedelta(minutes=50)
        window_end = now + timedelta(hours=1, minutes=10)
        col = "reminded_1h"

    ws = window_start.strftime("%Y-%m-%d %H:%M:%S")
    we = window_end.strftime("%Y-%m-%d %H:%M:%S")

    with get_conn() as conn:
        return conn.execute(
            f"""SELECT * FROM events
                WHERE status = 'active'
                  AND {col} = 0
                  AND scheduled_at BETWEEN ? AND ?""",
            (ws, we),
        ).fetchall()


def mark_reminded(event_id: int, reminder_type: str) -> None:
    col = "reminded_24h" if reminder_type == "24h" else "reminded_1h"
    with get_conn() as conn:
        conn.execute(f"UPDATE events SET {col} = 1 WHERE id = ?", (event_id,))


def mark_done_past_events() -> None:
    """Помечает прошедшие активные события как выполненные."""
    from datetime import timedelta
    now = datetime.now(TIMEZONE)
    threshold = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute(
            "UPDATE events SET status = 'done' WHERE status = 'active' AND scheduled_at < ?",
            (threshold,),
        )


# ─── Хелперы ──────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
