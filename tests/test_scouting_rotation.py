from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image
import pytest

from test_autonomous_engine import world  # noqa: F401
from vortex import scouting_render, scouting_rotation
from vortex.autonomous_render import render
from vortex.autonomous_schedule import RETIRED_EDITIONS, SCOUTING, catchup_slots, publication_key
from vortex.queue_retry import verified_caption
from vortex.schedule import SLOT_CRONS, SLOT_HOURS
from vortex.scheduled_dispatch import upcoming_editorial

SUNDAY = datetime(2026, 11, 15, 14, 30, tzinfo=ZoneInfo('America/New_York'))


def test_old_slots_retire_and_new_slot_deduplicates_by_eastern_date():
    assert 'transfer' not in SLOT_HOURS and 'transfer' not in SLOT_CRONS.values()
    assert 'four-team-targets' in RETIRED_EDITIONS
    public_slot = upcoming_editorial(SCOUTING, SUNDAY)
    assert public_slot['display_name'] == 'FPL Player Performance Comparisons'
    assert public_slot['post'] == 'scouting-rotation'
    assert SCOUTING not in catchup_slots(SUNDAY - timedelta(seconds=1), {}, 11, limit=None)
    assert SCOUTING in catchup_slots(SUNDAY, {}, 11, limit=None)
    key = publication_key(SCOUTING, SUNDAY, 11)
    assert key == publication_key(SCOUTING, SUNDAY + timedelta(hours=1), 12)
    assert SCOUTING not in catchup_slots(SUNDAY, {key: {'status': 'delivered'}}, 12, limit=None)


@pytest.mark.parametrize('day', range(7))
def test_one_branded_graphic_per_day(day, world, tmp_path, monkeypatch):
    snapshot, _, evidence, _ = world
    monkeypatch.setenv('FPL_TELEGRAM_HANDLE', '@FPLVortexDailyBot')
    monkeypatch.setenv('FPL_DISCORD_HANDLE', '@fplvortex')
    monkeypatch.setattr(scouting_render, '_media', lambda *a: Image.new('RGBA', (80, 90), '#647caa'))

    def stats(snap, through, year, session, fields, **kwargs):
        assert through == 9
        return ([(p, {'minutes': 500, **{field: (p['id'] + i) % 17 for i, field in enumerate(fields)}})
                 for p in snap.players], ['https://example.invalid/fixture-data.csv'])

    monkeypatch.setattr(scouting_rotation, 'player_totals', stats)
    if day == 6:
        now = snapshot.fetched_at
        events = snapshot.events + [
            {'id': n, 'deadline_time': (now + timedelta(days=(n-9)*7)).isoformat()}
            for n in (15, 16)
        ]
        fixtures = snapshot.fixtures + [
            {**f, 'event': n, 'id': n*10 + f['team_h']}
            for f in snapshot.fixtures if f['event'] == 10 for n in (15, 16)
        ]
        # Create one double and a club with a blank in the same gameweek.
        fixtures = [f for f in fixtures if f['id'] != 103]
        sample = next(f for f in fixtures if f['id'] == 101)
        fixtures.append({**sample, 'id': 107, 'team_a': 3})
        keepers = [{**p, 'starts': 10} for p in snapshot.players if p['element_type'] == 1]
        teams = {**snapshot.teams, 2: {**snapshot.teams[2], 'name': "Nott'm Forest"}}
        snapshot = replace(snapshot, teams=teams, events=events, fixtures=fixtures, players=keepers)
    now = SUNDAY + timedelta(days=day)
    plan = scouting_rotation.build_scouting(SCOUTING, snapshot, now, evidence.session)
    assert plan.extra['day'] == day + 1
    assert len([line for line in verified_caption(plan.title, plan.caption).splitlines() if line]) == 5
    assert len(plan.caption.splitlines()[-1].split()) == 4
    if day == 6:
        assert plan.extra['weeks'] == list(range(10, 17))
        assert len(plan.extra['rows']) == 4
        assert all(r['photo'] for r in plan.extra['rows'])
        first_week = [r['cells'][0] for r in plan.extra['rows']]
        assert any(not fixtures for fixtures in first_week)
        assert [('Nottingham Forest', 'H', 2), ('Team 3', 'H', 2)] in first_week
    else:
        assert plan.extra['x_name'] == scouting_rotation.TOPICS[day][1][0]
        assert plan.extra['y_name'] == scouting_rotation.TOPICS[day][2][0]
    image_path = tmp_path / f'day-{day}.png'
    assert render(plan, snapshot, now, image_path, evidence.session) == [image_path]
    with Image.open(image_path) as image:
        assert image.size == (1920, 1080)
        image.verify()



