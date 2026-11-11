"""Rotation Planner regression: factual FDR, preserved cron, no STATUS CHANGE replay."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from vortex.fpl import FplSnapshot
from vortex.rotation_planner import build_rotation_plan, render_rotation_plan
from vortex.syndication import NewsPost
from vortex import rotation_planner, unified_runner


def sample():
    now = datetime(2026, 11, 11, 14, 0, tzinfo=timezone.utc)
    names = ("ALB", "BRK", "CST", "DUN", "EVE", "FEX")
    teams = {i: {"id": i, "short_name": name, "name": f"Test Team {name}",
                 "code": 100 + i} for i, name in enumerate(names, 1)}
    players = []
    for team in teams:
        for n in range(2):
            players.append({
                "id": 100 * team + n, "web_name": f"Player {team}-{n}",
                "team": team, "status": "a", "minutes": 540 + n * 90,
                "now_cost": 44 + team + n, "code": 1100 + team * 10 + n,
                "chance_of_playing_next_round": None,
                "chance_of_playing_this_round": None, "news": ""
            })
    events = [
        {"id": gw, "deadline_time": (now + timedelta(days=(gw - 10) * 7)).isoformat(),
         "finished": False}
        for gw in range(11, 20)
    ]
    fixtures = []
    for gw in range(11, 20):
        pairs = [(1, 2), (3, 4), (5, 6)] if gw % 2 else [(1, 4), (2, 5), (3, 6)]
        for index, (home, away) in enumerate(pairs):
            fixtures.append({
                "id": (gw * 10 + index), "event": gw,
                "team_h": home, "team_a": away,
                "team_h_difficulty": 1 + (gw + index) % 5,
                "team_a_difficulty": 1 + (gw + index + 2) % 5,
                "kickoff_time": (now + timedelta(days=(gw - 10) * 7, hours=1)).isoformat(),
                "finished": False
            })
    return FplSnapshot(players, teams, events, fixtures, now), now


def test_rotation_matrix_uses_only_real_current_fpl_fixtures_and_clubs():
    snapshot, now = sample()
    plan = build_rotation_plan(snapshot, now)
    assert plan.identity == "rotation:2026-11-11:GW11"
    assert plan.weeks == tuple(range(11, 20))
    assert len(plan.clubs) == 4
    assert len({club["id"] for club in plan.clubs}) == 4
    assert "#RotationPlanner" in plan.caption
    for club in plan.clubs:
        assert club["code"] == snapshot.teams[club["id"]]["code"]
        assert club["options"] == 2
        assert club["min_price"] == (44 + club["id"]) / 10
        for gw, fixtures in zip(plan.weeks, club["fixtures"]):
            for fixture in fixtures:
                assert any(row["id"] == fixture["fixture_id"] and
                           row["event"] == gw and
                           club["id"] in (row["team_h"], row["team_a"])
                           for row in snapshot.fixtures)
                assert fixture["venue"] in ("H", "A")
                assert fixture["fdr"] in (1, 2, 3, 4, 5)


def test_doubles_and_blanks_are_not_invented():
    snapshot, now = sample()
    # GW15 unassigned to club 6, no fictional fixture is displayed.
    snapshot.fixtures[:] = [f for f in snapshot.fixtures
                            if f["event"] != 15 or f["team_a"] != 6]
    # A verified extra GW12 match for club 1 is a double, not silently collapsed.
    snapshot.fixtures.append({
        "id": 9999, "event": 12, "team_h": 1, "team_a": 6,
        "team_h_difficulty": 4, "team_a_difficulty": 2, "finished": False
    })
    plan = build_rotation_plan(snapshot, now)
    selected = {club["id"]: club for club in plan.clubs}
    if 1 in selected:
        assert len(selected[1]["fixtures"][1]) == 2
    if 6 in selected:
        assert selected[6]["fixtures"][4] == ()


def test_rotation_renderer_uses_four_real_crests_and_exports_png(tmp_path, monkeypatch):
    snapshot, now = sample()
    plan = build_rotation_plan(snapshot, now)
    master = tmp_path / "original.png"
    Image.new("RGB", (1536, 864), "#111133").save(master)
    monkeypatch.setattr(rotation_planner, "MASTER", master)
    used = []
    def crest(session, code, kind, cache):
        used.append((code, kind))
        return Image.new("RGBA", (100, 100), (90, 20, 160, 255))
    monkeypatch.setattr(rotation_planner, "_media", crest)
    output = tmp_path / "rotation.png"
    assert render_rotation_plan(plan, output) == output
    with Image.open(output) as image:
        assert image.size == (1920, 1080)
        image.verify()
    assert len(used) == 4
    assert set(code for code, kind in used) == {club["code"] for club in plan.clubs}
    assert all(kind == "crest" for _, kind in used)


class Telegram:
    def __init__(self):
        self.images = []
    def send_png(self, path, caption, title, gw):
        assert path.is_file() and path.stat().st_size > 500
        self.images.append((path.name, caption, title, gw))
        return 12345
    send_shared_png = send_png


class Discord:
    def __init__(self):
        self.images = []
    def send(self, post):
        self.images.append(post)
        return "54321"


def test_status_cards_retired_then_daily_rotation_posted_once(monkeypatch, tmp_path):
    snapshot, now = sample()
    for name in ("BASELINE", "SEEN", "PENDING", "RECEIPTS"):
        monkeypatch.setattr(unified_runner, name, tmp_path / (name.lower() + ".json"))
    monkeypatch.setattr(unified_runner, "NEWS_OUTPUT", tmp_path / "art")
    def fake_render(plan, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1920, 1080), "white").save(path)
    monkeypatch.setattr(rotation_planner, "render_rotation_plan", fake_render)
    t, d = Telegram(), Discord()
    # Pre-existing status queue is retired without deleting historical receipts.
    old = NewsPost("availability:old", "STATUS CHANGE", "Old injury card", 11)
    unified_runner.PENDING.write_text(json.dumps({old.identity: asdict(old)}))
    unified_runner.RECEIPTS.write_text(json.dumps({
        old.identity: {"delivered": True, "telegram_message_id": 55}
    }))
    warmup = unified_runner.run(snapshot=snapshot, now=now, rss=[], telegram=t, discord=d)
    assert warmup["warmup"] == 1 and warmup["sent"] == 0
    # Change official injury status: no STATUS CHANGE card should be sent.
    snapshot.players[0]["status"] = "d"
    posted = unified_runner.run(snapshot=snapshot, now=now + timedelta(hours=1),
                                rss=[], telegram=t, discord=d)
    assert posted["retired_status_cards"] == 1
    assert posted["sent"] == 1 and posted["rotation_due"]
    assert len(t.images) == len(d.images) == 1
    assert "ROTATION PLANNER" in t.images[0][2]
    assert not any(key.startswith("availability:") for key in
                   json.loads(unified_runner.PENDING.read_text()))
    journal = json.loads(unified_runner.RECEIPTS.read_text())
    assert journal["availability:old"]["telegram_message_id"] == 55
    assert len([key for key in journal if key.startswith("rotation:")]) == 1
    repeat = unified_runner.run(snapshot=snapshot, now=now + timedelta(hours=2),
                                rss=[], telegram=t, discord=d)
    assert repeat["sent"] == 0
    assert len(t.images) == 1


def test_existing_github_schedule_not_edited():
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/telegram-daily.yml").read_text()
    assert "cron: '43 9-23,0-2 * * *'" in workflow
    assert "cron: '13 10-23,0-2 * * *'" in workflow
    assert "python -m vortex.scheduled_dispatch" in workflow
