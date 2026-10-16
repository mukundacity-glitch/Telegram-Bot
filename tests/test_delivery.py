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
