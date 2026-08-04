"""
Единственное место в боте, знающее про HTTP журнала.

Бот и журнал живут на одной машине, поэтому адрес — localhost, а эндпоинты
дополнительно закрыты в nginx правилом allow 127.0.0.1.

Все функции при ошибке возвращают False/None и НИКОГДА не бросают: если журнал
недоступен, бот обязан продолжать отвечать человеку, а не молчать.
"""
from __future__ import annotations

import logging
import os

import httpx
from dotenv import load_dotenv

# Загружаем .env здесь же, а не полагаемся на то, что это уже сделал
# bot/config.py где-то раньше по цепочке импортов. load_dotenv() по умолчанию
# не перезаписывает уже выставленные переменные окружения, поэтому повторный
# вызов безопасен — но без этой строки модуль, импортированный напрямую
# (например, в тестах или отдельном скрипте) молча остался бы с пустым
# токеном, даже если .env на диске существует.
load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get('JOURNAL_API_URL', 'http://127.0.0.1:8000').rstrip('/')
SERVICE_TOKEN = os.environ.get('BOT_SERVICE_TOKEN', '')
TIMEOUT = 5.0

_HEADERS = {'X-Bot-Token': SERVICE_TOKEN}


def identify(*, telegram_id: int, username: str | None, full_name: str) -> bool:
    """Сообщить журналу, какому нику соответствует chat_id."""
    try:
        response = httpx.post(
            f'{BASE_URL}/api/integrations/telegram/identify',
            json={'telegram_id': telegram_id, 'username': username,
                  'full_name': full_name},
            headers=_HEADERS, timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.warning('identify не дошёл до журнала: %s', exc)
        return False
    if response.status_code != 204:
        # Журнал ответил отказом. Молчать здесь нельзя: снаружи это выглядит как
        # «бот работает, но аккаунт не появляется в списке привязки», и причину
        # искать негде. 400 — обычно Host не совпал с ALLOWED_HOSTS,
        # 403 — разошёлся BOT_SERVICE_TOKEN между двумя .env.
        logger.warning('identify отклонён журналом: HTTP %s, тело: %.200s',
                       response.status_code, response.text)
        return False
    return True


def my_events(*, telegram_id: int) -> dict | None:
    """Ближайшие события преподавателя. None — аккаунт не привязан или журнал молчит."""
    try:
        response = httpx.get(
            f'{BASE_URL}/api/integrations/telegram/my',
            params={'telegram_id': telegram_id},
            headers=_HEADERS, timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.warning('my не дошёл до журнала: %s', exc)
        return None
    if response.status_code == 404:
        return None            # штатный случай: аккаунт ещё не привязан
    if response.status_code != 200:
        logger.warning('my отклонён журналом: HTTP %s, тело: %.200s',
                       response.status_code, response.text)
        return None
    return response.json()
