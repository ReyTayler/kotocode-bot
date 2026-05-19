"""
Миграция схемы БД: role TEXT → отдельные булевы столбцы + удаление столбца role.

Запускать ОДИН РАЗ перед обновлением кода:
    python migrate_roles.py

Создаёт резервную копию БД перед миграцией.
Требует SQLite >= 3.35.0 (установлено: проверено).
"""
import sqlite3
import shutil
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "kotocode.db")
BACKUP_PATH = DB_PATH + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def migrate():
    # Резервная копия
    shutil.copy2(DB_PATH, BACKUP_PATH)
    print(f"Резервная копия: {BACKUP_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        print(f"Столбцы до миграции: {existing_cols}")

        # Шаг 1 — добавляем новые столбцы если их нет
        for col in ["is_admin", "is_manager", "is_teacher"]:
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} BOOLEAN NOT NULL DEFAULT 0")
                print(f"Добавлен столбец: {col}")

        # Шаг 2 — мигрируем данные из role → флаги (только если столбец role ещё есть)
        if "role" in existing_cols:
            users = conn.execute("SELECT * FROM users").fetchall()
            print(f"Пользователей в БД: {len(users)}")

            migrated = 0
            for user in users:
                role         = user["role"]
                is_superadmin = user["is_superadmin"]
                is_admin   = 1 if role == "admin" and not is_superadmin else 0
                is_manager = 1 if role == "manager" else 0
                is_teacher = 1 if role == "teacher" else 0
                conn.execute(
                    "UPDATE users SET is_admin=?, is_manager=?, is_teacher=? WHERE telegram_id=?",
                    (is_admin, is_manager, is_teacher, user["telegram_id"]),
                )
                migrated += 1

            conn.commit()
            print(f"Данные перенесены для {migrated} пользователей")

            # Шаг 3 — удаляем столбец role
            conn.execute("ALTER TABLE users DROP COLUMN role")
            conn.commit()
            print("Столбец 'role' удалён")
        else:
            print("Столбец 'role' уже отсутствует — пропускаем миграцию данных")

        # Итоговая проверка
        final_cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        print(f"\nСтолбцы после миграции: {final_cols}")
        print("\nПроверка пользователей:")
        for u in conn.execute(
            "SELECT username, is_superadmin, is_admin, is_manager, is_teacher FROM users"
        ).fetchall():
            flags = []
            if u["is_superadmin"]: flags.append("superadmin")
            if u["is_admin"]:      flags.append("admin")
            if u["is_manager"]:    flags.append("manager")
            if u["is_teacher"]:    flags.append("teacher")
            name = u["username"] or "?"
            print(f"  @{name:20} → {flags or ['blocked']}")

        print("\n✅ Миграция завершена успешно.")
        print("Теперь можно обновить файлы бота и перезапустить его.")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Ошибка миграции: {e}")
        print(f"Резервная копия сохранена: {BACKUP_PATH}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()