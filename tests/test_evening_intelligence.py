"""No-delivery tests: live-data contracts, weekday-only slots and graphics."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from vortex.autonomous_schedule import (
    ET, SLOTS, SUNDAY_CHANCES, MONDAY_DEFENCE, EVENING_WATCH_SLOTS,
    TUESDAY_SET_PIECES, WEDNESDAY_PREDICTED_XG, THURSDAY_ATTACKING_ZONES,
    FRIDAY_ROTATION_PLANNER, SATURDAY_FDR_GRID,
    catchup_slots, publication_key,
)
from vortex import evening_intelligence as e
from vortex import evening_intelligence_render as graphic
from vortex.editorial_inputs import RequiredInput
from vortex.fpl import FplSnapshot


def snapshot(*, length=11, players=True):
    at = datetime(2026, 11, 18, tzinfo=timezone.utc)
    clubs = {}
    for number in range(1, 21):
        name = ("Leeds United" if number == 1 else
                "Tottenham Hotspur" if number == 2 else f"Club {number}")
        clubs[number] = {
            "id": number, "name": name, "short_name": f"C{number}",
            "code": 1000 + number,
        }
    events = [{"id": i + 11, "finished": False,
               "deadline_time": (at + timedelta(days=3 + i*7)).isoformat()}
              for i in range(length)]
    fixtures = [
        {"id": gw*100+pair, "event": gw, "team_h": pair, "team_a": pair+1,
         "team_h_difficulty": 2, "team_a_difficulty": 4,
         "kickoff_time": (at + timedelta(days=4 + (gw-11)*7)).isoformat(),
         "finished": False}
        for gw in range(11, 11 + length) for pair in range(1, 21, 2)
    ]
    people = [
        {"id": i, "team": i, "code": 5000+i, "web_name": f"Player {i}",
         "minutes": 550, "corners_and_indirect_freekicks_order": 1,
         "direct_freekicks_order": 2, "penalties_order": 3,
         "set_piece_threat": "1.0"}
        for i in range(1, 21)
    ] if players else []
    return FplSnapshot(people, clubs, events, fixtures, at)


def test_all_seven_evening_slots_are_20_et_and_exactly_once_per_weekday():
    expected = (MONDAY_DEFENCE, TUESDAY_SET_PIECES, WEDNESDAY_PREDICTED_XG,
                THURSDAY_ATTACKING_ZONES, FRIDAY_ROTATION_PLANNER,
                SATURDAY_FDR_GRID, SUNDAY_CHANCES)
    assert len(EVENING_WATCH_SLOTS) == len(expected) == 7
    assert len({slot.edition for slot in EVENING_WATCH_SLOTS}) == 7
    assert all((slot.hour, slot.minute) == (20, 0) for slot in expected)
    for offset in range(7):
        date = datetime(2026, 11, 16 + offset, 20, 0, tzinfo=ET)
        due = [slot for slot in catchup_slots(date, {}, 11, limit=None)
               if slot in EVENING_WATCH_SLOTS]
        assert due == [expected[offset]]
        assert not [slot for slot in catchup_slots(date-timedelta(minutes=1), {}, 11,
                                                  limit=None) if slot in EVENING_WATCH_SLOTS]
        key = publication_key(expected[offset], date, 11)
        assert not [slot for slot in catchup_slots(date, {
            key: {"status": "delivered", "attempts": 1}}, 11, limit=None)
                    if slot in EVENING_WATCH_SLOTS]
    assert all(slot in SLOTS for slot in expected)


def test_tuesday_uses_actual_official_orders_and_never_renders_fake_per90():
    snap = snapshot()
    plan = e.build_evening(TUESDAY_SET_PIECES, snap, snap.fetched_at,
                           SimpleNamespace(session=None))
    assert plan.kind == "set_pieces"
    assert len(plan.extra["rows"]) == 12
    assert plan.extra["rows"][0]["orders"] == (1, 2, 3)
    assert "not" in plan.extra["method"]
    assert "not set pieces per 90" in plan.caption


def test_saturday_contains_six_real_weeks_and_20_club_cells():
    snap = snapshot()
    plan = e.build_evening(SATURDAY_FDR_GRID, snap, snap.fetched_at,
                           SimpleNamespace(session=None))
    assert plan.kind == "fdr_grid"
    assert plan.extra["weeks"] == [11, 12, 13, 14, 15, 16]
    assert len(plan.extra["rows"]) == 20
    assert all(len(r["cells"]) == 6 for r in plan.extra["rows"])
    assert all(r["average"] in (2, 4) for r in plan.extra["rows"])
    assert plan.extra["rows"][0]["average"] == 2


def test_wednesday_rejects_unverified_xg_and_accepts_matching_five_gw(monkeypatch):
    snap = snapshot()
    now = snap.fetched_at
    feed = {"model_version": "validated-model", "methodology_url": "https://source.test/method"}
    monkeypatch.setattr(e, "verified_feed", lambda *args, **kw: feed)
    model_rows = {}
    for team in snap.teams:
        model_rows[team] = defaultdict(list)
        for gw in range(11, 16):
            model_rows[team][gw] = [{"projected_goals": 1.5}]
    monkeypatch.setattr(e, "_team_fixture_rows", lambda *a: model_rows)
    plan = e.build_evening(WEDNESDAY_PREDICTED_XG, snap, now,
                           SimpleNamespace(session=None))
    assert len(plan.extra["rows"]) == 20
    assert plan.extra["rows"][0]["total"] == 7.5
    assert "model version validated-model" in plan.caption
    model_rows[3][13][0]["projected_goals"] = None
    import pytest
    with pytest.raises(RequiredInput):
        e.build_evening(WEDNESDAY_PREDICTED_XG, snap, now,
                        SimpleNamespace(session=None))


def test_friday_is_real_fdr_backed_when_model_missing(monkeypatch):
    snap = snapshot()
    now = snap.fetched_at
    monkeypatch.setattr(e, "verified_feed",
                        lambda *a, **k: (_ for _ in ()).throw(RequiredInput("down")))
    plan = e.build_evening(FRIDAY_ROTATION_PLANNER, snap, now,
                           SimpleNamespace(session=None))
    assert len(plan.extra["rows"]) == 11
    assert plan.extra["model"] is None
    assert all(row["decision_basis"] == "OFFICIAL FDR"
               for row in plan.extra["rows"])
    assert plan.extra["rows"][0]["chosen"] == 1
    assert plan.extra["rows"][0]["choices"][0]["cs"] is None
    assert "guaranteed" in plan.caption


def test_friday_does_not_compare_cs_from_only_one_team(monkeypatch):
    snap = snapshot()
    feed = {"model_version": "test", "methodology_url": "https://source.test"}
    monkeypatch.setattr(e, "verified_feed", lambda *a, **k: feed)
    modeled = {}
    for team in snap.teams:
        modeled[team] = defaultdict(list)
        for week in range(11, 16):
            modeled[team][week] = [{"clean_sheet_pct": 55 if team == 2 else 20}]
    monkeypatch.setattr(e, "_team_fixture_rows", lambda *args: modeled)
    plan = e.build_evening(FRIDAY_ROTATION_PLANNER, snap, snap.fetched_at,
                           SimpleNamespace(session=None))
    assert plan.extra["rows"][0]["chosen"] == 2
    assert plan.extra["rows"][0]["decision_basis"] == "MODEL CS%"
    assert plan.extra["rows"][-1]["decision_basis"] == "OFFICIAL FDR"


def test_no_blank_colourless_graphic_and_png_dimensions(tmp_path, monkeypatch):
    snap = snapshot()
    plan = e.build_evening(SATURDAY_FDR_GRID, snap, snap.fetched_at,
                           SimpleNamespace(session=None))
    monkeypatch.setattr(graphic, "_base",
                        lambda *args: Image.new("RGB", (1536, 864), "#0b1433"))
    monkeypatch.setattr(graphic, "_crest", lambda *args: None)
    monkeypatch.setattr(graphic, "_save",
                        lambda image, output: (image.resize((1920, 1080)).save(output), output)[1])
    target = tmp_path / "fdr.png"
    assert graphic.render_evening(plan, target, None) == target
    with Image.open(target) as image:
        assert image.size == (1920, 1080)
        assert len(image.getcolors(1920*1080) or []) > 7
