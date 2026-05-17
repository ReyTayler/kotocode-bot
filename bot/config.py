import os
import logging
import pytz
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Обязательная переменная окружения не задана: {key}")
    return value


BOT_TOKEN: str = _require("BOT_TOKEN")
GENERAL_CHAT_ID: int = int(_require("GENERAL_CHAT_ID"))
SUPERADMIN_ID: int = int(_require("SUPERADMIN_ID"))

TIMEZONE_STR: str = os.getenv("TIMEZONE", "Europe/Moscow")
TIMEZONE = pytz.timezone(TIMEZONE_STR)

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

DB_PATH: str = os.path.join(os.path.dirname(__file__), "..", "data", "kotocode.db")
DB_URL: str = f"sqlite:///{DB_PATH}"

LOG_FILE: str = os.path.join(os.path.dirname(__file__), "..", "logs", "bot.log")


def setup_logging() -> None:
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)
