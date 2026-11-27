"""Prevent regression of GitHub manual versus scheduled Telegram delivery semantics."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vortex.content import Card, Content
import vortex.bot as bot


@pytest.fixture()
def delivery_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    deliveries: list[str] = []
    date = datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York')).date()
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'deliveries.json').write_text(json.dumps({f'{date}:comparison': {'delivered': True}}), encoding='utf-8')

    class TestTelegramClient:
        def send_png(self, path: Path, caption: str, title: str, gw: int) -> int:
            deliveries.append(title)
            return 23

    class TestSnapshot:
        events: list[dict] = []

    content = Content(kind='comparison', title='THE FPL DECISION ROOM', kicker='8 AM',
                      cards=(Card('Example', 'ABC', 'TEST', ('Verified',)),),
                      verdict='TEST ONLY', caption='six\nline\ncaption\nfor\nunit\ntest',
                      data_at='today', gw=7, footer='Official FPL')
    monkeypatch.setattr(bot, 'STATE', state)
    monkeypatch.setattr(bot, 'OUTPUT', tmp_path / 'output')
    monkeypatch.setattr(bot, 'TelegramClient', TestTelegramClient)
    monkeypatch.setattr(bot, 'collect_snapshot', lambda: TestSnapshot())
    monkeypatch.setattr(bot, 'generate', lambda kind, snapshot, now, prior: content)
    def render_fixture(content, path):
        from PIL import Image
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (1920, 1080), 'navy').save(path)
        return path
    monkeypatch.setattr(bot, 'render', render_fixture)
    return deliveries


def test_retired_comparison_cannot_publish_through_old_schedule(delivery_environment: list[str]) -> None:
    with pytest.raises(ValueError, match='Unrecognized workflow schedule'):
        bot.run('auto', '0 8 * * *')
    assert delivery_environment == []


def test_manual_comparison_reposts_even_if_previously_delivered(delivery_environment: list[str]) -> None:
    assert bot.run('comparison') == 0
    assert delivery_environment == ['THE FPL DECISION ROOM']


def test_manual_preview_never_modifies_daily_state(delivery_environment: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path
    path = bot.STATE / 'deliveries.json'
    before = path.read_bytes()
    assert bot.run('preview-comparison') == 0
    assert delivery_environment == ['THE FPL DECISION ROOM — PREVIEW']
    assert path.read_bytes() == before

def test_retired_daily_captaincy_has_no_active_cron(
    delivery_environment: list[str],
) -> None:
    with pytest.raises(ValueError, match='Unrecognized workflow schedule'):
        bot.run('auto', '0 16 * * *')
    assert delivery_environment == []


def test_legacy_buy_deduplicates_when_given_a_schedule(delivery_environment, monkeypatch):
    from vortex.schedule import SLOT_CRONS
    monkeypatch.setitem(SLOT_CRONS, "0 9 * * *", "buy")
    from datetime import timedelta
    today = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date()
    store = bot.STATE / "deliveries.json"
    state = json.loads(store.read_text())
    state[f"{today}:buy:GW7"] = {"delivered": True}
    store.write_text(json.dumps(state))
    monkeypatch.setattr(bot, "upcoming_deadline", lambda snap: datetime.now(timezone.utc) + timedelta(days=1))
    assert bot.run("auto", "0 9 * * *") == 0
    assert delivery_environment == []


def test_new_buy_slot_never_sends_after_deadline(delivery_environment, monkeypatch):
    from datetime import timedelta
    monkeypatch.setattr(bot, "upcoming_deadline", lambda snap: datetime.now(timezone.utc) - timedelta(minutes=1))
    assert bot.run("buy") == 1
    assert delivery_environment == []


def test_manual_projection_route_preserves_gameweek_deduplication(delivery_environment, monkeypatch):
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    state_path = bot.STATE / "deliveries.json"
    ledger = json.loads(state_path.read_text(encoding="utf-8"))
    ledger[f"{today}:projections:GW7"] = {"delivered": True}
    state_path.write_text(json.dumps(ledger), encoding="utf-8")
    monkeypatch.setattr(bot, "upcoming_deadline", lambda snap: now + timedelta(days=1))
    assert bot.run("projections", "0 7 * * *") == 0
    assert bot.run("projections", "15 7 * * *") == 0
    assert delivery_environment == []


def test_new_team_and_transfer_slots_abort_after_deadline(delivery_environment, monkeypatch):
    from vortex.schedule import SLOT_CRONS
    monkeypatch.setitem(SLOT_CRONS, "0 11 * * *", "team_analysis")
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(bot, "upcoming_deadline", lambda snap: now - timedelta(minutes=1))
    assert bot.run("auto", "0 11 * * *") == 1
    with pytest.raises(ValueError, match="Unrecognized workflow schedule"):
        bot.run("auto", "0 15 * * *")
    monkeypatch.setitem(SLOT_CRONS, "0 15 * * *", "transfer_suggestions")
    assert bot.run("auto", "0 15 * * *") == 1
    assert delivery_environment == []


def test_default_manual_auto_never_sends_test_or_posts(delivery_environment, monkeypatch):
    """Clicking default 'Run workflow → auto' must be harmless, not a test send."""
    class TelegramMustNotStart:
        def __init__(self):
            raise AssertionError("Manual AUTO must not instantiate Telegram client")
    monkeypatch.setattr(bot, "TelegramClient", TelegramMustNotStart)
    assert bot.run("auto", None) == 0
    assert delivery_environment == []


def test_existing_cron_still_executes_normal_publish(delivery_environment):
    """The cron dispatcher, unlike manual AUTO, must deliver as before."""
    assert bot.run("auto", "30 6 * * *") == 0
    assert delivery_environment == ["THE FPL DECISION ROOM"]


def test_scheduled_prices_skip_a_card_without_confirmed_moves(delivery_environment, monkeypatch):
    from vortex.schedule import SLOT_CRONS
    monkeypatch.setitem(SLOT_CRONS, "15 12 * * *", "prices")
    baseline = bot.STATE / "prices.json"
    baseline.write_text(json.dumps({"prices": {"1": 50}}), encoding="utf-8")
    previous = baseline.read_bytes()

    assert bot.run("auto", "15 12 * * *") == 0
    assert delivery_environment == []
    assert baseline.read_bytes() == previous


def test_workflow_defaults_to_direct_post_without_test_or_preview_ui():
    """Manual dispatch selects a real edition; scheduled dispatch stays separate."""
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "telegram-daily.yml"
    workflow = path.read_text(encoding="utf-8")
    assert "  workflow_dispatch:\n    inputs:\n      edition:" in workflow
    assert 'python -m vortex.autonomous_runner --manual --edition "$MANUAL_EDITION"' in workflow
    assert "python -m vortex.scheduled_dispatch" in workflow
    assert "python -m vortex.bot" not in workflow
    assert "timezone: America/New_York" not in workflow




def test_shared_delivery_backfills_only_discord_for_previously_delivered_slot(
    delivery_environment, monkeypatch
):
    """No duplicate Telegram photo if Discord is enabled after the slot ran."""
    posts = []

    class FakeDiscord:
        def send(self, post):
            posts.append((post.title, post.caption, post.gameweek))
            return "discord-883"

    monkeypatch.setenv("DUAL_PUBLISH_ENABLED", "true")
    # Mocked Telegram/Discord transports: inert non-network secrets for preflight.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "INERT-UNIT-TEST")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "INERT-UNIT-TEST")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/0/inert-test")
    monkeypatch.setattr(bot, "DiscordWebhookClient", FakeDiscord)
    assert bot.run("comparison") == 0
    assert delivery_environment == []
    assert posts == [("THE FPL DECISION ROOM", "six\nline\ncaption\nfor\nunit\ntest", 7)]
    journal = bot.read_state(bot.STATE / "deliveries.json")
    key = f"{datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York')).date()}:comparison"
    assert journal[key]["discord_delivered"] is True
    assert journal[key]["delivered"] is True
    assert bot.run("comparison") == 0
    assert len(posts) == 1


def test_dated_scheduled_caption_keeps_format_and_has_distinct_receipt_digest():
    from datetime import date
    from vortex.queue_retry import dated_caption
    from vortex.syndication import _caption_digest

    caption = 'Same facts today\nFixture context\n\n#FPL #GW11 #FPLVORTEX'
    monday = dated_caption(caption, date(2026, 11, 16))
    tuesday = dated_caption(caption, date(2026, 11, 17))
    assert monday.splitlines()[1:] == caption.splitlines()[1:]
    assert _caption_digest(monday) != _caption_digest(tuesday)
