"""Duplicate guards respect real editorial identity, ET date and poster receipts."""
from datetime import datetime, timedelta, timezone

from vortex.content import Card, Content
from vortex.ported_topic_guard import previously_posted_same_players


def _post(kind, codes, gw=10):
    return Content(kind, "FPL Decision", "Next GW",
                   tuple(Card(f"P{i}", "ARS", "ACTION", (), code, 3)
                         for i, code in enumerate(codes)),
                   "MONITOR", "caption", "internal", gw, "")


def test_captaincy_not_reposted_after_task1_has_shared_same_picks():
    now = datetime(2026, 11, 2, 21, tzinfo=timezone.utc)
    versions = {"2026-27:GW10:task1:captain-differential": {
        "confirmed": True, "published_at": now.isoformat(),
        "last_player_ids": [12, 13, 14],
    }}
    assert previously_posted_same_players(
        "captaincy", _post("captaincy", [12, 13, 14, 15]), versions, now)
    assert not previously_posted_same_players(
        "captaincy", _post("captaincy", [12, 20, 21, 22]), versions, now)


def test_unchanged_prior_day_analysis_does_not_mask_new_news():
    now = datetime(2026, 11, 2, 21, tzinfo=timezone.utc)
    versions = {"2026-27:GW10:task1:availability-transfer-decisions": {
        "confirmed": True,
        "published_at": (now - timedelta(days=1)).isoformat(),
        "last_player_ids": [12, 13],
    }}
    assert not previously_posted_same_players("news", _post("news", [12, 13]), versions, now)


def test_new_player_in_legacy_news_still_gets_published():
    now = datetime(2026, 11, 2, 21, tzinfo=timezone.utc)
    versions = {"2026-27:GW10:task1:availability-transfer-decisions": {
        "confirmed": True, "published_at": now.isoformat(),
        "last_player_ids": [12, 13],
    }}
    assert not previously_posted_same_players("news", _post("news", [12, 14]), versions, now)
    assert previously_posted_same_players("news", _post("news", [12, 13]), versions, now)
