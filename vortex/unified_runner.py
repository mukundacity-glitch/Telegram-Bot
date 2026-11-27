"""Weekly four-club rotation planner queue; retired news rules remain historical."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from .fpl import collect_snapshot
from .syndication import DiscordWebhookClient, NewsPost, load_journal, publish_shared, save_journal
from .telegram import TelegramClient
from .queue_retry import ATTEMPTS, failure_reason, verified_caption

BASE = Path(__file__).resolve().parents[1] / "state"
PENDING = BASE / "news_pending.json"
READY = BASE / "rotation_initialized.json"
RECEIPTS = BASE / "news_deliveries.json"
NEWS_OUTPUT = BASE.parent / "output" / "news"
ET = ZoneInfo('America/New_York')


def rotation_due(now):
    """Friday 20:00 ET, using the existing Friday rotation publication slot."""
    local = now.astimezone(ET)
    return local.weekday() == 4 and (20, 0) <= (local.hour, local.minute) < (20, 15)


def rotation_research_due(now):
    local = now.astimezone(ET)
    return local.weekday() == 4 and (15, 28) <= (local.hour, local.minute) < (15, 40)


def rotation_research_valid(snapshot, now, state):
    from .autonomous_schedule import season_id
    from .research_gap import verified_gap
    local = now.astimezone(ET)
    post = local.replace(hour=20, minute=0, second=0, microsecond=0)
    row = state.get('research', {})
    return (row.get('date') == local.date().isoformat()
            and row.get('gw') == snapshot.gameweek()
            and row.get('season') == season_id(snapshot, now)
            and verified_gap(row.get('checked_at'), post)
            and verified_gap(row.get('checked_at'), now))


def prepare_rotation_research(snapshot, now, *, clock=None):
    if not rotation_research_due(now):
        return False
    from .rotation_planner import build_rotation_plan
    from .autonomous_schedule import season_id
    plan = build_rotation_plan(snapshot, now)
    state = _read(READY)
    state.update(initialized=True, research={
        'date': now.astimezone(ET).date().isoformat(), 'gw': plan.gameweek,
        'season': season_id(snapshot, now), 'checked_at': (clock() if clock else now).isoformat(),
        'club_ids': [club['id'] for club in plan.clubs],
    })
    save_journal(READY, state)
    return True


def rotation_week_claimed(receipts, pending, now):
    """Legacy date-keyed receipts also count; never replay an uncertain send."""
    week = now.astimezone(ET).date().isocalendar()[:2]
    for identity, row in {**receipts, **pending}.items():
        if not identity.startswith('rotation:'):
            continue
        try:
            date = datetime.fromisoformat(identity.split(':')[1]).date()
        except (ValueError, IndexError):
            raise ValueError('Unreadable rotation receipt identity')
        if date.isocalendar()[:2] == week and (identity in pending or any(
            row.get(k) for k in ('delivered', 'discord_delivered', 'telegram_send_pending', 'discord_send_pending')
        )):
            return True
    return False


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


def run(dry_run: bool = False, *, snapshot=None,
        telegram=None, discord=None, now: datetime | None = None,
        max_posts: int | None = None, drain=False, pending_only=False, audit_rows=None, live_clock=None) -> dict[str, int]:
    current_time = now or datetime.now(timezone.utc)
    clock = live_clock or ((lambda: now) if now is not None else (lambda: datetime.now(timezone.utc)))
    if current_time.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    snapshot = snapshot or collect_snapshot()
    pending = _read(PENDING)
    receipt = load_journal(RECEIPTS)
    retired = [key for key in pending if not key.startswith("rotation:")]
    pending = {key: value for key, value in pending.items() if key.startswith("rotation:")}
    from .rotation_planner import build_rotation_plan
    try:
        rotation = build_rotation_plan(snapshot, current_time)
    except (ValueError, KeyError, TypeError):
        rotation = None  # Never invent teams or FDR when official data is incomplete.

    for identity in list(pending):
        if (identity.startswith("rotation:") and
                (rotation is None or identity != rotation.identity)):
            pending.pop(identity)  # Old-day art cannot be replayed as fresh data.

    cap = max_posts if max_posts is not None else int(os.getenv("MAX_NEWS_PER_RUN", "2"))
    if not 0 <= cap <= 6:
        raise ValueError("MAX_NEWS_PER_RUN must be between 0 and 6")
    initial = not READY.exists()
    research_ok = rotation_research_valid(snapshot, current_time, _read(READY))

    if (not initial and rotation is not None and not pending_only and rotation_due(current_time) and research_ok
            and not rotation_week_claimed(receipt, pending, current_time)):
        identity = rotation.identity
        if identity not in pending and not (
            receipt.get(identity, {}).get("delivered") and
            receipt.get(identity, {}).get("discord_delivered")
        ):
            board = NewsPost(identity, rotation.title, rotation.caption,
                             rotation.gameweek, source="Official FPL",
                             source_url="https://fantasy.premierleague.com/")
            pending = {identity: asdict(board), **pending}
    summary = {"official_changes": 0, "reported_headlines": 0,
               "retired_status_cards": len(retired),
               "rotation_due": bool(rotation and rotation.identity in pending),
               "pending": len(pending), "sent": 0, "warmup": int(initial)}
    if dry_run:
        return summary  # Absolutely no state writes, Telegram or Discord calls

    if initial:
        save_journal(READY, {"initialized": True})
        save_journal(PENDING, pending)
        return summary
    save_journal(PENDING, pending)

    eligible = [(key, row) for key, row in pending.items()
                if rotation_due(current_time) and research_ok and row.get("attempts", 0) < ATTEMPTS]
    if drain:
        eligible.sort(key=lambda item: item[1].get("queued_at", ""))
    if not eligible or (cap == 0 and not drain):
        return summary
    if drain:
        telegram = telegram or TelegramClient()
        if discord is None:
            try:
                discord = DiscordWebhookClient()
            except ValueError:
                print("Discord credential unavailable; continuing Telegram delivery")
    elif telegram is None or discord is None:
        telegram, discord = _create_clients()
    failures: list[str] = []
    from .telegram_spacing import blocked_until
    for identity, data in (eligible if drain else eligible[:cap]):
        if blocked_until(datetime.now(timezone.utc)):
            break
        generated = False
        try:
            # Persisted media attachments are rebuilt from verified inputs.
            record = NewsPost(**{k: data[k] for k in (
                "identity", "title", "caption", "gameweek", "image", "source", "source_url"
            )} | {k: data[k] for k in ("player_name", "team_name", "photo_code", "club_code")
                  if k in data})
            if drain:
                record = replace(record, caption=verified_caption(record.title, record.caption))
            if rotation is None or rotation.identity != record.identity:
                raise RuntimeError("Stale rotation board must not publish")
            image_path = NEWS_OUTPUT / f"{record.identity.replace(':', '_')}.png"
            from .rotation_planner import render_rotation_plan
            from .graphic_numbers import stamp
            render_rotation_plan(rotation, image_path)
            stamp(image_path, 'news-rotation-planner')
            record = replace(record, image=image_path)
            generated = True
            delivered_at = clock()
            if not rotation_due(delivered_at) or not rotation_research_valid(snapshot, delivered_at, _read(READY)):
                break  # The window elapsed while rendering; never send late.
            result = publish_shared(record, RECEIPTS, telegram, discord,
                                    send_discord=discord is not None, now_iso=delivered_at.isoformat())
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            reason = failure_reason(exc)
            failures.append(f"{identity}: {reason}")
            data.update(attempts=data.get("attempts", 0) + 1, error=reason,
                        attempted_at=current_time.isoformat())
            if audit_rows is not None:
                saved = load_journal(RECEIPTS).get(identity, {})
                audit_rows.append({"post_id": identity, "type": "news",
                                   "trigger": data.get("queued_at", current_time.isoformat()),
                                   "status": "FAILED" if data["attempts"] >= ATTEMPTS else "RETRY",
                                   "generated": generated, "attempts": data["attempts"], "error": reason,
                                   "telegram_message_id": saved.get("telegram_message_id"),
                                   "timestamp": current_time.isoformat()})
            # A permanently unrenderable first item must not starve every
            # newer verified news story when MAX_NEWS_PER_RUN is one.
            # Move it to the back of the durable queue; the next scheduled
            # check retries its missing platform(s) using the same identity.
            pending.pop(identity, None)
            pending[identity] = data
            save_journal(PENDING, pending)
            continue
        if audit_rows is not None:
            audit_rows.append({"post_id": identity, "type": "news",
                               "trigger": data.get("queued_at", current_time.isoformat()),
                               "status": "POSTED" if result.get("delivered") else "RETRY",
                               "generated": generated, "attempts": data.get("attempts", 0) + 1,
                               "telegram_message_id": result.get("telegram_message_id"),
                               "timestamp": current_time.isoformat()})
        if result.get("delivered") and (result.get("discord_delivered") or drain):
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
