"""Dynamic 05:30 Availability & Transfer Decisions shortlist.

Names, clubs, prices and fixtures always originate in the live official FPL
snapshot. Verified *fixture-level* xPts are optional; missing model coverage is
never replaced by invented player projections. The fallback is an explicitly
editorial ranking using official FPL projections, recent minutes and FDR.
"""
from __future__ import annotations

from math import isfinite

from .publication_rules import fetch_verified_xpts, five_gw_fixtures
from .editorial_inputs import NoUpdate

TIERS = ("MUST HAVES", "STRONG BUYS", "SMART PICKS", "VALUE PLAYS", "PUNTS")
ACTIONS = ("PRIORITY", "BUY", "CONSIDER", "VALUE", "DIFFERENTIAL")
MAX_PER_TIER = 5
# Fetching histories is relatively expensive: preliminarily screen every FPL
# player, then verify recent full-match evidence for the strongest 100.
MAX_HISTORY_CHECKS = 100


def _number(value, default=0.0):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return default
    return result if isfinite(result) else default


def _fixture_forecast(rows, gw):
    """Return a model total only when EVERY real fixture is covered.

    A blank counts as no fixture, doubles require both fixture predictions.
    Never fill missing games by extrapolating FPL ep_next or form.
    """
    def complete(in_scope):
        games = [f for f in in_scope if not f["blank"]]
        if any(f["xpts"] is None for f in games):
            return None
        return round(sum(float(f["xpts"]) for f in games), 2)
    current = [f for f in rows if f["gw"] == gw]
    next_one = complete(current) if any(not f["blank"] for f in current) else None
    future = complete(rows) if any(not f["blank"] for f in rows) else None
    return next_one, future


def _score_factor(values, value):
    low, high = min(values), max(values)
    return (value-low)/(high-low) if high > low else 0.5


def _role_signal(p):
    minutes = max(1, int(p.get("minutes") or 0))
    pos = int(p.get("element_type") or 0)
    if pos in (3, 4):
        return (_number(p.get("expected_goal_involvements")) * 90 / minutes)
    if pos == 2:
        return (_number(p.get("expected_goal_involvements")) * 90 / minutes
                + _number(p.get("clean_sheets")) / max(1, _number(p.get("starts"), 1)))
    return (_number(p.get("saves")) / max(1, _number(p.get("starts"), 1)) * .06
            + _number(p.get("clean_sheets")) / max(1, _number(p.get("starts"), 1)))


def _initial_key(p):
    return (max(0, _number(p.get("ep_next"))) * 1.2
            + max(0, _number(p.get("points_per_game"))) * .5
            + max(0, _number(p.get("form"))) * .3)


def _select_rows(snapshot, evidence, verified):
    gw = snapshot.gameweek()
    pool = []
    for p in snapshot.players:
        if (p.get("status") != "a" or not isinstance(p.get("id"), int)
            or not p.get("code") or p.get("team") not in snapshot.teams
            or int(p.get("element_type") or 0) not in (1, 2, 3, 4)
            or int(p.get("now_cost") or 0) < 30
            or int(p.get("minutes") or 0) < 360):
            continue
        chance = p.get("chance_of_playing_next_round")
        if isinstance(chance, int) and chance < 80:
            continue
        try:
            fixtures = five_gw_fixtures(snapshot, p, verified)
        except ValueError:
            continue
        # A blank next week cannot be recommended as an immediate transfer.
        if not any(f["gw"] == gw and not f["blank"] for f in fixtures):
            continue
        one, five = _fixture_forecast(fixtures, gw)
        fdr = [f["fdr"] for f in fixtures if not f["blank"] and f["fdr"] in (1, 2, 3, 4, 5)]
        if not fdr:
            continue
        form = max(0, _number(p.get("form")))
        ppg = max(0, _number(p.get("points_per_game")))
        # Editorial future-run INDEX, not custom xPts. Its numerical value is
        # never displayed as a player forecast or labeled xPts.
        fixture_strength = max(.65, min(1.35, 1.0 + (3.0-sum(fdr)/len(fdr))*.11))
        editorial_run = (.55*form + .45*ppg) * fixture_strength
        pool.append({"player": p, "fixtures": fixtures,
                     "xpts1": one, "xpts5": five,
                     "official_next": max(0, _number(p.get("ep_next"))),
                     "editorial_run": editorial_run, "underlying": _role_signal(p),
                     "price": int(p["now_cost"])/10})
    # Consider every current registered player above, but bound remote player
    # history requests. Verified xPts takes priority over preliminary form.
    pool.sort(key=lambda r: (
        r["xpts1"] if r["xpts1"] is not None else r["official_next"],
        r["xpts5"] if r["xpts5"] is not None else r["editorial_run"]*5,
        _initial_key(r["player"])), reverse=True)
    qualified = []
    for r in pool[:MAX_HISTORY_CHECKS]:
        history = evidence.recent(r["player"])
        # Three completed recent matches with 70+ minutes: real observed
        # reliability, NOT a fabricated 80% probability of starting.
        if len(history) < 3 or any(int(h.get("minutes") or 0) < 70 for h in history[-3:]):
            continue
        r["recent_minutes"] = [int(h["minutes"]) for h in history[-3:]]
        qualified.append(r)
    return qualified


