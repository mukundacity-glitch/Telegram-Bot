"""Regression tests for every premium-rendered FPL VORTEX publication slot."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image

from vortex.content import generate
from vortex.fpl import price_snapshot
from vortex.render import render

from test_content import fake_snapshot

SLOTS = ('news', 'transfer', 'prices', 'captaincy', 'review', 'elite', 'evening')


def sample_content(slot: str, monkeypatch: pytest.MonkeyPatch):
    snapshot = fake_snapshot()
    now = datetime(2026, 10, 16, 14, tzinfo=timezone.utc)
    if slot == 'news':
        for player in snapshot.players[:3]:
            player['news'] = 'Injury status under review by the FPL team. Expected date unknown.'
            player['news_added'] = '2026-10-16T12:00:00Z'
    if slot == 'prices':
        old_prices = price_snapshot(snapshot)
        for player in snapshot.players[:4]:
            player['now_cost'] += 1
    else:
        old_prices = {}
    if slot == 'review':
        monkeypatch.setattr('vortex.content.previous_gw_top_players',
                            lambda sample: [(player, index + 12) for index, player in enumerate(sample.players[:4])])
    return generate(slot, snapshot, now, old_prices)


@pytest.mark.parametrize('slot', SLOTS)
def test_premium_templates_render_with_verified_media(slot: str, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    content = sample_content(slot, monkeypatch)
    assert content.cards

    def mock_media(session: object, code: int | None, kind: str, cache: dict):
        return Image.new('RGBA', (230, 300) if kind == 'photo' else (80, 80),
                         (45, 145, 225, 255) if kind == 'photo' else (245, 240, 225, 255))

    monkeypatch.setattr('vortex.matchup._media', mock_media)
    monkeypatch.setattr('vortex.premium._media', mock_media)
    result = render(content, tmp_path / f'{slot}.png', session=object())
    assert result.is_file() and result.stat().st_size > 100_000
    with Image.open(result) as image:
        assert image.size == (1536, 864)
        assert image.mode == 'RGB'


@pytest.mark.parametrize('slot', SLOTS)
def test_player_templates_fail_closed_on_missing_images(slot: str, tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    content = sample_content(slot, monkeypatch)
    monkeypatch.setattr('vortex.matchup._media', lambda *args: None)
    monkeypatch.setattr('vortex.premium._media', lambda *args: None)
    target = tmp_path / f'{slot}.png'
    with pytest.raises(RuntimeError, match='Mandatory club badge unavailable'):
        render(content, target, session=object())
    assert not target.exists()


def test_no_news_is_honest_not_fabricated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = generate('news', fake_snapshot(), datetime(2026, 10, 16, 14, tzinfo=timezone.utc), {})
    monkeypatch.setattr('vortex.premium._media', lambda *args: pytest.fail('No requests for empty news'))
    result = render(content, tmp_path / 'empty-news.png', session=object())
    assert result.exists()


def test_first_price_baseline_is_honest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = generate('prices', fake_snapshot(), datetime(2026, 10, 16, 14, tzinfo=timezone.utc), {})
    monkeypatch.setattr('vortex.premium._media', lambda *args: pytest.fail('No requests for baseline'))
    result = render(content, tmp_path / 'price-baseline.png', session=object())
    assert result.exists()


def test_last_gw_live_payload_supports_list_form(monkeypatch: pytest.MonkeyPatch) -> None:
    from vortex.fpl import previous_gw_top_players
    snapshot = fake_snapshot()
    monkeypatch.setattr('vortex.fpl._fetch_json', lambda *args: {
        'elements': [{'id': snapshot.players[1]['id'], 'stats': {'total_points': 14}}]
    })
    winners = previous_gw_top_players(snapshot)
    assert winners[0][0]['id'] == snapshot.players[1]['id']
    assert winners[0][1] == 14

@pytest.mark.parametrize('slot', SLOTS)
def test_premium_layout_handles_missing_player_portrait(
    slot: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = sample_content(slot, monkeypatch)

    def media_without_portrait(session: object, code: int | None, kind: str, cache: dict):
        return None if kind == 'photo' else Image.new('RGBA', (80, 80), (210, 220, 230, 255))

    monkeypatch.setattr('vortex.premium._media', media_without_portrait)
    result = render(content, tmp_path / f'{slot}-no-portrait.png', session=object())
    assert result.exists()
