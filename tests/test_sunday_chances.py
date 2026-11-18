from datetime import datetime, timedelta
from types import SimpleNamespace

from vortex import sunday_chances
from vortex.autonomous_schedule import ET, SLOTS, SUNDAY_CHANCES, catchup_slots, publication_key


def test_sunday_board_is_the_only_eight_pm_edition_and_retries_only_same_day():
    sunday = datetime(2026, 11, 22, 20, tzinfo=ET)
    assert [slot for slot in SLOTS if (slot.hour, slot.minute) == (20, 0)] == [SUNDAY_CHANCES]
    assert SUNDAY_CHANCES not in catchup_slots(sunday - timedelta(minutes=1), {}, 11, limit=None)
    assert SUNDAY_CHANCES in catchup_slots(sunday, {}, 11, limit=None)
    key = publication_key(SUNDAY_CHANCES, sunday, 11)
    assert SUNDAY_CHANCES in catchup_slots(sunday, {key: {'status': 'held', 'attempts': 1}}, 11, limit=None)
    assert SUNDAY_CHANCES not in catchup_slots(sunday, {key: {'status': 'delivered'}}, 11, limit=None)
    for offset in range(1, 7):
        assert SUNDAY_CHANCES not in catchup_slots(sunday + timedelta(days=offset), {}, 11, limit=None)


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
