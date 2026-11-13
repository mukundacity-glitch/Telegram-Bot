"""Universal pre-publication contract for all scheduled Telegram/Discord art.

This is staging-only until verified handles and the exact approved master are
installed. Missing required data stops the affected post, never silently
renders N/A, generic unverified claims or fake portraits.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import re

from PIL import Image
import requests

from .brand_footer import apply_footer
from .publication_rules import (required_footer_handles, five_gw_fixtures,
                                player_metrics, choose_manager_action)
from .render import render


def enriched_mode() -> bool:
    return os.getenv("FPL_ENRICHED_VISUALS_ENABLED", "false").lower() == "true"


def _unverified(value: object) -> bool:
    return isinstance(value, str) and bool(re.search(
        r"(?i)(?:\bN/A\b|\bNA\b|data unavailable|placeholder)", value))


def validate_article(article: Any, snapshot: Any) -> None:
    required_footer_handles()
    if not snapshot.gameweek() or snapshot.fetched_at.tzinfo is None:
        raise RuntimeError("Official FPL gameweek / dated snapshot not established")
    if article.gw != snapshot.gameweek() and article.kind != "review":
        raise RuntimeError("Graphic is for the wrong future Gameweek")
    if article.kind == "daily_stats":
        from .daily_stats import build
        from datetime import datetime
        # Recompute the entire edition from its official inputs before sending.
        published_day = datetime.strptime(article.kicker.split(" • ", 1)[1], "%d %b %Y")
        from .schedule import TIMEZONE
        if article != build(snapshot, published_day.replace(tzinfo=TIMEZONE)):
            raise RuntimeError("Daily stats board does not match the official FPL snapshot")
        return
    if hasattr(article, "cards"):
        player_cards = [card for card in article.cards if card.team_code is not None]
        if not player_cards:
            raise RuntimeError("Empty or placeholder graphic has no player to report")
        for card in player_cards:
            if card.photo_code is None:
                raise RuntimeError("Featured official player photo ID not found")
            matches = [p for p in snapshot.players if
                       snapshot.photo_code(p) == card.photo_code and
                       snapshot.team_code(p) == card.team_code]
            if len(matches) != 1:
                raise RuntimeError("Player photo and club no longer match official FPL")
            player_metrics(snapshot, matches[0])
            five_gw_fixtures(snapshot, matches[0])
            if any(_unverified(line) for line in card.fields):
                raise RuntimeError("Unknown stat in player card; omit or hold post")
            if card.metrics and any(_unverified(v) for v in card.metrics.values()):
                raise RuntimeError("Missing value in a visible player metric")
    if getattr(article, "kind", None) == "projections":
        if not article.fixtures:
            raise RuntimeError("No verified fixture rows")
        used = []
        for row in article.fixtures:
            if (not isinstance(row.get("id"), int)
                    or not row.get("home") or not row.get("away")
                    or not isinstance(row.get("home_code"), int)
                    or not isinstance(row.get("away_code"), int)
                    or row.get("h_fdr") not in (1, 2, 3, 4, 5)
                    or row.get("a_fdr") not in (1, 2, 3, 4, 5)):
                raise RuntimeError("Official fixture, club crest ID or FDR unverified")
            used.extend((row["home_code"], row["away_code"]))
            goal_cs = [row.get(k) for k in ("home_goals", "away_goals", "home_cs", "away_cs")]
            if any(x is None for x in goal_cs) and not all(x is None for x in goal_cs):
                raise RuntimeError("Partial bookmaker model figures cannot appear on slide")
        if len(article.fixtures) == 10 and len(set(used)) != 20:
            raise RuntimeError("Standard 10-fixture GW must cover 20 distinct current clubs")
        # Missing bookmaker odds are optional. Render real official matchups
        # with real crests and FDR instead of blocking ALL graphic production.
    if getattr(article, "kind", None) == "team_analysis":
        data = article.team_analysis or {}
        if (not data.get("history") or data.get("gf_total") is None
            or data.get("ga_total") is None or not data.get("opponent_code")):
            raise RuntimeError("Incomplete verified historical team form; hold team graphic")
        for p in data.get("players", []):
            if not p.get("photo_code") or not p.get("club_code"):
                raise RuntimeError("Missing portrait or club badge for a scout pick")
            if any(_unverified(p.get(f)) or p.get(f) is None
                   for f in ("price", "form", "opponent", "fdr", "minutes")):
                raise RuntimeError("Incomplete verified scout stats; hold this team graphic")
    if getattr(article, "kind", None) == "transfer_suggestions":
        rows = article.transfers
        if len(rows) != 4:
            raise RuntimeError("Four-position comparison must include GK DEF MID FWD")
        for row in rows:
            for p in (row["out"], row.get("incoming")):
                if p is None:
                    continue
                if any(_unverified(p.get(f)) or p.get(f) is None
                       for f in ("photo_code", "club_code", "price", "form", "fdr", "out_event", "opponent")):
                    raise RuntimeError("Transfer card contains an unverified visible field")
    if getattr(article, "kind", None) == "start_bench":
        for p in article.start_bench:
            if not p.get("photo_code") or not p.get("club_code"):
                raise RuntimeError("Player image and crest required for start/bench")
    if "shared caption" in article.caption.casefold():
        raise RuntimeError("Caption includes a forbidden internal channel label")


def render_checked(article: Any, snapshot: Any, output: Path,
                   session: requests.Session | None = None) -> Path:
    if not enriched_mode():
        return render(article, output, session=session)
    validate_article(article, snapshot)
    if article.kind == "daily_stats":
        result = render(article, output, session=session)
    elif hasattr(article, "cards") and len(article.cards) == 1:
        from .player_profile import render_player_profile
        result = render_player_profile(article, snapshot, output, session=session)
    elif hasattr(article, "cards") and 2 <= len(article.cards) <= 4:
        from .multi_profile import render_multi_profile
        result = render_multi_profile(article, snapshot, output, session=session)
    else:
        result = render(article, output, session=session)
        # Keep the entire approved user master graphic, logo, and original
        # footer. The closing strip is restored and includes verified handles.
        action = "MONITOR"
        if hasattr(article, "verdict"):
            for choice in ("CAPTAIN", "SELL", "BUY", "BENCH", "START", "HOLD", "MONITOR"):
                if re.search(r"\b" + choice + r"\b", article.verdict.upper()):
                    action = choice
                    break
        result = apply_footer(result, verdict=f"{action} • NEXT GW DECISION")
    with Image.open(result) as opened:
        if opened.width * 9 != opened.height * 16 or min(opened.size) < 800:
            raise RuntimeError("Final image failed full-resolution mobile-quality aspect check")
        if opened.size != (1920, 1080):
            scaled = opened.convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
            staging = result.with_suffix(".mobile.tmp.png")
            scaled.save(staging, "PNG", optimize=True)
            staging.replace(result)
    with Image.open(result) as verified:
        if verified.size != (1920, 1080):
            raise RuntimeError("Final FPL VORTEX image must be 1920x1080")
        verified.verify()
    return result
