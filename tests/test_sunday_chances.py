from datetime import datetime, timedelta
from types import SimpleNamespace

from vortex import sunday_chances
from vortex.autonomous_schedule import ET, SLOTS, MONDAY_DEFENCE, SUNDAY_CHANCES, catchup_slots, publication_key


def test_evening_boards_are_day_specific_and_retry_only_same_day():
    sunday = datetime(2026, 11, 22, 20, tzinfo=ET)
    assert [slot for slot in SLOTS if (slot.hour, slot.minute) == (20, 0)] [:2] == [SUNDAY_CHANCES, MONDAY_DEFENCE]
    assert SUNDAY_CHANCES not in catchup_slots(sunday - timedelta(minutes=1), {}, 11, limit=None)
    assert SUNDAY_CHANCES in catchup_slots(sunday, {}, 11, limit=None)
    key = publication_key(SUNDAY_CHANCES, sunday, 11)
    assert SUNDAY_CHANCES in catchup_slots(sunday, {key: {'status': 'held', 'attempts': 1}}, 11, limit=None)
    assert SUNDAY_CHANCES not in catchup_slots(sunday, {key: {'status': 'delivered'}}, 11, limit=None)
    assert MONDAY_DEFENCE not in catchup_slots(sunday, {}, 11, limit=None)
    monday = sunday + timedelta(days=1)
    assert MONDAY_DEFENCE not in catchup_slots(monday - timedelta(minutes=1), {}, 11, limit=None)
    due = catchup_slots(monday, {}, 11, limit=None)
    assert MONDAY_DEFENCE in due and SUNDAY_CHANCES not in due
    key = publication_key(MONDAY_DEFENCE, monday, 11)
    assert MONDAY_DEFENCE not in catchup_slots(monday, {key: {'status': 'delivered'}}, 11, limit=None)
    for offset in range(2, 7):
        due = catchup_slots(sunday + timedelta(days=offset), {}, 11, limit=None)
        assert MONDAY_DEFENCE not in due and SUNDAY_CHANCES not in due


def test_sunday_plot_uses_exact_position_minutes_and_thresholds(monkeypatch):
    now = datetime(2026, 11, 22, 20, tzinfo=ET)
    snapshot = SimpleNamespace(
        gameweek=lambda: 11, events=[], fetched_at=now, name=lambda p: p['name'],
        photo_code=lambda p: p['id'], team_code=lambda p: 100,
    )
    players = [
        ({'id': 1, 'name': 'All Three', 'element_type': 3},
         {'minutes': 450, 'xg': 2, 'total_shots': 15, 'touches_opposition_box': 25}),
        ({'id': 2, 'name': 'Box Only', 'element_type': 4},
         {'minutes': 900, 'xg': 3.99, 'total_shots': 29, 'touches_opposition_box': 50}),
        ({'id': 3, 'name': 'Below Minutes', 'element_type': 3}, {'minutes': 449}),
        ({'id': 4, 'name': 'Missing Metrics', 'element_type': 4},
         {'minutes': 450, 'incomplete_metrics': True}),
    ]
    monkeypatch.setattr(sunday_chances, 'latest_completed_gw', lambda snapshot: 10)
    monkeypatch.setattr(sunday_chances, 'player_totals', lambda *a, **k: (players, ['archive']))
    board = sunday_chances.build_sunday_chances(SUNDAY_CHANCES, snapshot, now, None)
    assert board.extra['rows']['MIDFIELDERS'][0]['mask'] == 7
    assert board.extra['rows']['FORWARDS'][0]['mask'] == 4
    assert board.extra['eligible'] == {'MIDFIELDERS': 1, 'FORWARDS': 2}
    assert board.extra['incomplete'] == {'MIDFIELDERS': 0, 'FORWARDS': 1}
    assert board.caption.splitlines()[-1].split() == ['#FPL', '#GW11', '#FPLVORTEX', '#PremierLeague']

def test_monday_uses_position_specific_rates_and_excludes_missing_metrics(monkeypatch):
    now = datetime(2026, 11, 23, 20, tzinfo=ET)
    snapshot = SimpleNamespace(
        gameweek=lambda: 12, events=[], fetched_at=now, name=lambda p: p['name'],
        photo_code=lambda p: p['id'], team_code=lambda p: 100,
    )
    players = [
        ({'id': 1, 'name': 'Keeper', 'element_type': 1},
         {'minutes': 450, 'saves': 15, 'saves_inside_box': 10, 'sweeper_actions': 2}),
        ({'id': 2, 'name': 'Defender', 'element_type': 2},
         {'minutes': 900, 'clearances': 40, 'interceptions': 10, 'tackles_won': 15}),
        ({'id': 3, 'name': 'Incomplete', 'element_type': 1},
         {'minutes': 450, 'incomplete_metrics': True}),
    ]
    monkeypatch.setattr(sunday_chances, 'latest_completed_gw', lambda snapshot: 11)
    monkeypatch.setattr(sunday_chances, 'player_totals', lambda *a, **k: (players, ['archive']))
    board = sunday_chances.build_monday_defence(MONDAY_DEFENCE, snapshot, now, None)
    assert tuple(board.extra['rows']) == ('GOALKEEPERS', 'DEFENDERS')
    assert board.extra['rows']['GOALKEEPERS'][0]['mask'] == 3
    assert board.extra['rows']['DEFENDERS'][0]['mask'] == 7
    assert board.extra['incomplete']['GOALKEEPERS'] == 1
    assert board.caption.splitlines()[-1].split() == ['#FPL', '#GW12', '#FPLVORTEX', '#PremierLeague']
