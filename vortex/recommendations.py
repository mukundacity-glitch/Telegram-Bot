"""One-gameweek BUY/SELL research using verified FPL fields and official history."""
from __future__ import annotations

from datetime import datetime
from typing import Any
import requests

from .fpl import FplSnapshot, _fetch_json, latest_completed_gw

POSITION = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def display(value: Any, decimals: int = 0) -> str:
    parsed = number(value)
    return "N/A" if parsed is None else f"{parsed:,.{decimals}f}"


def completed_rounds(snapshot: FplSnapshot, limit: int = 3) -> list[int]:
    # Do not use a simple arithmetic GW-1 range: postponements may be unresolved.
    finished = []
    for event in snapshot.events:
        gw = event.get("id")
        if not isinstance(gw, int) or event.get("finished") is not True:
            continue
        fixtures = [f for f in snapshot.fixtures if f.get("event") == gw]
        if any(f.get("finished") is not True for f in fixtures):
            continue
        finished.append(gw)
    return sorted(finished, reverse=True)[:limit]


def get_history(player_id: int, session: requests.Session) -> list[dict[str, Any]]:
    """One API request per featured player; transient errors are unavailable, not zero."""
    try:
        payload = _fetch_json(session, f"element-summary/{player_id}/", timeout=12)
        rows = payload.get("history") if isinstance(payload, dict) else None
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    except (requests.RequestException, ValueError, TypeError):
        return []


