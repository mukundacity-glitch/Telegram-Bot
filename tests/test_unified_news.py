"""No-live-post regression coverage for unified Telegram/Discord news."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vortex.fpl import FplSnapshot
from vortex.syndication import DiscordWebhookClient, NewsPost, load_journal, publish_shared
import vortex.unified_runner as runner


def sample_snapshot(now=None, *, status="a", cost=70, news=""):
    now = now or datetime(2026, 11, 2, tzinfo=timezone.utc)
    player = {"id": 99, "web_name": "Example", "team": 1, "status": status,
              "now_cost": cost, "news": news, "code": 123456,
              "chance_of_playing_next_round": None,
              "chance_of_playing_this_round": None}
    teams = {1: {"short_name": "ABC", "name": "Arsenal", "code": 3},
             2: {"short_name": "XYZ", "name": "Chelsea", "code": 8}}
    events = [{"id": 10, "deadline_time": (now + timedelta(days=2)).isoformat(),
               "finished": False}]
    fixtures = [{"id": 1, "event": 10, "team_h": 1, "team_a": 2,
                 "finished": False, "kickoff_time": (now + timedelta(days=2)).isoformat()}]
    return FplSnapshot([player], teams, events, fixtures, now)




class FakeTelegram:
    def __init__(self):
        self.calls = 0

    def send_text(self, text):
        self.calls += 1
        return 987

    def send_png(self, image, caption, title, gameweek):
        assert image.is_file()
        self.calls += 1
        return 987


class FakeDiscord:
    def __init__(self, fails=False):
        self.calls = 0
        self.fails = fails

    def send(self, post):
        self.calls += 1
        if self.fails:
            raise RuntimeError("Discord rejected")
        return "887766"


def test_partial_delivery_survives_and_retries_only_missing_platform(tmp_path):
    post = NewsPost("story1", "Update", "same exact facts and #FPL", 10)
    path = tmp_path / "deliveries.json"
    telegram, discord = FakeTelegram(), FakeDiscord(fails=True)
    with pytest.raises(RuntimeError):
        publish_shared(post, path, telegram, discord)
    assert telegram.calls == 1 and discord.calls == 1
    assert load_journal(path)["story1"]["telegram_message_id"] == 987
    discord.fails = False
    result = publish_shared(post, path, telegram, discord)
    assert telegram.calls == 1 and discord.calls == 2
    assert result["discord_message_id"] == "887766"
    assert publish_shared(post, path, telegram, discord)["delivered"] is True
    assert (telegram.calls, discord.calls) == (1, 2)


def test_legacy_telegram_receipt_does_not_repost(tmp_path):
    path = tmp_path / "deliveries.json"
    path.write_text(json.dumps({"2026-11-02:news": {"delivered": True,
                         "telegram_message_id": 21}}))
    t, d = FakeTelegram(), FakeDiscord()
    result = publish_shared(NewsPost("2026-11-02:news", "Title", "Fact", 10),
                            path, t, d)
    assert t.calls == 0 and d.calls == 1
    assert result["telegram_message_id"] == 21


def test_dry_run_creates_no_state_or_live_messages(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "BASE", tmp_path)
    monkeypatch.setattr(runner, "READY", tmp_path / "rotation_initialized.json")
    monkeypatch.setattr(runner, "PENDING", tmp_path / "news_pending.json")
    monkeypatch.setattr(runner, "RECEIPTS", tmp_path / "news_deliveries.json")
    snap = sample_snapshot()
    result = runner.run(dry_run=True, snapshot=snap)
    assert result["warmup"] == 1
    assert list(tmp_path.iterdir()) == []






def test_discord_rate_limit_bounded_and_success():
    class Result:
        def __init__(self, code, value):
            self.status_code, self.headers = code, {"Retry-After": "0.5"}
            self.value = value
        def json(self):
            return {"id": self.value}

    class Session:
        def __init__(self):
            self.codes = [Result(429, None), Result(200, "123")]
            self.calls = []
        def post(self, url, **kwargs):
            self.calls.append(kwargs)
            return self.codes.pop(0)

    session, sleeps = Session(), []
    client = DiscordWebhookClient("https://discord.com/api/webhooks/123/secret",
                                  session=session, sleeper=sleeps.append)
    receipt = client.send(NewsPost("a", "T", "same #FPL", 10))
    assert receipt == "123"
    assert len(session.calls) == 2 and sleeps == [0.5]
    assert all(call["json"]["allowed_mentions"] == {"parse": []} for call in session.calls)



def test_telegram_failure_does_not_block_discord_and_recovers(tmp_path):
    class FailingTelegram(FakeTelegram):
        fail = True
        def send_text(self, text):
            self.calls += 1
            if self.fail:
                raise RuntimeError("temporarily unavailable")
            return 42

    path = tmp_path / "receipts.json"
    telegram, discord = FailingTelegram(), FakeDiscord()
    post = NewsPost("new-story", "headline", "verified fact and tags", 10)
    with pytest.raises(RuntimeError):
        publish_shared(post, path, telegram, discord)
    assert telegram.calls == discord.calls == 1
    assert load_journal(path)["new-story"]["discord_delivered"] is True
    telegram.fail = False
    publish_shared(post, path, telegram, discord)
    assert (telegram.calls, discord.calls) == (2, 1)






def test_read_timeout_fences_telegram_and_keeps_discord_receipt(tmp_path):
    """No second Telegram upload when the first may already be in the chat."""
    from vortex.telegram import TelegramDeliveryError

    class UncertainTelegram(FakeTelegram):
        def send_text(self, text):
            self.calls += 1
            exc = TelegramDeliveryError("Telegram sendMessage network or JSON failure (ReadTimeout)")
            exc.delivery_uncertain = True
            raise exc

    path = tmp_path / "deliveries.json"
    bot, discord = UncertainTelegram(), FakeDiscord()
    post = NewsPost("fixture-timeout", "Fixture Targets", "verified fixtures #FPL", 11)
    with pytest.raises(RuntimeError, match="Partial delivery"):
        publish_shared(post, path, bot, discord, now_iso="2026-11-11T14:35:00+00:00")
    row = load_journal(path)["fixture-timeout"]
    assert row["telegram_send_pending"] is True
    assert row["discord_delivered"] is True
    assert not row.get("delivered")
    with pytest.raises(RuntimeError, match="manual reconciliation required"):
        publish_shared(post, path, bot, discord)
    assert bot.calls == 1 and discord.calls == 1


def test_telegram_400_rejection_remains_retryable(tmp_path):
    from vortex.telegram import TelegramDeliveryError

    class RejectedTelegram(FakeTelegram):
        reject = True
        def send_text(self, text):
            self.calls += 1
            if self.reject:
                error = TelegramDeliveryError("Telegram sendMessage: chat-not-found")
                error.confirmed_rejection = True
                error.delivery_uncertain = False
                raise error
            return 177

    path = tmp_path / "deliveries.json"
    bot, discord = RejectedTelegram(), FakeDiscord()
    post = NewsPost("confirmed-reject", "Fixture Targets", "verified #FPL", 11)
    with pytest.raises(RuntimeError, match="Partial delivery"):
        publish_shared(post, path, bot, discord)
    assert not load_journal(path)["confirmed-reject"].get("telegram_send_pending")
    bot.reject = False
    row = publish_shared(post, path, bot, discord)
    assert row["telegram_message_id"] == 177
    assert bot.calls == 2 and discord.calls == 1


def test_previous_ambiguous_fixture_receipt_does_not_resend(tmp_path):
    path = tmp_path / "deliveries.json"
    path.write_text(json.dumps({"fixture-pending": {
        "discord_delivered": True, "discord_message_id": "confirmed",
        "telegram_send_pending": True,
        "telegram_uncertain_at": "2026-11-11T14:35:00+00:00"
    }}))
    bot, discord = FakeTelegram(), FakeDiscord()
    with pytest.raises(RuntimeError, match="manual reconciliation required"):
        publish_shared(NewsPost("fixture-pending", "Target", "fixture #FPL", 11),
                       path, bot, discord)
    assert bot.calls == discord.calls == 0


def test_real_discord_client_does_not_blindly_retry_unknown_acceptance():
    import requests
    from vortex.syndication import DeliveryUncertain
    class Session:
        def __init__(self): self.calls = 0
        def post(self, *args, **kwargs):
            self.calls += 1
            raise requests.ReadTimeout("could have posted")
    session = Session()
    client = DiscordWebhookClient("https://discord.com/api/webhooks/123/unit-test",
                                  session=session, sleeper=lambda seconds: None)
    with pytest.raises(DeliveryUncertain):
        client.send(NewsPost("one", "Test", "One verified caption", 10))
    assert session.calls == 1


def test_real_discord_client_http_5xx_not_blindly_retried():
    from vortex.syndication import DeliveryUncertain
    class Response:
        status_code = 502
        headers = {}
    class Session:
        def __init__(self): self.calls = 0
        def post(self, *args, **kwargs):
            self.calls += 1
            return Response()
    session = Session()
    client = DiscordWebhookClient("https://discord.com/api/webhooks/123/unit-test",
                                  session=session, sleeper=lambda seconds: None)
    with pytest.raises(DeliveryUncertain):
        client.send(NewsPost("one", "Test", "One verified caption", 10))
    assert session.calls == 1


def test_telegram_write_5xx_is_not_retried(monkeypatch):
    import requests
    from vortex import telegram as tg
    from vortex.telegram import TelegramClient, TelegramDeliveryError
    monkeypatch.setattr("vortex.publishing_window.assert_allowed", lambda: None)
    calls = []
    class Response:
        status_code = 502
        def raise_for_status(self):
            raise requests.HTTPError("server error", response=self)
        def json(self): return {}
    def fake_post(*args, **kwargs):
        calls.append(args[0])
        return Response()
    monkeypatch.setattr(tg.requests, "post", fake_post)
    client = TelegramClient(token="INERT-UNIT-TEST", chat_id="INERT-UNIT-TEST")
    with pytest.raises(TelegramDeliveryError) as error:
        client.send_text("One verified story")
    assert error.value.delivery_uncertain is True
    assert len(calls) == 1


def test_live_discord_intent_written_before_any_webhook_call(tmp_path):
    from vortex.syndication import DiscordWebhookClient
    ledger = tmp_path / "receipts.json"
    class Telegram:
        def send_text(self, caption): return 7
    class Discord(DiscordWebhookClient):
        def __init__(self): pass
        def send(self, post):
            checkpoint = json.loads(ledger.read_text())[post.identity]
            assert checkpoint["delivered"] is True
            assert checkpoint["discord_send_pending"] is True
            return "discord-7"
    post = NewsPost("checkpoint", "Headline", "One verified caption", 10)
    result = publish_shared(post, ledger, Telegram(), Discord())
    assert result["discord_delivered"] and result["delivered"]
    assert not json.loads(ledger.read_text())["checkpoint"].get("discord_send_pending")




def test_retired_player_news_cannot_reenter_rotation_queue(monkeypatch, tmp_path):
    from vortex.syndication import save_journal
    for name in ("READY", "PENDING", "RECEIPTS"):
        monkeypatch.setattr(runner, name, tmp_path / (name + ".json"))
    save_journal(runner.READY, {"initialized": True})
    save_journal(runner.PENDING, {"rss:obsolete": {"title": "FPL NEWS"},
                                 "availability:old": {"title": "STATUS"}})
    save_journal(runner.RECEIPTS, {"rss:obsolete": {"telegram_message_id": 42, "delivered": True}})
    monkeypatch.setattr("vortex.rotation_planner.build_rotation_plan", lambda *a: None)
    t, d = FakeTelegram(), FakeDiscord()
    result = runner.run(snapshot=sample_snapshot(), telegram=t, discord=d)
    assert result["retired_status_cards"] == 2 and result["pending"] == result["sent"] == 0
    assert load_journal(runner.PENDING) == {}
    assert load_journal(runner.RECEIPTS)["rss:obsolete"]["telegram_message_id"] == 42
    assert t.calls == d.calls == 0
    assert not hasattr(runner, "render_news_card")
    assert not hasattr(runner, "collect_reported_headlines")
