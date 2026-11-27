from datetime import datetime, timedelta
from types import SimpleNamespace
from vortex import retire_player_news as retire
from vortex.syndication import save_journal, load_journal

def test_exact_rejected_player_news_only_and_idempotent(tmp_path, monkeypatch):
    receipts, state = tmp_path/"receipts.json", tmp_path/"retired.json"
    row = dict(delivered=True, discord_delivered=True, gameweek=12,
               timestamp=retire.STAMP, source="media.bbc_sport",
               caption_sha256=retire.CAPTION_HASH, telegram_message_id=retire.TELEGRAM_ID,
               discord_message_id=retire.DISCORD_ID)
    save_journal(receipts, {retire.IDENTITY: row, "rss:other": row})
    calls = []
    class Bot:
        chat_id = 1
        def get_bot_username(self): return "FPLVortexDailyBot"
        def _post(self, *args): return {"result": {"type": "private", "id": self.chat_id}}
        def delete_shared_message(self, mid):
            calls.append(mid)
            return True
    class Session:
        def get(self, url, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: dict(
                id=retire.DISCORD_ID, content="Calvert-Lewin", attachments=[{}]))
        def delete(self, url, **kwargs):
            calls.append(url.rsplit("/", 1)[-1])
            return SimpleNamespace(status_code=204)
    monkeypatch.setattr(retire, '_verify_telegram_original', lambda *a: True)
    now = datetime.fromisoformat(retire.STAMP)+timedelta(hours=1)
    kwargs = dict(telegram=Bot(), discord=SimpleNamespace(url="https://discord.com/api/webhooks/test/test", session=Session()),
                  receipts_path=receipts, state_path=state)
    result = retire.retire_calvert_lewin(now, **kwargs)
    assert result["telegram_deleted"] and result["discord_deleted"]
    retire.retire_calvert_lewin(now, **kwargs)
    assert calls == [retire.TELEGRAM_ID, retire.DISCORD_ID]
    assert list(load_journal(state)) == [retire.IDENTITY]
    row["caption_sha256"] = "wrong"
    save_journal(receipts, {retire.IDENTITY: row})
    assert retire.retire_calvert_lewin(now, **kwargs)["status"] == "receipt-mismatch"

def test_telegram_verification_checks_actual_chat_and_content(monkeypatch):
    caption = "Exact historic player story"
    monkeypatch.setattr(retire, "CAPTION_HASH", retire._caption_digest(caption))
    deleted = []
    class Bot:
        chat_id = "100"
        base_url = "https://api.telegram.org/test"
        def delete_shared_message(self, mid):
            deleted.append(mid)
            return True
    def forward(url, data, timeout):
        assert data["chat_id"] == data["from_chat_id"] == "100"
        assert data["message_id"] == retire.TELEGRAM_ID
        return SimpleNamespace(status_code=200, json=lambda: {"result": {
            "message_id": 642, "chat": {"id": 100}, "photo": [{}], "caption": caption,
            "forward_origin": {"sender_user": {"username": "FPLVortexDailyBot"},
                               "date": int(datetime.fromisoformat(retire.STAMP).timestamp())}}})
    monkeypatch.setattr(retire.requests, "post", forward)
    state = {}
    bot = Bot()
    assert retire._verify_telegram_original(bot, state, lambda: None)
    assert deleted == [642]
    bot.chat_id = "200"
    assert not retire._verify_telegram_original(bot, state, lambda: None)
    assert deleted == [642]
