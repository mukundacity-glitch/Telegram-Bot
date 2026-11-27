from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from vortex.autonomous_schedule import SERIES, catchup_slots, publication_key, weekly_analysis_slot
from vortex.odds_model import predicted_probabilities


def test_weekday_series_uses_latest_completed_gw_without_changing_receipt_keys():
    from vortex.autonomous_schedule import ET, retryable
    state = {}
    start = datetime(2026, 11, 16, 12, 30, tzinfo=ET)  # Monday
    snap = SimpleNamespace(events=[{'id': 10, 'finished': True, 'deadline_time': '2026-11-11T00:00:00Z'}],
                           fixtures=[])
    assert weekly_analysis_slot(snap, start-timedelta(seconds=1), state) is None
    assert SERIES not in catchup_slots(start, {}, 11, limit=None)
    slots = [weekly_analysis_slot(snap, start+timedelta(days=i), state) for i in range(7)]
    assert [slot.series_day for slot in slots] == list(range(1, 8))
    keys = [publication_key(slot, start, 11, '2026-27') for slot in slots]
    assert len(set(keys)) == 7
    state[keys[0]] = {'status': 'delivered'}
    next_week = start+timedelta(days=7)
    repeat = weekly_analysis_slot(snap, next_week, state)
    assert not retryable(state[publication_key(repeat, next_week, 11, '2026-27')])
    snap.events.append({'id': 11, 'finished': True, 'deadline_time': '2026-11-21T00:00:00Z'})
    next_slot = weekly_analysis_slot(snap, next_week, state)
    assert (next_slot.series_day, next_slot.series_gw) == (1, 11)
    assert publication_key(next_slot, next_week, 12, '2026-27') not in state


def test_migration_finishes_existing_series_before_using_weekdays():
    from vortex.autonomous_schedule import ET, SERIES_STATE
    start = datetime(2026, 11, 24, 12, 30, tzinfo=ET)  # Tuesday
    state = {SERIES_STATE: {'season': '2026-27', 'gw': 10, 'start': start.date().isoformat()}}
    snap = SimpleNamespace(events=[
        {'id': 10, 'finished': True, 'deadline_time': '2026-11-11T00:00:00Z'},
        {'id': 11, 'finished': True, 'deadline_time': '2026-11-21T00:00:00Z'}], fixtures=[])
    for i in range(7):
        now = start + timedelta(days=i)
        slot = weekly_analysis_slot(snap, now, state)
        assert (slot.series_day, slot.series_gw) == (i+1, 10)
        assert publication_key(slot, now, 12, '2026-27') == f'2026-27:GW10:task2:weekly-analysis:day{i+1}'
    slot = weekly_analysis_slot(snap, start+timedelta(days=7), state)
    assert (slot.series_day, slot.series_gw) == (2, 11)


def test_regular_and_dynamic_catalogue_are_disjoint_and_complete():
    from vortex.autonomous_schedule import schedule_catalogue, SPECIAL_EDITIONS
    from vortex.graphic_numbers import CATALOG, PRESS_REPORT_KEY
    regular, dynamic = schedule_catalogue()
    assert len(regular) == 43 and len(dynamic) == 8
    assert set(dynamic) == set(SPECIAL_EDITIONS) | {PRESS_REPORT_KEY, 'price-prediction'}
    assert not set(regular) & set(dynamic)
    assert set(regular) | set(dynamic) == set(CATALOG)
    assert all(('weekly-analysis' if day == 1 else f'weekly-analysis-{day}') in regular for day in range(1, 8))


def test_goal_at_final_whistle_turns_a_draw_into_a_win():
    assert predicted_probabilities(0, 0, goal_offset=0)[:3] == (0, 1, 0)
    assert predicted_probabilities(0, 0, goal_offset=1)[:3] == (1, 0, 0)
