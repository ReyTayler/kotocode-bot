"""
RoleService — единственный источник правды о правах, командах и help-тексте.

Вместо того чтобы проверять флаги в трёх разных файлах (role_check.py,
commands.py, common.py), вся логика ролей сосредоточена здесь.

Остальные модули импортируют только RoleService, не зная деталей реализации.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from telegram import BotCommand


# ─── Константы разрешений ─────────────────────────────────────────────────────
# Вместо is_manager_or_above / is_admin_or_above используем Permission —
# явный список того что конкретно требуется для команды.

class Permission:
    MANAGE_EVENTS   = "manage_events"    # добавить/отменить/редактировать событие
    VIEW_ALL_EVENTS = "view_all_events"  # /list
    VIEW_OWN_EVENTS = "view_own_events"  # /my
    MANAGE_TEACHERS = "manage_teachers"  # addteacher / removeteacher
    MANAGE_MANAGERS = "manage_managers"  # addmanager / removemanager
    MANAGE_ADMINS   = "manage_admins"    # addadmin / removeadmin
    VIEW_USERS      = "view_users"       # /users
    TRANSFER_RIGHTS = "transfer_rights"  # /transfer


# ─── Маппинг роль → разрешения ────────────────────────────────────────────────

_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "teacher": {
        Permission.VIEW_OWN_EVENTS,
    },
    "manager": {
        Permission.MANAGE_EVENTS,
        Permission.VIEW_ALL_EVENTS,
        Permission.VIEW_OWN_EVENTS,
    },
    "admin": {
        Permission.MANAGE_EVENTS,
        Permission.VIEW_ALL_EVENTS,
        Permission.VIEW_OWN_EVENTS,
        Permission.MANAGE_TEACHERS,
        Permission.MANAGE_MANAGERS,
        Permission.VIEW_USERS,
    },
    "superadmin": {
        Permission.MANAGE_EVENTS,
        Permission.VIEW_ALL_EVENTS,
        Permission.VIEW_OWN_EVENTS,
        Permission.MANAGE_TEACHERS,
        Permission.MANAGE_MANAGERS,
        Permission.MANAGE_ADMINS,
        Permission.VIEW_USERS,
        Permission.TRANSFER_RIGHTS,
    },
}


# ─── Команды по ролям ─────────────────────────────────────────────────────────

_COMMANDS_COMMON = [
    BotCommand("start", "Приветствие и информация о роли"),
    BotCommand("help",  "Список доступных команд"),
]

_COMMANDS_TEACHER = [
    BotCommand("my", "Мои назначенные события"),
]

_COMMANDS_MANAGER = [
    BotCommand("add_doproved", "Назначить допровед"),
    BotCommand("add_perenos",  "Назначить перенос"),
    BotCommand("cancel",       "Отменить событие — /cancel ID"),
    BotCommand("list",         "Все активные события"),
    BotCommand("teachers",     "Список преподавателей"),
]

_COMMANDS_ADMIN = [
    BotCommand("addmanager",    "Назначить менеджера"),
    BotCommand("removemanager", "Снять менеджера"),
    BotCommand("managers",      "Список менеджеров"),
    BotCommand("addteacher",    "Зарегистрировать преподавателя"),
    BotCommand("removeteacher", "Снять преподавателя"),
    BotCommand("users",         "Все пользователи бота по ролям"),
    BotCommand("admins",        "Список администраторов"),
    BotCommand("export_finish_events", "Экспорт завершённых/отменённых событий в CSV"),
]

_COMMANDS_SUPERADMIN = [
    BotCommand("addadmin",    "Назначить администратора"),
    BotCommand("removeadmin", "Снять администратора"),
    BotCommand("transfer",    "Передать права супер-админа"),
]


# ─── Секции help-текста ───────────────────────────────────────────────────────

_HELP_COMMON = """🤖 <b>Общие команды</b>
/start — приветствие и информация о роли
/help — список доступных команд
"""

_HELP_TEACHER = """
👨‍🏫 <b>Преподаватель</b>
/my — мои назначенные события
"""

_HELP_MANAGER = """
📋 <b>Менеджер</b>
/add_doproved — назначить допровед
/add_perenos — назначить перенос
/cancel ID — отменить событие по номеру
/list — все активные события
/list @username — события конкретного преподавателя
/teachers — список преподавателей
"""

_HELP_ADMIN = """
🔧 <b>Администратор</b>
/addmanager @username — назначить менеджера
/removemanager @username — снять менеджера
/managers — список менеджеров
/addteacher @username — зарегистрировать преподавателя
/removeteacher @username — снять преподавателя
/users — все пользователи бота по ролям
/admins — список администраторов
/export_finish_events — экспорт завершённых событий в CSV
"""

_HELP_SUPERADMIN = """
👑 <b>Супер-админ</b>
/addadmin @username — назначить администратора
/removeadmin @username — снять администратора
/transfer @username — передать права супер-админа
"""

_HELP_BLOCKED = "⛔ У вас нет доступа к боту.\nОбратитесь к администратору школы Котокод."


# ─── RoleService ──────────────────────────────────────────────────────────────

class RoleService:
    """
    Все операции связанные с ролями пользователя.
    Принимает строку из БД (sqlite3.Row) или telegram_id.
    """

    def __init__(self, superadmin_id: int):
        self._superadmin_id = superadmin_id

    # ── Получение пользователя ────────────────────────────────────────────────

    def _get_user(self, telegram_id: int) -> Optional[sqlite3.Row]:
        from bot import database as db
        return db.get_user(telegram_id)

    def _is_env_superadmin(self, telegram_id: int) -> bool:
        return telegram_id == self._superadmin_id

    # ── Проверка ролей ────────────────────────────────────────────────────────

    def is_superadmin(self, telegram_id: int) -> bool:
        if self._is_env_superadmin(telegram_id):
            return True
        user = self._get_user(telegram_id)
        return bool(user and user["is_superadmin"])

    def is_admin(self, telegram_id: int) -> bool:
        if self._is_env_superadmin(telegram_id):
            return True
        user = self._get_user(telegram_id)
        return bool(user and (user["is_superadmin"] or user["is_admin"]))

    def is_manager(self, telegram_id: int) -> bool:
        if self._is_env_superadmin(telegram_id):
            return True
        user = self._get_user(telegram_id)
        return bool(user and (
            user["is_superadmin"] or user["is_admin"] or user["is_manager"]
        ))

    def is_teacher(self, telegram_id: int) -> bool:
        user = self._get_user(telegram_id)
        return bool(user and user["is_teacher"])

    def has_any_role(self, telegram_id: int) -> bool:
        if self._is_env_superadmin(telegram_id):
            return True
        user = self._get_user(telegram_id)
        return bool(user and (
            user["is_superadmin"] or user["is_admin"] or
            user["is_manager"]    or user["is_teacher"]
        ))

    # ── Проверка разрешений ───────────────────────────────────────────────────

    def has_permission(self, telegram_id: int, permission: str) -> bool:
        """Проверяет наличие конкретного разрешения с учётом всех ролей."""
        if self._is_env_superadmin(telegram_id):
            return True
        user = self._get_user(telegram_id)
        if not user:
            return False
        return permission in self._get_permissions(user)

    def _get_permissions(self, user: sqlite3.Row) -> set[str]:
        perms: set[str] = set()
        if user["is_superadmin"]: perms |= _ROLE_PERMISSIONS["superadmin"]
        if user["is_admin"]:      perms |= _ROLE_PERMISSIONS["admin"]
        if user["is_manager"]:    perms |= _ROLE_PERMISSIONS["manager"]
        if user["is_teacher"]:    perms |= _ROLE_PERMISSIONS["teacher"]
        return perms

    # ── Отображаемые роли ─────────────────────────────────────────────────────

    def get_role_labels(self, telegram_id: int) -> list[str]:
        """Возвращает список названий всех активных ролей пользователя."""
        if self._is_env_superadmin(telegram_id):
            user = self._get_user(telegram_id)
            if not user:
                return ["Супер-админ 👑"]

        user = self._get_user(telegram_id)
        if not user:
            return ["Нет доступа ⛔"]

        labels = []
        if user["is_superadmin"]: labels.append("Супер-админ 👑")
        if user["is_admin"]:      labels.append("Администратор 🔧")
        if user["is_manager"]:    labels.append("Менеджер 📋")
        if user["is_teacher"]:    labels.append("Преподаватель 👨‍🏫")
        return labels or ["Нет доступа ⛔"]

    # ── Команды для меню бота ─────────────────────────────────────────────────

    def get_commands(self, telegram_id: int) -> list[BotCommand]:
        """Возвращает список команд для меню бота с учётом всех ролей."""
        if self._is_env_superadmin(telegram_id):
            user = self._get_user(telegram_id)
            if not user:
                return _COMMANDS_COMMON + _COMMANDS_MANAGER + _COMMANDS_ADMIN + _COMMANDS_SUPERADMIN

        user = self._get_user(telegram_id)
        if not user:
            return list(_COMMANDS_COMMON)

        seen: set[str] = set()
        result: list[BotCommand] = []

        def add(cmds: list[BotCommand]) -> None:
            for c in cmds:
                if c.command not in seen:
                    result.append(c)
                    seen.add(c.command)

        add(_COMMANDS_COMMON)

        if user["is_superadmin"]:
            add(_COMMANDS_MANAGER)
            add(_COMMANDS_ADMIN)
            add(_COMMANDS_SUPERADMIN)
        else:
            if user["is_admin"]:
                add(_COMMANDS_MANAGER)
                add(_COMMANDS_ADMIN)
            elif user["is_manager"]:
                add(_COMMANDS_MANAGER)

            if user["is_teacher"]:
                add(_COMMANDS_TEACHER)

        return result

    # ── Help-текст ────────────────────────────────────────────────────────────

    def get_help_text(self, telegram_id: int) -> str:
        """Возвращает текст /help с секциями всех активных ролей."""
        if self._is_env_superadmin(telegram_id):
            user = self._get_user(telegram_id)
            if not user:
                return _HELP_COMMON + _HELP_MANAGER + _HELP_ADMIN + _HELP_SUPERADMIN

        user = self._get_user(telegram_id)
        if not user:
            return _HELP_BLOCKED

        sections = [_HELP_COMMON]

        if user["is_superadmin"]:
            sections += [_HELP_MANAGER, _HELP_ADMIN, _HELP_SUPERADMIN]
        else:
            if user["is_admin"]:
                sections += [_HELP_MANAGER, _HELP_ADMIN]
            elif user["is_manager"]:
                sections.append(_HELP_MANAGER)

            if user["is_teacher"]:
                sections.append(_HELP_TEACHER)

        if not any([user["is_superadmin"], user["is_admin"],
                    user["is_manager"], user["is_teacher"]]):
            return _HELP_BLOCKED

        return "".join(sections).strip()


# ─── Синглтон ─────────────────────────────────────────────────────────────────
# Инициализируется один раз при старте в main.py через init_role_service()

_role_service: Optional[RoleService] = None


def init_role_service(superadmin_id: int) -> RoleService:
    global _role_service
    _role_service = RoleService(superadmin_id)
    return _role_service


def get_role_service() -> RoleService:
    if _role_service is None:
        raise RuntimeError("RoleService не инициализирован. Вызови init_role_service() при старте.")
    return _role_service
