"""Four former ChatGPT task streams, scheduled inside the existing GitHub job.

There are no additional GitHub workflows or ChatGPT tasks. Each edition is
defined by a season-aware ET slot, not a hard-coded player or gameweek.
The task bridge is opt-in until BOTH actual platform receipts are verified.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from zoneinfo import ZoneInfo
from typing import Any

from .content import Card, Content, generate
from .fpl import FplSnapshot, choose_news, choose_comparison, score
from .extra_posts import generate_extra
from .recommendations import completed_rounds
from .publication_rules import player_metrics, five_gw_fixtures

ET = ZoneInfo("America/New_York")
PRESS_START = date(2026, 10, 30)


@dataclass(frozen=True)
class Edition:
    task: str
    label: str
    hour: int
    minute: int
    kind: str


# These are the four original ChatGPT tasks and their exact local-time slots.
# Overlapping posts already served by the legacy editions are reassigned as
# delivery-backup candidates, never deliberately broadcast a second time.
EDITIONS: tuple[Edition, ...] = (
    Edition("task1", "availability-transfer-decisions", 6, 0, "availability"),
    Edition("three_daily", "fixture-targets", 7, 30, "fixture_targets"),
    Edition("task2", "all20-projected-goals", 8, 0, "projections"),
    Edition("task1", "form-minutes-targets", 10, 0, "form_targets"),
    Edition("task2", "three-midfielders", 10, 45, "midfielders"),
    Edition("task2", "team-attack-defence", 12, 0, "team_analysis"),
    Edition("three_daily", "transfer-squad-structure", 12, 30, "squad_structure"),
    Edition("press_news", "verified-press-availability", 14, 0, "press_availability"),
    Edition("task1", "captain-differential", 15, 0, "captain_differential"),
    Edition("task2", "four-position-transfers", 15, 45, "transfer_suggestions"),
    Edition("task1", "transfer-market-team-news", 19, 0, "transfer_market"),
    Edition("three_daily", "next-gw-evening-decisions", 19, 30, "next_gw_decisions"),
)
CRONS = {f"{e.minute} {e.hour} * * *": e for e in EDITIONS}

# An existing original post is the primary source at these slots or earlier
# in the same day. Reusing the canonical topic receipt is not a fresh post.
COVERED_BY_ORIGINAL = {
    "midfielders": "midfielders",
    "projections": "projections",
    "team_analysis": "team_analysis",
    "transfer_suggestions": "transfer_suggestions",
}


def due_editions(now: datetime, cron: str | None = None) -> tuple[Edition, ...]:
    local = now.astimezone(ET)
    if cron:
        candidate = CRONS.get(cron.strip())
        selected = (candidate,) if candidate else ()
    else:
        selected = tuple(e for e in EDITIONS
                         if (e.hour, e.minute) == (local.hour, local.minute))
    if any(e.task == "press_news" for e in selected):
        days = (local.date() - PRESS_START).days
        selected = tuple(e for e in selected
                         if e.task != "press_news" or (days >= 0 and days % 3 == 0))
    return selected


def _valid_current(snapshot: FplSnapshot, player: dict, *, include_flags: bool = False) -> bool:
    if not include_flags and player.get("status") != "a":
        return False
    if not isinstance(player.get("id"), int) or not snapshot.photo_code(player) or not snapshot.team_code(player):
        return False
    if not snapshot.fixtures_for_gameweek(player, snapshot.gameweek()):
        return False
    return True


def _evidence(snapshot: FplSnapshot, player: dict) -> str:
    """Actual FPL values, not next-fixture xPts or inferred fit percentages."""
    fixture = snapshot.fixtures_for_gameweek(player, snapshot.gameweek())
    home = ", ".join(f"{opp}({venue}) FDR{fdr}" for opp, venue, fdr, _ in fixture if fdr)
    return f"{snapshot.price(player)} • {home} • form {player.get('form')}"


def _make_cards(snapshot: FplSnapshot, players: list[dict], labels: list[str]) -> tuple[Card, ...]:
    if not 1 <= len(players) <= 3 or len(players) != len(labels):
        raise ValueError("Decision edition supports one to three real players")
    result = []
    for player, label in zip(players, labels):
        if not _valid_current(snapshot, player, include_flags=True):
            raise RuntimeError("Player missing current real photograph, crest or fixture")
        if any(player.get(key) is None for key in ("now_cost", "selected_by_percent", "form", "minutes")):
            raise RuntimeError("Missing verified player price, ownership, form or minutes")
        details = [
            f"{snapshot.price(player)} • {snapshot.team(player)} • {int(player.get('minutes') or 0)} min",
            f"OWN {player['selected_by_percent']}% • FORM {player.get('form')}",
        ]
        if player.get("status") != "a":
            details.append("CHECK TEAM NEWS • PLAYER FLAG")
        profile = player_metrics(snapshot, player)
        future = five_gw_fixtures(snapshot, player)
        signature = ";".join(
            f"{row['gw']}:{row['fixture_id']}:{row['opponent']}:{row['venue']}:{row['fdr']}"
            if not row["blank"] else f"{row['gw']}:BLANK"
            for row in future)
        # Position-specific real FPL profile metrics and five-GW fixture
        # signatures are part of the *editorial version*. Updated statistics
        # require a changed post, while new retrieval timestamps alone do not.
        profile["FIVE GW FIXTURE VERSION"] = signature
        result.append(Card(snapshot.name(player), snapshot.team(player), label,
                           tuple(details), snapshot.photo_code(player), snapshot.team_code(player),
                           metrics=profile))
    return tuple(result)


def _report(gw: int, hook: str, factual: str, action: str, topic: str) -> str:
    lines = [
        f"GW{gw}: {hook}.",
        factual,
        "Assess actual minutes, fixtures and latest lineup news.",
        f"{action}; confirm the lineup before deadline.",
        f"#FPL #GW{gw} #FPLVortex #{topic}",
    ]
    caption = "\n".join(lines)
    if len(caption) > 1024:
        raise ValueError("Caption too long for shared image delivery")
    return caption


def generate_edition(edition: Edition, snapshot: FplSnapshot, now: datetime,
                     prices: dict[str, Any] | None = None) -> Content | Any:
    gw = snapshot.gameweek()
    if not gw:
        raise RuntimeError("No verified next FPL gameweek")
    # Task 2's existing categories keep their current correctly-tested
    # model+artwork. Cross-slot receipt guard suppresses repeats from
    # 07:00/11:00/15:00 originals.
    if edition.kind in COVERED_BY_ORIGINAL:
        return generate(edition.kind, snapshot, now, prices or {})

    candidate = [p for p in snapshot.players if _valid_current(snapshot, p)
                 and int(p.get("minutes") or 0) >= 180]
    if not candidate:
        raise RuntimeError("No sourced active player with upcoming verified fixture")
    candidate.sort(key=lambda p: (score(p), int(p.get("total_points") or 0)), reverse=True)
    choices: list[dict]
    labels: list[str]
    heading: str
    action: str
    if edition.kind in ("availability", "press_availability"):
        # Official FPL 72-hour dated status flags only; no invented manager quote.
        # A press-conference source is NOT inferred from FPL status/news.
        flags = [p for p in choose_news(snapshot, now) if _valid_current(snapshot, p, include_flags=True)]
        if not flags:
            raise RuntimeError("No newly verified official player status changes; no duplicate filler post")
        flags.sort(key=lambda p: (p.get("status") == "a", -int(p.get("transfers_out_event") or 0)))
        choices = flags[:3]
        labels = ["MONITOR" if p.get("status") != "a" else "HOLD" for p in choices]
        heading, action = ("AVAILABILITY & TRANSFER DECISIONS"
                           if edition.kind == "availability" else "TEAM NEWS • PLAYER FLAGS"), "MONITOR"
    elif edition.kind in ("form_targets", "fixture_targets", "next_gw_decisions", "squad_structure"):
        if edition.kind == "squad_structure":
            pair = choose_comparison(snapshot)
            choices = list(pair)
            labels = ["HOLD", "MONITOR"]
            heading, action = "TRANSFER & SQUAD STRUCTURE", "HOLD"
        elif edition.kind == "fixture_targets":
            candidates = [
                p for p in candidate if p.get("element_type") in (2, 3, 4)
                and all(isinstance(fdr, int) and 1 <= fdr <= 5
                        for _, _, fdr, _ in snapshot.fixtures_for_gameweek(p, gw))
            ]
            choices = sorted(candidates, key=lambda p: (
                min(fdr for _, _, fdr, _ in snapshot.fixtures_for_gameweek(p, gw)
                    if isinstance(fdr, int)), -score(p)))[:3]
            labels = ["START" if p.get("status") == "a" else "MONITOR" for p in choices]
            heading, action = "NEXT GAMEWEEK • FIXTURE TARGETS", "START"
        else:
            choices = candidate[:3]
            labels = ["BUY", "HOLD", "MONITOR"]
            heading, action = ("FORM, MINUTES & BEST TARGETS"
                               if edition.kind == "form_targets" else "NEXT GW • DECISION"), "HOLD"
    elif edition.kind == "captain_differential":
        available = [p for p in candidate if p.get("element_type") in (3, 4)]
        choices = available[:3]
        labels = ["CAPTAIN", "STRONG ALTERNATIVE", "DIFFERENTIAL"]
        heading, action = "CAPTAINCY & DIFFERENTIAL EDGE", "CAPTAIN"
    elif edition.kind == "transfer_market":
        transfers = [p for p in snapshot.players if
                     _valid_current(snapshot, p, include_flags=True)
                     and isinstance(p.get("transfers_out_event"), int)
                     and isinstance(p.get("transfers_in_event"), int)]
        transfers.sort(key=lambda p: p["transfers_out_event"], reverse=True)
        choices = transfers[:3]
        labels = ["MONITOR" if p.get("status") != "a" else "HOLD" for p in choices]
        heading, action = "TRANSFER MARKET & TEAM NEWS", "MONITOR"
    else:
        raise ValueError("Unknown former ChatGPT task edition")
    if not 1 <= len(choices) <= 3:
        raise RuntimeError("Insufficient verified current options for edition")
    labels = labels[:len(choices)]
    cards = _make_cards(snapshot, choices, labels)
    lead = choices[0]
    evidence = _evidence(snapshot, lead)
    # All real source audit details remain in internal logs; never in pixels.
    hashtags = {"task1": "FPLTips", "task2": "FPLStats",
                "three_daily": "FPLTransfers", "press_news": "TeamNews"}
    caption = _report(gw, heading.lower(), f"{snapshot.name(lead)}: {evidence}.",
                      action, hashtags[edition.task])
    return Content(
        kind="ported_task", title=heading, kicker=f"NEXT GW • {edition.task.upper()}",
        cards=cards, verdict=action, caption=caption,
        data_at=now.astimezone(ET).isoformat(), gw=gw,
        footer="Internal: current official FPL snapshot; historical player history fetched by renderer")
