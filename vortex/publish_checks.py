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
        for row in article.fixtures:
            if (row.get("home_goals") is None or row.get("away_goals") is None
                or row.get("home_cs") is None or row.get("away_cs") is None):
                raise RuntimeError("Goal/CS projections unverified; hold this edition, not N/A")
    if getattr(article, "kind", None) == "team_analysis":
        data = article.team_analysis or {}
        for p in data.get("players", []):
            if not p.get("photo_code") or not p.get("club_code"):
                raise RuntimeError("Missing portrait or club badge for a scout pick")
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
    if article.kind == "elite":
        from .player_profile import render_player_profile
        result = render_player_profile(article, snapshot, output, session=session)
    else:
        result = render(article, output, session=session)
        # Keep the entire approved user master graphic, logo, and original
        # footer. The closing strip is restored and includes verified handles.
        from .publication_rules import USABLE_ACTIONS
        action = next((word for word in ("CAPTAIN", "SELL", "BUY", "BENCH",
                                        "START", "HOLD", "MONITOR")
                       if word in article.verdict.upper().split()),
                      "MONITOR") if hasattr(article, "verdict") else "MONITOR"
        result = apply_footer(result, verdict=f"{action} • NEXT GW DECISION")
    with Image.open(result) as opened:
        if opened.width * 9 != opened.height * 16 or min(opened.size) < 800:
            raise RuntimeError("Final image failed full-resolution mobile-quality aspect check")
        opened.verify()
    return result
