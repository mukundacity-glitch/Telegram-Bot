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
    monkeypatch.setattr(bot, 'render', lambda content, path: path)
    return deliveries


def test_scheduled_comparison_deduplicates(delivery_environment: list[str]) -> None:
    assert bot.run('auto', '0 8 * * *') == 0
    assert delivery_environment == []


def test_manual_comparison_reposts_even_if_previously_delivered(delivery_environment: list[str]) -> None:
    assert bot.run('comparison') == 0
    assert delivery_environment == ['THE FPL DECISION ROOM']


def test_manual_preview_never_modifies_daily_state(delivery_environment: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path
    path = bot.STATE / 'deliveries.json'
    before = path.read_bytes()
    assert bot.run('preview-news') == 0
    assert delivery_environment == ['THE FPL DECISION ROOM — PREVIEW']
    assert path.read_bytes() == before

def test_daily_captaincy_publishes_without_deadline_tomorrow(
    delivery_environment: list[str],
) -> None:
    assert bot.run('captaincy', '0 16 * * *') == 0
    assert delivery_environment == ['THE FPL DECISION ROOM']


def test_new_buy_slot_deduplicates_by_gw(delivery_environment, monkeypatch):
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
    assert bot.run("auto", "0 9 * * *") == 1
    assert delivery_environment == []


def test_new_projection_slot_deduplicates_across_backup_check(delivery_environment, monkeypatch):
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    state_path = bot.STATE / "deliveries.json"
    ledger = json.loads(state_path.read_text(encoding="utf-8"))
    ledger[f"{today}:projections:GW7"] = {"delivered": True}
    state_path.write_text(json.dumps(ledger), encoding="utf-8")
    monkeypatch.setattr(bot, "upcoming_deadline", lambda snap: now + timedelta(days=1))
    assert bot.run("auto", "0 7 * * *") == 0
    assert bot.run("auto", "15 7 * * *") == 0
    assert delivery_environment == []


def test_new_team_and_transfer_slots_abort_after_deadline(delivery_environment, monkeypatch):
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(bot, "upcoming_deadline", lambda snap: now - timedelta(minutes=1))
    assert bot.run("auto", "0 11 * * *") == 1
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


def test_workflow_default_is_auto_and_never_test():
    """Regression guard on workflow_dispatch and forced scheduled AUTO selection."""
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "telegram-daily.yml"
    workflow = path.read_text(encoding="utf-8")
    assert "default: auto" in workflow
    assert "default: test" not in workflow
    assert "\\n          - test\\n" not in workflow
    assert "REQUESTED_SLOT: ${{ github.event_name == 'schedule' && 'auto' || inputs.slot || 'auto' }}" in workflow
    assert "timezone: America/New_York" in workflow
