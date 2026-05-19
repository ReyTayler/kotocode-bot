import sqlite3
import logging
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

from bot.config import DB_PATH, TIMEZONE

logger = logging.getLogger(__name__)

# ─── Роли — константы для удобства использования в коде ──────────────────────
ROLE_SUPERADMIN = "superadmin"
ROLE_ADMIN      = "admin"
ROLE_MANAGER    = "manager"
ROLE_TEACHER    = "teacher"
ROLE_BLOCKED    = "blocked"   # нет ни одной роли

# ─── Типы событий ─────────────────────────────────────────────────────────────
TYPE_DOPROVED = "doproved"
TYPE_PERENOS  = "perenos"

# ─── Статусы событий ──────────────────────────────────────────────────────────
STATUS_ACTIVE    = "active"
STATUS_DONE      = "done"
STATUS_CANCELLED = "cancelled"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id   INTEGER UNIQUE NOT NULL,
                username      TEXT,
                full_name     TEXT,
                is_superadmin BOOLEAN NOT NULL DEFAULT 0,
                is_admin      BOOLEAN NOT NULL DEFAULT 0,
                is_manager    BOOLEAN NOT NULL DEFAULT 0,
                is_teacher    BOOLEAN NOT NULL DEFAULT 0,
                added_by      INTEGER,
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                type                TEXT NOT NULL,
                teacher_username    TEXT NOT NULL,
                teacher_telegram_id INTEGER,
                group_name          TEXT NOT NULL,
                lesson_number       TEXT NOT NULL,
                scheduled_at        TEXT NOT NULL,
                children            TEXT NOT NULL,
                comment             TEXT,
                created_by          INTEGER NOT NULL,
                created_at          TEXT NOT NULL,
                status              TEXT NOT NULL DEFAULT 'active',
                reminded_24h        INTEGER NOT NULL DEFAULT 0,
                reminded_1h         INTEGER NOT NULL DEFAULT 0
            );
        """)
    logger.info("БД инициализирована: %s", DB_PATH)


# ─── Хелпер: определить строковую роль по флагам ─────────────────────────────

def get_primary_role(user: sqlite3.Row) -> str:
    """
    Возвращает строковое обозначение наивысшей роли пользователя.
    Используется для /start, /help, меню команд.
    Приоритет: superadmin > admin > manager > teacher > blocked
    """
    if user["is_superadmin"]: return ROLE_SUPERADMIN
    if user["is_admin"]:      return ROLE_ADMIN
    if user["is_manager"]:    return ROLE_MANAGER
    if user["is_teacher"]:    return ROLE_TEACHER
    return ROLE_BLOCKED


def has_role(user: sqlite3.Row, role: str) -> bool:
    """Проверяет наличие конкретной роли у пользователя."""
    if role == ROLE_SUPERADMIN: return bool(user["is_superadmin"])
    if role == ROLE_ADMIN:      return bool(user["is_admin"])
    if role == ROLE_MANAGER:    return bool(user["is_manager"])
    if role == ROLE_TEACHER:    return bool(user["is_teacher"])
    return False


# ─── Пользователи ─────────────────────────────────────────────────────────────

def get_user(telegram_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()


def get_user_by_username(username: str) -> Optional[sqlite3.Row]:
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
                """INSERT INTO users (telegram_id, username, full_name, created_at)
                   VALUES (?, ?, ?, ?)""",
                (telegram_id, username, full_name, now),
            )


def grant_role(telegram_id: int, role: str, added_by: int) -> bool:
    """Выдаёт роль пользователю (не снимает остальные). Возвращает True если успешно."""
    col = _role_col(role)
    if not col:
        raise ValueError(f"Недопустимая роль: {role}")
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE users SET {col} = 1, added_by = ? WHERE telegram_id = ?",
            (added_by, telegram_id),
        )
        return cur.rowcount > 0


def revoke_role(telegram_id: int, role: str, added_by: int) -> bool:
    """Снимает конкретную роль у пользователя. Возвращает True если успешно."""
    col = _role_col(role)
    if not col:
        raise ValueError(f"Недопустимая роль: {role}")
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE users SET {col} = 0, added_by = ? WHERE telegram_id = ?",
            (added_by, telegram_id),
        )
        return cur.rowcount > 0


def _role_col(role: str) -> Optional[str]:
    """Возвращает имя столбца для роли."""
    return {
        ROLE_SUPERADMIN: "is_superadmin",
        ROLE_ADMIN:      "is_admin",
        ROLE_MANAGER:    "is_manager",
        ROLE_TEACHER:    "is_teacher",
    }.get(role)


def get_superadmin() -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE is_superadmin = 1"
        ).fetchone()


def transfer_superadmin(from_id: int, to_telegram_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET is_superadmin = 0 WHERE telegram_id = ?", (from_id,))
        conn.execute(
            "UPDATE users SET is_superadmin = 1 WHERE telegram_id = ?",
            (to_telegram_id,),
        )


def get_users_by_role(role: str) -> list:
    col = _role_col(role)
    if not col:
        return []
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM users WHERE {col} = 1 ORDER BY full_name"
        ).fetchall()


def get_all_users_by_roles() -> dict:
    """Возвращает словарь {role: [users]} для всех ролей.
    Пользователь с несколькими ролями появляется в каждой секции."""
    with get_conn() as conn:
        result = {
            ROLE_SUPERADMIN: conn.execute(
                "SELECT * FROM users WHERE is_superadmin = 1 ORDER BY full_name"
            ).fetchall(),
            ROLE_ADMIN: conn.execute(
                "SELECT * FROM users WHERE is_admin = 1 ORDER BY full_name"
            ).fetchall(),
            ROLE_MANAGER: conn.execute(
                "SELECT * FROM users WHERE is_manager = 1 ORDER BY full_name"
            ).fetchall(),
            ROLE_TEACHER: conn.execute(
                "SELECT * FROM users WHERE is_teacher = 1 ORDER BY full_name"
            ).fetchall(),
            ROLE_BLOCKED: conn.execute(
                """SELECT * FROM users
                   WHERE is_superadmin = 0 AND is_admin = 0
                     AND is_manager = 0 AND is_teacher = 0
                   ORDER BY full_name"""
            ).fetchall(),
        }
    return result


def ensure_superadmin(telegram_id: int, username: Optional[str], full_name: str) -> None:
    """Гарантирует что супер-админ из .env корректно записан в БД.
    Устанавливает только is_superadmin — не трогает другие роли."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        now = _now_str()
        if existing:
            conn.execute(
                "UPDATE users SET is_superadmin = 1, username = ?, full_name = ? WHERE telegram_id = ?",
                (username, full_name, telegram_id),
            )
        else:
            conn.execute(
                """INSERT INTO users (telegram_id, username, full_name, is_superadmin, created_at)
                   VALUES (?, ?, ?, 1, ?)""",
                (telegram_id, username, full_name, now),
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


EDITABLE_FIELDS = {"group_name", "lesson_number", "scheduled_at", "children", "comment"}


def update_event_field(event_id: int, field: str, value: str) -> bool:
    if field not in EDITABLE_FIELDS:
        raise ValueError(f"Поле {field} не доступно для редактирования")
    with get_conn() as conn:
        if field == "scheduled_at":
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
    from datetime import timedelta
    tz = TIMEZONE
    now = datetime.now(tz)
    if reminder_type == "24h":
        window_start = now + timedelta(hours=23, minutes=50)
        window_end   = now + timedelta(hours=24, minutes=10)
        col = "reminded_24h"
    else:
        window_start = now + timedelta(minutes=50)
        window_end   = now + timedelta(hours=1, minutes=10)
        col = "reminded_1h"
    ws = window_start.strftime("%Y-%m-%d %H:%M:%S")
    we = window_end.strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        return conn.execute(
            f"""SELECT * FROM events
                WHERE status = 'active' AND {col} = 0
                  AND scheduled_at BETWEEN ? AND ?""",
            (ws, we),
        ).fetchall()


def mark_reminded(event_id: int, reminder_type: str) -> None:
    col = "reminded_24h" if reminder_type == "24h" else "reminded_1h"
    with get_conn() as conn:
        conn.execute(f"UPDATE events SET {col} = 1 WHERE id = ?", (event_id,))


def mark_done_past_events() -> None:
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