def test_missing_dribbles_replaces_all_four_editions_without_inventing_zeros(world, monkeypatch, tmp_path):
    snapshot, _, evidence, _ = world

    def stats(snap, through, year, session, fields, **kwargs):
        assert kwargs['optional_fields'] == ('successful_dribbles',)
        return ([(p, {'minutes': 500, **{field: (p['id'] + i) % 17 for i, field in enumerate(fields)
                                          if field != 'successful_dribbles'}})
                 for p in snap.players], ['https://example.invalid/fixture-data.csv'])

    monkeypatch.setattr(scouting_rotation, 'player_totals', stats)
    for day, (title, x, y, _) in enumerate(scouting_rotation.DRIBBLE_FALLBACKS):
        plan = scouting_rotation.build_scouting(SCOUTING, snapshot, SUNDAY+timedelta(days=day), evidence.session)
        assert plan.title == title
        assert (plan.extra['x_name'], plan.extra['y_name']) == (x[0], y[0])
        assert len({r['x'] for r in plan.extra['rows']}) > 1
        assert 'Dribble counts unavailable' in plan.extra['metric_note']
    monkeypatch.setenv('FPL_TELEGRAM_HANDLE', '@FPLVortexDailyBot')
    monkeypatch.setenv('FPL_DISCORD_HANDLE', '@fplvortex')
    monkeypatch.setattr(scouting_render, '_media', lambda *a: Image.new('RGBA', (80, 90), '#647caa'))
    sunday = scouting_rotation.build_scouting(SCOUTING, snapshot, SUNDAY, evidence.session)
    image_path = tmp_path / 'sunday-fallback.png'
    assert render(sunday, snapshot, SUNDAY, image_path, evidence.session) == [image_path]
    with Image.open(image_path) as image:
        assert image.size == (1920, 1080)
        image.verify()



def test_flat_metrics_are_ineligible(world):
    snapshot, _, _, _ = world
    players = [(p, {'minutes': 500, 'successful_dribbles': 0, 'touches_opposition_box': p['id']})
               for p in snapshot.players]
    assert scouting_rotation.profile_rows(players, snapshot, scouting_rotation.DRIBBLES,
                                           scouting_rotation.BOX, (), 350, False) == ([], [])


def test_passing_creators_is_a_wednesday_chart_with_per_90_rates(world, monkeypatch):
    from vortex.autonomous_schedule import PASSING_CREATORS, eligible_on

    snapshot, _, evidence, _ = world
    wednesday = SUNDAY + timedelta(days=3, hours=1, minutes=45)
    assert eligible_on(PASSING_CREATORS, wednesday)
    assert not eligible_on(PASSING_CREATORS, wednesday + timedelta(days=1))
    players = [p for p in snapshot.players if p['element_type'] != 1][:3]

    def stats(snap, through, session, year, fields, **kwargs):
        assert fields == ('accurate_passes', 'chances_created')
        return ([(players[0], {'minutes': 450, 'accurate_passes': 200, 'chances_created': 10}),
                 (players[1], {'minutes': 900, 'accurate_passes': 600, 'chances_created': 10}),
                 (players[2], {'minutes': 900, 'accurate_passes': 600})], ['https://example.invalid/stats.csv'])

    monkeypatch.setattr(scouting_rotation, 'player_totals', stats)
    plan = scouting_rotation.build_passing_creators(PASSING_CREATORS, snapshot, wednesday, evidence.session)
    assert [(row['x'], row['y']) for row in plan.extra['rows']] == [(40, 2), (60, 1)]
    assert plan.extra['x_name'] == 'Completed passes'
    assert plan.extra['y_name'] == 'Chances created'
    assert len([line for line in verified_caption(plan.title, plan.caption).splitlines() if line]) == 5
