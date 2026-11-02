"""Prevent a legacy edition from echoing the same player/topic already posted.

Runs only when the new dual-platform ported-task stream is explicitly enabled.
It never deletes old scheduled slots or interferes with original default mode.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MAP = {
    "news": ("task1:availability-transfer-decisions", "press_news:verified-press-availability"),
    "captaincy": ("task1:captain-differential",),
    "transfer": ("three_daily:transfer-squad-structure",),
    "evening": ("three_daily:next-gw-evening-decisions",),
}


def previously_posted_same_players(slot: str, original, versions: dict,
                                   now: datetime) -> bool:
    """Same ET day and same upcoming GW, with real published player overlap."""
    tags = MAP.get(slot, ())
    if not tags or not getattr(original, "cards", None):
        return False
    ids = {c.photo_code for c in original.cards if c.photo_code is not None}
    if not ids:
        return False
    today = now.astimezone(ET).date()
    for suffix in tags:
        key = f"2026-27:GW{original.gw}:{suffix}"
        record = versions.get(key)
        if not isinstance(record, dict) or not record.get("confirmed"):
            continue
        try:
            published = datetime.fromisoformat(record["published_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError, AttributeError):
            continue
        if published.tzinfo is None or published.astimezone(ET).date() != today:
            continue
        overlap = ids.intersection(record.get("last_player_ids") or [])
        if slot == "captaincy" and len(overlap) >= 2:
            return True
        if slot != "captaincy" and len(overlap) >= len(ids):
            return True
    return False
