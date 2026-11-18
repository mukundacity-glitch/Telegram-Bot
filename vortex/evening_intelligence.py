"""Verified day-specific evening boards (Tuesday–Saturday).

Sources are official FPL, the provenance-checked VORTEX model and the
FPL Core match archive. Never copy numbers from a reference image.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from math import isfinite
import os

from .autonomous_schedule import ET, season_id
from .editorial_inputs import RequiredInput, verified_feed
from .fpl import latest_completed_gw
from .weekly_analysis import archive_url, csv_rows, rounds_for
from .team_points import kickoff, integral

KINDS = {
    "tuesday-set-pieces": "set_pieces",
    "wednesday-predicted-xg": "predicted_xg",
    "thursday-attacking-zones": "attacking_zones",
    "friday-rotation-planner": "rotation_planner",
    "saturday-fdr-grid": "fdr_grid",
}

FPL_SOURCE = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_SOURCE = "https://fantasy.premierleague.com/api/fixtures/"


def _weeks(snapshot, count):
    first = snapshot.gameweek()
    if not isinstance(first, int) or first < 1:
        raise RequiredInput("No future official FPL deadline")
    weeks = sorted({
        event["id"] for event in snapshot.events
        if type(event.get("id")) is int and event["id"] >= first
    })[:count]
    if not weeks or weeks[0] != first:
        raise RequiredInput("Official gameweek calendar missing")
    return weeks


def _caption(title, snapshot, now, fact, note):
    gw = snapshot.gameweek()
    return "\n".join((
        f"📊 {title} | GW{gw}",
        fact,
        note,
        f"Official data checked {now.astimezone(ET):%d %b %Y}; verify changes before deadline.",
        f"#FPL #GW{gw} #FPLVORTEX #PremierLeague",
    ))


def _plan(slot, snapshot, now, title, fact, note, kind, extra):
    from .autonomous_content import Plan
    return Plan(slot.task, slot.edition, title,
                _caption(title, snapshot, now, fact, note),
                snapshot.gameweek(), [], [], kind, extra)


def _number(value, *, min_value=0, max_value=10000):
    if type(value) not in (float, int, str) or value == "":
        raise RequiredInput("Missing verified numerical field")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise RequiredInput("Invalid numerical field") from None
    if not isfinite(parsed) or not min_value <= parsed <= max_value:
        raise RequiredInput("Out-of-range numerical field")
    return parsed


def _set_piece_order(player, field):
    value = player.get(field)
    return value if type(value) is int and 1 <= value <= 30 else None


def _set_pieces(slot, snapshot, now):
    rows = []
    for player in snapshot.players:
        team = snapshot.teams.get(player.get("team"))
        if not team or type(player.get("minutes")) is not int or player["minutes"] < 270:
            continue
        orders = tuple(_set_piece_order(player, field) for field in (
            "corners_and_indirect_freekicks_order",
            "direct_freekicks_order", "penalties_order"))
        if not any(orders):
            continue
        rows.append({
            "name": snapshot.name(player), "code": team["code"],
            "club": team["short_name"], "minutes": player["minutes"],
            "orders": orders,
            "threat": (_number(player["set_piece_threat"], max_value=10000)
                       if player.get("set_piece_threat") not in (None, "") else None),
            "id": player["id"],
        })
    rows.sort(key=lambda r: (min(x for x in r["orders"] if x is not None),
                             -sum(x == 1 for x in r["orders"]), -r["minutes"], r["id"]))
    if len(rows) < 10:
        raise RequiredInput("Not enough current FPL set-piece order records")
    rows = rows[:12]
    return _plan(slot, snapshot, now, "FPL SET-PIECE TAKERS",
                 f"{len(rows)} current official FPL set-piece duty leaders (270+ minutes).",
                 "Order 1 means first in line, not set pieces per 90. Roles can change.",
                 "set_pieces", {
                     "rows": rows, "sources": [FPL_SOURCE],
                     "method": "Official FPL set-piece duty order; not RotoWire CRN/90",
                 })


def _team_fixture_rows(snapshot, feed, weeks):
    """Exact official fixture-ID/venue join; reject partial model coverage."""
    from .autonomous_content import _team_rows
    rows = {}
    for team_id, team in snapshot.teams.items():
        validated = _team_rows(feed, snapshot, team_id)
        by_week = defaultdict(list)
        for fixture in validated:
            if fixture["gw"] in weeks:
                by_week[fixture["gw"]].append(fixture)
        rows[team_id] = by_week
    if len(rows) != 20:
        raise RequiredInput("League forecast must include all 20 current clubs")
    return rows


def _predicted_xg(slot, snapshot, now, session):
    weeks = _weeks(snapshot, 5)
    feed = verified_feed(snapshot, now, session=session)
    by_team = _team_fixture_rows(snapshot, feed, weeks)
    rows = []
    for team_id, club in snapshot.teams.items():
        cells = []
        for gw in weeks:
            fixtures = by_team[team_id][gw]
            total = sum(_number(f["projected_goals"], max_value=12) for f in fixtures)
            cells.append({"gw": gw, "xg": round(total, 2), "fixtures": len(fixtures)})
        total = sum(cell["xg"] for cell in cells)
        rows.append({"name": club["name"], "code": club["code"],
                     "short": club["short_name"], "cells": cells,
                     "total": round(total, 2), "average": round(total / len(weeks), 2)})
    rows.sort(key=lambda r: (-r["total"], r["name"]))
    return _plan(slot, snapshot, now, "PREDICTED TEAM xG",
                 f"{len(rows)} teams · GW{weeks[0]}–GW{weeks[-1]} · model version {feed['model_version']}.",
                 "Forward-looking model estimates, not measured match xG or bookmaker odds.",
                 "predicted_xg", {
                     "rows": rows, "weeks": weeks, "model": feed["model_version"],
                     "sources": [FPL_SOURCE, FIXTURES_SOURCE, feed["methodology_url"]],
                 })


def _attacking_zones(slot, snapshot, now, session):
    """Summarize shot origin, explicitly NOT all touches or attack channels."""
    through = latest_completed_gw(snapshot)
    if through is None:
        raise RequiredInput("No verified finished gameweek for shot-origin zones")
    weeks = rounds_for(snapshot, through)[-5:]
    if not weeks:
        raise RequiredInput("No completed round for shot-origin zones")
    year = int(season_id(snapshot, now).split("-")[0])
    official = {}
    for f in snapshot.fixtures:
        if f.get("event") not in weeks or f.get("finished") is not True:
            continue
        key = (kickoff(f["kickoff_time"]),
               snapshot.teams[f["team_h"]]["code"], snapshot.teams[f["team_a"]]["code"])
        if key in official:
            raise RequiredInput("Duplicate official completed fixture")
        official[key] = f
    if not official:
        raise RequiredInput("No completed official fixtures in zone window")

    counts = {team_id: Counter() for team_id in snapshot.teams}
    matched = set()
    sources = []
    for gw in weeks:
        match_url = archive_url(year, "matches.csv", gw)
        shot_url = archive_url(year, "shots.csv", gw)
        matches = csv_rows(session, match_url)
        shots = csv_rows(session, shot_url)
        sources.extend((match_url, shot_url))
        by_match = {}
        for row in matches:
            key = (kickoff(row["kickoff_time"]),
                   integral(row["home_team"]), integral(row["away_team"]))
            f = official.get(key)
            if not f or f["event"] != gw or row.get("finished", "").lower() not in ("true", "1"):
                continue
            if (integral(row["home_score"]), integral(row["away_score"])) != (
                    f["team_h_score"], f["team_a_score"]):
                raise RequiredInput("FPL Core zone source score mismatch")
            if f["id"] in matched or row["match_id"] in by_match:
                raise RequiredInput("Duplicate archive match for zone board")
            matched.add(f["id"])
            by_match[row["match_id"]] = f
        for shot in shots:
            match = by_match.get(shot.get("match_id"))
            if match is None:
                continue
            side = shot.get("is_home", "").lower()
            if side not in ("true", "false", "1", "0"):
                raise RequiredInput("Unverified shot team-side label")
            y = _number(shot.get("start_y"), max_value=100)
            team = match["team_h"] if side in ("true", "1") else match["team_a"]
            zone = "left" if y < 100/3 else "centre" if y < 200/3 else "right"
            counts[team][zone] += 1
    if matched != {f["id"] for f in official.values()}:
        raise RequiredInput("FPL Core zone source does not cover completed official matches")
    rows = []
    for team_id, club in snapshot.teams.items():
        values = counts[team_id]
        total = sum(values.values())
        if total < 5:
            raise RequiredInput("Incomplete team shot origins for attacking-zone chart")
        pct = [100 * values[k] / total for k in ("left", "centre", "right")]
        rows.append({"name": club["name"], "code": club["code"],
                     "left": pct[0], "centre": pct[1], "right": pct[2],
                     "shots": total})
    rows.sort(key=lambda r: (-r["centre"], r["name"]))
    return _plan(slot, snapshot, now, "ATTACKING ZONES • SHOT ORIGINS",
                 f"All 20 clubs · {len(weeks)} completed rounds through GW{through}.",
                 "Lateral shot locations by third; this is NOT the share of all attacks.",
                 "attacking_zones", {
                     "rows": rows, "through": through, "weeks": weeks, "sources": sources,
                     "method": "FPL Core shot start_y, not FotMob attack-channel percentages",
                 })


def _rotation_team_ids(snapshot):
    """Editorial club pair is configurable; fixtures and ratings are always live."""
    choices = [x.strip().casefold() for x in
               os.environ.get("VORTEX_ROTATION_TEAMS", "Leeds United,Tottenham Hotspur").split(",")]
    if len(choices) != 2 or not all(choices) or choices[0] == choices[1]:
        raise RequiredInput("VORTEX_ROTATION_TEAMS must specify two different clubs")
    aliases = {
        team_id: {str(club.get(key, "")).casefold() for key in
                  ("name", "short_name", "code")} |
                 ({"spurs"} if "tottenham" in club["name"].lower() else set())
        for team_id, club in snapshot.teams.items()
    }
    matches = []
    for choice in choices:
        found = [team_id for team_id, names in aliases.items()
                 if choice in names or any(name.startswith(choice) for name in names)]
        if len(found) != 1:
            raise RequiredInput("A configured rotation club is not uniquely in the current league")
        matches.append(found[0])
    if len(set(matches)) != 2:
        raise RequiredInput("Rotation teams must be different")
    return matches


def _rotation(slot, snapshot, now, session):
    """Use independently verified CS model only where supported, FDR elsewhere."""
    weeks = _weeks(snapshot, 11)
    team_ids = _rotation_team_ids(snapshot)
    # The current VORTEX model only has five future GWs. Later weeks and model
    # downtime must use honest official FPL FDR, not invented clean-sheet odds.
    feed = None
    model_rows = {}
    try:
        feed = verified_feed(snapshot, now, session=session)
        model_rows = _team_fixture_rows(snapshot, feed, weeks[:5])
    except RequiredInput:
        feed = None
    rows = []
    for gw in weeks:
        options = []
        for team_id in team_ids:
            official = snapshot.fixtures_for_gameweek({"team": team_id}, gw)
            if len(official) > 1:
                raise RequiredInput("Rotation board requires a separate double-GW model")
            fixture = official[0] if official else None
            model_items = model_rows.get(team_id, {}).get(gw, []) if feed else []
            if len(model_items) > 1:
                raise RequiredInput("No joint defensive model for double fixtures")
            probability = None
            if model_items:
                if not fixture:
                    raise RequiredInput("Verified CS fixture not found in official FPL")
                probability = _number(model_items[0]["clean_sheet_pct"], max_value=100)
            club = snapshot.teams[team_id]
            if fixture:
                opp, venue, fdr, opp_code = fixture
                if type(fdr) is not int or not 1 <= fdr <= 5 or not opp_code:
                    raise RequiredInput("Official rotation FDR/opponent incomplete")
                details = {"team": team_id, "name": club["short_name"],
                           "code": club["code"], "opp": opp, "opp_code": opp_code,
                           "venue": venue, "fdr": fdr, "cs": probability}
            else:
                details = {"team": team_id, "name": club["short_name"],
                           "code": club["code"], "opp": "BLANK",
                           "opp_code": None, "venue": "-", "fdr": None, "cs": None}
            options.append(details)
        # Choose verified CS if BOTH sides have it; otherwise use FDR for
        # both so the two data types are never compared as interchangeable.
        both_cs = all(r["cs"] is not None for r in options)
        if both_cs:
            chosen = max(options, key=lambda r: (r["cs"], -r["fdr"], -r["team"]))
        else:
            chosen = min(options, key=lambda r: (r["fdr"] if r["fdr"] is not None else 6,
                                                r["team"]))
        rows.append({"gw": gw, "choices": options,
                     "chosen": chosen["team"] if chosen["fdr"] is not None else None,
                     "decision_basis": "MODEL CS%" if both_cs else "OFFICIAL FDR"})
    model_note = (f"VORTEX {feed['model_version']} for covered GWs; later use official FDR."
                  if feed else "Official FPL FDR only; verified CS model unavailable.")
    return _plan(slot, snapshot, now, "TWO-CLUB ROTATION PLANNER",
                 " vs ".join(snapshot.teams[team_id]["name"] for team_id in team_ids),
                 f"{model_note} Clean sheets are never guaranteed.",
                 "rotation_planner", {
                     "rows": rows, "club_ids": team_ids,
                     "model": feed["model_version"] if feed else None, "weeks": weeks,
                     "sources": [FPL_SOURCE, FIXTURES_SOURCE] +
                                ([feed["methodology_url"]] if feed else []),
                 })

def _fdr_grid(slot, snapshot, now):
    weeks = _weeks(snapshot, 6)
    rows = []
    if len(snapshot.teams) != 20:
        raise RequiredInput("FDR board needs all 20 current Premier League clubs")
    for team_id, club in snapshot.teams.items():
        cells = []
        fdr_values = []
        for gw in weeks:
            fixtures = snapshot.fixtures_for_gameweek({"team": team_id}, gw)
            if any(opp == "TBD" or venue not in ("H", "A")
                   or type(fdr) is not int or not 1 <= fdr <= 5
                   or type(code) is not int
                   for opp, venue, fdr, code in fixtures):
                raise RequiredInput("Incomplete official FDR or opponent identity")
            cells.append([{"opp": opp, "venue": venue, "fdr": fdr, "code": code}
                          for opp, venue, fdr, code in fixtures])
            fdr_values.extend(fdr for _, _, fdr, _ in fixtures)
        if not fdr_values:
            raise RequiredInput("No future FDR for a current club")
        rows.append({"name": club["name"], "short": club["short_name"],
                     "code": club["code"], "cells": cells,
                     "average": round(sum(fdr_values) / len(fdr_values), 2),
                     "games": len(fdr_values)})
    rows.sort(key=lambda row: (row["average"], -row["games"], row["name"]))
    return _plan(slot, snapshot, now, "FIXTURE DIFFICULTY RATING",
                 f"Official FPL FDR • GW{weeks[0]}–GW{weeks[-1]}.",
                 "1 easiest / 5 toughest; blank and double gameweeks marked explicitly.",
                 "fdr_grid", {"rows": rows, "weeks": weeks,
                              "sources": [FPL_SOURCE, FIXTURES_SOURCE]})


def build_evening(slot, snapshot, now, evidence):
    if slot.edition not in KINDS:
        raise ValueError("Unsupported evening intelligence edition")
    if slot.edition == "tuesday-set-pieces":
        return _set_pieces(slot, snapshot, now)
    if slot.edition == "wednesday-predicted-xg":
        return _predicted_xg(slot, snapshot, now, evidence.session)
    if slot.edition == "thursday-attacking-zones":
        return _attacking_zones(slot, snapshot, now, evidence.session)
    if slot.edition == "friday-rotation-planner":
        return _rotation(slot, snapshot, now, evidence.session)
    return _fdr_grid(slot, snapshot, now)
