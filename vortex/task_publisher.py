"""Scheduled four-task migration into the EXISTING FPL VORTEX GitHub workflow.

One source-derived PNG and identical copy-ready caption to Telegram + Discord.
No new task or job schedule. All writes to independent durable receipt ledgers.
Default OFF until stage-delivery parity is confirmed; never send test posts to
production automatically.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .bot import ROOT, STATE, OUTPUT, read_state, write_state
from .chatgpt_task_editions import CRONS, EDITIONS, COVERED_BY_ORIGINAL, due_editions, generate_edition
from .fpl import collect_snapshot, upcoming_deadline
from .publication_rules import semantic_fingerprint
from .publish_checks import render_checked
from .syndication import NewsPost, DiscordWebhookClient, publish_shared
from .telegram import TelegramClient
from .content import Content

RECEIPTS = STATE / "deliveries.json"
TASK_VERSIONS = STATE / "ported_task_versions.json"


def _original_was_served(deliveries: dict, edition, now: datetime, gw: int) -> bool:
    original = COVERED_BY_ORIGINAL.get(edition.kind)
    if not original:
        return False
    # Don't publish the same matchup/transfer board one hour later.
    # If the original is Telegram-only, the 4-task bridge must not create a
    # different Discord PNG and falsely call it the SAME dual-platform post.
    day = now.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    for key in (f"{day}:{original}:GW{gw}", f"{day}:{original}"):
        if deliveries.get(key, {}).get("delivered"):
            return True
    return False


def _topic(edition, gw: int) -> str:
    return f"2026-27:GW{gw}:{edition.task}:{edition.label}"


def _get_editions(now, cron: str | None, selected_name: str | None):
    if selected_name:
        candidates = tuple(e for e in EDITIONS if e.label == selected_name)
        if len(candidates) != 1:
            raise ValueError("Unknown or ambiguous original ChatGPT edition")
        # Manager-requested manual re-run is safe: receipt/topic guard is still
        # enforced and only real changed facts can be a new content version.
        return candidates
    return due_editions(now, cron)


def run(*, cron: str | None = None, selected_name: str | None = None,
        dry_run: bool = False, now: datetime | None = None,
        snapshot=None, telegram=None, discord=None) -> dict:
    now = now or datetime.now(timezone.utc)
    due = _get_editions(now, cron, selected_name)
    if not due:
        return {"due": [], "published": 0, "skipped": 0}
    # Scheduling is active in the original legacy bot even while migration
    # is off. Never accidentally publish only one of two target channels.
    enabled = (
        os.getenv("FPL_PORTED_TASKS_ENABLED", "false").lower() == "true"
        and os.getenv("DUAL_PUBLISH_ENABLED", "false").lower() == "true"
        and os.getenv("FPL_ENRICHED_VISUALS_ENABLED", "false").lower() == "true"
    )
    if not dry_run and not enabled:
        print("FOUR TASKS STAGED BUT NOT ENABLED: dual-channel verified branding is required")
        return {"due": [e.label for e in due], "published": 0,
                "skipped": len(due), "reason": "staging"}
    source = snapshot or collect_snapshot()
    deadline = upcoming_deadline(source)
    if deadline is None or deadline <= now:
        raise RuntimeError("No independently verified future FPL gameweek deadline")
    gw = source.gameweek()
    deliveries = read_state(RECEIPTS)
    versions = read_state(TASK_VERSIONS)
    report = {"due": [e.label for e in due], "published": 0,
              "skipped": 0, "held": [], "version_updates": 0}
    for edition in due:
        if _original_was_served(deliveries, edition, now, gw):
            print(f"ALREADY COVERED by original edition: {edition.label}")
            report["skipped"] += 1
            continue
        topic = _topic(edition, gw)
        prior = versions.get(topic, {})
        if not isinstance(prior, dict):
            raise RuntimeError("Invalid historical topic record; cannot risk reposting")
        try:
            post = generate_edition(edition, source, now, read_state(STATE / "prices.json"))
            if post.gw != gw:
                raise RuntimeError("Output GW mismatch vs official next deadline")
            # A press report requires genuinely new official player flags.
            # No manager quotes or invented injury updates are published.
            if not post.caption or len([part for part in post.caption.split()
                                         if part.startswith("#")]) != 4:
                raise RuntimeError("Four required FPL hashtags missing")
            canonical_version = semantic_fingerprint(post)
            identity = f"{topic}:{canonical_version[:16]}"
            receipt = deliveries.get(identity, {})
            if receipt.get("delivered") and receipt.get("discord_delivered"):
                print(f"ALREADY DELIVERED {topic} version {canonical_version[:8]}")
                report["skipped"] += 1
                continue
            if prior.get("version") == canonical_version and prior.get("confirmed"):
                print(f"ALREADY VERIFIED EDITION {topic}")
                report["skipped"] += 1
                continue
            if prior and not prior.get("confirmed", False) and prior.get("version") != canonical_version:
                raise RuntimeError("Previous topic version not fully delivered; resolve partial receipt first")
            if prior and prior.get("confirmed", False) and prior.get("version") != canonical_version:
                # Only actual content version changes can become a new post.
                post = replace(post, title="UPDATED • " + post.title)
                report["version_updates"] += 1
            if isinstance(post, Content) and len(post.cards) == 1:
                # The original single-player evidence table is preserved.
                post = replace(post, kind="elite")
            file = OUTPUT / f"ported_{edition.task}_{edition.label}_GW{gw}.png"
            if dry_run:
                print(f"READY {topic}: {len(post.cards) if hasattr(post, 'cards') else 0} real player cards; not sent")
                report["skipped"] += 1
                continue
            render_checked(post, source, file)
            if datetime.now(timezone.utc) >= deadline:
                raise RuntimeError("Deadline elapsed during graphic preparation")
            message = NewsPost(identity=identity, title=post.title,
                               caption=post.caption, gameweek=gw, image=file)
            try:
                result = publish_shared(message, RECEIPTS,
                                        telegram or TelegramClient(),
                                        discord or DiscordWebhookClient(),
                                        now_iso=now.isoformat())
            finally:
                fresh = read_state(RECEIPTS).get(identity, {})
                versions[topic] = {
                    "version": canonical_version,
                    "identity": identity,
                    "confirmed": bool(fresh.get("delivered")) and
                                 bool(fresh.get("discord_delivered")),
                    "published_at": now.isoformat(),
                    "last_player_ids": [c.photo_code for c in post.cards] if
                                       hasattr(post, "cards") else [],
                }
                write_state(TASK_VERSIONS, versions)
            deliveries = read_state(RECEIPTS)
            if not (result.get("delivered") and result.get("discord_delivered")):
                raise RuntimeError("Both actual posting receipts were not received")
            report["published"] += 1
            print(f"POSTED BOTH {topic} Telegram#{result.get('telegram_message_id')} "
                  f"Discord#{result.get('discord_message_id')}")
        except (ValueError, RuntimeError, OSError, TypeError) as exc:
            # No generic audience-facing story or fabricated asset on failure.
            report["held"].append({"edition": edition.label, "reason": type(exc).__name__})
            print(f"HOLD {topic}: {type(exc).__name__}", file=sys.stderr)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--edition", default=None, choices=[e.label for e in EDITIONS])
    args = parser.parse_args()
    outcome = run(cron=os.getenv("SCHEDULED_CRON"), selected_name=args.edition, dry_run=args.dry_run)
    print("Task edition status: " + str(outcome))
    return 1 if outcome.get("held") and not args.dry_run else 0


if __name__ == "__main__":
    raise SystemExit(main())
