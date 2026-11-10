"""Single canonical news queue for Telegram and Discord, initially opt-in.

Safe dry-run: no writes and no external posts.
Production: checkpoint baseline and pending queue before independent delivery.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .fpl import collect_snapshot
from .news_sources import collect_fpl_changes, collect_reported_headlines, fpl_baseline
from .news_graphics import render_news_card
from .syndication import DiscordWebhookClient, NewsPost, load_journal, publish_shared, save_journal
from .telegram import TelegramClient

BASE = Path(__file__).resolve().parents[1] / "state"
PENDING = BASE / "news_pending.json"
BASELINE = BASE / "news_baseline.json"
SEEN = BASE / "news_seen.json"
RECEIPTS = BASE / "news_deliveries.json"
NEWS_OUTPUT = BASE.parent / "output" / "news"


def _expire_undelivered_old_news(pending, receipt, now, gameweek, *, max_hours=20):
    """Clear superseded editorial queue stories before any attempt to post them.

    The stored caption contains the explicit official-data or RSS timestamp.
    Do not silently discard an uncertain/partial upload: such records require
    the separate destination-receipt reconciliation procedure.
    """
    expired = []
    for identity, record in list(pending.items()):
        if not isinstance(record, dict):
            continue
        delivery = receipt.get(identity, {})
        if delivery.get("delivered") or delivery.get("discord_delivered"):
            continue  # An existing one-platform receipt must not be lost.
        source_times = re.findall(r"20\d{2}-\d{2}-\d{2} \d{2}:\d{2} UTC",
                                  str(record.get("caption") or ""))
        stamped = None
        if source_times:
            try:
                stamped = datetime.strptime(source_times[-1], "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        wrong_gw = record.get("gameweek") != gameweek
        too_old = bool(stamped is not None and (now - stamped) > timedelta(hours=max_hours))
        if wrong_gw or too_old:
            pending.pop(identity, None)
            expired.append(identity)
    return expired


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"News state file {path.name} is unreadable; refusing replay") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Invalid news state {path.name}")
    return value


def _create_clients() -> tuple[TelegramClient, DiscordWebhookClient]:
    # Explicitly require both channels at cutover; do not pretend dual posting
    # works when a destination has no credentials.
    return TelegramClient(), DiscordWebhookClient()


def run(dry_run: bool = False, *, snapshot=None, rss=None,
        telegram=None, discord=None, now: datetime | None = None,
        max_posts: int | None = None) -> dict[str, int]:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    snapshot = snapshot or collect_snapshot()
    prior = _read(BASELINE)
    prior_seen = _read(SEEN)
    pending = _read(PENDING)
    receipt = load_journal(RECEIPTS)

    official = collect_fpl_changes(snapshot, prior, current_time)
    reported = (rss if rss is not None else
                collect_reported_headlines(snapshot, current_time))
    stories = {s.identity: s for s in [*official, *reported]}
    cap = max_posts if max_posts is not None else int(os.getenv("MAX_NEWS_PER_RUN", "2"))
    if not 0 <= cap <= 6:
        raise ValueError("MAX_NEWS_PER_RUN must be between 0 and 6")
    initial = not BASELINE.exists() or not SEEN.exists()

    # First run is a warm-up, not a 16-feed backfill into live channels.
    if not initial:
        for ident, story in stories.items():
            if ident not in prior_seen and ident not in pending and not (
                receipt.get(ident, {}).get("delivered")
                and receipt.get(ident, {}).get("discord_delivered")
            ):
                pending[ident] = asdict(story) | {"image": None}
    summary = {"official_changes": len(official), "reported_headlines": len(reported),
               "pending": len(pending), "sent": 0, "warmup": int(initial)}
    if dry_run:
        return summary  # Absolutely no state writes, Telegram or Discord calls

    if initial:
        save_journal(BASELINE, fpl_baseline(snapshot))
        seen = {ident: current_time.isoformat() for ident in stories}
        save_journal(SEEN, seen)
        return summary

    # Remove aged news from the durable backlog before attempting any upload.
    # Retired records remain in the seen ledger, so stale RSS headlines cannot
    # regenerate or crowd out new verified FPL changes on the next heartbeat.
    expired = _expire_undelivered_old_news(pending, receipt, current_time, snapshot.gameweek())
    summary["expired_unposted"] = len(expired)
    summary["pending"] = len(pending)

    # Preserve a bounded source-seen ledger; pending + delivered receipts are durable.
    seen = {k: v for k, v in prior_seen.items() if isinstance(v, str)}
    seen.update({k: current_time.isoformat() for k in stories})
    if len(seen) > 5000:
        seen = dict(sorted(seen.items(), key=lambda pair: pair[1])[-3500:])
    save_journal(SEEN, seen)
    save_journal(BASELINE, fpl_baseline(snapshot))
    save_journal(PENDING, pending)

    if not pending or cap == 0:
        return summary
    if telegram is None or discord is None:
        telegram, discord = _create_clients()
    failures: list[str] = []
    for identity, data in list(pending.items())[:cap]:
        # Persisted media attachments are not supported by the news queue.
        record = NewsPost(**{k: data[k] for k in (
            "identity", "title", "caption", "gameweek", "image", "source", "source_url"
        )} | {k: data.get(k) for k in ("player_name", "team_name", "photo_code", "club_code")
             if k in data})
        try:
            # One immutable story ID and ONE image are supplied to both.
            # The news lane never silently falls back to text-only delivery.
            from dataclasses import replace
            image_path = NEWS_OUTPUT / f"{record.identity.replace(':', '_')}.png"
            if os.getenv("FPL_ENRICHED_VISUALS_ENABLED", "false").lower() == "true":
                # Keep original approved blue slide and genuine current player
                # portrait/crest. Source and technical verification never enter
                # the image; the same exact caption accompanies both channels.
                from .content import Card, Content
                from .player_profile import render_player_profile
                if not record.photo_code or not record.club_code or not record.player_name:
                    raise RuntimeError("Verified player identity and club portrait required")
                tag = "PRICE CHANGE" if record.identity.startswith("price:") else "STATUS CHANGE"
                visual = Content(
                    kind="news_profile", title=tag, kicker="GW NEWS",
                    cards=(Card(record.player_name, record.team_name, tag, (),
                                record.photo_code, record.club_code),),
                    verdict="MONITOR", caption=record.caption,
                    data_at="", gw=record.gameweek, footer="")
                render_player_profile(visual, snapshot, image_path)
            else:
                render_news_card(record, image_path)
            record = replace(record, image=image_path)
            result = publish_shared(record, RECEIPTS, telegram, discord,
                                    now_iso=current_time.isoformat())
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            failures.append(f"{identity}: {type(exc).__name__}")
            # A permanently unrenderable first item must not starve every
            # newer verified news story when MAX_NEWS_PER_RUN is one.
            # Move it to the back of the durable queue; the next scheduled
            # check retries its missing platform(s) using the same identity.
            pending.pop(identity, None)
            pending[identity] = data
            save_journal(PENDING, pending)
            continue
        if result.get("delivered") and result.get("discord_delivered"):
            pending.pop(identity, None)
            save_journal(PENDING, pending)
            summary["sent"] += 1
    summary["pending"] = len(pending)
    if failures:
        raise RuntimeError("Some news delivery attempts failed: " + ", ".join(failures))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Collect live sources without publishing or writing state")
    args = parser.parse_args()
    if not args.dry_run and os.getenv("UNIFIED_NEWS_ENABLED", "false").lower() != "true":
        print("Unified news publishing is disabled until approved cutover")
        return 0
    try:
        summary = run(dry_run=args.dry_run)
        print(json.dumps(summary, sort_keys=True))
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"Unified news failed: {type(exc).__name__} (see source health / state)")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
