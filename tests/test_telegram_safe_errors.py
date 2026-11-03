from vortex.telegram import TelegramClient, TelegramDeliveryError, rejection_code
import pytest
import requests


@pytest.mark.parametrize('status,description,code', [
    (400, 'Bad Request: chat not found', 'chat-not-found'),
    (403, 'Forbidden: bot was blocked by the user', 'bot-blocked'),
    (400, "bot can't send messages to bots", 'target-is-another-bot'),
    (401, 'Unauthorized', 'invalid-bot-token'),
])
def test_safe_api_rejection(status, description, code):
    assert rejection_code(status, {'description': description}) == code


def test_http_failure_preserves_diagnostic_without_secret(monkeypatch):
    class Response:
        status_code = 400
        def json(self):
            return {'description': 'Bad Request: chat not found private-sensitive-data'}
        def raise_for_status(self):
            raise requests.HTTPError('https://api.telegram.org/botSECRET', response=self)
    monkeypatch.setattr(requests, 'post', lambda *a, **kw: Response())
    with pytest.raises(TelegramDeliveryError) as caught:
        TelegramClient('SECRET', 'private-chat')._post('sendPhoto', {})
    assert str(caught.value) == 'Telegram sendPhoto: chat-not-found'
