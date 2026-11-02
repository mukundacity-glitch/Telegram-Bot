"""Tests for three new editions: independent markets, dynamic fixtures, images and schedule."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

from test_content import fake_snapshot
from vortex.extra_posts import caption, generate_extra, _transfers
from vortex.extra_render import render_extra
from vortex.market_odds import canonical, verified_match_odds
from vortex.render import render
from vortex.schedule import SLOT_CRONS, SLOT_HOURS


def sample():
    snap = fake_snapshot()
    now = snap.fetched_at
    snap.fixtures[:] = []
    # Standard event: precisely 20 clubs, 10 genuine home/away pairings.
    for i in range(10):
        snap.fixtures.append({
            "id": i + 100, "event": 7, "team_h": 2 * i + 1, "team_a": 2 * i + 2,
            "team_h_difficulty": 2 if i % 2 else 3,
            "team_a_difficulty": 3 if i % 2 else 2,
            "kickoff_time": "2026-10-18T16:00:00Z", "finished": False,
        })
        snap.fixtures.append({
            "id": i + 200, "event": 6, "team_h": 2 * i + 1, "team_a": 2 * i + 2,
            "team_h_difficulty": 2, "team_a_difficulty": 3,
            "kickoff_time": "2026-10-10T16:00:00Z", "finished": True,
            "team_h_score": i % 4, "team_a_score": i % 3,
        })
    for idx, player in enumerate(snap.players):
        player.update({
            "code": 20000 + idx, "element_type": idx % 4 + 1,
            "transfers_in_event": 120000 - idx * 115,
            "transfers_out_event": 100000 - idx * 90,
            "expected_goals": "2.5", "expected_assists": "1.2",
        })
    return snap


def test_matchup_board_uses_all_20_clubs_in_actual_ten_matchups(monkeypatch):
    snap = sample()
    monkeypatch.setattr("vortex.extra_posts.verified_match_odds", lambda s, fixtures: {})
    post = generate_extra("projections", snap, snap.fetched_at)
    assert post.gw == 7
    assert len(post.fixtures) == 10
    assert len({x for item in post.fixtures for x in (item["home_name"], item["away_name"])}) == 20
    assert all(row["home_goals"] is None and row["away_cs"] is None for row in post.fixtures)
    assert post.caption.endswith("#FPL #GW7 #FPLVortex #PremierLeague")
    assert len(post.caption.splitlines()) == 6
    assert len(post.caption) <= 280


def test_nonstandard_gw_never_invents_missing_fixtures(monkeypatch):
    snap = sample()
    snap.fixtures[:] = [f for f in snap.fixtures if f["event"] != 7 or f["id"] != 100]
    monkeypatch.setattr("vortex.extra_posts.verified_match_odds", lambda s, fixtures: {})
    post = generate_extra("projections", snap, snap.fetched_at)
    assert len(post.fixtures) == 9
    assert "9 official matchups" in post.caption


def test_team_history_uses_only_completed_fpl_scorelines():
    snap = sample()
    data = generate_extra("team_analysis", snap, snap.fetched_at)
    club = data.team_analysis
    assert club and club["fdr"] in {2, 3}
    assert 1 <= len(club["history"]) <= 9
    assert all(row["gw"] == 6 for row in club["history"])
    assert len(club["players"]) == 3
    assert all(player["status"] == "a" for player in club["players"])
    assert club["team"] in data.caption or club["short"] in data.caption
    assert len(data.caption.splitlines()) == 6


def test_transfer_suggestions_cover_four_positions_and_event_period():
    snap = sample()
    post = generate_extra("transfer_suggestions", snap, snap.fetched_at)
    assert [row["position"] for row in post.transfers] == ["GK", "DEF", "MID", "FWD"]
    assert all(row["verdict"] in {"HOLD", "SELL → BUY"} for row in post.transfers)
    assert all(row["period"] == "FPL EVENT-TO-DATE" for row in post.transfers)
    for row in post.transfers:
        assert row["out"]["out_event"] is not None
        if row["incoming"]:
            assert row["incoming"]["position"] == row["position"]
            assert row["incoming"]["cost"] <= row["out"]["cost"] + 5
    assert len(post.caption.splitlines()) == 6


def test_no_fake_24_hour_market_data():
    snap = sample()
    for kind in ("projections", "team_analysis", "transfer_suggestions"):
        post = generate_extra(kind, snap, snap.fetched_at)
        assert "last 24" not in post.caption.lower()
        assert post.caption.count("#") == 4


def test_unavailable_markets_do_not_invent_odds(monkeypatch):
    snap = sample()
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    actual = verified_match_odds(snap, snap.fixtures[:10], api_key="")
    assert actual == {}


def test_independent_fresh_two_bookmakers_make_probabilities():
    snap = sample()
    fixture = snap.fixtures[0]
    market_when = (snap.fetched_at - timedelta(minutes=30)).isoformat()
    def book(name):
        return {
            "key": name, "last_update": market_when,
            "markets": [{"key": "alternate_team_totals", "last_update": market_when, "outcomes": [
                {"description": "Team 1", "name": "Over", "point": 0.5, "price": 1.9},
                {"description": "Team 1", "name": "Under", "point": 0.5, "price": 2.1},
                {"description": "Team 2", "name": "Over", "point": 0.5, "price": 1.9},
                {"description": "Team 2", "name": "Under", "point": 0.5, "price": 2.1},
            ]}],
        }
    class FakeResponse:
        def __init__(self, content):
            self.content = content
        def raise_for_status(self):
            pass
        def json(self):
            return self.content
    class FakeSession:
        def get(self, url, **kwargs):
            if url.endswith("/events"):
                return FakeResponse([{
                    "id": "fixture-1", "home_team": "Team 1", "away_team": "Team 2",
                    "commence_time": fixture["kickoff_time"],
                }])
            return FakeResponse({
                "home_team": "Team 1", "away_team": "Team 2",
                "bookmakers": [book("book1"), book("book2")],
            })
    market = verified_match_odds(snap, [fixture], session=FakeSession(), api_key="TEST_ONLY")
    assert fixture["id"] in market
    assert market[fixture["id"]]["home_goals"] is not None
    assert 0 < market[fixture["id"]]["home_cs"] < 100
    assert market[fixture["id"]]["home_books"] == 2
    assert market[fixture["id"]]["home_cs"] == market[fixture["id"]]["away_cs"]


def test_one_bookmaker_or_stale_prices_are_na():
    from vortex.market_odds import _two_sided_quotes, _projection
    now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    def quotes(date):
        return {"bookmakers": [{
            "key": "one_book", "last_update": date.isoformat(),
            "markets": [{"key": "team_totals", "last_update": date.isoformat(),
                         "outcomes": [
                             {"name": "Over", "description": "Team 1", "point": 0.5, "price": 2.0},
                             {"name": "Under", "description": "Team 1", "point": 0.5, "price": 2.0},
                         ]}],
        }]}
    fresh = _two_sided_quotes(quotes(now), ("team 1", "team 2"), now)
    assert _projection(fresh["team 1"]) is None
    stale = _two_sided_quotes(quotes(now - timedelta(days=2)), ("team 1", "team 2"), now)
    assert not stale.get("team 1")


@pytest.mark.parametrize("kind", ["projections", "team_analysis", "transfer_suggestions"])
def test_new_blue_master_graphics_render_with_authentic_media_mock(kind, tmp_path, monkeypatch):
    snap = sample()
    monkeypatch.setattr("vortex.extra_posts.verified_match_odds", lambda s, f: {})
    post = generate_extra(kind, snap, snap.fetched_at)
    monkeypatch.setattr("vortex.extra_render._media", lambda session, code, t, cache:
                        Image.new("RGBA", (220, 330) if t == "photo" else (90, 90),
                                  (110, 175, 220, 255)))
    target = tmp_path / f"{kind}.png"
    result = render(post, target, session=object())
    assert result.is_file() and result.stat().st_size > 50_000
    with Image.open(result) as img:
        assert img.size == (1536, 864)


@pytest.mark.parametrize("kind", ["projections", "team_analysis", "transfer_suggestions"])
def test_new_editions_never_publish_missing_verified_images(kind, tmp_path, monkeypatch):
    snap = sample()
    monkeypatch.setattr("vortex.extra_posts.verified_match_odds", lambda s, f: {})
    post = generate_extra(kind, snap, snap.fetched_at)
    monkeypatch.setattr("vortex.extra_render._media", lambda *args: None)
    with pytest.raises(RuntimeError, match="Verified (photo|crest) unavailable"):
        render(post, tmp_path / f"{kind}.png", session=object())
    assert not (tmp_path / f"{kind}.png").exists()


def test_new_posts_have_exact_four_hashtags_not_legacy_three():
    with pytest.raises(ValueError):
        caption(["a"] * 6, 7)
    text = caption(["a", "b", "c", "d", "e"], 7)
    assert text.splitlines()[-1] == "#FPL #GW7 #FPLVortex #PremierLeague"
