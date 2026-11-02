"""Task 1 WHO TO BENCH • WHO TO START: evidence-based generic next-GW watchlist.

No access to any manager's real 15-player squad: decisions are explicitly
comparative examples, NOT personalized bench recommendations or model xPts.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .extra_posts import ExtraPost
from .fpl import FplSnapshot

ET = ZoneInfo("America/New_York")
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
QUOTAS = (1, 1, 2, 1)


def _value(value: object) -> float | None:
    try:
        number = float(value)
        return number if -1000 <= number <= 1000 and number == number else None
    except (TypeError, ValueError):
        return None


def start_bench(snapshot: FplSnapshot, now: datetime) -> ExtraPost:
    gw = snapshot.gameweek()
    if not gw:
        raise RuntimeError("No verified future FPL gameweek")
    groups: dict[int, list[dict]] = {pos: [] for pos in POSITIONS}
    for player in snapshot.players:
        position = player.get("element_type")
        if position not in groups or player.get("status") != "a":
            continue
        minutes = _value(player.get("minutes"))
        if minutes is None or minutes < 270:
            continue
        chance = player.get("chance_of_playing_next_round")
        if isinstance(chance, int) and chance < 75:
            continue
        fixture = snapshot.fixtures_for_gameweek(player, gw)
        if not fixture or not all(isinstance(row[2], int) for row in fixture):
            continue
        if snapshot.photo_code(player) is None or snapshot.team_code(player) is None:
            continue
        form = _value(player.get("form"))
        ppg = _value(player.get("points_per_game"))
        if form is None or ppg is None:
            continue
        avg_fdr = sum(row[2] for row in fixture) / len(fixture)
        # Transparent internal sorting heuristic: NOT independently modeled xPts.
        priority = form + 0.30 * ppg + 1.20 * (4 - avg_fdr)
        opponent = ", ".join(f"{name} ({side})" for name, side, _, _ in fixture)
        groups[position].append({
            "id": player["id"], "name": snapshot.name(player),
            "team": snapshot.team(player), "pos": POSITIONS[position],
            "club_code": snapshot.team_code(player),
            "photo_code": snapshot.photo_code(player),
            "price": snapshot.price(player),
            "opponent": opponent, "fdr": round(avg_fdr, 1),
            "form": round(form, 1), "ppg": round(ppg, 1),
            "minutes": int(minutes), "priority": priority,
            "status": "AVAILABLE", "xpts": None,
        })
    starting: list[dict] = []
    benching: list[dict] = []
    for position, quota in zip(POSITIONS, QUOTAS):
        candidates = sorted(groups[position], key=lambda row: (row["priority"], row["minutes"]), reverse=True)
        if len(candidates) < quota * 2:
            raise RuntimeError(f"Not enough eligible current players for {POSITIONS[position]} start/bench comparison")
        starting.extend(candidates[:quota])
        benching.extend(candidates[-quota:])
    starting.sort(key=lambda row: row["priority"], reverse=True)
    benching.sort(key=lambda row: row["priority"])
    if len(starting) != 5 or len(benching) != 5:
        raise RuntimeError("A five-per-side FPL decision board could not be verified")
    if set(row["id"] for row in starting) & set(row["id"] for row in benching):
        raise RuntimeError("Player cannot appear in start and bench groups")

    hook = f"GW{gw}: start/bench comparison, all positions."
    caption = "\n".join([
        hook,
        f"START WATCH: {starting[0]['name']} • {starting[0]['opponent']}.",
        f"BENCH WATCH: {benching[0]['name']} • {benching[0]['opponent']}.",
        "Official form/PPG/FDR; no verified model xPts.",
        "Use your own squad, lineup news & chip strategy.",
        f"#FPL #GW{gw} #FPLVortex #StartBench",
    ])
    if len(caption) > 280:
        caption = caption.replace(f" • {starting[0]['opponent']}", "").replace(f" • {benching[0]['opponent']}", "")
    timestamp = snapshot.fetched_at.astimezone(ET).strftime("%d %b %Y · %I:%M %p ET")
    return ExtraPost(
        kind="start_bench", title="WHO TO BENCH • WHO TO START",
        kicker="NEXT ONE GAMEWEEK • DATA-LED EXAMPLES, NOT YOUR SQUAD",
        caption=caption, data_at=timestamp, gw=gw,
        footer="Official FPL API • no model xPts claimed",
        start_bench=tuple([dict(row, advice="START") for row in starting]
                          + [dict(row, advice="BENCH") for row in benching]),
    )
