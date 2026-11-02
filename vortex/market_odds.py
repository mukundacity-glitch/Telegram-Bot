"""Optional independently sourced football odds; never infer markets from FPL FDR.

Only complete, fresh, two-sided 0.5 team-total markets from at least two
different bookmakers are converted into projections. No API key or coverage
means N/A, not fabricated projected goals or clean-sheet percentages.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import log
import os
import re
from typing import Any

import requests

from .fpl import FplSnapshot

ODDS_ROOT = "https://api.the-odds-api.com/v4/sports/soccer_epl"
MAX_MARKET_AGE = timedelta(hours=12)
MIN_BOOKMAKERS = 2


def _datetime(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else None
    except ValueError:
        return None


def canonical(name: str) -> str:
    clean = re.sub(r"[^a-z0-9 ]", "", str(name).lower())
    clean = re.sub(r"\s+", " ", clean).strip()
    alias = {
        "afc bournemouth": "bournemouth", "bournemouth": "bournemouth",
        "brighton and hove albion": "brighton", "brighton hove albion": "brighton",
        "manchester city": "man city", "man city": "man city", "manchester united": "man united",
        "man utd": "man united", "man united": "man united",
        "nottingham forest": "nottingham forest", "nottm forest": "nottingham forest",
        "tottenham": "tottenham", "tottenham hotspur": "tottenham",
        "wolverhampton wanderers": "wolves", "wolves": "wolves",
        "west ham united": "west ham", "west ham": "west ham",
        "leeds united": "leeds", "leeds": "leeds",
        "newcastle united": "newcastle", "newcastle": "newcastle",
        "leicester city": "leicester", "leicester": "leicester",
        "ipswich town": "ipswich", "ipswich": "ipswich",
        "hull city": "hull", "hull": "hull",
        "coventry city": "coventry", "coventry": "coventry",
        "sunderland afc": "sunderland", "sunderland": "sunderland",
    }
    if clean.endswith(" fc"):
        clean = clean[:-3]
    return alias.get(clean, clean)


def _safe_get(client: requests.Session, path: str, key: str,
              params: dict[str, Any]) -> Any | None:
    try:
        result = client.get(f"{ODDS_ROOT}{path}",
                            params={**params, "apiKey": key},
                            headers={"Accept": "application/json"}, timeout=9)
        result.raise_for_status()
        return result.json()
    except (requests.RequestException, ValueError):
        # Requests exceptions may embed the URL containing the API key.
        # Never return or log them.
        return None


def _matched_event(events: list[dict[str, Any]],
                   fixture: dict[str, Any],
                   snapshot: FplSnapshot) -> str | None:
    home = snapshot.teams.get(fixture.get("team_h"), {})
    away = snapshot.teams.get(fixture.get("team_a"), {})
    kick = _datetime(fixture.get("kickoff_time"))
    if kick is None:
        return None
    home_name, away_name = canonical(home.get("name", "")), canonical(away.get("name", ""))
    valid = []
    for event in events:
        when = _datetime(event.get("commence_time"))
        if (canonical(event.get("home_team", "")) == home_name
            and canonical(event.get("away_team", "")) == away_name
            and when is not None and abs(when - kick) <= timedelta(hours=12)
            and isinstance(event.get("id"), str)):
            valid.append(event["id"])
    return valid[0] if len(valid) == 1 else None


def _two_sided_quotes(payload: dict[str, Any], teams: tuple[str, str],
                      now: datetime) -> dict[str, list[tuple[str, float, float]]]:
    """Return de-vigged under-0.5 probabilities grouped by independent bookmaker."""
    all_quotes: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    for book in payload.get("bookmakers", []):
        if not isinstance(book, dict) or not isinstance(book.get("key"), str):
            continue
        book_key = book["key"]
        for market in book.get("markets", []):
            if not isinstance(market, dict) or market.get("key") not in {"team_totals", "alternate_team_totals"}:
                continue
            updated = _datetime(market.get("last_update") or book.get("last_update"))
            if updated is None or not (timedelta(0) <= now - updated <= MAX_MARKET_AGE):
                continue
            pairs: dict[str, dict[str, float]] = defaultdict(dict)
            for outcome in market.get("outcomes", []):
                if not isinstance(outcome, dict) or outcome.get("point") != 0.5:
                    continue
                team = canonical(outcome.get("description", ""))
                side = str(outcome.get("name") or "").lower()
                price = outcome.get("price")
                if team not in teams or side not in {"over", "under"}:
                    continue
                if isinstance(price, (float, int)) and not isinstance(price, bool) and 1.01 < price <= 80:
                    pairs[team][side] = float(price)
            for team, sides in pairs.items():
                if set(sides) != {"over", "under"}:
                    continue
                inv_over, inv_under = 1.0 / sides["over"], 1.0 / sides["under"]
                overround = inv_over + inv_under
                if not 0.99 <= overround <= 1.4:
                    continue
                p_nil = inv_under / overround
                if 0.005 <= p_nil <= 0.98:
                    all_quotes[team].append((book_key, p_nil, updated.timestamp()))
    return all_quotes


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2


def _projection(quotes: list[tuple[str, float, float]]) -> dict[str, Any] | None:
    unique = {}
    for key, p_nil, updated in sorted(quotes, key=lambda item: item[2], reverse=True):
        unique.setdefault(key, p_nil)
    if len(unique) < MIN_BOOKMAKERS:
        return None
    p_nil = _median(list(unique.values()))
    # A Poisson-equivalent mean from the P(score zero) implied by no-vig
    # 0.5 team totals. This is a modeled expectation, NOT bookmaker xG.
    goals = -log(p_nil)
    if not 0 <= goals <= 5:
        return None
    latest_quote = datetime.fromtimestamp(max(row[2] for row in quotes), tz=timezone.utc)
    return {"goals": round(goals, 2), "p_zero": p_nil,
            "books": len(unique), "updated_at": latest_quote.isoformat(),
            "source": "The Odds API · team totals 0.5"}


def verified_match_odds(snapshot: FplSnapshot,
                        fixtures: list[dict[str, Any]],
                        session: requests.Session | None = None,
                        api_key: str | None = None) -> dict[int, dict[str, Any]]:
    """Return per-fixture modeled goals and CS for both teams, or no estimates.

    API v4 optional key: THE_ODDS_API_KEY. Market availability cannot be
    guaranteed and no API key is ever persisted into a card, caption or log.
    """
    key = api_key if api_key is not None else os.getenv("THE_ODDS_API_KEY", "")
    if not key or not fixtures:
        return {}
    client = session or requests.Session()
    now = snapshot.fetched_at.astimezone(timezone.utc)
    events = _safe_get(client, "/events", key, {"dateFormat": "iso"})
    if not isinstance(events, list):
        return {}
    verified: dict[int, dict[str, Any]] = {}
    for f in fixtures[:12]:
        if not isinstance(f.get("id"), int):
            continue
        event_id = _matched_event([e for e in events if isinstance(e, dict)], f, snapshot)
        if event_id is None:
            continue
        odds = _safe_get(client, f"/events/{event_id}/odds", key, {
            "regions": "uk,eu", "markets": "alternate_team_totals,team_totals",
            "oddsFormat": "decimal", "dateFormat": "iso",
        })
        if not isinstance(odds, dict):
            continue
        home = canonical(snapshot.teams.get(f.get("team_h"), {}).get("name", ""))
        away = canonical(snapshot.teams.get(f.get("team_a"), {}).get("name", ""))
        # Verify event match again in the odds payload, not only event list.
        if canonical(odds.get("home_team", "")) != home or canonical(odds.get("away_team", "")) != away:
            continue
        quotes = _two_sided_quotes(odds, (home, away), now)
        h, a = _projection(quotes.get(home, [])), _projection(quotes.get(away, []))
        verified[f["id"]] = {
            "home_goals": h["goals"] if h else None,
            "away_goals": a["goals"] if a else None,
            # Clean sheet = opponent scores zero, never team's own nil chance.
            "home_cs": round(a["p_zero"] * 100) if a else None,
            "away_cs": round(h["p_zero"] * 100) if h else None,
            "home_books": h["books"] if h else 0,
            "away_books": a["books"] if a else 0,
            "home_quote_utc": h["updated_at"] if h else None,
            "away_quote_utc": a["updated_at"] if a else None,
            "source": "The Odds API · 2+ books · team totals O/U 0.5",
            "method": "no-vig, Poisson-equivalent mean",
        }
    return verified