def recent_summary(rows: list[dict[str, Any]], rounds: list[int], position: int) -> dict[str, Any]:
    records = [r for r in rows if r.get("round") in rounds]
    if not records:
        return {}
    def total(field: str) -> float | None:
        values = [number(r.get(field)) for r in records]
        return sum(values) if len(values) == len(records) and all(x is not None for x in values) else None
    result: dict[str, Any] = {
        "points": total("total_points"), "minutes": total("minutes"),
        "goals": total("goals_scored"), "assists": total("assists"),
        "clean_sheets": total("clean_sheets"), "saves": total("saves"),
        "goals_conceded": total("goals_conceded"), "bonus": total("bonus"),
        "xgc": total("expected_goals_conceded"),
        "xg": total("expected_goals"), "xa": total("expected_assists"),
        "dc_actions": total("defensive_contribution") if position != 1 else None,
    }
    if position == 1 and all(integer(r.get("saves")) is not None for r in records):
        result["save_points"] = sum(r["saves"] // 3 for r in records)
    elif position in (2, 3, 4) and all(integer(r.get("defensive_contribution")) is not None for r in records):
        # Official 2026/27 rules: +2 points per MATCH at 10 CBIT (DEF) or
        # 12 CBIRT (MID/FWD), not +2 per multiple; GK receives no DC points.
        threshold = 10 if position == 2 else 12
        result["dc_points"] = sum(2 if r["defensive_contribution"] >= threshold else 0 for r in records)
    return result


def position_stats(player: dict[str, Any], recent: dict[str, Any]) -> tuple[str, str]:
    """Each statistic is either explicitly season or last three COMPLETED rounds."""
    pos = int(player.get("element_type") or 0)
    if pos == 1:
        season = f"SZN: {display(player.get('saves'))} saves · {display(player.get('clean_sheets'))} CS"
        last3 = f"L3: {display(recent.get('save_points'))} save pts · {display(recent.get('xgc'), 1)} xGC"
    elif pos == 2:
        season = f"SZN: {display(player.get('defensive_contribution'))} DC acts · {display(player.get('clean_sheets'))} CS"
        last3 = f"L3: {display(recent.get('dc_points'))} DC pts · {display(recent.get('points'))} FPL pts"
    elif pos == 3:
        season = f"SZN: {display(player.get('expected_goals'), 1)} xG · {display(player.get('expected_assists'), 1)} xA"
        last3 = f"L3: {display(recent.get('points'))} pts · {display(recent.get('dc_actions'))} DC acts"
    else:
        season = f"SZN: {display(player.get('expected_goals'), 1)} xG · {display(player.get('expected_assists'), 1)} xA"
        last3 = f"L3: {display(recent.get('goals'))} G · {display(recent.get('assists'))} A"
    return season, last3


def risk(player: dict[str, Any], fixtures: list[tuple], status: str) -> str:
    if not fixtures:
        return "BLANK GW: no scheduled fixture."
    chance = integer(player.get("chance_of_playing_next_round"))
    if status != "a":
        note = str(player.get("news") or "").strip()
        return (f"FPL status {status.upper()}: {note[:75]}" if note else f"FPL status {status.upper()}: verify availability.")
    if chance is not None and chance < 100:
        return f"FPL playing chance: {chance}%; check team news."
    return "Verify starting XI; one-GW transfers can cost points."


def _average_fdr(fixtures: list[tuple]) -> float | None:
    values = [row[2] for row in fixtures if isinstance(row[2], int) and 1 <= row[2] <= 5]
    return sum(values) / len(values) if len(values) == len(fixtures) and values else None


def _evidence(player: dict[str, Any], fixtures: list[tuple], kind: str) -> tuple[bool, str, str]:
    status = str(player.get("status") or "u")
    chance = integer(player.get("chance_of_playing_next_round"))
    form = number(player.get("form"))
    minutes = integer(player.get("minutes"))
    fdr = _average_fdr(fixtures)
    blank = not fixtures
    if kind == "buy":
        strong = (not blank and status == "a" and (chance is None or chance >= 75)
                  and minutes is not None and minutes >= 360 and form is not None and form >= 4
                  and fdr is not None and fdr <= 3.5)
        reason = (f"Good GW fixture (FDR {display(fdr, 1)}); "
                  f"FPL form {display(form, 1)} with {display(minutes)} season mins.")
        if not strong:
            reason = "Popular transfer; minutes, form or GW fixture do not yet justify a firm buy."
        return strong, reason, risk(player, fixtures, status)
    if blank:
        return True, "Confirmed GW blank; no scheduled scoring opportunity.", "HOLD if saving a transfer is worth more."
    if status in {"i", "s", "u"} or (chance is not None and chance < 75):
        return True, "Official FPL availability indicates material non-appearance risk.", risk(player, fixtures, status)
    if minutes is not None and minutes < 180 and (form is None or form <= 3):
        return True, "Low season minutes and limited FPL form.", "HOLD if an imminent start is independently verified."
    if fdr is not None and fdr >= 4 and form is not None and form <= 2.5:
        return True, f"Hard GW fixture (FDR {display(fdr, 1)}) and weak FPL form ({display(form, 1)}).", "HOLD if a free transfer has higher value elsewhere."
    return False, "High transfers out do not, by themselves, make a player a sell.", risk(player, fixtures, status)


def select(snapshot: FplSnapshot, kind: str) -> list[tuple[dict[str, Any], bool, str, str, list[tuple]]]:
    if kind not in {"buy", "sell"}:
        raise ValueError("Expected buy or sell")
    transfer_key = "transfers_in_event" if kind == "buy" else "transfers_out_event"
    eligible = [p for p in snapshot.players if integer(p.get(transfer_key)) is not None
                and integer(p.get("element_type")) in POSITION and integer(p.get("now_cost")) is not None]
    eligible.sort(key=lambda p: (-p[transfer_key], p["id"]))
    strong: list[tuple] = []
    watch: list[tuple] = []
    for player in eligible[:80]:
        matches = snapshot.fixtures_for_gameweek(player)
        good, why, caution = _evidence(player, matches, kind)
        row = (player, good, why, caution, matches)
        (strong if good else watch).append(row)
    # Prefer evidence over popularity, while still starting from the official
    # most-transferred cohorts. Never claim conditional picks are strong verdicts.
    return (strong[:4] + watch[:max(0, 4 - len(strong))])[:4]


def build(kind: str, snapshot: FplSnapshot, now: datetime, session: requests.Session | None = None):
    """Build Content while preserving the bot's existing five-line + hashtag contract."""
    from .content import Card, Content, _caption
    if kind not in ("buy", "sell"):
        raise ValueError("Unsupported recommendation kind")
    gw = snapshot.gameweek()
    if not gw:
        raise ValueError("No verified next gameweek")
    selections = select(snapshot, kind)
    if len(selections) != 4:
        raise ValueError("Fewer than four players with verified event transfer counts")
    client = session or requests.Session()
    rounds = completed_rounds(snapshot)
    buy_options = [row for row in select(snapshot, "buy") if row[1]] if kind == "sell" else []
    cards = []
    for player, strong, why, caution, fixtures in selections:
        pos = POSITION[int(player["element_type"])]
        history = get_history(int(player["id"]), client)
        recent = recent_summary(history, rounds, int(player["element_type"]))
        season_text, last_three_text = position_stats(player, recent)
        transferred = player.get("transfers_in_event" if kind == "buy" else "transfers_out_event")
        opponent = " · ".join(f"{opp} ({venue}) FDR {fdr if fdr is not None else 'N/A'}"
                              for opp, venue, fdr, _ in fixtures) if fixtures else "BLANK GW"
        replacement = "N/A"
        if kind == "sell" and strong:
            possible = next((r[0] for r in buy_options if r[0]["element_type"] == player["element_type"]
                             and r[0]["id"] != player["id"]), None)
            if possible is not None:
                replacement = f"{snapshot.name(possible)} ({snapshot.price(possible)})"
        set_pieces = [
            f"{label} #{player[field]}" for label, field in (
                ("PEN", "penalties_order"), ("FK", "direct_freekicks_order"),
                ("COR", "corners_and_indirect_freekicks_order"))
            if integer(player.get(field)) is not None and 1 <= player[field] <= 2
        ] if pos in ("MID", "FWD") else []
        metrics = {
            "price": snapshot.price(player),
            "position": pos,
            "ownership": f"{display(player.get('selected_by_percent'), 1)}%",
            "goals_season": display(player.get("goals_scored")),
            "assists_season": display(player.get("assists")),
            "bonus_season": display(player.get("bonus")),
            "clean_sheets_season": display(player.get("clean_sheets")),
            "goals_conceded_season": display(player.get("goals_conceded")),
            "saves_season": display(player.get("saves")),
            "xg_season": display(player.get("expected_goals"), 2),
            "xa_season": display(player.get("expected_assists"), 2),
            "xgc_season": display(player.get("expected_goals_conceded"), 2),
            "dc_actions_season": display(player.get("defensive_contribution")) if pos != "GK" else "N/A",
            "dc_points_last_three_completed_gws": display(recent.get("dc_points")) if pos != "GK" else "N/A",
            "save_points_last_three_completed_gws": display(recent.get("save_points")) if pos == "GK" else "N/A",
            "minutes_last_three_completed_gws": display(recent.get("minutes")),
            "points_last_three_completed_gws": display(recent.get("points")),
            "set_pieces_current_order": " · ".join(set_pieces) if set_pieces else "N/A",
            "form": display(player.get("form"), 1),
            "minutes": display(player.get("minutes")),
            "transfers": display(transferred),
            "transfer_period": "OFFICIAL EVENT-TO-DATE",
            "decision": ("BUY" if kind == "buy" else "SELL") if strong else "WATCHLIST",
            "reason": why,
            "caveat": caution,
            "season_stat": season_text,
            "recent_stat": last_three_text if rounds else "L3: N/A — no confirmed completed GW",
            "fixture": opponent,
            "replacement": replacement,
            "next_gw": str(gw),
        }
        cards.append(Card(
            snapshot.name(player), f"{snapshot.team(player)} · {pos}", metrics["decision"],
            (season_text, last_three_text, opponent, why, caution),
            snapshot.photo_code(player), snapshot.team_code(player), metrics,
            tuple((opp, venue, fdr if fdr is not None else 0, code)
                  for opp, venue, fdr, code in fixtures),
        ))
    noun = "BUYS" if kind == "buy" else "SELLS"
    title = f"GW{gw}: FOUR {noun} TO CONSIDER"
    verb = "buy" if kind == "buy" else "sell"
    count = sum(c.label != "WATCHLIST" for c in cards)
    lead = " & ".join(card.headline for card in cards[:2])
    caption = _caption([
        f"GW{gw}: four {verb} candidates for the NEXT gameweek.",
        f"Featured: {lead}.",
        f"{count} evidence-backed; {4 - count} conditional watchlist.",
        "Official event-to-date transfers, form and GW FDR.",
        "Check final XI; avoid unnecessary points hits.",
    ], gw)
    from zoneinfo import ZoneInfo
    timestamp = snapshot.fetched_at.astimezone(ZoneInfo("America/New_York")).strftime("%d %b %Y · %I:%M %p ET")
    return Content(kind, title, "ONE GAMEWEEK · OFFICIAL EVENT-TO-DATE TRANSFERS",
                   tuple(cards), "NO AUTOMATIC HITS · CHECK TEAM NEWS", caption,
                   timestamp, gw, "Source: Official Fantasy Premier League API")
