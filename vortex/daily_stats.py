"""Build the daily stats board directly from a fresh official FPL snapshot."""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Callable

from .content import Card, Content
from .fpl import FplSnapshot
from .schedule import TIMEZONE

KIND = "daily_stats"
TITLE = "10 SURPRISING FPL STATS"


def number(row: dict[str, Any], field: str) -> float | None:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def difference(row, left, right):
    a, b = number(row, left), number(row, right)
    return a - b if a is not None and b is not None else None


def build(snapshot: FplSnapshot, now: datetime) -> Content:
    gw = snapshot.gameweek()
    if not gw:
        raise ValueError("No verified upcoming gameweek for the daily stats board")
    players = [p for p in snapshot.players if p.get("web_name") and snapshot.team_code(p)]
    cards: list[Card] = []

    def leader(label: str, score: Callable, detail: Callable, *,
               decimals=0, suffix="", signed=False, eligible=lambda p: True):
        ranked = []
        for player in players:
            if eligible(player) and (value := score(player)) is not None and value > 0:
                ranked.append((value, player))
        if not ranked:
            return
        value, player = max(ranked, key=lambda item: (item[0], -item[1]["id"]))
        display = format(value, f"{'+' if signed else ''},.{decimals}f") + suffix
        cards.append(Card(snapshot.name(player), snapshot.team(player), label,
                          (display, detail(player)), snapshot.photo_code(player),
                          snapshot.team_code(player), {"value": display}))

    def field(key):
        return lambda p: number(p, key)

    def count(p, key, label):
        value = number(p, key)
        return f"{value:.0f} {label}" if value is not None else ""

    def season(p):
        return f"{snapshot.team(p)} • Season total"

    def differential(p):
        ownership = number(p, "selected_by_percent")
        return ownership is not None and 0 <= ownership < 10

    def outfield(p):
        return p.get("element_type") in (2, 3, 4)

    leader("Highest xG", field("expected_goals"), lambda p: count(p, "goals_scored", "goals"), decimals=2)
    leader("Most above xG", lambda p: difference(p, "goals_scored", "expected_goals"),
           lambda p: f"{p['goals_scored']} goals / {float(p['expected_goals']):.2f} xG",
           decimals=2, signed=True)
    leader("Most below xG", lambda p: difference(p, "expected_goals", "goals_scored"),
           lambda p: f"{p['goals_scored']} goals / {float(p['expected_goals']):.2f} xG", decimals=2, suffix=" short")
    leader("Highest xA", field("expected_assists"), lambda p: count(p, "assists", "FPL assists"), decimals=2)
    leader("Keeper clean sheets", field("clean_sheets"), season,
           eligible=lambda p: p.get("element_type") == 1)
    leader("Net transfers in", lambda p: difference(p, "transfers_in_event", "transfers_out_event"),
           lambda p: f"GW{gw} transfer window", signed=True)
    leader("Net transfers out", lambda p: difference(p, "transfers_out_event", "transfers_in_event"),
           lambda p: f"GW{gw} transfer window", signed=True)
    leader("Top points scorer", field("total_points"), season, suffix=" pts")
    leader("Differential points", field("total_points"),
           lambda p: f"{float(p['selected_by_percent']):.1f}% owned", suffix=" pts",
           eligible=differential)
    leader("Most bonus points", field("bonus"), season)
    leader("Most saves", field("saves"), season, eligible=lambda p: p.get("element_type") == 1)
    leader("Most def. contributions", field("defensive_contribution"), season, eligible=outfield)
    leader("Highest ownership", field("selected_by_percent"), lambda p: count(p, "total_points", "FPL pts"),
           decimals=1, suffix="%")
    leader("Most goals", field("goals_scored"), season)
    leader("Most FPL assists", field("assists"), season)
    leader("Most minutes", field("minutes"), season)
    leader("Most points per £m", lambda p: (
        float(p["total_points"]) * 10 / float(p["now_cost"])
        if number(p, "total_points") is not None and (number(p, "now_cost") or 0) > 0 else None
    ), snapshot.price, decimals=1)

    if len(cards) < 10:
        raise ValueError("Official FPL data has fewer than ten publishable stats")
    date = now.astimezone(TIMEZONE).date()
    # Keep xG, finishing and defending near the top when available. Rotate
    # the remaining categories during quiet days between fixtures.
    featured, rotating = cards[:5], cards[5:]
    offset = date.toordinal() % len(rotating)
    selected = tuple(featured + (rotating[offset:] + rotating[:offset])[:5])
    highlights = (*selected[:2], *selected[5:7])
    caption = "\n".join([
        f"10 FPL STATS THAT WILL SHOCK YOU! 📊 | {date:%d %b}",
        *(f"{emoji} {card.label} — {card.headline} ({card.fields[0]})"
          for emoji, card in zip(("👀", "🔥", "🧤", "📉"), highlights)),
        "👇 Which stat surprised you?",
        f"#FPL #FPLCommunity #GW{gw} #FPLVORTEX #FantasyPremierLeague",
    ])
    return Content(KIND, TITLE, f"GW{gw} • {date:%d %b %Y}", selected, "", caption,
                   snapshot.fetched_at.isoformat(), gw, "")
