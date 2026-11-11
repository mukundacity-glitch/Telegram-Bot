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


def test_transient_gateway_retries_rewind_photo_and_require_receipt(monkeypatch, tmp_path):
    attempts = []
    class Response:
        def __init__(self, status): self.status_code = status
        def json(self): return {'ok': True, 'result': {'message_id': 42}}
        def raise_for_status(self): assert self.status_code == 200
    def post(url, data, files, timeout):
        attempts.append(files['photo'][1].read())
        return Response(502 if len(attempts) == 1 else 200)
    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.setattr('vortex.telegram.time.sleep', lambda n: None)
    image = tmp_path / 'graphic.png'
    image.write_bytes(b'x' * 600)
    assert TelegramClient('SECRET', 'private-chat').send_shared_png(image, 'caption', 'title', 10) == 42
    assert attempts == [b'x' * 600, b'x' * 600]


def test_timeout_has_safe_visible_diagnostic_and_is_not_blindly_retried(monkeypatch):
    calls = []
    def post(*a, **kw):
        calls.append(1)
        raise requests.ReadTimeout('SECRET in private URL')
    monkeypatch.setattr(requests, 'post', post)
    with pytest.raises(TelegramDeliveryError, match=r'network or JSON failure \(ReadTimeout\)') as caught:
        TelegramClient('SECRET', 'private-chat')._post('sendPhoto', {})
    assert 'SECRET' not in str(caught.value)
    assert len(calls) == 1
    assert caught.value.delivery_uncertain is True


def test_photo_upload_allows_slow_telegram_confirmation(monkeypatch):
    def post(*args, **kwargs):
        assert kwargs["timeout"] == (15, 120)
        class Response:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"ok": True, "result": {"message_id": 77}}
        return Response()
    monkeypatch.setattr(requests, "post", post)
    result = TelegramClient("SECRET", "chat")._post("sendPhoto", {})
    assert result["result"]["message_id"] == 77


def test_confirmed_400_rejection_is_safe_to_retry(monkeypatch):
    class Response:
        status_code = 400
        def raise_for_status(self):
            raise requests.HTTPError("hidden token", response=self)
        def json(self): return {"description": "Bad Request: chat not found"}
    monkeypatch.setattr(requests, "post", lambda *args, **kw: Response())
    with pytest.raises(TelegramDeliveryError) as exc:
        TelegramClient("SECRET", "chat")._post("sendPhoto", {})
    assert exc.value.confirmed_rejection is True
    assert exc.value.delivery_uncertain is False
