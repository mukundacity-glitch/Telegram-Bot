"""Offline, no-publish regression contract for the dynamic 05:30 edition."""
from datetime import datetime, timedelta, timezone

from vortex.availability_board import (
    TIERS, _fixture_forecast, select,
)
from vortex.fpl import FplSnapshot


def _world():
    now = datetime(2026, 11, 12, 10, 30, tzinfo=timezone.utc)
    clubs = {n: {"id": n, "code": 100+n, "name": f"Club {n}",
                 "short_name": f"C{n}"} for n in range(1, 5)}
    events = [{"id": n, "is_next": n == 11, "finished": False,
               "deadline_time": (now+timedelta(days=7*(n-10))).isoformat()}
              for n in range(11, 16)]
    fixtures = []
    for gw in range(11, 16):
        for home, away in ((1, 2), (3, 4)):
            fixtures.append({"id": gw*10+home, "event": gw, "team_h": home,
                             "team_a": away, "finished": False,
                             "kickoff_time": (now+timedelta(days=gw-10)).isoformat(),
                             "team_h_difficulty": 2, "team_a_difficulty": 3})
    players = []
    for pid in range(1, 61):
        players.append({
            "id": pid, "code": 1000+pid, "web_name": f"EXAMPLE-{pid}",
            "team": 1+(pid % 4), "element_type": 1+(pid % 4),
            "status": "a", "now_cost": 40+pid, "minutes": 810+pid,
            "starts": 9, "form": str(1+(pid%9)*.6),
            "points_per_game": str(2+(pid%7)*.7),
            "ep_next": str(1+(pid%13)*.35),
            "expected_goal_involvements": "2.6",
            "selected_by_percent": str(pid%22),
            "clean_sheets": 3, "saves": 26,
        })
    snap = FplSnapshot(players, clubs, events, fixtures, now)

    class Evidence:
        session = None
        def recent(self, player):
            return [{"round": gw, "minutes": 90, "total_points": 4}
                    for gw in (8, 9, 10)]
    return snap, now, Evidence()


def test_shortlist_is_dynamic_unique_and_never_manufactures_xpts(monkeypatch):
    from vortex import availability_board as a
    monkeypatch.setattr(a, "fetch_verified_xpts", lambda *args, **kwargs: {})
    snap, now, evidence = _world()
    selected, groups, meta = select(snap, now, evidence)
    chosen = [p["player"]["id"] for p in selected]
    assert 1 <= len(chosen) <= 25
    assert len(chosen) == len(set(chosen))
    assert list(groups) == list(TIERS)
    assert all(len(ids) <= 5 for ids in groups.values())
    assert all(r["xpts1"] is None and r["xpts5"] is None for r in selected)
    assert all(r["player"]["web_name"].startswith("EXAMPLE-") for r in selected)
    assert meta["screened_players"] == 60


def test_injured_and_unreliable_players_never_qualify(monkeypatch):
    from vortex import availability_board as a
    monkeypatch.setattr(a, "fetch_verified_xpts", lambda *args, **kwargs: {})
    snap, now, evidence = _world()
    snap.players[0]["status"] = "d"
    snap.players[1]["chance_of_playing_next_round"] = 75
    original_recent = evidence.recent
    evidence.recent = lambda p: ([{"round": 8, "minutes": 20},
                                  {"round": 9, "minutes": 90},
                                  {"round": 10, "minutes": 90}]
                                 if p["id"] == 3 else original_recent(p))
    selected, _, _ = select(snap, now, evidence)
    assert not {1, 2, 3} & {r["player"]["id"] for r in selected}


def test_double_gw_requires_both_verified_fixtures_and_blank_is_not_zero():
    rows = [
        {"gw": 11, "blank": False, "xpts": 5.1},
        {"gw": 11, "blank": False, "xpts": None},
        {"gw": 12, "blank": True, "xpts": None},
        {"gw": 13, "blank": False, "xpts": 4.0},
        {"gw": 14, "blank": False, "xpts": 3.0},
        {"gw": 15, "blank": False, "xpts": 2.0},
    ]
    assert _fixture_forecast(rows, 11) == (None, None)
    rows[1]["xpts"] = 6.2
    assert _fixture_forecast(rows, 11) == (11.3, 20.3)
    rows[0]["xpts"] = None
    assert _fixture_forecast(rows, 11) == (None, None)


def test_05_30_schedule_is_identical():
    from vortex.autonomous_schedule import SLOTS
    slot = next(s for s in SLOTS if s.edition == "availability-transfer-decisions")
    assert (slot.task, slot.hour, slot.minute) == ("task1", 5, 30)


def test_branded_single_page_renders_offline_without_posts(tmp_path, monkeypatch):
    """Real approved master and actual 16:9 renderer, no external requests."""
    from types import SimpleNamespace
    from PIL import Image
    from vortex import availability_board as a
    from vortex import availability_render as visual

    monkeypatch.setattr(a, "fetch_verified_xpts", lambda *args, **kwargs: {})
    monkeypatch.setenv("FPL_TELEGRAM_HANDLE", "@FPLVortexDailyBot")
    monkeypatch.setenv("FPL_DISCORD_HANDLE", "@fplvortex")
    monkeypatch.setattr(visual, "_assets", lambda *args, **kwargs: (
        Image.new("RGBA", (80, 90), "#627FC0"),
        Image.new("RGBA", (40, 40), "#40DCD8")))
    snap, now, evidence = _world()
    rows, tiers, meta = select(snap, now, evidence)
    plan = SimpleNamespace(
        title="AVAILABILITY & TRANSFER DECISIONS", gw=11,
        extra={"tiers": tiers, "rows": {str(r["player"]["id"]): r for r in rows},
               "method": meta})
    path = tmp_path / "0530-preview-not-for-publishing.png"
    result = visual.render_availability(plan, snap, now, path, None)
    assert result == path
    with Image.open(result) as picture:
        picture.verify()
    with Image.open(result) as picture:
        assert picture.size == (1920, 1080)
        assert picture.getpixel((800, 550)) != (255, 255, 255)
