"""
Настройки бота из окружения и логирование.

Ролей и собственного хранилища у бота больше нет — кому слать уведомления,
решает журнал. Здесь остаётся только то, что нужно самому боту: токен,
таймзона (для отображения времени) и уровень логирования.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f'Обязательная переменная окружения не задана: {key}')
    return value


BOT_TOKEN: str = _require('BOT_TOKEN')

TIMEZONE: str = os.getenv('TIMEZONE', 'Europe/Moscow')

LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO').upper()

LOG_FILE: str = os.path.join(os.path.dirname(__file__), '..', 'logs', 'bot.log')


def setup_logging() -> None:
    """Настраивает логирование в консоль и в файл с ротацией."""
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    fmt = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,  # 5 МБ
            backupCount=3,              # хранить 3 архивных файла
            encoding='utf-8',
        ),
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)

    # httpx на уровне INFO печатает полный URL каждого запроса, а токен бота —
    # часть URL обращений к api.telegram.org. То есть при LOG_LEVEL=INFO секрет
    # утекает в journalctl и в logs/bot.log целиком. Глушим до WARNING: ошибки
    # запросов по-прежнему видны, а рутинные обращения — нет.
    logging.getLogger('httpx').setLevel(logging.WARNING)
