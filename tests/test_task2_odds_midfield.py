"""Task 2 edition math, strict sourced visuals and no-fabricated-output tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import exp

from PIL import Image
import pytest

from test_content import fake_snapshot
from vortex.content import generate
from vortex.market_odds import canonical, verified_match_odds
from vortex.odds_model import market_consensus, model_from_consensus, predicted_probabilities
from vortex.render import render


def test_midfielder_edition_exact_three_official_current_players(monkeypatch, tmp_path):
    snap = fake_snapshot()
    for index, player in enumerate(snap.players):
        player["code"] = 10000 + index
        player["expected_goals"] = "1.42"
        player["expected_assists"] = "2.50"
    for idx, f in enumerate(snap.fixtures):
        f["event"] = 7
        f["finished"] = False
        f["kickoff_time"] = "2026-10-17T15:00:00Z"
    snap.fixtures[0]["team_h"] = 2
    snap.fixtures[0]["team_a"] = 3

    content = generate("midfielders", snap, datetime(2026, 10, 16, tzinfo=timezone.utc), {})
    assert len(content.cards) == 3
    assert all(card.photo_code is not None and card.team_code is not None for card in content.cards)
    assert all(card.metrics["xg"] == "1.42" for card in content.cards)
    assert "not next-GW xPts" in content.caption
    assert len(content.caption.splitlines()) == 5
    assert len([word for word in content.caption.split() if word.startswith("#")]) == 4

    monkeypatch.setattr("vortex.premium._media",
                        lambda sess, code, kind, cache: Image.new(
                            "RGBA", (240, 300) if kind == "photo" else (70, 70),
                            (120, 180, 235, 255)
                        ))
    image = render(content, tmp_path / "three_mids.png", session=object())
    with Image.open(image) as output:
        assert output.size == (1920, 1080)


def _quoted_market(now, home="Arsenal", away="Chelsea", include_totals=True):
    home_p, draw_p, away_p, over_p = predicted_probabilities(1.80, 1.10)
    books = []
    for key in ("alpha", "bravo"):
        markets = [{
            "key": "h2h", "last_update": now.isoformat(),
            "outcomes": [
                {"name": home, "price": 1 / (home_p * 1.055)},
                {"name": "Draw", "price": 1 / (draw_p * 1.055)},
                {"name": away, "price": 1 / (away_p * 1.055)},
            ],
        }]
        if include_totals:
            markets.append({
                "key": "totals", "last_update": now.isoformat(),
                "outcomes": [
                    {"name": "Over", "point": 2.5, "price": 1 / (over_p * 1.055)},
                    {"name": "Under", "point": 2.5, "price": 1 / ((1 - over_p) * 1.055)},
                ],
            })
        books.append({"key": key, "markets": markets})
    return {"id": "odds_fixture", "home_team": home, "away_team": away,
            "commence_time": (now + timedelta(hours=24)).isoformat(),
            "bookmakers": books}


def test_de_vig_two_market_model_recovers_actual_goal_rate():
    now = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)
    odds = _quoted_market(now)
    consensus = market_consensus(odds, "arsenal", "chelsea", now, canonical)
    assert consensus is not None and consensus["books_totals"] == 2
    result = model_from_consensus(consensus)
    assert result is not None
    assert abs(result["home_goals"] - 1.8) < 0.06
    assert abs(result["away_goals"] - 1.1) < 0.06
    assert abs(result["home_cs"] - round(100 * exp(-1.1))) <= 1
    assert abs(result["away_cs"] - round(100 * exp(-1.8))) <= 1
    assert result["fit_rmse"] < 0.01


def test_partial_h2h_does_not_create_fake_clean_sheet_numbers():
    now = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)
    assert market_consensus(_quoted_market(now, include_totals=False),
                            "arsenal", "chelsea", now, canonical) is None


def test_stale_bookmaker_quotes_never_fit():
    now = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)
    old = _quoted_market(now - timedelta(hours=14))
    assert market_consensus(old, "arsenal", "chelsea", now, canonical) is None


def test_verified_fpl_fixture_join_and_api_source_with_two_markets():
    now = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)
    odds = _quoted_market(now)
    class FakeResponse:
        def __init__(self, content):
            self.content = content
        def raise_for_status(self):
            return None
        def json(self):
            return self.content
    class Session:
        def get(self, url, **kwargs):
            if url.endswith("/events"):
                return FakeResponse([{"id": "odds_fixture", "home_team": "Arsenal",
                                      "away_team": "Chelsea",
                                      "commence_time": odds["commence_time"]}])
            return FakeResponse(odds)

    from vortex.fpl import FplSnapshot
    teams = {1: {"name": "Arsenal", "short_name": "ARS", "code": 3},
             2: {"name": "Chelsea", "short_name": "CHE", "code": 8}}
    fixture = {"id": 100, "event": 10, "team_h": 1, "team_a": 2,
               "kickoff_time": odds["commence_time"], "finished": False}
    snap = FplSnapshot([], teams, [], [fixture], now)
    match = verified_match_odds(snap, [fixture], session=Session(), api_key="secret-not-logged")[100]
    assert abs(match["home_goals"] - 1.8) < 0.06
    assert abs(match["away_goals"] - 1.1) < 0.06
    assert match["home_cs"] is not None
    assert "odds" in match["source"].casefold()
