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




def _h2h_projection(payload: dict[str, Any], teams: tuple[str, str],
                    now: datetime) -> dict[str, Any] | None:
    """No-vig 90-minute HOME/DRAW/AWAY consensus from fresh three-way h2h.

    This is a market-implied probability, never a model-generated win forecast.
    Exclude two-way markets and bookmaker duplicates.
    """
    quotes: dict[str, tuple[float, tuple[float, float, float]]] = {}
    for book in payload.get("bookmakers", []):
        if not isinstance(book, dict) or not isinstance(book.get("key"), str):
            continue
        for market in book.get("markets", []):
            if not isinstance(market, dict) or market.get("key") != "h2h":
                continue
            updated = _datetime(market.get("last_update") or book.get("last_update"))
            if updated is None or not (timedelta(0) <= now - updated <= MAX_MARKET_AGE):
                continue
            prices = {}
            for outcome in market.get("outcomes", []):
                if not isinstance(outcome, dict):
                    continue
                name = canonical(outcome.get("name", ""))
                value = outcome.get("price")
                if name in {*teams, "draw"} and type(value) in (int, float) and 1.01 < value <= 80:
                    prices[name] = 1.0 / float(value)
            if set(prices) != {*teams, "draw"}:
                continue
            overround = sum(prices.values())
            if not 0.99 <= overround <= 1.4:
                continue
            probabilities = (prices[teams[0]] / overround,
                             prices["draw"] / overround,
                             prices[teams[1]] / overround)
            if book["key"] not in quotes or updated.timestamp() > quotes[book["key"]][0]:
                quotes[book["key"]] = (updated.timestamp(), probabilities)
    if len(quotes) < MIN_BOOKMAKERS:
        return None
    estimates = [_median([row[1][idx] for row in quotes.values()]) for idx in range(3)]
    total = sum(estimates)
    if total <= 0:
        return None
    return {
        "home_win_pct": round(100 * estimates[0] / total, 1),
        "draw_pct": round(100 * estimates[1] / total, 1),
        "away_win_pct": round(100 * estimates[2] / total, 1),
        "bookmakers": len(quotes),
        "source": "The Odds API · no-vig 3-way h2h market",
    }


def verified_match_odds(snapshot: FplSnapshot,
                        fixtures: list[dict[str, Any]],
                        session: requests.Session | None = None,
                        api_key: str | None = None) -> dict[int, dict[str, Any]]:
    """Live bookmaker-derived matchup projections, or explicit unavailable.

    Official fixtures constrain teams/kickoff. The Odds API gives h2h/total
    prices, devigged per bookmaker, fitted by bounded Poisson L-BFGS-B.
    A rate from market odds is a model output, never an official FPL metric.
    """
    from .odds_model import market_consensus, model_from_consensus

    # Only secrets already injected into THIS repository's runner are usable.
    # A secret name in another repository does not expose its value here.
    key = (api_key if api_key is not None
           else (os.getenv("THE_ODDS_API_KEY") or os.getenv("ODDS_API_KEY") or ""))
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
        kick = _datetime(f.get("kickoff_time"))
        if kick is None or kick <= now or f.get("finished"):
            continue
        event_id = _matched_event([e for e in events if isinstance(e, dict)], f, snapshot)
        if event_id is None:
            continue
        home = canonical(snapshot.teams.get(f.get("team_h"), {}).get("name", ""))
        away = canonical(snapshot.teams.get(f.get("team_a"), {}).get("name", ""))
        for region in ("uk,eu", "uk"):
            odds = _safe_get(client, f"/events/{event_id}/odds", key, {
                "regions": region, "markets": "h2h,totals",
                "oddsFormat": "decimal", "dateFormat": "iso",
            })
            if not isinstance(odds, dict):
                continue
            # Verify match identity *again* on returned market data.
            if canonical(odds.get("home_team", "")) != home or canonical(odds.get("away_team", "")) != away:
                continue
            when = _datetime(odds.get("commence_time"))
            if when is not None and (abs(when - kick) > timedelta(hours=12) or when <= now):
                continue
            # Event ID and kickoff already matched in /events. Some valid
            # event-odds payloads omit commence_time; do not fabricate it.
                continue
            h2h = _h2h_projection(odds, (home, away), now)
            consensus = market_consensus(odds, home, away, now, canonical)
            model = model_from_consensus(consensus) if consensus else None
            if model is not None:
                verified[f["id"]] = model
                break
            # Preserve the original verified two-bookmaker team-total 0.5
            # projection path (it was in production before this upgrade).
            # These markets are optional and independently authenticated;
            # try the current response first, then a market-specific request.
            market_payloads = [odds]
            additional = _safe_get(client, f"/events/{event_id}/odds", key, {
                "regions": region,
                "markets": "team_totals,alternate_team_totals",
                "oddsFormat": "decimal", "dateFormat": "iso",
            })
            if (isinstance(additional, dict)
                    and canonical(additional.get("home_team", "")) == home
                    and canonical(additional.get("away_team", "")) == away):
                when_extra = _datetime(additional.get("commence_time"))
                if when_extra is None or (abs(when_extra-kick) <= timedelta(hours=12) and when_extra > now):
                    market_payloads.append(additional)
            for market_payload in market_payloads:
                quotes = _two_sided_quotes(market_payload, (home, away), now)
                hm, am = _projection(quotes.get(home, [])), _projection(quotes.get(away, []))
                if hm and am:
                    verified[f["id"]] = {
                        "home_goals": hm["goals"], "away_goals": am["goals"],
                        "home_cs": round(am["p_zero"]*100),
                        "away_cs": round(hm["p_zero"]*100),
                        "home_books": hm["books"], "away_books": am["books"],
                        "home_quote_utc": hm["updated_at"],
                        "away_quote_utc": am["updated_at"],
                        "source": "The Odds API · two-book team O/U 0.5 · Poisson-equivalent",
                        "method": "Independent no-vig team total 0.5 market; not an FPL prediction",
                        "home_win_market_pct": h2h["home_win_pct"] if h2h else None,
                        "draw_market_pct": h2h["draw_pct"] if h2h else None,
                        "away_win_market_pct": h2h["away_win_pct"] if h2h else None,
                        "win_market_bookmakers": h2h["bookmakers"] if h2h else 0,
                    }
                    break
            if f["id"] in verified:
                break
            # Partial verified h2h is NOT a valid goal-rate forecast.
            # Its 1X2 percentage may still be cited separately.
            if h2h is not None and f["id"] not in verified:
                verified[f["id"]] = {
                    "home_goals": None, "away_goals": None,
                    "home_cs": None, "away_cs": None,
                    "home_books": 0, "away_books": 0,
                    "home_quote_utc": None, "away_quote_utc": None,
                    "source": "The Odds API · partial h2h (goals/CS N/A)",
                    "method": "Missing independently verified totals market; goals/CS not estimated",
                    "home_win_market_pct": h2h["home_win_pct"],
                    "draw_market_pct": h2h["draw_pct"],
                    "away_win_market_pct": h2h["away_win_pct"],
                    "win_market_bookmakers": h2h["bookmakers"],
                }
    return verified
