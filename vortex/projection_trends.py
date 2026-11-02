"""Production safeguards and meaningful day-to-day shifts for the GW odds board.

This is independent of any particular odds provider. Only fresh upstream
projections that passed the existing fixture/source checks enter this module.
Never compare bookmaker-derived estimates against Solio model estimates, or
a fixture against a different opponent, and never treat N/A as a market move.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from math import ceil, isfinite
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
GOAL_CHANGE = 0.60
GOAL_RELATIVE = 0.30
CS_POINTS_CHANGE = 15
MIN_COVERAGE = 0.80


def _number(value: object, low: float, high: float) -> bool:
    return type(value) in (float, int) and isfinite(value) and low <= value <= high


def complete(fixture: dict[str, Any]) -> bool:
    return (
        _number(fixture.get("home_goals"), 0, 6)
        and _number(fixture.get("away_goals"), 0, 6)
        and _number(fixture.get("home_cs"), 0, 100)
        and _number(fixture.get("away_cs"), 0, 100)
        and ("The Odds API" in fixture.get("odds_source", "")
             or "Solio Analytics" in fixture.get("odds_source", ""))
    )


def coverage(post: Any) -> tuple[int, int]:
    rows = getattr(post, "fixtures", ())
    return sum(complete(row) for row in rows), len(rows)


def require_publishable(post: Any) -> None:
    """Hold rather than publish a zero-odds FDR board; permit limited gaps as N/A."""
    if getattr(post, "kind", None) != "projections":
        return
    verified, total = coverage(post)
    if not total or verified < ceil(total * MIN_COVERAGE):
        raise RuntimeError(
            f"GOALS/CS HOLD: only {verified}/{total} matchups have source-verified "
            "projected goals and clean-sheet percentages; no fallback to FDR"
        )


def _family(source: str) -> str:
    if "The Odds API" in source:
        return "bookmaker"
    if "Solio Analytics" in source:
        return "solio"
    return ""


def _sides(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    family = _family(str(row.get("odds_source", "")))
    return {
        side: {
            "team": row.get(side + "_code"),
            "opponent": row.get(("away" if side == "home" else "home") + "_code"),
            "kickoff": row.get("kickoff"),
            "family": family,
            "goals": row.get(side + "_goals"),
            "cs": row.get(side + "_cs"),
        }
        for side in ("home", "away")
    }


def _previous(history: dict[str, Any], gw: int, day: str) -> dict[str, Any]:
    days = (history.get("gameweeks") or {}).get(str(gw)) or {}
    candidates = [d for d in days if isinstance(d, str) and d < day]
    return days[max(candidates)] if candidates else {}


def compare(post: Any, history: dict[str, Any], now: datetime) -> tuple[Any, int]:
    """Add only large, same-fixture, same-source-family daily changes to rows."""
    if getattr(post, "kind", None) != "projections":
        return post, 0
    if now.tzinfo is None:
        raise ValueError("Daily trends require a timezone-aware time")
    day = now.astimezone(ET).date().isoformat()
    previous = _previous(history, post.gw, day).get("fixtures") or {}
    rows = []
    major = []
    for row in post.fixtures:
        updated = dict(row)
        if complete(row):
            old = previous.get(str(row["id"]), {})
            for side, current in _sides(row).items():
                before = old.get(side, {})
                if (
                    before.get("family") != current["family"]
                    or not current["family"]
                    or before.get("team") != current["team"]
                    or before.get("opponent") != current["opponent"]
                    or before.get("kickoff") != current["kickoff"]
                    or not _number(before.get("goals"), 0, 6)
                    or not _number(before.get("cs"), 0, 100)
                ):
                    continue
                gd = current["goals"] - before["goals"]
                cd = current["cs"] - before["cs"]
                gflag = abs(gd) >= GOAL_CHANGE and (
                    abs(gd) / max(abs(before["goals"]), 0.2) >= GOAL_RELATIVE
                )
                cflag = abs(cd) >= CS_POINTS_CHANGE
                if gflag or cflag:
                    updated[side + "_major_change"] = {
                        "goals": round(gd, 2) if gflag else None,
                        "cs_points": round(cd, 1) if cflag else None,
                    }
                    major.append((str(row.get(side, "")), gd if gflag else None, cd if cflag else None))
        rows.append(updated)
    caption = post.caption
    if major:
        lines = caption.splitlines()
        if len(lines) == 5 and lines[-1].count("#") == 4:
            label, gd, cd = sorted(major, key=lambda m: max(
                abs(m[1] or 0) / GOAL_CHANGE, abs(m[2] or 0) / CS_POINTS_CHANGE),
                reverse=True)[0]
            metric = f"prG {gd:+.2f}" if gd is not None else f"CS {cd:+.0f}pp"
            lines[3] = f"MAJOR MOVES: {len(major)} teams; {label} {metric}. Recheck news."
            candidate = "\n".join(lines)
            if len(candidate) <= 280:
                caption = candidate
            else:
                lines[3] = f"MAJOR MOVES: {len(major)} teams. Check highlighted changes."
                candidate = "\n".join(lines)
                if len(candidate) <= 280:
                    caption = candidate
    return replace(post, fixtures=tuple(rows), caption=caption), len(major)


def record(post: Any, history: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Build immutable history update only AFTER a confirmed platform send."""
    if getattr(post, "kind", None) != "projections":
        return history
    require_publishable(post)
    day = now.astimezone(ET).date().isoformat()
    saved = dict(history)
    gameweeks = dict(saved.get("gameweeks") or {})
    days = dict(gameweeks.get(str(post.gw)) or {})
    fixtures = {
        str(row["id"]): _sides(row) for row in post.fixtures if complete(row)
    }
    days[day] = {"recorded_at": now.isoformat(), "fixtures": fixtures}
    # Keep three gameweeks and their most recent 14 dates. No old, stale baseline.
    gameweeks[str(post.gw)] = {k: days[k] for k in sorted(days)[-14:]}
    saved["gameweeks"] = {
        k: gameweeks[k] for k in sorted(gameweeks, key=lambda v: int(v))[-3:]
    }
    return saved
