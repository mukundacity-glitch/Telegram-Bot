"""Daily transfer comparison from official FPL player and fixture records."""
from math import isfinite
from statistics import mean

from .autonomous_schedule import ET
from .editorial_inputs import RequiredInput
from .publication_rules import five_gw_fixtures
from .recommendations import completed_rounds, get_history, number

METRICS = (
    ("Points", "total_points"), ("Minutes", "minutes"), ("Goals", "goals_scored"),
    ("Assists", "assists"), ("xG", "expected_goals"), ("xA", "expected_assists"),
    ("Bonus", "bonus"), ("Def. contributions", "defensive_contribution"),
)


def build_radar(slot, snapshot, now, evidence):
    from .autonomous_content import Plan

    gw = snapshot.gameweek()
    rounds = completed_rounds(snapshot, 5)
    if not gw or len(rounds) < 5:
        raise RequiredInput("Five completed FPL gameweeks and a future deadline are required")
    candidates = [
        p for p in snapshot.players
        if p.get("element_type") in (2, 3, 4) and p.get("status") == "a"
        and p.get("web_name") and snapshot.photo_code(p) and snapshot.team_code(p)
        and (number(p.get("minutes")) or 0) >= 180 and (number(p.get("now_cost")) or 0) > 0
    ]
    date = now.astimezone(ET).date()
    order = (3, 4, 2)
    preferred = order[(date - date.replace(month=1, day=1)).days % len(order)]
    candidates.sort(key=lambda p: (
        p["element_type"] != preferred, -(number(p.get("transfers_in_event")) or 0),
        -(number(p.get("form")) or 0), p["id"],
    ))
    verified = []
    for player in candidates[:12]:
        history = sorted(
            (row for row in get_history(player["id"], evidence.session) if row.get("round") in rounds),
            key=lambda row: (row["round"], row.get("fixture", 0)),
        )
        if {row["round"] for row in history} != set(rounds):
            continue
        values = {}
        for label, key in METRICS:
            numbers = [number(row.get(key)) for row in history]
            if all(value is not None and isfinite(value) for value in numbers):
                values[label] = round(sum(numbers), 2)
        if any(label not in values for label, _ in METRICS[:6]) or values["Minutes"] < 180:
            continue
        fixtures = five_gw_fixtures(snapshot, player)
        if not fixtures:
            continue
        for peer, other_values, other_fixtures in verified:
            if (peer["element_type"] == player["element_type"] and peer["team"] != player["team"]
                    and abs(peer["now_cost"] - player["now_cost"]) <= 35):
                shared = [label for label, _ in METRICS if label in values and label in other_values]
                left, right = snapshot.name(peer), snapshot.name(player)
                left_fdr, right_fdr = (
                    [row["fdr"] for row in run if not row["blank"]]
                    for run in (other_fixtures, fixtures)
                )
                fixture_line = (
                    f"Next 5 GW avg FDR {mean(left_fdr):.1f} vs {mean(right_fdr):.1f}. "
                    if left_fdr and right_fdr else ""
                )
                caption = (
                    f"📊 {left} vs {right} | {date:%d %b}\n"
                    f"Last 5 GWs: {other_values['Goals']:.0f}–{values['Goals']:.0f} goals, "
                    f"{other_values['xG']:.2f}–{values['xG']:.2f} xG.\n"
                    f"{fixture_line}Who would you pick?\n"
                    f"#FPL #GW{gw} #FPLVORTEX #FPLCommunity"
                )
                return Plan(slot.task, slot.edition, "FPL VORTEX PLAYER RADAR", caption,
                            gw, [peer, player], [], kind="player_radar", extra={
                                "rounds": sorted(rounds), "metrics": shared,
                                "values": [other_values, values], "fixtures": [other_fixtures, fixtures],
                            })
        verified.append((player, values, fixtures))
    raise RequiredInput("No comparable player pair with verified five-gameweek history")
