"""De-vig h2h and total-2.5 odds, then fit independent Poisson goals.

Only genuine current pre-match The Odds API bookmaker outcomes are inputs.
FPL fixtures identify the event; no priors, FDR, or invented betting odds.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import exp, isfinite, sqrt
from typing import Any

from scipy.optimize import minimize

MAX_AGE = timedelta(hours=12)
MIN_BOOKS = 2
STARTS = ((1.55, 1.25), (1.20, 1.20), (2.00, 1.00),
          (1.00, 2.00), (2.00, 2.00))


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def _median(numbers: list[float]) -> float:
    seq = sorted(numbers)
    return (seq[(len(seq)-1)//2] + seq[len(seq)//2]) / 2


def _safe_price(value: Any) -> float | None:
    return float(value) if type(value) in (int, float) and 1.01 < value <= 80 and isfinite(value) else None


def market_consensus(odds: dict[str, Any], home: str, away: str,
                     now: datetime, canonical) -> dict[str, Any] | None:
    """Require 2+ independent books for each complete h2h and O/U 2.5 market."""
    prices: dict[str, dict[str, tuple[datetime, Any]]] = {"h2h": {}, "totals": {}}
    for book in odds.get("bookmakers", []):
        if not isinstance(book, dict) or not isinstance(book.get("key"), str):
            continue
        key = book["key"]
        for market in book.get("markets", []):
            if not isinstance(market, dict) or market.get("key") not in prices:
                continue
            updated = _when(market.get("last_update") or book.get("last_update"))
            if updated is None or not timedelta(0) <= now - updated <= MAX_AGE:
                continue
            if market["key"] == "h2h":
                found = {}
                for value in market.get("outcomes", []):
                    if not isinstance(value, dict):
                        continue
                    name = canonical(value.get("name", ""))
                    price = _safe_price(value.get("price"))
                    if name in (home, away, "draw") and price is not None:
                        found[name] = 1 / price
                if set(found) != {home, away, "draw"}:
                    continue
                implied = sum(found.values())
                if not 0.99 <= implied <= 1.4:
                    continue
                estimate = (found[home]/implied, found["draw"]/implied, found[away]/implied)
            else:
                found = {}
                for value in market.get("outcomes", []):
                    if not isinstance(value, dict):
                        continue
                    if value.get("point") != 2.5:
                        continue
                    name = str(value.get("name", "")).lower().strip()
                    price = _safe_price(value.get("price"))
                    if name in ("over", "under") and price is not None:
                        found[name] = 1/price
                if set(found) != {"over", "under"}:
                    continue
                implied = sum(found.values())
                if not 0.99 <= implied <= 1.4:
                    continue
                estimate = found["over"]/implied
            previous = prices[market["key"]].get(key)
            if previous is None or updated > previous[0]:
                prices[market["key"]][key] = (updated, estimate)
    h2h, totals = prices["h2h"], prices["totals"]
    if len(h2h) < MIN_BOOKS or len(totals) < MIN_BOOKS:
        return None
    prob = [_median([p[i] for _, p in h2h.values()]) for i in range(3)]
    total = sum(prob)
    # Coordinate medians need renormalization even for small deviations.
    prob = [p/total for p in prob]
    latest = max(updated for market in prices.values() for updated, _ in market.values())
    return {"home": prob[0], "draw": prob[1], "away": prob[2],
            "over25": _median([p for _, p in totals.values()]),
            "books_h2h": len(h2h), "books_totals": len(totals),
            "updated_at": latest.isoformat()}


def _poisson_pmf(rate: float) -> list[float]:
    # Maximum rate 5.5; support through 28 goals has negligible tail.
    probabilities = [exp(-rate)]
    for n in range(1, 29):
        probabilities.append(probabilities[-1] * rate / n)
    return probabilities


def predicted_probabilities(home_rate: float, away_rate: float) -> tuple[float, float, float, float]:
    hp, ap = _poisson_pmf(home_rate), _poisson_pmf(away_rate)
    home = draw = away = 0.0
    for goals_h, p_h in enumerate(hp):
        for goals_a, p_a in enumerate(ap):
            both = p_h * p_a
            if goals_h > goals_a:
                home += both
            elif goals_h < goals_a:
                away += both
            else:
                draw += both
    total = home_rate + away_rate
    over = 1.0 - exp(-total)*(1 + total + total*total/2)
    return home, draw, away, over


def model_from_consensus(market: dict[str, Any]) -> dict[str, Any] | None:
    target = (market["home"], market["draw"], market["away"], market["over25"])
    if any(not isfinite(value) or not 0 < value < 1 for value in target):
        return None

    def objective(point) -> float:
        probs = predicted_probabilities(float(point[0]), float(point[1]))
        return sum((probs[i] - target[i])**2 for i in range(3)) / 3 + (probs[3] - target[3])**2

    solutions = [minimize(objective, start, method="L-BFGS-B",
                          bounds=((0.05, 5.5), (0.05, 5.5)),
                          options={"maxiter": 170, "ftol": 1e-12})
                 for start in STARTS]
    acceptable = [result for result in solutions if result.success
                  and all(isfinite(float(val)) for val in result.x)]
    if not acceptable:
        return None
    best = min(acceptable, key=lambda result: float(result.fun))
    lh, la = float(best.x[0]), float(best.x[1])
    fitted = predicted_probabilities(lh, la)
    rmse = sqrt(sum((a-b)**2 for a, b in zip(fitted, target))/4)
    if not isfinite(rmse) or rmse > 0.08:
        return None
    return {"home_goals": round(lh, 2), "away_goals": round(la, 2),
            "home_cs": round(100*exp(-la)), "away_cs": round(100*exp(-lh)),
            "fit_rmse": round(rmse, 4),
            "home_win_model_pct": round(100*fitted[0], 1),
            "draw_model_pct": round(100*fitted[1], 1),
            "away_win_model_pct": round(100*fitted[2], 1),
            "home_win_market_pct": round(100*market["home"], 1),
            "draw_market_pct": round(100*market["draw"], 1),
            "away_win_market_pct": round(100*market["away"], 1),
            "win_market_bookmakers": market["books_h2h"],
            "home_books": min(market["books_h2h"], market["books_totals"]),
            "away_books": min(market["books_h2h"], market["books_totals"]),
            "home_quote_utc": market["updated_at"],
            "away_quote_utc": market["updated_at"],
            "source": "The Odds API · devig h2h + O/U 2.5 · fitted independent Poisson",
            "method": "2+ books per market; L-BFGS-B fit; model not official FPL or direct bookmaker goals"}
