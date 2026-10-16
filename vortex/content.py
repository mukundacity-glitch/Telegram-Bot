"""Produce fact-grounded data cards and six-line X captions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .fpl import (
    FplSnapshot,
    choose_captains,
    choose_comparison,
    choose_creators,
    choose_elite,
    choose_news,
    confirmed_price_changes,
    latest_completed_gw,
    previous_gw_top_players,
)


@dataclass(frozen=True)
class Card:
    headline: str
    subtitle: str
    label: str
    fields: tuple[str, ...]
    photo_code: int | None = None
    team_code: int | None = None


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
    return Card(snapshot.name(player), snapshot.team(player), label, tuple(stats), snapshot.photo_code(player), snapshot.team_code(player))


def _caption(lines: list[str], gw: int) -> str:
    if len(lines) != 5:
        raise ValueError("Exactly five X caption lines required")
    sanitized = [line.replace("\n", " ").replace("#", "").strip() for line in lines]
    hashtags = f"#FPL #GW{gw} #FPLVortex"
    result = "\n".join([*sanitized, hashtags])
    if len(result) > 280:
        raise ValueError(f"X description too long ({len(result)} characters)")
    if any(not line for line in sanitized):
        raise ValueError("X caption contains an empty line")
    return result


def generate(kind: str, snapshot: FplSnapshot, now: datetime, previous_prices: dict[str, Any]) -> Content:
    gw = snapshot.gameweek()
    timestamp = snapshot.fetched_at.strftime("%d %b %Y • %H:%M UTC")
    source = "Source: Official Fantasy Premier League API"
    cards: list[Card]
    if kind == "elite":
        p = choose_elite(snapshot)
        cards = [_card(snapshot, p, "ELITE DIFFERENTIAL", [f"Owned by {p.get('selected_by_percent', 'N/A')}%", " | ".join(f"{opp} FDR{fdr}" for opp, fdr in snapshot.fixtures_for(p, 3))])]
        title, kicker = "ELITE FPL EDGE", "6:30 AM • UNDER-OWNED SCOUT PICK"
        verdict = "DATA-LED DIFFERENTIAL • RECHECK LINEUP"
        lines = [f"FPL GW{gw}: an under-owned player to watch.", f"{snapshot.name(p)} ({snapshot.team(p)}) at {snapshot.price(p)}.", f"{p.get('form', '0')} form; {p.get('selected_by_percent', 'N/A')}% owned.", "Assess fixtures and team news before buying.", "Who is your differential pick?"]
    elif kind == "comparison":
        first, second = choose_comparison(snapshot)
        cards = [_card(snapshot, p, "PLAYER COMPARISON", ["NEXT: " + " • ".join(f"{opp} ({fdr})" for opp, fdr in snapshot.fixtures_for(p, 3))]) for p in (first, second)]
        title, kicker = "THE FPL DECISION ROOM", "8:00 AM • PLAYER VS PLAYER"
        verdict = f"FORM EDGE: {snapshot.name(first)} • ACCOUNT FOR FIXTURES"
        lines = [f"FPL GW{gw}: player comparison showdown.", f"{snapshot.name(first)} vs {snapshot.name(second)}.", f"Prices: {snapshot.price(first)} vs {snapshot.price(second)}.", "Compare form, minutes and fixture difficulty.", "Who makes your team?"]
    elif kind == "news":
        news = choose_news(snapshot, now)
        cards = [Card(snapshot.name(p), snapshot.team(p), "FPL STATUS UPDATE", (snapshot.price(p), str(p.get("news") or "")[:120], "FPL flag: " + str(p.get("status") or "unknown")), snapshot.photo_code(p), snapshot.team_code(p)) for p in news[:3]]
        if not cards:
            cards = [Card("NO NEW DATED FPL FLAGS", "Official FPL", "VERIFIED STATUS", ("No fresh changes in the last 72 hours.", "No injury story has been invented."))]
        title, kicker = "FPL NEWS BOARD", "10:00 AM • OFFICIAL FPL STATUS"
        verdict = "FPL FLAGS ARE NOT MEDICAL CONFIRMATIONS"
        lines = [f"FPL GW{gw}: morning status board.", "Latest dated FPL availability notes checked.", f"{len(news)} relevant player flags in the last 72h.", "Verify club team news before final transfers.", "Which fitness update matters to your squad?"]
    elif kind == "prices":
        changes = confirmed_price_changes(snapshot, previous_prices)
        valid_baseline = isinstance(previous_prices.get("prices"), dict)
        cards = [Card(snapshot.name(p), snapshot.team(p), "CONFIRMED PRICE MOVE", (f"£{old / 10:.1f}m → £{new / 10:.1f}m", f"{'▲ RISE' if new > old else '▼ FALL'} £{abs(new-old) / 10:.1f}m", "Official snapshots compared"), snapshot.photo_code(p), snapshot.team_code(p)) for p, old, new in changes[:4]]
        if not cards:
            label = "BASELINE ESTABLISHED" if not valid_baseline else "NO CHANGES DETECTED"
            cards = [Card(label, "Official FPL", "PRICE MONITOR", ("Next run compares official snapshots.", "Predictions are never presented as confirmed."))]
        title, kicker = "FPL PRICE MOVEMENTS", "12:00 PM • VERIFIED BEFORE / AFTER"
        verdict = "OFFICIAL FPL PRICES • SNAPSHOT COMPARISON"
        count = len(changes)
        lines = [f"FPL GW{gw}: confirmed price tracker.", f"{count} official price movements detected." if valid_baseline else "Today's official price baseline is saved.", "Previous vs current FPL prices compared.", "Review selling value before any transfer.", "Which price move affects your squad?"]
    elif kind == "transfer":
        lead, other = choose_comparison(snapshot)
        cards = [_card(snapshot, p, label, ["NEXT: " + " • ".join(opp for opp, _ in snapshot.fixtures_for(p, 3))]) for label, p in (("TRANSFER TARGET", lead), ("ALTERNATIVE", other))]
        title, kicker = "TRANSFER DECISION", "2:00 PM • FREE TRANSFER INTELLIGENCE"
        verdict = "CONSIDER • DO NOT TAKE A HIT ON THIS ALONE"
        lines = [f"FPL GW{gw}: transfer decision desk.", f"{snapshot.name(lead)} or {snapshot.name(other)}?", f"{snapshot.price(lead)} vs {snapshot.price(other)} today.", "Compare fixtures, fitness and free transfers.", "Who is your priority transfer?"]
    elif kind == "captaincy":
        ranked = choose_captains(snapshot)
        cards = [_card(snapshot, p, f"CAPTAIN OPTION {i + 1}", ["NEXT: " + (snapshot.fixtures_for(p, 1)[0][0] if snapshot.fixtures_for(p, 1) else "TBD")]) for i, p in enumerate(ranked)]
        title, kicker = "CAPTAINCY SHOWDOWN", "4:00 PM • PRE-DEADLINE ANALYSIS"
        verdict = f"CAPTAIN: {snapshot.name(ranked[0])} • VC: {snapshot.name(ranked[1])}"
        lines = [f"FPL GW{gw}: captaincy showdown.", f"Top pick: {snapshot.name(ranked[0])}.", f"Vice-captain: {snapshot.name(ranked[1])}.", "Balance form, fixtures and minutes risk.", "Who gets your armband?"]
    elif kind == "review":
        highlights = previous_gw_top_players(snapshot)
        prev = latest_completed_gw(snapshot)
        cards = [Card(snapshot.name(p), snapshot.team(p), f"GW{prev} RETURN", (f"{points} FPL points", f"Current price: {snapshot.price(p)}", f"Season total: {p.get('total_points', 0)}"), snapshot.photo_code(p), snapshot.team_code(p)) for p, points in highlights[:4]]
        if not cards:
            cards = [Card("NO COMPLETED GW YET", "Official FPL", "REVIEW STATUS", ("Upcoming GW watch only.", "Do not treat unfinished fixtures as final."))]
        title, kicker = f"GW{prev or '–'} REVIEW → GW{gw} WATCH", "5:30 PM • VERIFIED COMPLETED GAMEWEEK"
        verdict = "PREVIOUS RESULTS + NEXT FIXTURE TARGETS"
        leader = snapshot.name(highlights[0][0]) if highlights else "No completed GW"
        lines = [f"FPL GW{prev or 0} review → GW{gw} watch.", f"Top completed-GW return: {leader}.", "Review official points and upcoming fixtures.", "Avoid chasing points without checking minutes.", "Who is your next target?"]
    elif kind == "evening":
        creators = choose_creators(snapshot)
        cards = [_card(snapshot, p, "ASSISTS / CREATOR WATCH", [f"{int(p.get('assists') or 0)} assists", f"xA: {p.get('expected_assists', 'N/A')}"]) for p in creators]
        title, kicker = "EVENING CREATOR WATCH", "8:00 PM • ASSISTS & NEXT GW TARGETS"
        verdict = "CREATOR METRICS • NOT A BREAKING NEWS CLAIM"
        top = snapshot.name(creators[0]) if creators else "None"
        lines = [f"FPL GW{gw}: evening assists watch.", f"Featured creator: {top}.", "Check assists, xA and FPL form together.", "Next opponent and minutes still matter.", "Who leads your assists shortlist?"]
    else:
        raise ValueError(f"Unsupported content kind: {kind}")
    caption = _caption(lines, gw)
    return Content(kind, title, kicker, tuple(cards), verdict, caption, timestamp, gw, source)