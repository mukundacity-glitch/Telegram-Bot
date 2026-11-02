"""Market-vs-model numerical invariants; no API calls or fabricated odds."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isclose, log

from vortex.market_odds import _h2h_projection, _projection, _two_sided_quotes


def test_no_vig_team_total_and_poisson_equivalent():
    now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    books = [
        {"key": key, "markets": [{"key": "team_totals", "last_update": now.isoformat(),
              "outcomes": [
                  {"name": "Over", "description": "Arsenal", "point": 0.5, "price": 1.91},
                  {"name": "Under", "description": "Arsenal", "point": 0.5, "price": 1.91}]}]}
        for key in ("first", "second")
    ]
    quotes = _two_sided_quotes({"bookmakers": books}, ("arsenal", "chelsea"), now)
    result = _projection(quotes["arsenal"])
    assert result is not None
    assert isclose(result["p_zero"], 0.5)
    assert result["goals"] == round(-log(0.5), 2)
    assert result["books"] == 2


def test_one_bookmaker_is_insufficient():
    assert _projection([("one", 0.5, 1800)]) is None


def test_three_way_market_de_vig_renormalizes_percentages():
    now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    markets = []
    for book in ("a", "b"):
        markets.append({"key": book, "markets": [{
            "key": "h2h", "last_update": now.isoformat(),
            "outcomes": [{"name": "Arsenal", "price": 2.0},
                         {"name": "Draw", "price": 3.5},
                         {"name": "Chelsea", "price": 4.0}],
        }]})
    result = _h2h_projection({"bookmakers": markets}, ("arsenal", "chelsea"), now)
    assert result is not None
    assert 47 < result["home_win_pct"] < 49
    assert 27 < result["draw_pct"] < 29
    assert 23 < result["away_win_pct"] < 25
    assert abs(sum(result[k] for k in ("home_win_pct", "draw_pct", "away_win_pct")) - 100) < 0.2


def test_stale_quotes_rejected_without_invented_win_rate():
    now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    stale = (now - timedelta(days=1)).isoformat()
    entry = {"key": "book", "markets": [{"key": "h2h",
        "last_update": stale,
        "outcomes": [{"name": "Arsenal", "price": 2.0},
                     {"name": "Draw", "price": 3.5},
                     {"name": "Chelsea", "price": 4.0}]}]}
    assert _h2h_projection({"bookmakers": [entry, entry]},
                            ("arsenal", "chelsea"), now) is None
