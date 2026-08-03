"""Клиент журнала: заголовок с секретом, обработка ответов."""
from unittest.mock import patch

import pytest

from bot import journal_api


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_identify_sends_secret_header():
    with patch('bot.journal_api.httpx.post', return_value=_Resp(204)) as post:
        journal_api.identify(telegram_id=1, username='anna', full_name='Анна')
    _args, kwargs = post.call_args
    assert kwargs['headers']['X-Bot-Token'] == journal_api.SERVICE_TOKEN


def test_identify_never_raises_on_failure():
    """Журнал недоступен — бот обязан продолжать отвечать человеку."""
    import httpx
    with patch('bot.journal_api.httpx.post', side_effect=httpx.ConnectError('down')):
        assert journal_api.identify(telegram_id=1, username=None, full_name='Аноним') is False


def test_my_returns_none_when_not_linked():
    with patch('bot.journal_api.httpx.get', return_value=_Resp(404)):
        assert journal_api.my_events(telegram_id=1) is None


def test_my_returns_payload():
    payload = {'teacher_name': 'Анна', 'events': [{'date': '2026-08-05'}]}
    with patch('bot.journal_api.httpx.get', return_value=_Resp(200, payload)):
        assert journal_api.my_events(telegram_id=1) == payload
