"""Build the full gameweek board from the configured bookmaker-odds pipeline."""
from math import isfinite

from .editorial_inputs import RequiredInput
from .market_odds import verified_match_odds


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
    rows = []
    for fixture in fixtures:
        fixture_id = fixture["id"]
        market = odds.get(fixture_id, {})
        values = [market.get(key) for key in ("home_goals", "away_goals", "home_cs", "away_cs")]
        verified = all(type(v) in (int, float) and isfinite(v) and 0 <= v <= ceiling
                       for v, ceiling in zip(values, (12, 12, 100, 100)))
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
                "fdr": fdr, "goals": market[f"{side}_goals"] if verified else None,
                "clean_sheet": market[f"{side}_cs"] if verified else None,
            })
    covered = sum(row["goals"] is not None for row in rows) // 2
    if not covered:
        raise RequiredInput("No fresh verified bookmaker goal or clean-sheet projections")
    lead_goals = max((row for row in rows if row["goals"] is not None), key=lambda row: row["goals"])
    lead_cs = max((row for row in rows if row["clean_sheet"] is not None), key=lambda row: row["clean_sheet"])
    caption = (
        f"📊 GW{gw} Projected Goals & Clean Sheets\n"
        f"⚽ {lead_goals['team']} {lead_goals['goals']:.2f} projected goals · "
        f"🧤 {lead_cs['team']} {lead_cs['clean_sheet']:.0f}% clean sheet\n"
        f"Verified market coverage: {covered}/{len(fixtures)} fixtures.\n"
        f"#FPL #GW{gw} #FPLVORTEX #FPLFixtures"
    )
    return Plan(slot.task, slot.edition, f"GW{gw} PROJECTED GOALS & CLEAN SHEETS",
                caption, gw, [], [], kind="odds_board",
                extra={"rows": rows, "covered": covered, "fixture_count": len(fixtures)})
