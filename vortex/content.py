"""Produce fact-grounded data cards and five-line X captions."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from .fpl import (
    FplSnapshot,
    choose_captains,
    choose_comparison,
    choose_creators,
    confirmed_price_changes,
)


@dataclass(frozen=True)
class Card:
    headline: str
    subtitle: str
    label: str
    fields: tuple[str, ...]
    photo_code: int | None = None
    team_code: int | None = None
    metrics: dict[str, int | str] | None = None
    fixtures: tuple[tuple[str, str, int, int | None], ...] = ()


@dataclass(frozen=True)
class Content:
    kind: str
    title: str
    kicker: str
    cards: tuple[Card, ...]
    verdict: str
    caption: str
    data_at: str
    gw: int
    footer: str


def _card(snapshot: FplSnapshot, player: dict[str, Any], label: str, extra: list[str] | None = None) -> Card:
    stats = [
        f"{snapshot.price(player)}  |  {snapshot.team(player)}",
        f"{int(player.get('total_points') or 0)} pts  |  {player.get('form', '0')} form",
        f"{int(player.get('goals_scored') or 0)} G  /  {int(player.get('assists') or 0)} A",
    ]
    if extra:
        stats.extend(extra)
    upcoming: list[tuple[str, str, int, int | None]] = []
    for label_text, difficulty in snapshot.fixtures_for(player, 3):
        opponent, _, side = label_text.partition(" (")
        venue = side.rstrip(")") if side else "?"
        opponent_code = next(
            (int(team["code"]) for team in snapshot.teams.values()
             if team.get("short_name") == opponent and isinstance(team.get("code"), int)),
            None,
        )
        upcoming.append((opponent, venue, difficulty, opponent_code))
    metrics: dict[str, int | str] = {
        "price": snapshot.price(player),
        "total_points": int(player.get("total_points") or 0),
        "form": str(player.get("form") or "0"),
        "goals": int(player.get("goals_scored") or 0),
        "assists": int(player.get("assists") or 0),
        "minutes": int(player.get("minutes") or 0),
        "clean_sheets": int(player.get("clean_sheets") or 0),
        "bonus": int(player.get("bonus") or 0),
    }
    return Card(
        snapshot.name(player), snapshot.team(player), label, tuple(stats),
        snapshot.photo_code(player), snapshot.team_code(player), metrics, tuple(upcoming),
    )


def _card_with_metrics(base: Card, fields: tuple[str, ...], extra_metrics: dict[str, int | str]) -> Card:
    return replace(base, fields=fields, metrics={**(base.metrics or {}), **extra_metrics})


def _caption(lines: list[str], gw: int) -> str:
    if len(lines) != 5:
        raise ValueError("Exactly five X caption lines required")
    sanitized = [line.replace("\n", " ").replace("#", "").strip() for line in lines]
    hashtags = f"#FPL #GW{gw} #FPLVortex #PremierLeague"
    # Keep the action and optional engagement prompt on one line; hashtags
    # occupy line five in every publication path.
    result = "\n".join([*sanitized[:3], " ".join(sanitized[3:]), hashtags])
    if len(result) > 280:
        raise ValueError(f"X description too long ({len(result)} characters)")
    if any(not line for line in sanitized):
        raise ValueError("X caption contains an empty line")
    return result


def generate(kind: str, snapshot: FplSnapshot, now: datetime, previous_prices: dict[str, Any]) -> Content:
    if kind == "daily_stats":
        from .daily_stats import build
        return build(snapshot, now)
    if kind == "elite":
        from .fixture_guide import build
        return build(snapshot)
    if kind in ("projections", "team_analysis", "transfer_suggestions", "start_bench"):
        from .extra_posts import generate_extra
        return generate_extra(kind, snapshot, now)
    if kind == "midfielders":
        from .midfielders import generate_midfielders
        return generate_midfielders(snapshot, now)
    if kind in ("buy", "sell", "review"):
        from .recommendations import build
        return build(kind, snapshot, now)
    gw = snapshot.gameweek()
    if not gw:
        raise ValueError("No verified upcoming FPL deadline; refusing a stale GW label")
    from zoneinfo import ZoneInfo
    timestamp = snapshot.fetched_at.astimezone(ZoneInfo("America/New_York")).strftime("%d %b %Y • %I:%M %p ET")
    source = "Source: Official Fantasy Premier League API"
    cards: list[Card]
    if kind == "comparison":
        first, second = choose_comparison(snapshot)
        cards = [_card(snapshot, p, "PLAYER COMPARISON", ["NEXT: " + " • ".join(f"{opp} ({fdr})" for opp, fdr in snapshot.fixtures_for(p, 3))]) for p in (first, second)]
        title, kicker = "THE FPL DECISION ROOM", "8:00 AM • PLAYER VS PLAYER"
        verdict = f"FORM EDGE: {snapshot.name(first)} • ACCOUNT FOR FIXTURES"
        lines = [f"FPL GW{gw}: player comparison showdown.", f"{snapshot.name(first)} vs {snapshot.name(second)}.", f"Prices: {snapshot.price(first)} vs {snapshot.price(second)}.", "Compare form, minutes and fixture difficulty.", "Who makes your team?"]
    elif kind == "prices":
        changes = confirmed_price_changes(snapshot, previous_prices)
        valid_baseline = isinstance(previous_prices.get("prices"), dict)
        cards = [replace(
            _card(snapshot, player, "CONFIRMED PRICE MOVE"),
            fields=(f"£{old / 10:.1f}m → £{new / 10:.1f}m", "Official snapshots compared"),
            metrics={**_card(snapshot, player, "CONFIRMED PRICE MOVE").metrics,
                     "before": f"£{old / 10:.1f}m", "after": f"£{new / 10:.1f}m",
                     "change": f"{'+' if new > old else '-'}£{abs(new-old) / 10:.1f}m"},
        ) for player, old, new in changes[:4]]
        if not cards:
            label = "BASELINE ESTABLISHED" if not valid_baseline else "NO CHANGES DETECTED"
            cards = [Card(label, "Official FPL", "PRICE MONITOR", ("Next run compares official snapshots.", "Predictions are never presented as confirmed."))]
        title, kicker = "FPL PRICE MOVEMENTS", "12:00 PM • VERIFIED BEFORE / AFTER"
        verdict = "OFFICIAL FPL PRICES • SNAPSHOT COMPARISON"
        count = len(changes)
        if changes:
            moves = [
                f"{snapshot.name(player)}: £{old / 10:.1f}m to £{new / 10:.1f}m; MONITOR."
                for player, old, new in changes[:2]
            ]
            while len(moves) < 2:
                moves.append("Check your player selling value before moving.")
            lines = [f"FPL GW{gw}: official price moves.", *moves,
                     f"{count} verified changes vs prior snapshot.", "Price alone is not a reason to sell."]
        else:
            lines = [f"FPL GW{gw}: official price monitor.",
                     "Today's baseline saved." if not valid_baseline else "No new confirmed moves.",
                     "Compared FPL player cost snapshots.", "HOLD: avoid speculative transfers.",
                     "Check your selling value before switching."]
    elif kind == "transfer":
        lead, other = choose_comparison(snapshot)
        cards = [_card(snapshot, p, label, ["NEXT: " + " • ".join(opp for opp, _ in snapshot.fixtures_for(p, 3))]) for label, p in (("TRANSFER TARGET", lead), ("ALTERNATIVE", other))]
        title, kicker = "TRANSFER DECISION", "2:00 PM • FREE TRANSFER INTELLIGENCE"
        verdict = "CONSIDER • DO NOT TAKE A HIT ON THIS ALONE"
        lines = [f"FPL GW{gw}: transfer decision desk.", f"MONITOR: {snapshot.name(lead)} ({snapshot.price(lead)}).", f"ALTERNATIVE: {snapshot.name(other)} ({snapshot.price(other)}).", "Confirm starts and next three fixtures first.", "BUY only if it fits your team and budget."]
    elif kind == "captaincy":
        ranked = choose_captains(snapshot)
        cards = [_card(snapshot, p, f"CAPTAIN OPTION {i + 1}", ["NEXT: " + (snapshot.fixtures_for(p, 1)[0][0] if snapshot.fixtures_for(p, 1) else "TBD")]) for i, p in enumerate(ranked)]
        title, kicker = "CAPTAINCY SHOWDOWN", "4:00 PM • DAILY CAPTAINCY ANALYSIS"
        verdict = f"CAPTAIN: {snapshot.name(ranked[0])} • VC: {snapshot.name(ranked[1])}"
        lines = [f"FPL GW{gw}: captaincy showdown.", f"Top pick: {snapshot.name(ranked[0])}.", f"Vice-captain: {snapshot.name(ranked[1])}.", "Balance form, fixtures and minutes risk.", "Who gets your armband?"]
    elif kind == "evening":
        creators = choose_creators(snapshot)
        cards = [replace(
            _card(snapshot, player, "ASSISTS / CREATOR WATCH",
                  [f"{int(player.get('assists') or 0)} assists", f"xA: {player.get('expected_assists', 'N/A')}"]),
            metrics={**_card(snapshot, player, "ASSISTS / CREATOR WATCH").metrics,
                     "xa": str(player.get("expected_assists") or "N/A")},
        ) for player in creators]
        title, kicker = "EVENING CREATOR WATCH", "8:00 PM • ASSISTS & NEXT GW TARGETS"
        verdict = "CREATOR METRICS • NOT A BREAKING NEWS CLAIM"
        top = snapshot.name(creators[0]) if creators else "None"
        lines = [f"FPL GW{gw}: evening assists watch.", f"Featured creator: {top}.", "Check assists, xA and FPL form together.", "Next opponent and minutes still matter.", "Who leads your assists shortlist?"]
    else:
        raise ValueError(f"Unsupported content kind: {kind}")
    caption = _caption(lines, gw)
    return Content(kind, title, kicker, tuple(cards), verdict, caption, timestamp, gw, source)
