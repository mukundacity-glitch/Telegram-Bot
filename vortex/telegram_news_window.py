"""FPL VORTEX Telegram news monitoring, 06:00-21:00 Eastern, in EXISTING job.

Official FPL *changes* only; exact approved master and actual portrait/crest;
one graphic + five-line caption per new verified item, not hourly filler.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def in_window(cron):
    match = re.fullmatch(r"0 (\d{1,2}) \* \* \*", (cron or "").strip())
    return bool(match and 6 <= int(match.group(1)) <= 21)


def _player(snapshot, entry):
    found = [p for p in snapshot.players
             if snapshot.photo_code(p) == entry["photo_code"]
             and snapshot.team_code(p) == entry["club_code"]
             and snapshot.name(p) == entry["player_name"]]
    if len(found) != 1:
        raise RuntimeError("Official player/club identity not unique")
    return found[0]


def _copy(snapshot, entry, player, now):
    gw = snapshot.gameweek()
    deadline = upcoming_deadline(snapshot)
    if not gw or deadline is None or deadline <= now:
        raise RuntimeError("Verified actionable deadline missing")
    matches = snapshot.fixtures_for_gameweek(player, gw)
    if not matches or any(not opp or not code or fdr not in (1, 2, 3, 4, 5)
                          for opp, venue, fdr, code in matches):
        raise RuntimeError("Verified next-GW fixture missing")
    target = ", ".join(f"{opp}({venue})" for opp, venue, fdr, code in matches)
    name = snapshot.name(player)
    old = entry.get("old", {})
    if entry["identity"].startswith("price:"):
        before, after = old.get("now_cost"), player.get("now_cost")
        if type(before) is not int or type(after) is not int or before == after:
            raise RuntimeError("No dated prior price evidence")
        direction = "RISE" if after > before else "FALL"
        headline = f"GW{gw} • CONFIRMED PRICE {direction}"
        fact = f"{name}: £{before/10:.1f}m → £{after/10:.1f}m."
        action = "HOLD" if after > before else "MONITOR"
    else:
        status = player.get("status")
        labels = {"a": "AVAILABLE", "d": "DOUBT", "i": "INJURY FLAG",
                  "s": "SUSPENDED", "u": "UNAVAILABLE"}
        if status not in labels:
            raise RuntimeError("Missing official FPL player status")
        changes = ("status", "news", "chance_of_playing_next_round",
                   "chance_of_playing_this_round")
        if not any(old.get(k) != player.get(k) for k in changes):
            raise RuntimeError("Availability update no longer verified")
        headline = f"GW{gw} • PLAYER STATUS UPDATE"
        fact = f"{name}: FPL status {labels[status].lower()}."
        action = "HOLD" if status == "a" else "MONITOR"
    caption = "\n".join((
        headline,
        fact,
        f"Next GW: {target}. Check updated squad news.",
        f"{action} {name}; confirm minutes before the deadline.",
        f"#FPL #FantasyPremierLeague #FPLVortex #GW{gw}",
    ))
    if len(caption.splitlines()) != 5 or len(caption) > 1024:
        raise RuntimeError("Caption must be exactly five lines and Telegram-sized")
    return headline, caption, action


def _artwork(snapshot, player, headline, caption, action, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    article = Content(
        kind="news_profile", title=headline, kicker="FPL VORTEX",
        cards=(Card(snapshot.name(player), snapshot.team(player), action, (),
                    snapshot.photo_code(player), snapshot.team_code(player)),),
        verdict=action, caption=caption, data_at=snapshot.fetched_at.isoformat(),
        gw=snapshot.gameweek(), footer="")
    render_player_profile(article, snapshot, path)
    with Image.open(path) as im:
        if im.size != (1920, 1080):
            raise RuntimeError("Final Telegram graphic is not 1920x1080")
        im.verify()


def run(cron=None, now=None, snapshot=None, telegram=None, renderer=None):
    if not in_window(cron):
        return {"status": "outside-window", "posted": 0}
    if os.getenv("FPL_PUBLISH_PAUSED", "false").lower() == "true":
        return {"status": "paused", "posted": 0}
    now = now or datetime.now(timezone.utc)
    snapshot = snapshot or collect_snapshot()
    old = read_state(BASELINE)
    if not BASELINE.exists():
        write_state(BASELINE, fpl_baseline(snapshot))
        return {"status": "baseline-initialized-no-backfill", "posted": 0}
    pending = read_state(PENDING)
    receipts = read_state(RECEIPTS)
    shared = read_state(SHARED)
    changes = collect_fpl_changes(snapshot, old, now)
    for story in changes:
        key = f"2026-27:GW{snapshot.gameweek()}:news:{story.identity}"
        if (key not in pending and key not in receipts
                and not shared.get(story.identity, {}).get("telegram_message_id")):
            player = _player(snapshot, {
                "photo_code": story.photo_code,
                "club_code": story.club_code,
                "player_name": story.player_name})
            pending[key] = {
                "identity": story.identity, "player_name": story.player_name,
                "photo_code": story.photo_code, "club_code": story.club_code,
                "old": old.get(str(player["id"]), {}), "seen": now.isoformat(),
            }
    write_state(BASELINE, fpl_baseline(snapshot))
    write_state(PENDING, pending)
    posted = 0
    held = 0
    for key, entry in list(pending.items()):
        if (receipts.get(key, {}).get("telegram_message_id")
                or shared.get(entry["identity"], {}).get("telegram_message_id")):
            pending.pop(key)
            continue
        try:
            seen = datetime.fromisoformat(entry["seen"].replace("Z", "+00:00"))
            if now - seen > timedelta(hours=8):
                pending.pop(key)
                continue
            player = _player(snapshot, entry)
            title, caption, action = _copy(snapshot, entry, player, now)
            image = OUTPUT / f"gw{snapshot.gameweek()}_{key.replace(':', '_')}.png"
            (renderer or _artwork)(snapshot, player, title, caption, action, image)
            client = telegram or TelegramClient()
            message_id = client.send_shared_png(image, caption, title, snapshot.gameweek())
            if type(message_id) is not int or message_id <= 0:
                raise RuntimeError("Telegram did not return a valid message ID")
            receipts[key] = {"delivered": True, "telegram_message_id": message_id,
                             "gameweek": snapshot.gameweek(),
                             "published_at": now.isoformat(), "player_id": player["id"]}
            write_state(RECEIPTS, receipts)
            pending.pop(key)
            print(f"TELEGRAM NEWS POSTED: message={message_id}, GW={snapshot.gameweek()}")
            posted += 1
            break  # Do not flood channel: maximum one real news story per check.
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            held += 1
            print(f"TELEGRAM NEWS HELD: {type(exc).__name__}; no post claimed")
    write_state(PENDING, pending)
    return {"status": "checked", "posted": posted, "held": held,
            "pending": len(pending)}


def main():
    print(json.dumps(run(cron=os.getenv("SCHEDULED_CRON")), sort_keys=True))


if __name__ == "__main__":
    main()
