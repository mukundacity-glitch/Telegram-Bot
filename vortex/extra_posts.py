"""Three additional FPL VORTEX Telegram editions, preserving all legacy posts.

All gameweek fixtures, scores, badges, FDRs and player statistics originate
from the SAME official FPL snapshot. Optional odds come from a separate,
timestamp-verified bookmaker source, never estimated from FPL difficulty.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from zoneinfo import ZoneInfo

from .fpl import FplSnapshot, upcoming_deadline
from .market_odds import verified_match_odds
from .recommendations import number, integer, display

ET = ZoneInfo("America/New_York")
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


@dataclass(frozen=True)
class ExtraPost:
    kind: str
    title: str
    kicker: str
    caption: str
    data_at: str
    gw: int
    footer: str
    fixtures: tuple[dict[str, Any], ...] = ()
    team_analysis: dict[str, Any] | None = None
    transfers: tuple[dict[str, Any], ...] = ()


def caption(lines: list[str], gw: int) -> str:
    """New editions: original 5-story-line format, exactly FOUR hashtags."""
    if len(lines) != 5 or any(not line.strip() for line in lines):
        raise ValueError("New Telegram posts require exactly five story lines")
    body = [s.replace("#", "").replace("\n", " ").strip() for s in lines]
    result = "\n".join([*body, f"#FPL #GW{gw} #FPLVortex #PremierLeague"])
    if len(result) > 280 or len(result.splitlines()) != 6:
        raise ValueError("New caption exceeds original X limits")
    return result


def _next_fixtures(snapshot: FplSnapshot) -> list[dict[str, Any]]:
    gw = snapshot.gameweek()
    if not gw:
        raise ValueError("Cannot determine a confirmed future FPL Gameweek")
    data = [f for f in snapshot.fixtures if f.get("event") == gw
            and not f.get("finished")
            and isinstance(f.get("team_h"), int) and isinstance(f.get("team_a"), int)]
    data.sort(key=lambda f: (f.get("kickoff_time") or "9999", f.get("id") or 0))
    if not data:
        raise ValueError("No confirmed upcoming FPL fixtures")
    if len(data) > 12:
        raise ValueError("More than twelve fixtures; refuse to silently omit matchups")
    return data


def _fixture_name(snapshot: FplSnapshot, item: dict[str, Any], side: str) -> str:
    team = snapshot.teams.get(item.get(f"team_{side}"), {})
    return str(team.get("short_name") or "TBD")


def _fixture_model(snapshot: FplSnapshot, item: dict[str, Any],
                   market: dict[str, Any] | None = None) -> dict[str, Any]:
    home, away = snapshot.teams.get(item["team_h"], {}), snapshot.teams.get(item["team_a"], {})
    odds = market or {}
    return {
        "id": item.get("id"),
        "home": str(home.get("short_name") or "TBD"),
        "away": str(away.get("short_name") or "TBD"),
        "home_name": str(home.get("name") or "TBD"),
        "away_name": str(away.get("name") or "TBD"),
        "home_code": home.get("code"),
        "away_code": away.get("code"),
        "h_fdr": item.get("team_h_difficulty"),
        "a_fdr": item.get("team_a_difficulty"),
        "kickoff": item.get("kickoff_time") or "TBD",
        "home_goals": odds.get("home_goals"),
        "away_goals": odds.get("away_goals"),
        "home_cs": odds.get("home_cs"),
        "away_cs": odds.get("away_cs"),
        "bookmakers_home": odds.get("home_books", 0),
        "bookmakers_away": odds.get("away_books", 0),
        "odds_source": odds.get("source") or "NO VERIFIED 0.5 TEAM-TOTAL MARKET",
    }


def _player_model(snapshot: FplSnapshot, player: dict[str, Any]) -> dict[str, Any]:
    fixture = snapshot.fixtures_for_gameweek(player)
    opp = " · ".join(f"{opp} ({venue}) FDR {fd if fd is not None else 'N/A'}"
                     for opp, venue, fd, _ in fixture) if fixture else "BLANK"
    fdrs = [fd for _, _, fd, _ in fixture]
    average = sum(fdrs) / len(fdrs) if fdrs and all(isinstance(f, int) and f > 0 for f in fdrs) else None
    return {
        "id": player.get("id"), "name": snapshot.name(player),
        "team": snapshot.team(player), "club_code": snapshot.team_code(player),
        "photo_code": snapshot.photo_code(player),
        "position": POS.get(player.get("element_type"), "N/A"),
        "price": snapshot.price(player), "cost": player.get("now_cost"),
        "form": display(player.get("form"), 1),
        "form_value": number(player.get("form")),
        "minutes": player.get("minutes"),
        "ppg": number(player.get("points_per_game")),
        "ownership": display(player.get("selected_by_percent"), 1),
        "status": str(player.get("status") or "u"),
        "chance": player.get("chance_of_playing_next_round"),
        "opponent": opp, "fdr": average,
        "matches": tuple(fixture),
        "in_event": player.get("transfers_in_event"),
        "out_event": player.get("transfers_out_event"),
    }


def _score(player: dict[str, Any]) -> float:
    form = player.get("form_value")
    mins = integer(player.get("minutes"))
    fd = player.get("fdr")
    if form is None or mins is None:
        return -100
    health = 1.0 if player.get("status") == "a" else -7
    if isinstance(player.get("chance"), int) and player["chance"] < 75:
        health -= 5
    fixture = (4 - fd) * 0.9 if fd is not None else -6
    return form + min(1.6, mins / 1500) + fixture + health


def _team_history(snapshot: FplSnapshot, team_id: int, limit: int = 9) -> list[dict[str, Any]]:
    rows = []
    for f in snapshot.fixtures:
        if f.get("finished") is not True or team_id not in (f.get("team_h"), f.get("team_a")):
            continue
        sh, sa = integer(f.get("team_h_score")), integer(f.get("team_a_score"))
        if sh is None or sa is None:
            continue
        home = f.get("team_h") == team_id
        other = f.get("team_a") if home else f.get("team_h")
        rows.append({
            "kickoff": f.get("kickoff_time") or "",
            "gw": f.get("event"),
            "opponent": snapshot.teams.get(other, {}).get("short_name", "TBD"),
            "venue": "H" if home else "A",
            "gf": sh if home else sa, "ga": sa if home else sh,
        })
    rows.sort(key=lambda r: r["kickoff"])
    return rows[-limit:]


def _best_team(snapshot: FplSnapshot, upcoming: list[dict[str, Any]],
               current: datetime) -> dict[str, Any]:
    candidates = []
    for f in upcoming:
        for side in ("h", "a"):
            fid = f.get(f"team_{side}")
            fd = f.get(f"team_{side}_difficulty")
            if not isinstance(fd, int) or not 1 <= fd <= 5:
                continue
            club = snapshot.teams.get(fid, {})
            if not club:
                continue
            candidates.append((fd, str(club.get("short_name") or ""), fid, f, side))
    candidates.sort(key=lambda r: (r[0], r[1]))
    attractive = [c for c in candidates if c[0] <= 3] or candidates
    if not attractive:
        raise ValueError("Unable to select a fixture-based team")
    # Rotate the focal club daily among the most favourable options; maintain
    # verified selection criteria while avoiding identical daily editions.
    pool = attractive[:min(8, len(attractive))]
    fdr, _, team_id, fixture, side = pool[current.astimezone(ET).date().toordinal() % len(pool)]
    opp_id = fixture["team_a" if side == "h" else "team_h"]
    club = snapshot.teams[team_id]
    available = [_player_model(snapshot, p) for p in snapshot.players if p.get("team") == team_id
                 and p.get("status") == "a" and isinstance(p.get("code"), int)]
    available.sort(key=_score, reverse=True)
    featured = available[:3]
    if len(featured) < 3:
        raise ValueError("Not enough verifiable available players for team analysis")
    goals = _team_history(snapshot, team_id)
    return {
        "team_id": team_id, "team": str(club.get("name")), "short": str(club.get("short_name")),
        "code": club.get("code"),
        "opponent": snapshot.teams.get(opp_id, {}).get("short_name", "TBD"),
        "opponent_code": snapshot.teams.get(opp_id, {}).get("code"),
        "venue": "H" if side == "h" else "A", "fdr": fdr,
        "history": goals, "players": featured,
        "gf_total": sum(x["gf"] for x in goals) if goals else None,
        "ga_total": sum(x["ga"] for x in goals) if goals else None,
        "period": f"LAST {len(goals)} COMPLETED MATCHES",
        "action": "TARGET / MONITOR" if fdr <= 3 else "HOLD / MONITOR",
    }


def _transfers(snapshot: FplSnapshot) -> list[dict[str, Any]]:
    # A comparison in every position, not a rewrite of the existing 2 PM post.
    players = [_player_model(snapshot, p) for p in snapshot.players
               if isinstance(p.get("now_cost"), int)
               and p.get("element_type") in POS]
    rows: list[dict[str, Any]] = []
    for position in POS.values():
        outgoing = [p for p in players if p["position"] == position
                    and integer(p["out_event"]) is not None]
        outgoing.sort(key=lambda p: (-p["out_event"], str(p["name"])))
        incoming = [p for p in players if p["position"] == position
                    and integer(p["in_event"]) is not None and p["status"] == "a"
                    and p["fdr"] is not None and _score(p) > -20
                    and isinstance(p.get("photo_code"), int)]
        incoming.sort(key=lambda p: (-_score(p), -p["in_event"]))
        if not outgoing:
            raise ValueError(f"No verified transfer-out record for {position}")
        # Consider high transfers-out but do not force a swap when not supported.
        best_row = None
        for out in outgoing[:30]:
            options = [p for p in incoming if p["id"] != out["id"]
                       and p["team"] != out["team"]
                       and p["cost"] <= out["cost"] + 5
                       and p["cost"] >= out["cost"] - 35]
            option = options[0] if options else None
            delta = (_score(option) - _score(out)) if option else None
            should_swap = bool(option and delta is not None and delta >= 2.0
                               and (out["status"] != "a" or out["fdr"] is None
                                    or out["form_value"] is None
                                    or option["fdr"] <= out["fdr"]))
            reason = (
                f"Official availability risk; alternative has next-GW FDR {display(option['fdr'],1)}."
                if should_swap and out["status"] != "a"
                else f"Better fixture/form indicators; next-GW FDR {display(option['fdr'],1)}."
                if should_swap else
                "Popularity alone does not justify a move; HOLD and review minutes."
            )
            candidate = {"position": position, "out": out, "incoming": option if should_swap else None,
                         "verdict": "SELL → BUY" if should_swap else "HOLD",
                         "reason": reason, "period": "FPL EVENT-TO-DATE"}
            if best_row is None or should_swap:
                best_row = candidate
            if should_swap:
                break
        if best_row is None:
            raise ValueError(f"Unable to choose transfer comparison for {position}")
        rows.append(best_row)
    return rows


def generate_extra(kind: str, snapshot: FplSnapshot, now: datetime) -> ExtraPost:
    if kind not in {"projections", "team_analysis", "transfer_suggestions"}:
        raise ValueError("Unsupported extra post kind")
    gw = snapshot.gameweek()
    deadline = upcoming_deadline(snapshot)
    if not gw or deadline is None:
        raise ValueError("No verified next-GW deadline for new post")
    time_label = snapshot.fetched_at.astimezone(ET).strftime("%d %b %Y · %I:%M %p ET")
    if kind == "projections":
        future = _next_fixtures(snapshot)
        odds = verified_match_odds(snapshot, future)
        games = tuple(_fixture_model(snapshot, f, odds.get(f.get("id"))) for f in future)
        n = len(games)
        confirmed = sum(1 for f in games if f["home_goals"] is not None and f["away_goals"] is not None)
        c = caption([
            f"GW{gw}: {n} official matchups for next GW.",
            f"{confirmed}/{n} backed by two-bookmaker markets.",
            "Projected goals/CS: model estimate or N/A.",
            "Crests and fixtures: official FPL API.",
            "Which fixture is your next target?",
        ], gw)
        return ExtraPost(kind, f"GW{gw} · GOALS & CLEAN SHEETS", "ALL CLUBS · 10 MATCHUPS WHEN STANDARD",
                         c, time_label, gw, "FPL fixtures + separately checked bookmaker markets", fixtures=games)
    if kind == "team_analysis":
        subject = _best_team(snapshot, _next_fixtures(snapshot), now)
        c = caption([
            f"GW{gw}: {subject['short']} attack and defence under the microscope.",
            f"Next: {subject['opponent']} ({subject['venue']}) · official FDR {subject['fdr']}.",
            f"GF/GA chart: {subject['period'].lower()}.",
            f"FPL options: {', '.join(p['name'] for p in subject['players'][:2])}.",
            "Minutes and availability matter before buying.",
        ], gw)
        return ExtraPost(kind, f"GW{gw} · TEAM DECISION DESK", "ATTACK · DEFENCE · FPL OPTIONS",
                         c, time_label, gw, "Official FPL fixture scores and player totals",
                         team_analysis=subject)
    rows = tuple(_transfers(snapshot))
    swaps = sum(row["verdict"] != "HOLD" for row in rows)
    c = caption([
        f"GW{gw}: one-GW transfer calls across all four positions.",
        f"{swaps} evidence-led swaps; {4-swaps} HOLD decisions.",
        "Out/in counts: official FPL event-to-date totals.",
        "Same position, budget-aware picks; no invented xPts.",
        "Avoid hits without checking your exact team.",
    ], gw)
    return ExtraPost(kind, f"GW{gw} · TRANSFER SUGGESTIONS", "GK · DEF · MID · FWD · BUY / HOLD / SELL",
                     c, time_label, gw, "Official Fantasy Premier League API",
                     transfers=rows)
