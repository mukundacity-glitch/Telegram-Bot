"""No-live-post regression coverage for unified Telegram/Discord news."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vortex.fpl import FplSnapshot
from vortex.news_sources import _feed_items, collect_fpl_changes, collect_reported_headlines, fpl_baseline, _tags
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


def test_official_baseline_has_no_false_changes():
    snap = sample_snapshot()
    assert collect_fpl_changes(snap, {}, snap.fetched_at) == []
    assert collect_fpl_changes(snap, fpl_baseline(snap), snap.fetched_at) == []


def test_real_injury_and_price_change_generate_verifiable_posts():
    prior = fpl_baseline(sample_snapshot())
    snap = sample_snapshot(status="d", cost=71, news="Knock")
    news = collect_fpl_changes(snap, prior, snap.fetched_at)
    assert len(news) == 2
    assert all("Official FPL" in post.caption for post in news)
    assert "£7.0m to £7.1m" in news[1].caption
    assert "not a predicted start probability" not in news[0].caption
    assert "Chelsea" not in news[0].caption
    assert all(len([w for w in post.caption.split() if w.startswith("#")]) == 4 for post in news)


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
    monkeypatch.setattr(runner, "BASELINE", tmp_path / "news_baseline.json")
    monkeypatch.setattr(runner, "SEEN", tmp_path / "news_seen.json")
    monkeypatch.setattr(runner, "PENDING", tmp_path / "news_pending.json")
    monkeypatch.setattr(runner, "RECEIPTS", tmp_path / "news_deliveries.json")
    snap = sample_snapshot()
    result = runner.run(dry_run=True, snapshot=snap, rss=[])
    assert result["warmup"] == 1
    assert list(tmp_path.iterdir()) == []


def test_first_run_warms_baseline_without_flood(monkeypatch, tmp_path):
    for name in ("BASELINE", "SEEN", "PENDING", "RECEIPTS"):
        monkeypatch.setattr(runner, name, tmp_path / (name.lower() + ".json"))
    report = NewsPost("rss1", "Headline", "Only a report", 10)
    snap = sample_snapshot()
    output = runner.run(snapshot=snap, rss=[report], telegram=FakeTelegram(),
                        discord=FakeDiscord())
    assert output["warmup"] == 1
    assert json.loads(runner.BASELINE.read_text())["99"]["now_cost"] == 70
    assert json.loads(runner.SEEN.read_text())["rss1"]


def test_news_queue_dispatched_to_both_without_repeating(monkeypatch, tmp_path):
    for name in ("BASELINE", "SEEN", "PENDING", "RECEIPTS"):
        monkeypatch.setattr(runner, name, tmp_path / (name.lower() + ".json"))
    from PIL import Image
    def fake_render(post, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1920, 1080), "navy").save(output)
        return output
    monkeypatch.setattr(runner, "render_news_card", fake_render)
    monkeypatch.setattr(runner, "NEWS_OUTPUT", tmp_path / "output")
    snap = sample_snapshot()
    runner.run(snapshot=snap, rss=[], telegram=FakeTelegram(), discord=FakeDiscord())
    t, d = FakeTelegram(), FakeDiscord()
    story = NewsPost("rss-new", "Headline", "Attributed report with source", 10,
                     player_name="Example", photo_code=123456, club_code=3)
    first = runner.run(snapshot=snap, rss=[story], telegram=t, discord=d)
    second = runner.run(snapshot=snap, rss=[story], telegram=t, discord=d)
    assert first["sent"] == 1 and second["sent"] == 0
    assert t.calls == d.calls == 1


def test_feed_xml_rejects_unsafe_entities():
    xml = b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel/></rss>'
    assert _feed_items(xml) == []


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


def test_x_source_registry_rss_filters_and_deduplicates():
    now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    xml = ('''<rss><channel><item><title>Arsenal player Example injury update from club</title>
    <link>https://example.org/arsenal/1</link><pubDate>Mon, 02 Nov 2026 11:00:00 GMT</pubDate>
    </item></channel></rss>''').encode()
    class Response:
        content = xml
        def raise_for_status(self):
            return None
    class Session:
        def __init__(self):
            self.calls = []
        def get(self, url, **kwargs):
            self.calls.append(url)
            return Response()
    session = Session()
    registry = {"feeds": [{"id": "rss-a", "url": "https://feeds.bbci.co.uk/a"},
                          {"id": "rss-b", "url": "https://feeds.bbci.co.uk/b"}]}
    posts = collect_reported_headlines(sample_snapshot(now), now,
                                      session=session, registry=registry)
    assert len(session.calls) == 2
    assert len(posts) == 1
    assert posts[0].source == "rss-a"
    assert "Report only; details not independently confirmed." in posts[0].caption
    assert "https://example.org/arsenal/1" in posts[0].caption


def test_unapproved_feed_host_is_not_fetched():
    now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    class NeverRequest:
        def get(self, url, **kwargs):
            raise AssertionError("Unapproved external domain must not be fetched")
    registry = {"feeds": [{"id": "bad", "url": "https://127.0.0.1/internal"}]}
    assert collect_reported_headlines(sample_snapshot(now), now, session=NeverRequest(),
                                      registry=registry) == []


def test_failed_head_story_cannot_starve_following_verified_news(monkeypatch, tmp_path):
    """A held story remains retryable without blocking tomorrow's usable news."""
    from PIL import Image
    for name in ("BASELINE", "SEEN", "PENDING", "RECEIPTS"):
        monkeypatch.setattr(runner, name, tmp_path / (name.lower() + ".json"))
    monkeypatch.setattr(runner, "NEWS_OUTPUT", tmp_path / "images")
    now = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
    snapshot = sample_snapshot(now)
    telegram, discord = FakeTelegram(), FakeDiscord()
    runner.run(snapshot=snapshot, now=now, rss=[],
               telegram=telegram, discord=discord)

    def render(post, output):
        if post.identity == "unrenderable":
            raise RuntimeError("Missing verified media")
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1920, 1080), "navy").save(output)
        return output

    monkeypatch.setattr(runner, "render_news_card", render)
    unavailable = NewsPost("unrenderable", "Bad media", "Verified facts", 10)
    ready = NewsPost("ready", "Verified news", "Verified facts", 10)
    with pytest.raises(RuntimeError, match="unrenderable"):
        runner.run(snapshot=snapshot, now=now, rss=[unavailable, ready],
                   telegram=telegram, discord=discord, max_posts=1)
    assert list(json.loads(runner.PENDING.read_text())) == ["ready", "unrenderable"]
    report = runner.run(snapshot=snapshot, now=now, rss=[unavailable, ready],
                        telegram=telegram, discord=discord, max_posts=1)
    assert report["sent"] == 1
    assert telegram.calls == discord.calls == 1
    assert list(json.loads(runner.PENDING.read_text())) == ["unrenderable"]

def test_expired_news_queue_never_replays_old_verified_headlines():
    now = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)
    pending = {
        'old': {'gameweek': 11,
                'caption': 'GW11 change. Source: Official FPL, 2026-11-07 16:00 UTC'},
        'fresh': {'gameweek': 11,
                  'caption': 'GW11 change. Source: Official FPL, 2026-11-10 17:30 UTC'},
        'past-gw': {'gameweek': 10,
                    'caption': 'GW10 change. Source: Official FPL, 2026-11-10 17:30 UTC'},
        'partial': {'gameweek': 11,
                    'caption': 'GW11 change. Source: Official FPL, 2026-11-02 17:30 UTC'}
    }
    ledger = {'partial': {'delivered': True}}
    expired = runner._expire_undelivered_old_news(pending, ledger, now, 11)
    assert set(expired) == {'old', 'past-gw'}
    assert set(pending) == {'fresh', 'partial'}


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
