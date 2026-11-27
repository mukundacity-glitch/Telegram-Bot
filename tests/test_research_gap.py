from datetime import datetime, timedelta, timezone
import pytest
from vortex.research_gap import verified_gap

NOW = datetime(2026, 11, 27, 18, tzinfo=timezone.utc)

@pytest.mark.parametrize("elapsed, expected", [(179, False), (180, True), (181, True), (-1, False)])
def test_minimum_elapsed_research_gap(elapsed, expected):
    assert verified_gap((NOW - timedelta(minutes=elapsed)).isoformat(), NOW) is expected

@pytest.mark.parametrize("stamp", [None, "", "invalid", "2026-11-27T14:00:00"])
def test_invalid_research_evidence_fails_closed(stamp):
    assert not verified_gap(stamp, NOW)


def test_radar_gap_requires_same_finalized_gw_and_actual_three_hours():
    from types import SimpleNamespace
    from vortex.autonomous_schedule import ET, Slot, RADAR_RESEARCH_STATE, radar_research_valid, season_id
    now = datetime(2026, 11, 27, 11, 30, tzinfo=ET)
    snapshot = SimpleNamespace(events=[])
    slot = Slot('task1', 'player-radar-comparison', 11, 30, series_gw=11)
    row = {'date': now.date().isoformat(), 'season': season_id(snapshot, now),
           'completed_gw': 11, 'checked_at': (now-timedelta(hours=3)).isoformat()}
    state = {RADAR_RESEARCH_STATE: row}
    assert radar_research_valid(state, slot, snapshot, now)
    row['checked_at'] = (now-timedelta(minutes=179)).isoformat()
    assert not radar_research_valid(state, slot, snapshot, now)
    row['checked_at'] = (now-timedelta(hours=3)).isoformat()
    row['completed_gw'] = 10
    assert not radar_research_valid(state, slot, snapshot, now)
