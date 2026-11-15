from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from vortex.autonomous_schedule import SERIES, catchup_slots, publication_key, weekly_analysis_slot
from vortex.odds_model import predicted_probabilities


def test_series_releases_seven_distinct_topics_and_never_repeats_a_completed_cohort():
    state = {}
    start = datetime(2026, 11, 15, 17, 30, tzinfo=timezone.utc)
    snap = SimpleNamespace(events=[{'id': 10, 'finished': True, 'deadline_time': '2026-11-11T00:00:00Z'}],
                           fixtures=[])
    assert weekly_analysis_slot(snap, start-timedelta(seconds=1), state) is None
    assert SERIES not in catchup_slots(start, {}, 11, limit=None)
    slots = [weekly_analysis_slot(snap, start+timedelta(days=i), state) for i in range(7)]
    assert [slot.series_day for slot in slots] == list(range(1, 8))
    assert len({publication_key(slot, start, 11, '2026-27') for slot in slots}) == 7
    assert weekly_analysis_slot(snap, start+timedelta(days=7), state) is None
    snap.events.append({'id': 11, 'finished': True, 'deadline_time': '2026-11-21T00:00:00Z'})
    next_slot = weekly_analysis_slot(snap, start+timedelta(days=7), state)
    assert (next_slot.series_day, next_slot.series_gw) == (1, 11)


def test_goal_at_final_whistle_turns_a_draw_into_a_win():
    assert predicted_probabilities(0, 0, goal_offset=0)[:3] == (0, 1, 0)
    assert predicted_probabilities(0, 0, goal_offset=1)[:3] == (1, 0, 0)
