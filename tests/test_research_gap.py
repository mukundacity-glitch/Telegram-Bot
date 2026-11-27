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
           'completed_gw': 11, 'checked_at': now.replace(hour=5, minute=58).isoformat()}
    state = {RADAR_RESEARCH_STATE: row}
    assert radar_research_valid(state, slot, snapshot, now)
    row['checked_at'] = now.replace(hour=6, minute=10).isoformat()
    assert not radar_research_valid(state, slot, snapshot, now)
    row['checked_at'] = (now-timedelta(minutes=179)).isoformat()
    assert not radar_research_valid(state, slot, snapshot, now)
    row['checked_at'] = now.replace(hour=5, minute=58).isoformat()
    row['completed_gw'] = 10
    assert not radar_research_valid(state, slot, snapshot, now)


def test_exclusive_publication_preserves_other_due_jobs():
    from vortex.autonomous_schedule import ET, Slot
    from vortex.scheduled_dispatch import exclusive_cutover_jobs
    post = datetime(2026, 11, 27, 11, 30, tzinfo=ET)
    radar = (post, 'editorial', 'radar', Slot('task1', 'player-radar-comparison', 11, 30))
    legacy = (post, 'legacy', 'legacy', ('elite', 'cron'))
    idle_news = (post, 'news', 'news', True)
    assert exclusive_cutover_jobs([radar, idle_news], post) == [radar]
    assert exclusive_cutover_jobs([radar, legacy], post) == [legacy]
    assert exclusive_cutover_jobs([idle_news], post, research_due=True) == []
    from vortex.autonomous_schedule import radar_post_due
    assert radar_post_due(post)
    assert not radar_post_due(post + timedelta(minutes=15))


def test_weekly_rotation_cannot_displace_another_due_job():
    from vortex.autonomous_schedule import ET
    from vortex.scheduled_dispatch import exclusive_cutover_jobs
    post = datetime(2026, 11, 27, 20, 0, tzinfo=ET)
    rotation = (post, 'news', 'rotation', True)
    legacy = (post, 'legacy', 'legacy', ('sell', 'cron'))
    assert exclusive_cutover_jobs([rotation], post) == [rotation]
    assert exclusive_cutover_jobs([rotation, legacy], post) == [legacy]


@pytest.mark.parametrize("month", [7, 11])
@pytest.mark.parametrize("minutes,expected", [(-1,False),(0,True),(11,True),(12,False)])
def test_reserved_research_proof_boundaries_in_both_eastern_offsets(month, minutes, expected):
    from vortex.autonomous_schedule import ET
    from vortex.research_gap import reserved_research_valid
    target = datetime(2026, month, 21, 20, tzinfo=ET)
    start = target.replace(hour=15, minute=28)
    stamp = (start + timedelta(minutes=minutes)).astimezone(timezone.utc).isoformat()
    assert reserved_research_valid(stamp, target, 15, 28, 12) is expected


def test_outbox_rejects_radar_proof_outside_reserved_window():
    from vortex.autonomous_schedule import ET
    from vortex.research_gap import verify_settled_or_weekly_record
    post = datetime(2026, 11, 27, 11, 30, tzinfo=ET)
    record = {"edition": "player-radar-comparison", "season": "2026-27", "gameweek": 12,
              "facts": {"extra": {"completed_gw": 11}, "research": {
                  "date": post.date().isoformat(), "season": "2026-27", "completed_gw": 11,
                  "checked_at": post.replace(hour=5, minute=58).isoformat()}}}
    assert verify_settled_or_weekly_record(record, post, post).endswith("GW11:task1:player-radar-comparison")
    record["facts"]["research"]["checked_at"] = post.replace(hour=6, minute=10).isoformat()
    with pytest.raises(ValueError, match="research"):
        verify_settled_or_weekly_record(record, post, post)


@pytest.mark.parametrize("age,expected", [(-1,False),(0,True),(30,True),(31,False)])
def test_fdr_research_requires_fresh_source_before_completion(age, expected):
    from vortex.research_gap import fresh_research_source
    checked = NOW
    fetched = checked - timedelta(minutes=age)
    assert fresh_research_source(fetched.isoformat(), checked.isoformat()) is expected


def test_fdr_research_rejects_missing_or_naive_source():
    from vortex.research_gap import fresh_research_source
    assert not fresh_research_source(None, NOW.isoformat())
    assert not fresh_research_source("2026-11-27T17:50:00", NOW.isoformat())
