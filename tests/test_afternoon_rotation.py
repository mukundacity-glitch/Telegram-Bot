from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image
import pytest

from vortex import (afternoon_rotation_render, autonomous_render, availability_board,
                    availability_render, odds_board, odds_board_render)
from vortex.afternoon_rotation import build_rotation
from vortex.autonomous_schedule import AFTERNOON, catchup_slots, publication_key
from vortex.queue_retry import verified_caption
from test_autonomous_engine import world  # noqa: F401

MONDAY = datetime(2026, 11, 16, 13, 30, tzinfo=ZoneInfo('America/New_York'))


def test_one_slot_per_eastern_date_even_when_gameweek_rolls():
    assert AFTERNOON not in catchup_slots(MONDAY-timedelta(seconds=1), {}, 11, limit=None)
    assert AFTERNOON in catchup_slots(MONDAY, {}, 11, limit=None)
    key = publication_key(AFTERNOON, MONDAY, 11, '2026-27')
    assert key == publication_key(AFTERNOON, MONDAY+timedelta(hours=2), 12, '2026-27')
    state = {key: {'status': 'delivered'}}
    assert AFTERNOON not in catchup_slots(MONDAY, state, 12, limit=None)
    assert AFTERNOON in catchup_slots(MONDAY+timedelta(days=1), state, 12, limit=None)


@pytest.mark.parametrize('day,kind', [
    (1, 'availability25'), (2, 'low_owned_six'), (3, 'odds_board'),
    (4, 'rotation_value'), (5, 'rotation_transfers'), (6, 'odds_board'), (7, 'rotation_transfers'),
])
def test_all_editions_render_one_png_with_five_caption_lines(day, kind, world, tmp_path, monkeypatch):
    snapshot, _, evidence, model = world
    monkeypatch.setenv('FPL_TELEGRAM_HANDLE', '@FPLVortexDailyBot')
    monkeypatch.setenv('FPL_DISCORD_HANDLE', '@fplvortex')
    monkeypatch.setattr(availability_board, 'fetch_verified_xpts', lambda *a, **kw: {})
    for renderer in (autonomous_render, availability_render, afternoon_rotation_render):
        monkeypatch.setattr(renderer, '_assets', lambda *a, **kw: (
            Image.new('RGBA', (80, 90), '#627FC0'), Image.new('RGBA', (40, 40), '#40DCD8')))
    monkeypatch.setattr(odds_board_render, '_media', lambda *a: Image.new('RGBA', (40, 40), '#40DCD8'))
    # Simulate more than ten fixtures to exercise the single-image double-GW layouts.
    if day in (3, 6):
        source = snapshot.fixtures[0]
        snapshot.fixtures.extend({**source, 'id': 901 + i} for i in range(9))
    mk = {'home_goals': 1.8, 'away_goals': 1.0, 'home_cs': 36, 'away_cs': 17,
          'home_win_market_pct': 53, 'away_win_market_pct': 20}
    monkeypatch.setattr(odds_board, 'verified_match_odds',
                        lambda snap, fixtures, **kw: {f['id']: mk for f in fixtures})
    now = MONDAY + timedelta(days=day-1)
    plan = build_rotation(AFTERNOON, snapshot, now, evidence, model)
    assert plan.edition == AFTERNOON.edition and plan.kind == kind
    assert plan.extra['rotation_day'] == day
    assert plan.extra.get('market_outlook', False) == (day == 3)
    assert len([l for l in verified_caption(plan.title, plan.caption).splitlines() if l]) == 5
    assert len(plan.caption.splitlines()[-1].split()) == 4
    if day == 4:
        assert len(plan.players) == 17
    image_path = tmp_path / f'day-{day}.png'
    assert autonomous_render.render(plan, snapshot, now, image_path, evidence.session) == [image_path]
    with Image.open(image_path) as image:
        assert image.size == ((1080, 1920) if day in (3, 6) else (1920, 1080))
        image.verify()
