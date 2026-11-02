"""Offline integrity checks for every scheduled dual-platform production post."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from PIL import Image

from vortex.content import Card, Content
from vortex.editorial_dedup import check_revision, revision_record
from vortex.fpl import FplSnapshot
from vortex.publication_rules import (
    five_gw_fixtures, player_metrics, required_footer_handles,
    verified_xpts_snapshot, semantic_fingerprint, publication_group,
)
import vortex.brand_footer as footer
from vortex.fplcore import completed_gw_enrichment, latest_completed_event
from vortex.publish_checks import validate_article


def snap():
    now = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
    player = dict(id=99, code=123, web_name="Example", team=1, element_type=2,
                  now_cost=71, selected_by_percent="25.0", minutes=840,
                  total_points=53, form="5.4", points_per_game="6.2",
                  status="a", clean_sheets=4, goals_conceded=5,
                  defensive_contribution=57, goals_scored=2,
                  expected_goals="1.24", expected_assists="1.01")
    teams = {1: {"id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS"},
             2: {"id": 2, "code": 8, "name": "Chelsea", "short_name": "CHE"}}
    events = [{"id": n, "deadline_time": (now+timedelta(days=n-9)).isoformat(),
               "finished": False} for n in range(10, 15)]
    events += [{"id": 9, "deadline_time": (now-timedelta(days=3)).isoformat(),
                "finished": True}]
    fixtures = [
        {"id": 90, "event": 9, "team_h": 1, "team_a": 2,
         "finished": True, "kickoff_time": (now-timedelta(days=2)).isoformat()},
        {"id": 100, "event": 10, "team_h": 1, "team_a": 2,
         "finished": False, "kickoff_time": (now+timedelta(days=2)).isoformat(),
         "team_h_difficulty": 2, "team_a_difficulty": 4},
        {"id": 101, "event": 10, "team_h": 2, "team_a": 1,
         "finished": False, "kickoff_time": (now+timedelta(days=3)).isoformat(),
         "team_h_difficulty": 4, "team_a_difficulty": 3},
        {"id": 103, "event": 12, "team_h": 1, "team_a": 2,
         "finished": False, "kickoff_time": (now+timedelta(days=8)).isoformat(),
         "team_h_difficulty": 1, "team_a_difficulty": 5},
        {"id": 104, "event": 13, "team_h": 2, "team_a": 1,
         "finished": False, "kickoff_time": (now+timedelta(days=15)).isoformat(),
         "team_h_difficulty": 2, "team_a_difficulty": 4},
        {"id": 105, "event": 14, "team_h": 1, "team_a": 2,
         "finished": False, "kickoff_time": (now+timedelta(days=22)).isoformat(),
         "team_h_difficulty": 3, "team_a_difficulty": 3},
    ]
    return FplSnapshot([player], teams, events, fixtures, now)


def test_five_gameweek_slots_blank_and_double_without_fake_zeroes():
    s = snap()
    fixtures = five_gw_fixtures(s, s.players[0])
    assert len(fixtures) == 6
    assert [a["gw"] for a in fixtures] == [10, 10, 11, 12, 13, 14]
    assert [a["venue"] for a in fixtures[:2]] == ["H", "A"]
    assert all(x["double"] for x in fixtures[:2])
    assert fixtures[2]["blank"] and fixtures[2]["xpts"] is None
    assert fixtures[0]["fdr"] == 2


def test_independent_per_fixture_xpts_display_only_when_verified():
    s = snap()
    good = verified_xpts_snapshot(
        {"generated_at": s.fetched_at.isoformat(), "model_version": "reviewed-fpl-model-v2",
         "projections": [{"player_id": 99, "fixture_id": 100, "gw": 10, "xpts": 5.61},
                         {"player_id": 999, "fixture_id": 101, "gw": 10, "xpts": 9.0}]},
        s.fetched_at, {99}, {100, 101})
    assert len(good) == 1
    rows = five_gw_fixtures(s, s.players[0], good)
    assert rows[0]["xpts"] == 5.61
    assert all(x["xpts"] is None for x in rows[1:])


def test_unverified_xpts_does_not_sneak_into_slide():
    s = snap()
    assert verified_xpts_snapshot(
        {"model_version": "m", "generated_at": (s.fetched_at-timedelta(days=3)).isoformat(),
         "projections": [{"player_id": 99, "fixture_id": 100, "gw": 10, "xpts": 12}]},
        s.fetched_at, {99}, {100}) == {}
    with pytest.raises(ValueError, match="not verified"):
        five_gw_fixtures(s, s.players[0], {(99, 100): {"gw": 11, "xpts": 5.0}})


def test_defensive_contribution_action_not_confused_with_points():
    s = snap()
    facts = player_metrics(s, s.players[0])
    assert facts["DC ACTIONS"] == "57"
    assert "DC AWARDED PTS" not in facts
    assert facts["CS"] == "4"
    assert facts["PRICE"] == "£7.1m"
    assert facts["OWNERSHIP"] == "25.0%"


def test_missing_verified_footer_handle_blocks_publishing(monkeypatch):
    monkeypatch.delenv("FPL_TELEGRAM_HANDLE", raising=False)
    monkeypatch.delenv("FPL_DISCORD_HANDLE", raising=False)
    with pytest.raises(RuntimeError, match="FPL_TELEGRAM_HANDLE"):
        required_footer_handles()


def test_user_original_footer_restored_and_both_verified_handles(monkeypatch, tmp_path):
    master = tmp_path / "blue.png"
    image = Image.new("RGB", (1536, 864), (4, 17, 53))
    Image.Image.save(image, master)
    output = tmp_path / "post.png"
    Image.new("RGB", (1920, 1080), (54, 26, 47)).save(output)
    monkeypatch.setenv("FPL_TELEGRAM_HANDLE", "@verifiedTelegram")
    monkeypatch.setenv("FPL_DISCORD_HANDLE", "@verifiedDiscord")
    monkeypatch.setattr(footer, "MASTER", master)
    assert footer.apply_footer(output, verdict="HOLD • Strong fixture evidence") == output
    with Image.open(output) as checked:
        assert checked.size == (1920, 1080)
        assert checked.getpixel((5, 1070)) == (4, 17, 53)


def test_semantic_revision_avoids_repeat_cross_day_but_allows_real_change():
    base = Content("elite", "Watch", "6AM", (Card("Example", "ARS", "PICK", ("Stats 5",), 123, 3),),
                   "HOLD", "Data\n#FPL #GW10 #FPLVortex #PremierLeague", "now", 10, "internal source")
    group = publication_group(base)
    version = semantic_fingerprint(base)
    delivery = {"2026-11-02:elite": {"delivered": True, "discord_delivered": True}}
    old = revision_record(group, "2026-11-02:elite", version, {}, delivery["2026-11-02:elite"], True, "now")
    result = check_revision({group: old}, base, delivery, "2026-11-03:elite", True)
    assert result[-1] is True and result[2] == "2026-11-02:elite"
    changed = Content("elite", "Watch", "6AM",
                      (Card("Example", "ARS", "PICK", ("Stats 6",), 123, 3),),
                      "HOLD", base.caption, "later", 10, "internal source")
    new_result = check_revision({group: old}, changed, delivery, "2026-11-03:elite", True)
    assert not new_result[-1]
    assert new_result[1].title.startswith("UPDATED")


def test_missing_personal_player_photo_id_blocks_every_enriched_post(monkeypatch):
    s = snap()
    article = Content("elite", "Watch", "Scout", (Card("Example", "ARS", "TEST", ("Hi",), None, 3),),
                      "HOLD", "Text", "today", 10, "src")
    monkeypatch.setenv("FPL_TELEGRAM_HANDLE", "@verifiedTelegram")
    monkeypatch.setenv("FPL_DISCORD_HANDLE", "@verifiedDiscord")
    with pytest.raises(RuntimeError, match="photo ID"):
        validate_article(article, s)


def test_completed_fplcore_ignores_unfinished_gameweek():
    s = snap()
    assert latest_completed_event(s) == 9
    s.fixtures[0]["finished"] = False
    assert latest_completed_event(s) is None


def test_historical_fplcore_id_team_join_and_timestamp(monkeypatch):
    s = snap()
    commit_time = (s.fetched_at-timedelta(hours=2)).isoformat()
    class Resp:
        def __init__(self, data, is_json=False):
            self._data, self.is_json = data, is_json
            self.content = json.dumps(data).encode() if is_json else data.encode()
        def raise_for_status(self):
            pass
        def json(self):
            return self._data
    class Session:
        def get(self, url, **kw):
            if url.endswith("/commits"):
                return Resp([{"commit": {"committer": {"date": commit_time}}}], True)
            if url.endswith("/players.csv"):
                return Resp("player_code,player_id,team_code\n123,99,3\n")
            return Resp("id,gw,tackles,clearances_blocks_interceptions,minutes\n99,9,4,6,90\n")
    enriched = completed_gw_enrichment(s, Session(), s.fetched_at)
    assert enriched[99]["gw_tackles"] == 4
    assert enriched[99]["gw_clearances_blocks_interceptions"] == 6
