"""Next-GW three-midfielder scouting edition; official FPL stats only.

This is a NEW edition in the existing shared workflow, not a new automation.
Expected points are never inferred from FPL's season-long expected-goal fields.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .content import Card, Content
from .fpl import FplSnapshot

ET = ZoneInfo("America/New_York")


def _num(value: object) -> float | None:
    try:
        result = float(value)
        return result if result == result and abs(result) < 10_000 else None
    except (TypeError, ValueError):
        return None


def _shown(value: object, suffix: str = "", digits: int = 2) -> str:
    parsed = _num(value)
    return f"{parsed:.{digits}f}{suffix}" if parsed is not None else "N/A"


def _rank(player: dict, fdr: float) -> float:
    # Deterministic shortlist score, NOT model xPts or a promised return.
    form = _num(player.get("form")) or 0.0
    ppg = _num(player.get("points_per_game")) or 0.0
    mins = _num(player.get("minutes")) or 0.0
    games = _num(player.get("starts")) or 0.0
    return 0.44 * form + 0.36 * ppg + 0.45 * (5 - fdr) + 0.05 * min(mins / 90, 10) + 0.02 * games


def generate_midfielders(snapshot: FplSnapshot, now: datetime) -> Content:
    gw = snapshot.gameweek()
    if not gw:
        raise ValueError("Missing verified next-GW deadline")
    eligible: list[tuple[float, dict, list[tuple[str, str, int | None, int | None]]]] = []
    for p in snapshot.players:
        if p.get("element_type") != 3 or p.get("status") != "a":
            continue
        if (_num(p.get("minutes")) or 0) < 180:
            continue
        if isinstance(p.get("chance_of_playing_next_round"), int) and p["chance_of_playing_next_round"] < 75:
            continue
        fixtures = snapshot.fixtures_for_gameweek(p, gw)
        if not fixtures or any(not isinstance(item[2], int) for item in fixtures):
            continue
        if snapshot.photo_code(p) is None or snapshot.team_code(p) is None:
            continue
        difficulty = sum(item[2] for item in fixtures if item[2] is not None) / len(fixtures)
        eligible.append((_rank(p, difficulty), p, fixtures))
    eligible.sort(key=lambda item: (item[0], int(item[1].get("total_points") or 0),
                                   -int(item[1].get("id") or 0)), reverse=True)
    if len(eligible) < 3:
        raise RuntimeError("Fewer than three eligible current-club midfielders; refusing invented picks")

    cards: list[Card] = []
    roles = ("PRIMARY MIDFIELD PICK", "STRONG ALTERNATIVE", "THIRD OPTION")
    for rank, (_, player, fixtures) in enumerate(eligible[:3]):
        opponent = ", ".join(f"{opp} ({side}) FDR {fdr}" for opp, side, fdr, _ in fixtures)
        xg = _num(player.get("expected_goals"))
        xa = _num(player.get("expected_assists"))
        form = _shown(player.get("form"), digits=1)
        ownership = _shown(player.get("selected_by_percent"), "%", 1)
        if "N/A" in (form, ownership):
            raise RuntimeError("Mandatory form or ownership missing")
        attacks = " • ".join(
            f"{label} {value:.2f}" for label, value in (("xG", xg), ("xA", xa))
            if value is not None)
        fields = [f"{snapshot.price(player)} • {ownership} owned",
                  f"NEXT: {opponent}",
                  f"FORM {form}" + (f" • {attacks}" if attacks else ""),
                  "HOLD/START only after checking current minutes risk"]
        metrics = {"price": snapshot.price(player), "ownership": ownership,
                   "form": form, "minutes": int(player.get("minutes") or 0),
                   "role": roles[rank]}
        if xg is not None:
            metrics["xg"] = f"{xg:.2f}"
        if xa is not None:
            metrics["xa"] = f"{xa:.2f}"
        cards.append(Card(snapshot.name(player), snapshot.team(player), roles[rank],
                          tuple(fields), snapshot.photo_code(player),
                          snapshot.team_code(player), metrics=metrics,
                          fixtures=tuple((opp, side, int(fdr), code)
                                         for opp, side, fdr, code in fixtures)))
    names = ", ".join(card.headline for card in cards)
    stamp = snapshot.fetched_at.astimezone(ET).strftime("%d %b %Y • %I:%M %p ET")
    lines = [
        f"GW{gw}: three eligible midfielders for the next fixture.",
        f"Watch: {names}.",
        "FPL form, PPG and minutes; xG/xA are season totals, not next-GW xPts.",
        "START/HOLD based on fixture and verified availability.",
        f"#FPL #GW{gw} #FPLVortex #Midfield",
    ]
    caption = "\n".join(lines)
    if len(caption) > 280:
        lines[1] = f"Primary mid: {cards[0].headline}."
        caption = "\n".join(lines)
    if len(caption.splitlines()) != 5 or caption.splitlines()[-1].count("#") != 4:
        raise RuntimeError("Midfielder caption must be five lines with four hashtags")
    return Content("midfielders", "TOP 3 MIDFIELDERS", "ONE UPCOMING GW • OFFICIAL DATA",
                   tuple(cards), "SCOUTING RANK • NOT PROJECTED FPL POINTS",
                   caption, stamp, gw, "Official Fantasy Premier League API")
