"""Offline contract for daily major-market changes and safe odds publication."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from vortex.editorial_dedup import check_revision, revision_record
from vortex.extra_posts import ExtraPost
from vortex.projection_trends import compare, coverage, record, require_publishable
from vortex.publication_rules import publication_group, semantic_fingerprint

ET = ZoneInfo("America/New_York")


def board() -> ExtraPost:
    rows = tuple({
        "id": 900 + i, "home": f"H{i}", "away": f"A{i}",
        "home_name": f"Home {i}", "away_name": f"Away {i}",
        "home_code": 100 + i * 2, "away_code": 101 + i * 2,
        "kickoff": f"2026-11-{7+i//5:02d}T15:00:00Z",
        "home_goals": 1.70, "away_goals": 1.40,
        "home_cs": 45, "away_cs": 27,
        "odds_source": "The Odds API · fitted bookmaker markets",
    } for i in range(10))
    caption = ("GW10: 10 verified matchups for the next GW.\n"
               "10/10 have source-verified projected goals and CS odds.\n"
               "Source: verified bookmaker markets; FDR is not a forecast.\n"
               "MONITOR fixtures before changing your FPL squad.\n"
               "#FPL #GW10 #FPLVortex #PremierLeague")
    return ExtraPost("projections", "GW10 · GOALS & CLEAN SHEETS",
                     "ALL CLUBS", caption, "02 Nov 2026", 10,
                     "Official FPL", fixtures=rows)


def date(day: int) -> datetime:
    return datetime(2026, 11, day, 7, 0, tzinfo=ET)


def altered(post, changes: dict[int, dict]) -> ExtraPost:
    from dataclasses import replace
    rows = [deepcopy(row) for row in post.fixtures]
    for idx, diff in changes.items():
        rows[idx].update(diff)
    return replace(post, fixtures=tuple(rows))


def test_only_large_movements_on_both_sides_of_all_twenty_clubs():
    yesterday = board()
    history = record(yesterday, {}, date(2))
    today = altered(board(), {
        0: {"home_goals": 0.70, "home_cs": 25},  # large decline
        1: {"away_goals": 2.05},  # large improvement
        2: {"home_goals": 1.88, "away_cs": 29},  # small changes ignored
    })
    revised, count = compare(today, history, date(3))
    assert count == 2
    assert revised.fixtures[0]["home_major_change"] == {
        "goals": -1.0, "cs_points": -20}
    assert revised.fixtures[1]["away_major_change"]["goals"] == 0.65
    assert "home_major_change" not in revised.fixtures[2]
    assert "MAJOR MOVES" in revised.caption
    assert revised.caption.count("#") == 4
    assert len(revised.caption) <= 280


def test_source_switch_and_opponent_switch_never_look_like_market_swings():
    history = record(board(), {}, date(2))
    switched = altered(board(), {
        0: {"home_goals": 0.70,
            "odds_source": "Solio Analytics · market-informed model"},
        1: {"away_goals": 0.40, "away_code": 999},
    })
    revised, count = compare(switched, history, date(3))
    assert count == 0
    assert all("home_major_change" not in r and
               "away_major_change" not in r for r in revised.fixtures)


def test_no_false_shift_without_past_verified_board_or_different_gameweek():
    current = board()
    empty, count = compare(current, {}, date(3))
    assert count == 0 and empty.fixtures == current.fixtures
    yesterday = record(board(), {}, date(2))
    from dataclasses import replace
    new_gw, count = compare(replace(current, gw=11), yesterday, date(3))
    assert count == 0 and new_gw.gw == 11


def test_unsourced_or_sparse_board_is_held_without_delivery_receipt():
    good = board()
    assert coverage(good) == (10, 10)
    require_publishable(good)
    sparse = altered(good, {
        0: dict(home_goals=None, away_goals=None, home_cs=None, away_cs=None),
        1: dict(home_goals=None, away_goals=None, home_cs=None, away_cs=None),
        2: dict(home_goals=None, away_goals=None, home_cs=None, away_cs=None),
    })
    assert coverage(sparse) == (7, 10)
    with pytest.raises(RuntimeError, match="GOALS/CS HOLD"):
        require_publishable(sparse)
    with pytest.raises(RuntimeError, match="GOALS/CS HOLD"):
        record(sparse, {}, date(3))


def test_successful_snapshot_persists_by_eastern_date_and_gameweek():
    one = record(board(), {}, date(2))
    assert one["gameweeks"]["10"]["2026-11-02"]["fixtures"]["900"]["home"]["goals"] == 1.70
    two = record(board(), one, date(3))
    assert sorted(two["gameweeks"]["10"]) == ["2026-11-02", "2026-11-03"]


def test_same_day_duplicate_stays_suppressed_but_next_day_is_fresh():
    post = board()
    old_key = "2026-11-02:projections:GW10"
    new_key = "2026-11-03:projections:GW10"
    group = publication_group(post)
    version = semantic_fingerprint(post)
    prior_receipt = {"delivered": True, "discord_delivered": True}
    history = {group: revision_record(
        group, old_key, version, {}, prior_receipt, True, date(2).isoformat())}
    deliveries = {old_key: prior_receipt}
    *_, duplicate = check_revision(history, post, deliveries, old_key, True)
    assert duplicate is True
    _, _, result_key, _, _, duplicate = check_revision(
        history, post, deliveries, new_key, True)
    assert duplicate is False
    assert result_key == new_key
