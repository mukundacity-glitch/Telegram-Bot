from datetime import datetime, timedelta

from PIL import Image

from test_autonomous_engine import world  # noqa: F401
from vortex import scouting_render, shot_quality
from vortex.autonomous_content import build
from vortex.autonomous_render import render
from vortex.autonomous_schedule import ET, RETIRED_EDITIONS, SHOT_QUALITY, catchup_slots, publication_key
from vortex.queue_retry import verified_caption
from vortex.schedule import SLOT_HOURS

SUNDAY = datetime(2026, 11, 22, 16, 30, tzinfo=ET)


def test_sunday_chart_takes_the_retired_slot():
    assert (16, 0) not in SLOT_HOURS.values()
    assert 'deadline-watch' in RETIRED_EDITIONS
    assert SHOT_QUALITY not in catchup_slots(SUNDAY-timedelta(minutes=1), {}, 11, limit=None)
    assert SHOT_QUALITY in catchup_slots(SUNDAY, {}, 11, limit=None)
    assert all(SHOT_QUALITY not in catchup_slots(SUNDAY+timedelta(days=day), {}, 11, limit=None)
               for day in range(1, 7))
    assert SHOT_QUALITY in catchup_slots(SUNDAY+timedelta(days=7), {}, 11, limit=None)
    key = publication_key(SHOT_QUALITY, SUNDAY, 11)
    assert SHOT_QUALITY not in catchup_slots(SUNDAY, {key: {'status': 'delivered'}}, 12, limit=None)


def test_shot_quality_uses_exact_denominators_and_renders(world, tmp_path, monkeypatch):
    snapshot, _, evidence, _ = world
    players = [p for p in snapshot.players if p['element_type'] == 4][:9]
    stats = [(p, {'minutes': 450, 'total_shots': 10 + i, 'xg': (i + 1) / 2, 'assists': i})
             for i, p in enumerate(players)]
    stats[-1][1]['incomplete_shot_xg'] = True
    stats[-2][1]['minutes'] = 349
    stats[-3][1]['total_shots'] = 9

    def archived(snap, through, session, year, fields, *, require_shot_xg):
        assert through == 9 and require_shot_xg
        return stats, ['https://example.invalid/verified.csv']

    monkeypatch.setattr(shot_quality, 'player_totals', archived)
    monkeypatch.setattr(scouting_render, '_media', lambda *a: Image.new('RGBA', (80, 90), '#647caa'))
    monkeypatch.setenv('FPL_TELEGRAM_HANDLE', '@FPLVortexDailyBot')
    monkeypatch.setenv('FPL_DISCORD_HANDLE', '@fplvortex')
    plan = build(SHOT_QUALITY, snapshot, SUNDAY, evidence)
    assert len(plan.extra['rows']) == 6
    row = plan.extra['rows'][2]
    assert row['x'] == 2 * 90 / 450
    assert row['y'] == 1.5 / 12
    assert plan.extra['units'] == ('PER 90', 'PER SHOT')
    assert len([line for line in verified_caption(plan.title, plan.caption).splitlines() if line]) == 5
    image_path = tmp_path / 'shot-quality.png'
    assert render(plan, snapshot, SUNDAY, image_path, evidence.session) == [image_path]
    with Image.open(image_path) as image:
        assert image.size == (1920, 1080)
        image.verify()
