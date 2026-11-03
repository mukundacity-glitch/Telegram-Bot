"""Single-player edition of the reference-2 yellow-table broadcast graphic.

Only verified facts and existing advice rules are used. The current fixture
appears once; the five-GW model context still informs the existing advice.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import timezone

from PIL import Image
import requests

from .brand_footer import MASTER, apply_footer
from .publication_rules import (fetch_verified_xpts,
                                five_gw_fixtures, player_metrics,
                                choose_manager_action)
from .matchup import _media, _bundled_portrait
from .recommendations import completed_rounds, get_history
from .fplcore import completed_gw_enrichment


def render_player_profile(content: Any, snapshot: Any, output: Path,
                          *, session: requests.Session | None = None) -> Path:
    if len(content.cards) != 1:
        raise ValueError("Full 5-GW player profile requires exactly one featured player")
    card = content.cards[0]
    selected = [p for p in snapshot.players
                if snapshot.photo_code(p) == card.photo_code
                and snapshot.team_code(p) == card.team_code
                and snapshot.name(p) == card.headline]
    if len(selected) != 1:
        raise ValueError("Featured player is not uniquely matched to live official FPL")
    p = selected[0]
    if p.get("status") != "a" and p.get("news") is None:
        raise ValueError("No verified player availability")
    if not MASTER.is_file():
        raise FileNotFoundError("Existing FPL VORTEX stadium master missing")
    client = session or requests.Session()
    photo = _media(client, snapshot.photo_code(p), "photo", {})
    if photo is None:
        photo = _bundled_portrait(snapshot.name(p))
    logo = _media(client, snapshot.team_code(p), "crest", {})
    if photo is None or logo is None:
        raise RuntimeError("Full FPL profile needs a verified player photo and authentic club badge")
    metrics = player_metrics(snapshot, p)
    history = get_history(p["id"], client)
    completed = set(completed_rounds(snapshot, 5))
    previous = [r for r in history if r.get("round") in completed and r.get("minutes", 0) > 0]
    if previous:
        pts = [r for r in previous if type(r.get("total_points")) in (int, float)]
        if pts:
            metrics["LAST RETURNS"] = "/".join(str(int(r["total_points"])) for r in pts[-3:])
        metrics["RECENT STARTS"] = f"{sum(int(r.get('minutes') or 0) >= 60 for r in previous[-3:])}/{len(previous[-3:])}"
        if p.get("element_type") in (2, 3, 4):
            threshold = 10 if p.get("element_type") == 2 else 12
            hits = sum(int(r.get("defensive_contribution") or 0) >= threshold for r in previous)
            metrics["DC HIT / GAMES"] = f"{hits}/{len(previous)}"
            metrics["DC AWARDED PTS"] = str(hits * 2)
    # An optional read-only completed-GW public FPL Core dataset is joined by
    # exact official player + current club code. FPL remains authoritative.
    enrichment = completed_gw_enrichment(snapshot, client, snapshot.fetched_at)
    extra = enrichment.get(p["id"], {})
    if "gw_tackles" in extra and p.get("element_type") == 2:
        metrics["LAST GW TACKLES"] = str(int(extra["gw_tackles"]))
    if "gw_clearances_blocks_interceptions" in extra and p.get("element_type") == 2:
        metrics["LAST GW CBI"] = str(int(extra["gw_clearances_blocks_interceptions"]))
    expected = fetch_verified_xpts(snapshot.fetched_at.astimezone(timezone.utc), snapshot, client)
    fixtures = five_gw_fixtures(snapshot, p, expected)
    action, reason = choose_manager_action(p, fixtures, previous[-3:])
    # Avoid policy-inappropriate "SELL" if club player remains in unusually
    # strong form despite one hard fixture; this is advice, not a guarantee.
    from .comparison_board import comparison_board
    club = snapshot.teams[p["team"]]
    profile = {"name": snapshot.name(p), "club": club.get("name") or snapshot.team(p),
               "position": metrics["POSITION"], "metrics": metrics,
               "fixtures": fixtures, "portrait": photo, "badge": logo,
               "action": action, "reason": str(p.get("news") or reason)
               if p.get("status") != "a" else reason, "label": action}
    with Image.open(MASTER) as template:
        canvas = comparison_board(template, content.title, snapshot.gameweek(),
                                  [profile], verdict=content.verdict)
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch = output.with_suffix(".staging.png")
    canvas.resize((1920, 1080), Image.Resampling.LANCZOS).save(scratch, "PNG", optimize=True)
    scratch.replace(output)
    return apply_footer(output, verdict="VERIFY MINUTES • FIXTURES • PLAYER FORM BEFORE TRANSFERS")
