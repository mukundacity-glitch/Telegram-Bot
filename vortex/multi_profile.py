"""Reference-2 multi-player comparison for every shared Telegram/Discord post.

The current fixture appears once per player; advanced stats appear once in the
shared yellow table. Five-GW context remains available to the advice rules.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image
import requests

from .brand_footer import MASTER, apply_footer
from .matchup import _media, _bundled_portrait
from .publication_rules import (
    five_gw_fixtures, fetch_verified_xpts,
    player_metrics, choose_manager_action,
)
from .recommendations import get_history, completed_rounds


def render_multi_profile(post, snapshot, output: Path, session=None) -> Path:
    """Reference-2 portrait cards and one non-repeating advanced-stats table."""
    from .comparison_board import comparison_board
    cards = tuple(post.cards)
    if not 2 <= len(cards) <= 4:
        raise RuntimeError("Multi-player infographic supports 2 to 4 current players")
    client = session or requests.Session()
    with Image.open(MASTER) as original:
        if original.width * 9 != original.height * 16:
            raise RuntimeError("Approved master aspect ratio differs from required 16:9")
        master = original.convert("RGB")
    xpts = fetch_verified_xpts(snapshot.fetched_at, snapshot, client)
    completed = set(completed_rounds(snapshot, 4))
    cache, profiles = {}, []
    for idx, card in enumerate(cards):
        players = [p for p in snapshot.players
                   if snapshot.photo_code(p) == card.photo_code
                   and snapshot.team_code(p) == card.team_code
                   and snapshot.name(p) == card.headline]
        if len(players) != 1:
            raise RuntimeError("Featured card is not a unique verified current FPL player")
        player = players[0]
        portrait = _media(client, card.photo_code, "photo", cache)
        if portrait is None:
            portrait = _bundled_portrait(card.headline)
        badge = _media(client, card.team_code, "crest", cache)
        if portrait is None or badge is None:
            raise RuntimeError("Full verified portrait and authentic crest mandatory")
        history = get_history(player["id"], client)
        recent = [r for r in history if r.get("round") in completed
                  and int(r.get("minutes") or 0) > 0]
        values = player_metrics(snapshot, player, recent[-3:])
        fixtures = five_gw_fixtures(snapshot, player, xpts)
        action, reason = choose_manager_action(player, fixtures, recent[-3:])
        published_label = str(card.label or "").upper()
        if player.get("status") == "a":
            if published_label in ("BUY", "SELL", "HOLD", "MONITOR", "START", "BENCH", "CAPTAIN", "WATCHLIST"):
                action = "MONITOR" if published_label == "WATCHLIST" else published_label
            elif post.kind == "captaincy" and idx == 0:
                action = "CAPTAIN"
        elif player.get("news"):
            reason = str(player["news"])
        elif recent:
            reason = 'Recent minutes: ' + '/'.join(str(int(r.get('minutes') or 0)) for r in recent[-3:]) + f". Form {values['FORM']}."
        club = snapshot.teams[player["team"]]
        profiles.append({"name": snapshot.name(player),
                         "club": club.get("name") or snapshot.team(player),
                         "position": values["POSITION"], "metrics": values,
                         "fixtures": fixtures, "portrait": portrait, "badge": badge,
                         "action": action, "reason": reason,
                         "label": published_label if published_label in ('PREMIUM', 'BUDGET VALUE') else action})
    canvas = comparison_board(master, post.title, post.gw, profiles,
                              verdict=post.verdict)
    output.parent.mkdir(parents=True, exist_ok=True)
    interim = output.with_suffix(".tmp.png")
    canvas.resize((1920, 1080), Image.Resampling.LANCZOS).save(interim, "PNG", optimize=True)
    interim.replace(output)
    # Preserve the five-GW fixture bands drawn immediately above the footer.
    return apply_footer(output)