def select(snapshot, now, evidence, *, session=None):
    """Return (player rows, tiered IDs, provenance).

    The existing trusted optional xPts snapshot is shared with other posts.
    Do not alter its URL, credentials, publication schedule or receipts.
    """
    verified = fetch_verified_xpts(now, snapshot, session=session)
    rows = _select_rows(snapshot, evidence, verified)
    if not rows:
        raise NoUpdate("No 05:30 player met verified fixture and recent-minutes criteria")
    # Do not mix model forecasts with an unofficial proxy in any displayed data.
    # Official FPL ep_next can inform ranking, but is never called custom xPts.
    metrics = []
    for r in rows:
        one = r["xpts1"] if r["xpts1"] is not None else r["official_next"]
        five = r["xpts5"]/5 if r["xpts5"] is not None else r["editorial_run"]
        value = five / r["price"]
        metrics.append((one, five, value, r["underlying"]))
    axes = list(zip(*metrics))
    for r, values in zip(rows, metrics):
        r["ranking"] = round(
            .45*_score_factor(axes[0], values[0])
            + .35*_score_factor(axes[1], values[1])
            + .10*_score_factor(axes[2], values[2])
            + .10*_score_factor(axes[3], values[3]), 6)
        r["value_index"] = values[2]
        r["next_signal"] = values[0]
    remaining = {r["player"]["id"]: r for r in rows}
    groups = {name: [] for name in TIERS}

    def take(tier, order, eligible=lambda r: True, floor=0.35):
        counts = {}
        for r in sorted(remaining.values(), key=order, reverse=True):
            if len(groups[tier]) >= MAX_PER_TIER:
                break
            p = r["player"]
            position = p["element_type"]
            if (r["ranking"] < floor or not eligible(r)
                or counts.get(position, 0) >= 3):
                continue
            groups[tier].append(p["id"])
            counts[position] = counts.get(position, 0)+1
            del remaining[p["id"]]

    take("MUST HAVES", lambda r: (r["ranking"], r["next_signal"]), floor=.57)
    take("STRONG BUYS", lambda r: (r["ranking"], r["next_signal"]), floor=.48)
    take("VALUE PLAYS", lambda r: (r["value_index"], r["ranking"]), floor=.38)
    take("PUNTS", lambda r: (r["ranking"], r["next_signal"]),
         eligible=lambda r: (_number(r["player"].get("selected_by_percent"), 100) <= 15
                             and r["next_signal"] > 0), floor=.39)
    take("SMART PICKS", lambda r: (r["ranking"], r["next_signal"]), floor=.40)

    by_id = {r["player"]["id"]: r for r in rows}
    selected = [by_id[pid] for tier in TIERS for pid in groups[tier]]
    if not selected:
        raise NoUpdate("No verified player cleared the 05:30 editorial quality floor")
    return selected, groups, {
        "screened_players": len(snapshot.players),
        "minutes_verified_players": len(rows),
        "verified_xpts_fixtures": len(verified),
        "forecast_notice": ("xPts1/xPts5 appear only with complete verified "
                            "fixture-level projections; otherwise —"),
        "selection_method": ("45% next / 35% five-GW / 10% value / 10% underlying;"
                             " official FPL and editorial rank fallback never shown as xPts"),
    }
