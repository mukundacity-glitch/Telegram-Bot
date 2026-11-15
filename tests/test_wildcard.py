from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from os import getenv
from types import SimpleNamespace

from PIL import Image

from test_autonomous_engine import world  # noqa: F401
from vortex import wildcard, wildcard_render
from vortex.autonomous_schedule import ET, RETIRED_EDITIONS, WILDCARD, catchup_slots, publication_key
from vortex.queue_retry import verified_caption
from vortex.schedule import SLOT_CRONS

DUE = datetime(2026, 11, 17, 15, 30, tzinfo=ET)


def test_wildcard_repeats_on_tuesdays():
    assert 'market-verdict' in RETIRED_EDITIONS
    assert 'transfer_suggestions' not in SLOT_CRONS.values()
    for timestamp in (DUE - timedelta(days=1), DUE - timedelta(seconds=1), DUE + timedelta(days=1)):
        assert WILDCARD not in catchup_slots(timestamp, {}, 11, limit=None)
    assert WILDCARD in catchup_slots(DUE, {}, 11, limit=None)
    key = publication_key(WILDCARD, DUE, 11)
    assert key == publication_key(WILDCARD, DUE + timedelta(hours=1), 12)
    delivered = {key: {'status': 'delivered'}}
    assert WILDCARD not in catchup_slots(DUE, delivered, 12, limit=None)
    for weeks in (1, 12, 104):
        future = DUE + timedelta(weeks=weeks)
        assert WILDCARD in catchup_slots(future, delivered, 12, limit=None)
        assert publication_key(WILDCARD, future, 11) != key


def test_wildcard_draft_and_five_gameweek_art(world, tmp_path, monkeypatch):
    s, now, _, _ = world
    teams = {i: {'code': i, 'name': f'Team {i}', 'short_name': f'T{i}'} for i in range(1, 9)}
    fixtures = [{
        'id': week * 100 + i, 'event': week, 'team_h': i, 'team_a': i + 1, 'finished': week < 10,
        'team_h_difficulty': i % 5 + 1, 'team_a_difficulty': (i + 2) % 5 + 1,
        'kickoff_time': (now + timedelta(days=week-9)).isoformat(),
    } for week in range(7, 15) for i in (1, 3, 5, 7)]
    players = [{**p, 'team': i % 8 + 1, 'starts': 3, 'minutes': 260, 'now_cost': 44 + i % 8 * 3}
               for i, p in enumerate(s.players)]
    players[0]['status'] = 'i'
    snapshot = replace(s, teams=teams, fixtures=fixtures, players=players)
    monkeypatch.setattr(wildcard, 'fetch_verified_xpts', lambda *a: {})
    monkeypatch.setattr(wildcard_render, '_media', lambda *a: Image.new('RGBA', (80, 90), '#79a1bf'))
    monkeypatch.setenv('FPL_TELEGRAM_HANDLE', '@FPLVortexDailyBot')
    monkeypatch.setenv('FPL_DISCORD_HANDLE', '@fplvortex')
    plan = wildcard.build_wildcard(WILDCARD, snapshot, now, SimpleNamespace(session=None))
    data = plan.extra
    assert data['weeks'] == list(range(10, 15))
    assert len(plan.players) == 15 and len(data['xi']) == 11 and len(data['bench']) == 4
    assert Counter(p['element_type'] for p in plan.players) == wildcard.QUOTAS
    assert max(Counter(p['team'] for p in plan.players).values()) <= 3
    assert data['cost'] <= 1000 and all(p['status'] == 'a' for p in plan.players)
    assert all(c in xi for c, xi in zip(data['weekly_captains'], data['lineups']))
    assert not data['model'] and 'xPts' not in plan.caption
    assert len([line for line in verified_caption(plan.title, plan.caption).splitlines() if line]) == 5
    html = wildcard_render.build_html(plan, snapshot, None)
    assert html.count('class="player"') == 15 and html.count('class="fdr fdr-') == 75
    assert 'class="pitch"' in html and 'GW14' in html
    (tmp_path / 'wildcard.html').write_text(html, encoding='utf-8')
    if getenv('GITHUB_ACTIONS') == 'true':
        output = wildcard_render.render_wildcard(plan, snapshot, tmp_path / 'wildcard.png', None)
        with Image.open(output) as graphic:
            assert graphic.size == (1920, 1080)
            graphic.verify()
