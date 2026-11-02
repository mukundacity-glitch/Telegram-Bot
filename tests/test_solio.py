"""Live Solio HTML adaptation: genuine published values, fixture join and stale guards."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import exp

import pytest

from vortex.extra_posts import generate_extra
from vortex.fpl import FplSnapshot
from vortex.solio import parse_public_html, solio_match_projections

NOW = datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)
FIXTURES = [
    {"id": 101, "event": 10, "team_h": 1, "team_a": 2,
     "team_h_difficulty": 2, "team_a_difficulty": 5,
     "kickoff_time": "2026-11-07T15:00:00Z", "finished": False},
    {"id": 102, "event": 10, "team_h": 3, "team_a": 4,
     "team_h_difficulty": 2, "team_a_difficulty": 3,
     "kickoff_time": "2026-11-06T20:00:00Z", "finished": False},
]
TEAMS = {
    1: {"id": 1, "name": "Arsenal", "short_name": "ARS", "code": 3},
    2: {"id": 2, "name": "Hull City", "short_name": "HUL", "code": 25},
    3: {"id": 3, "name": "Everton", "short_name": "EVE", "code": 11},
    4: {"id": 4, "name": "Coventry City", "short_name": "COV", "code": 33},
}


def snapshot() -> FplSnapshot:
    return FplSnapshot([], TEAMS, [{"id": 10, "is_next": True,
                         "deadline_time": "2026-11-06T18:30:00Z",
                         "finished": False}], list(FIXTURES), NOW)


def page(*, gw: int = 10, stamp: str = "2026-11-02T19:47:56.894Z",
         arsenal_opp: str = "HUL") -> str:
    return f"""<!doctype html><html><body>
    <h1>FPL Gameweek {gw}: projections, captains, and transfers</h1>
    <h2>Which teams have the best clean sheet odds for Gameweek {gw}?</h2>
    <table><thead><tr><th>#</th><th>Team</th><th>Fixtures</th>
    <th>Proj. G Against</th><th>CS %</th></tr></thead><tbody>
    <tr><td>1</td><td>Arsenal</td><td>vs {arsenal_opp}</td><td>0.55</td><td>58%</td></tr>
    <tr><td>2</td><td>Everton</td><td>vs COV</td><td>1.04</td><td>35%</td></tr>
    </tbody></table>
    <h2>Which teams have the best attacking fixtures for Gameweek {gw}?</h2>
    <table><tr><th>#</th><th>Team</th><th>Fixtures</th>
    <th>Proj. G For</th><th>Proj. G Against</th></tr>
    <tr><td>1</td><td>Arsenal</td><td>vs {arsenal_opp}</td><td>2.78</td><td>0.55</td></tr>
    <tr><td>2</td><td>Everton</td><td>vs COV</td><td>1.90</td><td>1.04</td></tr>
    </table>
    <p>Generated at {stamp}</p></body></html>"""


def test_public_solio_fills_both_teams_from_scored_and_conceded_projection():
    result = parse_public_html(snapshot(), FIXTURES, page())
    assert set(result) == {101, 102}
    arsenal = result[101]
    assert (arsenal["home_goals"], arsenal["away_goals"]) == (2.78, 0.55)
    assert arsenal["home_cs"] == 58
    assert arsenal["away_cs"] == round(100 * exp(-2.78))
    assert (result[102]["home_goals"], result[102]["away_goals"]) == (1.90, 1.04)
    assert result[102]["home_cs"] == 35
    assert "Solio Analytics" in arsenal["source"]
    assert "NOT live bookmaker odds" in arsenal["source"]


def test_solio_rejects_wrong_gameweek_stale_and_unmatched_fixture():
    s = snapshot()
    assert parse_public_html(s, FIXTURES, page(gw=9)) == {}
    assert parse_public_html(s, FIXTURES,
        page(stamp="2026-10-31T19:47:56.894Z")) == {}
    result = parse_public_html(s, FIXTURES, page(arsenal_opp="CHE"))
    assert 101 not in result
    assert 102 in result


def test_solio_rejects_double_gameweek_aggregate_data():
    double = [*FIXTURES, dict(FIXTURES[0], id=103, team_a=4)]
    assert parse_public_html(snapshot(), double, page()) == {}


def test_solio_network_failure_is_explicit_no_data():
    class BadSession:
        def get(self, *_a, **_kw):
            from requests import RequestException
            raise RequestException("unavailable")
    assert solio_match_projections(snapshot(), FIXTURES, session=BadSession()) == {}


def test_solio_fetched_once_and_preferred_only_when_no_complete_bookmaker(monkeypatch):
    import vortex.extra_posts as m
    s = snapshot()
    data = parse_public_html(s, FIXTURES, page())
    market = dict(data[101], home_goals=1.88, away_goals=1.21,
                  home_cs=30, away_cs=15, source="The Odds API")
    monkeypatch.setattr(m, "verified_match_odds", lambda *_: {101: market})
    calls = []
    monkeypatch.setattr(m, "solio_match_projections",
                        lambda *_: calls.append("fetched") or data)
    post = generate_extra("projections", s, NOW)
    assert calls == ["fetched"]
    by_id = {row["id"]: row for row in post.fixtures}
    assert by_id[101]["home_goals"] == 1.88
    assert by_id[102]["home_goals"] == 1.90
    assert "Solio Analytics" in by_id[102]["odds_source"]
    assert "#PremierLeague" in post.caption


def test_solio_never_overwrites_valid_bookmaker_data(monkeypatch):
    import vortex.extra_posts as m
    s = snapshot()
    data = parse_public_html(s, FIXTURES, page())
    book = {fid: dict(model, source="The Odds API") for fid, model in data.items()}
    monkeypatch.setattr(m, "verified_match_odds", lambda *_: book)
    monkeypatch.setattr(m, "solio_match_projections",
                        lambda *_: pytest.fail("Unnecessary Solio network call"))
    post = generate_extra("projections", s, NOW)
    assert all(row["odds_source"] == "The Odds API" for row in post.fixtures)
