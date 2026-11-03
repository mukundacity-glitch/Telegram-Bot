"""Telegram-only official FPL news and actionable decisions, 05:00–22:00 ET.

Retains all pre-existing Telegram graphics/times. Builds a genuine original-blue
1920x1080 image only for an actual changed official FPL status or price.
Updates an earlier *same player + same topic + same GW* Telegram photo in place
rather than posting it again; never claims delivery without a message receipt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import re

from PIL import Image

from .bot import ROOT, STATE, read_state, write_state
from .content import Card, Content
from .fpl import collect_snapshot, upcoming_deadline
from .news_sources import collect_fpl_changes, fpl_baseline
from .player_profile import render_player_profile
from .telegram import TelegramClient

BASELINE = STATE / "telegram_news_baseline.json"
PENDING = STATE / "telegram_news_pending.json"
RECEIPTS = STATE / "telegram_news_deliveries.json"
SHARED = STATE / "news_deliveries.json"
OUTPUT = ROOT / "output" / "telegram-news"
STALE_AFTER = timedelta(hours=8)


def in_window(cron: str | None) -> bool:
    """Route by the exact GitHub triggering cron, not a delayed runner clock."""
    if (cron or "").strip() == "15 5 * * *":
        return True  # existing 05:15 backup; never an extra news edition
    match = re.fullmatch(r"0 (\d{1,2}) \* \* \*", (cron or "").strip())
    return bool(match and 5 <= int(match.group(1)) <= 22)


def _player(snapshot, entry):
    found = [p for p in snapshot.players
             if snapshot.photo_code(p) == entry["photo_code"]
             and snapshot.team_code(p) == entry["club_code"]
             and snapshot.name(p) == entry["player_name"]
             and isinstance(p.get("id"), int)]
    if len(found) != 1:
        raise RuntimeError("Official player/current club join is not unique")
    return found[0]


def _version(player, kind):
    """No generation time/date in version: stable across unchanged news."""
    if kind == "price":
        values = (player.get("id"), player.get("team"), player.get("now_cost"))
    elif kind == "availability":
        values = (player.get("id"), player.get("team"), player.get("status"),
                  player.get("news"), player.get("chance_of_playing_next_round"),
                  player.get("chance_of_playing_this_round"))
    else:
        raise ValueError("Unsupported official FPL news topic")
    return sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()[:24]


def _copy(snapshot, entry, player, now, *, edited=False):
    gw = snapshot.gameweek()
    deadline = upcoming_deadline(snapshot)
    if not gw or deadline is None or deadline <= now:
        raise RuntimeError("Next actionable FPL deadline unverified/passed")
    matches = snapshot.fixtures_for_gameweek(player, gw)
    if not matches or any(not opp or not code or fdr not in (1, 2, 3, 4, 5)
                          or venue not in ("H", "A")
                          for opp, venue, fdr, code in matches):
        raise RuntimeError("Official upcoming opponent or fixture missing")
    target = ", ".join(f"{op} ({ha})" for op, ha, _, _ in matches)
    name = snapshot.name(player)
    old = entry.get("old") or {}
    kind = entry["kind"]
    if kind == "price":
        before, after = old.get("now_cost"), player.get("now_cost")
        if type(before) is not int or type(after) is not int or before == after:
            raise RuntimeError("Price movement lacks previous real FPL snapshot")
        direction = "RISE" if after > before else "FALL"
        headline = f"GW{gw} • CONFIRMED PRICE {direction}"
        fact = f"{name}: £{before/10:.1f}m → £{after/10:.1f}m on FPL."
        action = "HOLD" if after > before else "MONITOR"
    elif kind == "availability":
        flag = {"a": "AVAILABLE", "d": "DOUBT", "i": "INJURY FLAG",
                "s": "SUSPENDED", "u": "UNAVAILABLE"}
        status = player.get("status")
        if status not in flag:
            raise RuntimeError("Official FPL status unknown")
        changed = ("status", "news", "chance_of_playing_next_round",
                   "chance_of_playing_this_round")
        if not any(old.get(field) != player.get(field) for field in changed):
            raise RuntimeError("No verified changed official FPL status/news")
        headline = f"GW{gw} • PLAYER AVAILABILITY UPDATE"
        fact = f"{name}: FPL status {flag[status].lower()}."
        note = " ".join(str(player.get("news") or "").split())
        if note:
            fact += f" {note[:100].rstrip()}."
        action = "HOLD" if status == "a" else "MONITOR"
    else:
        raise RuntimeError("News edition is not a sourced official FPL change")
    if edited:
        headline = "UPDATED • " + headline
    caption = "\n".join([
        headline,
        fact,
        f"Next GW: {target}; check confirmed squad news.",
        f"{action} {name}; verify minutes before the deadline.",
        f"#FPL #FantasyPremierLeague #FPLVortex #GW{gw}",
    ])
    if len(caption.splitlines()) != 5 or len(caption) > 1024:
        raise RuntimeError("Telegram image caption must contain exactly five short lines")
    return headline, caption, action


def _artwork(snapshot, player, title, caption, action, target):
    """Approved pinned blue master; real portrait, crest, and five GW fixtures."""
    target.parent.mkdir(parents=True, exist_ok=True)
    article = Content(
        kind="news_profile", title=title, kicker="FPL VORTEX",
        cards=(Card(snapshot.name(player), snapshot.team(player), action, (),
                    snapshot.photo_code(player), snapshot.team_code(player)),),
        verdict=action, caption=caption, data_at=snapshot.fetched_at.isoformat(),
        gw=snapshot.gameweek(), footer="")
    render_player_profile(article, snapshot, target)
    with Image.open(target) as verified:
        if verified.size != (1920, 1080) or verified.format != "PNG":
            raise RuntimeError("Original-branded news graphic failed 1920x1080 PNG QA")
        verified.verify()


def _story_kind(story):
    kind = story.identity.split(":", 1)[0]
    if kind not in ("availability", "price"):
        raise RuntimeError("Unknown FPL news category")
    return kind


def run(cron=None, now=None, snapshot=None, telegram=None, renderer=None):
    """Exactly one new or edited news image at most; no generic hourly filler."""
    if not in_window(cron):
        return {"status": "outside-window", "posted": 0, "edited": 0}
    if os.getenv("FPL_PUBLISH_PAUSED", "false").lower() == "true":
        return {"status": "paused", "posted": 0, "edited": 0}
    if os.getenv("UNIFIED_NEWS_ENABLED", "false").lower() == "true":
        # The existing shared Telegram/Discord FPL news queue owns these
        # topics when enabled. Never have two news lanes send the same fact.
        return {"status": "shared-news-owns-topic", "posted": 0, "edited": 0}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("News snapshot time requires timezone")
    snapshot = snapshot or collect_snapshot()
    baseline = read_state(BASELINE)
    if not BASELINE.exists():
        write_state(BASELINE, fpl_baseline(snapshot))
        print("FPL NEWS: initialized real official baseline; not backfilling old news")
        return {"status": "baseline-initialized", "posted": 0, "edited": 0}

    pending = read_state(PENDING)
    receipts = read_state(RECEIPTS)
    shared = read_state(SHARED)
    for story in collect_fpl_changes(snapshot, baseline, now):
        player = _player(snapshot, {
            "photo_code": story.photo_code, "club_code": story.club_code,
            "player_name": story.player_name})
        kind = _story_kind(story)
        topic = f"2026-27:GW{snapshot.gameweek()}:news:{kind}:{player['id']}"
        version = _version(player, kind)
        previous = receipts.get(topic, {})
        if previous.get("content_version") == version and previous.get("telegram_message_id"):
            continue
        if shared.get(story.identity, {}).get("telegram_message_id"):
            continue  # this exact verified item already delivered by shared news
        pending[topic] = {
            "identity": story.identity, "player_name": story.player_name,
            "photo_code": story.photo_code, "club_code": story.club_code,
            "kind": kind, "old": baseline.get(str(player["id"]), {}),
            "first_seen": now.isoformat(), "content_version": version,
        }
    write_state(BASELINE, fpl_baseline(snapshot))
    write_state(PENDING, pending)

    posted = edited = held = 0
    for topic, record in list(pending.items()):
        try:
            seen = datetime.fromisoformat(record["first_seen"].replace("Z", "+00:00"))
            if seen.tzinfo is None or not timedelta(0) <= now - seen <= STALE_AFTER:
                pending.pop(topic, None)
                continue
            if shared.get(record["identity"], {}).get("telegram_message_id"):
                pending.pop(topic, None)
                continue
            player = _player(snapshot, record)
            if _version(player, record["kind"]) != record["content_version"]:
                # Source changed again before publication: never publish a
                # stale cached "injured" or "available" claim.
                pending.pop(topic, None)
                continue
            existing = receipts.get(topic, {})
            if existing.get("content_version") == record["content_version"] and existing.get("telegram_message_id"):
                pending.pop(topic, None)
                continue
            is_update = bool(existing.get("telegram_message_id"))
            title, caption, action = _copy(snapshot, record, player, now, edited=is_update)
            file = OUTPUT / f"gw{snapshot.gameweek()}_{record['identity'].replace(':', '_')}.png"
            (renderer or _artwork)(snapshot, player, title, caption, action, file)
            client = telegram or TelegramClient()
            if is_update:
                # Don't send a second post for the same player/topic/GW.
                # If Telegram won't allow editing, HOLD rather than reposting.
                mid = client.edit_shared_png(file, caption, int(existing["telegram_message_id"]))
            else:
                mid = client.send_shared_png(file, caption, title, snapshot.gameweek())
            if type(mid) is not int or mid <= 0:
                raise RuntimeError("Telegram returned no valid send/edit receipt")
            receipts[topic] = {
                "delivered": True, "telegram_message_id": mid,
                "gameweek": snapshot.gameweek(), "player_id": player["id"],
                "topic": topic, "content_version": record["content_version"],
                "source_identity": record["identity"],
                "published_at": existing.get("published_at") or now.isoformat(),
                "last_updated_at": now.isoformat(),
                "edit_count": int(existing.get("edit_count") or 0) + int(is_update),
            }
            write_state(RECEIPTS, receipts)  # checkpoint confirmed message ID
            pending.pop(topic, None)
            posted += int(not is_update)
            edited += int(is_update)
            print(f"FPL NEWS {'EDITED' if is_update else 'POSTED'}: "
                  f"GW{snapshot.gameweek()}, Telegram message_id={mid}")
            break
        except (RuntimeError, ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
            held += 1
            from .telegram import TelegramDeliveryError
            if isinstance(exc, TelegramDeliveryError):
                print(str(exc))
            # Log only a fixed diagnostic category; never expose API responses,
            # bot tokens, destination identifiers, or player-specific payloads.
            reason = "unknown-runtime"
            if isinstance(exc, (KeyError, AttributeError, TypeError)):
                reason = "unexpected-data-shape"
            elif isinstance(exc, OSError):
                reason = "file-or-renderer-io"
            elif isinstance(exc, ValueError):
                reason = "invalid-value-or-receipt"
            elif isinstance(exc, RuntimeError):
                safe_reasons = {
                    "Official player/current club join is not unique": "ambiguous-player-club",
                    "Next actionable FPL deadline unverified/passed": "deadline-unverified",
                    "Official upcoming opponent or fixture missing": "fixture-unverified",
                    "Price movement lacks previous real FPL snapshot": "price-baseline-missing",
                    "Official FPL status unknown": "player-status-unknown",
                    "No verified changed official FPL status/news": "no-verified-news-change",
                    "News edition is not a sourced official FPL change": "source-verification-failed",
                    "Telegram image caption must contain exactly five short lines": "caption-validation",
                    "Original-branded news graphic failed 1920x1080 PNG QA": "graphic-validation",
                    "Unknown FPL news category": "unknown-news-category",
                    "Telegram returned no valid send/edit receipt": "telegram-receipt-missing",
                }
                reason = safe_reasons.get(str(exc), "telegram-or-runtime-failure")
            print(f"FPL NEWS HELD: {reason}; no delivery claimed")
            # Keep pending for bounded retries; never issue a duplicate.
    write_state(PENDING, pending)
    return {"status": "checked", "posted": posted, "edited": edited,
            "held": held, "pending": len(pending)}


def main():
    print(json.dumps(run(cron=os.getenv("SCHEDULED_CRON")), sort_keys=True))


if __name__ == "__main__":
    main()
