"""Build the full gameweek board from the configured bookmaker-odds pipeline."""
from math import isfinite

from .autonomous_schedule import ET
from .editorial_inputs import RequiredInput
from .market_odds import verified_match_odds
from .solio import URL as SOLIO_URL, solio_match_projections


def complete(projection):
    return all(type(value) in (int, float) and isfinite(value) and 0 <= value <= ceiling
               for value, ceiling in (
                   (projection.get("home_goals"), 12), (projection.get("away_goals"), 12),
                   (projection.get("home_cs"), 100), (projection.get("away_cs"), 100),
               ))


def build_odds_board(slot, snapshot, evidence):
    from .autonomous_content import Plan

    gw = snapshot.gameweek()
    fixtures = sorted(
        (f for f in snapshot.fixtures if f.get("event") == gw and not f.get("finished")),
        key=lambda f: (f.get("kickoff_time") or "", f["id"]),
    )
    if not gw or not fixtures:
        raise RequiredInput("No verified upcoming FPL fixtures for the odds board")
    odds = verified_match_odds(snapshot, fixtures, session=evidence.session)
    missing = [fixture for fixture in fixtures if not complete(odds.get(fixture["id"], {}))]
    solio = solio_match_projections(snapshot, fixtures, session=evidence.session) if missing else {}
    rows = []
    for fixture in fixtures:
        fixture_id = fixture["id"]
        projection = odds.get(fixture_id, {})
        source = "market"
        if not complete(projection):
            projection = solio.get(fixture_id, {})
            source = "solio" if complete(projection) else None
        keys = {"home": "team_h", "away": "team_a"}
        for side, other, venue in (("home", "away", "H"), ("away", "home", "A")):
            team = snapshot.teams.get(fixture.get(keys[side]), {})
            opponent = snapshot.teams.get(fixture.get(keys[other]), {})
            if not all(club.get("short_name") and club.get("code") for club in (team, opponent)):
                raise RequiredInput("Official fixture clubs could not be verified")
            fdr = fixture.get(f"{keys[side]}_difficulty")
            if fdr not in (1, 2, 3, 4, 5):
                raise RequiredInput("Official fixture difficulty is missing")
            rows.append({
                "fixture": fixture_id, "team": team["short_name"], "team_code": team["code"],
                "opponent": opponent["short_name"], "opponent_code": opponent["code"], "venue": venue,
                "fdr": fdr, "goals": projection[f"{side}_goals"] if source else None,
                "clean_sheet": projection[f"{side}_cs"] if source else None, "source": source,
            })
    market_count = sum(row["source"] == "market" for row in rows) // 2
    solio_count = sum(row["source"] == "solio" for row in rows) // 2
    covered = market_count + solio_count
    if not covered:
        raise RequiredInput("No fresh verified projections from The Odds API or Solio Analytics")
    date = snapshot.fetched_at.astimezone(ET).date().isoformat()
    lead_goals = max((row for row in rows if row["goals"] is not None), key=lambda row: row["goals"])
    lead_cs = max((row for row in rows if row["clean_sheet"] is not None), key=lambda row: row["clean_sheet"])
    caption = (
        f"📊 GW{gw} Projected Goals & Clean Sheets\n"
        f"⚽ {lead_goals['team']} {lead_goals['goals']:.2f} projected goals · "
        f"🧤 {lead_cs['team']} {lead_cs['clean_sheet']:.0f}% clean sheet\n"
        f"{date} ET • {market_count} market · {solio_count} Solio Analytics model · {len(fixtures)-covered} unavailable.\n"
        f"#FPL #GW{gw} #FPLVORTEX #FPLFixtures"
    )
    return Plan(slot.task, slot.edition, f"GW{gw} PROJECTED GOALS & CLEAN SHEETS",
                caption, gw, [], [], kind="odds_board",
                extra={"rows": rows, "covered": covered, "fixture_count": len(fixtures),
                       "market_count": market_count, "solio_count": solio_count, "edition_date": date,
                       "sources": (["https://the-odds-api.com/"] if market_count else [])
                                  + ([SOLIO_URL] if solio_count else [])})
