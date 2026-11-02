"""Entry point for cron dispatch, Telegram delivery, and durable-state writes."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

from .content import generate
from .fpl import collect_snapshot, price_snapshot, upcoming_deadline
from .render import render
from .schedule import resolve_slot
from .telegram import TelegramClient
from .syndication import DiscordWebhookClient, NewsPost, publish_shared
from .editorial_dedup import check_revision, revision_record
from .publication_rules import publication_group

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
OUTPUT = ROOT / "output"


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Cannot safely read prior state at {path.name}") from error
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Invalid state format for {path.name}")
    return parsed


def write_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def run(requested: str, scheduled_cron: str | None = None) -> int:
    now = datetime.now(timezone.utc)
    # The GitHub "Run workflow" button is NOT how to turn on cron.
    # A manual AUTO selection must never send a test message or
    # accidentally post a duplicate at the wrong time.
    if requested == "auto" and not scheduled_cron:
        print("AUTO SCHEDULING CONFIGURED: no manual post. GitHub's scheduled "
              "cron events publish the appropriate slot automatically.")
        return 0
    slot = resolve_slot(requested, scheduled_cron, now)
    client = TelegramClient()
    if slot == "discover":
        connected_username = client.get_bot_username()
        print(f"GitHub secret connects to Telegram bot: @{connected_username}")
        if connected_username.casefold() != "fplvortexdailybot":
            print("WRONG BOT TOKEN: TELEGRAM_BOT_TOKEN does not belong to @FPLVortexDailyBot.", file=sys.stderr)
            return 1
        chats = client.discover_chats()
        for item in chats:
            print(f"Telegram chat: {item['title']} ({item['type']}) => chat id {item['id']}")
        if not chats:
            print("No pending chat messages found for @FPLVortexDailyBot. Send a NEW message such as 'hello' to the bot, then immediately run discover again. Check that another service is not polling the same bot.")
        return 0
    if slot == "test":
        client.send_text("🦁 FPL VORTEX Telegram delivery test ✅\nNo scheduled graphics have been activated by this test.")
        print("Telegram test delivered successfully")
        return 0

    preview_only = slot == "preview" or slot.startswith("preview-")
    dual_publish = os.getenv("DUAL_PUBLISH_ENABLED", "false").lower() == "true" and not preview_only
    if dual_publish:
        from .delivery_preflight import assert_dual_destinations
        try:
            assert_dual_destinations()
        except RuntimeError:
            # Preserve the PRE-EXISTING working Telegram schedule if the
            # Telegram repository lacks its own Discord webhook secret.
            # New migrated tasks still fail closed without both destinations.
            print("Discord credential not configured here; retaining legacy Telegram delivery")
            dual_publish = False
            # Telegram-only runs still require the real blue master, authentic
            # player/club imagery, and semantic cross-day duplicate checks.
            # Missing Discord credentials must NOT disable Telegram QA.
    publication_slot = "comparison" if slot == "preview" else slot.removeprefix("preview-") if preview_only else slot
    delivery_state_path = STATE / "deliveries.json"
    price_state_path = STATE / "prices.json"
    delivery_state = read_state(delivery_state_path)
    editorial_path = STATE / "editorial_versions.json"
    editorial = read_state(editorial_path)
    key = f"{now.astimezone(ZoneInfo('America/New_York')).date()}:{slot}"
    if scheduled_cron and not preview_only and slot != "projections" and delivery_state.get(key, {}).get("delivered") and (
        not dual_publish or delivery_state.get(key, {}).get("discord_delivered")
    ):
        print(f"ALREADY DELIVERED {key}; skipping duplicate")
        return 0

    try:
        snapshot = collect_snapshot()
        previous_prices = read_state(price_state_path)
        article = generate(publication_slot, snapshot, now, previous_prices)
        projection_history_path = STATE / "projection_history.json"
        projection_history = {}
        if publication_slot == "projections":
            from .projection_trends import compare, require_publishable
            # Do not render or acknowledge an all-unverified FDR-only board.
            require_publishable(article)
            projection_history = read_state(projection_history_path)
            article, major_moves = compare(article, projection_history, now)
            print(f"PROJECTION QA: sufficient verified data; {major_moves} major moves")
        if (not preview_only
            and os.getenv("FPL_PORTED_TASKS_ENABLED", "false").lower() == "true"
            and dual_publish):
            from .ported_topic_guard import previously_posted_same_players
            recorded = read_state(STATE / "ported_task_versions.json")
            if previously_posted_same_players(publication_slot, article, recorded, now):
                print(f"ALREADY COVERED TODAY {publication_slot}: official player/topic overlap; skip duplicate")
                return 0
        if publication_slot in ("buy", "sell", "projections", "team_analysis", "transfer_suggestions", "midfielders", "start_bench"):
            deadline = upcoming_deadline(snapshot)
            # Use the same API snapshot for both the heading and the deadline.
            # A delayed scheduled job must never publish a locked GW.
            if deadline is None or deadline <= datetime.now(timezone.utc):
                raise RuntimeError("Next-GW recommendation deadline has passed or is unavailable")
            # Existing slots retain their original dedup keys and publish behavior.
            key += f":GW{article.gw}"
            if scheduled_cron and not preview_only and delivery_state.get(key, {}).get("delivered") and (
                not dual_publish or delivery_state.get(key, {}).get("discord_delivered")
            ):
                if publication_slot != "projections":
                    print(f"ALREADY DELIVERED {key}; skipping duplicate")
                    return 0
                # Old release delivered an unsourced FDR-only graphic.
                # Permit exactly one sourced correction, but never a second
                # successful full-coverage report on the same Eastern day.
                from .publication_rules import publication_group, semantic_fingerprint
                from math import ceil
                prior = editorial.get(publication_group(article), {})
                rows = (prior.get("evidence") or {}).get("fixtures") or []
                valid_previous = sum(
                    all(row.get(k) is not None for k in
                        ("home_goals", "away_goals", "home_cs", "away_cs"))
                    for row in rows
                )
                if not (prior.get("confirmed") and rows
                        and valid_previous < ceil(0.8 * len(rows))):
                    print(f"ALREADY DELIVERED {key}; one valid daily board already sent")
                    return 0
                key += f":corrected:{semantic_fingerprint(article)[:12]}"
        if not preview_only and os.getenv("FPL_SEMANTIC_DEDUP_ENABLED", "false").lower() == "true":
            group, article, key, version, evidence, already_posted = check_revision(
                editorial, article, delivery_state, key, dual_publish)
            if already_posted:
                print(f"UNCHANGED TOPIC {group}; skipped repeated publication")
                return 0
            editorial[group] = revision_record(
                group, key, version, evidence, delivery_state.get(key, {}),
                dual_publish, now.isoformat())
            # Write the new version only AFTER rendering and delivery.
            # A missing crest must not leave a permanent pending revision.
        else:
            group = None

        path = OUTPUT / f"FPLVortex_GW{article.gw}_{slot}.png"
        if os.getenv("FPL_ENRICHED_VISUALS_ENABLED", "false").lower() == "true":
            from .publish_checks import render_checked
            render_checked(article, snapshot, path)
        else:
            render(article, path)
        if publication_slot in ("buy", "sell", "projections", "team_analysis", "transfer_suggestions", "midfielders", "start_bench"):
            # Rendering can run across a deadline; abort before external delivery.
            if datetime.now(timezone.utc) >= deadline:
                raise RuntimeError("GW deadline elapsed during recommendation generation")
        if dual_publish:
            # One canonical image/caption, two independent durable receipts.
            # An existing Telegram delivery is never resent solely because
            # Discord failed or was enabled later.
            post = NewsPost(identity=key, title=article.title, caption=article.caption,
                            gameweek=article.gw, image=path, source="Official FPL")
            try:
                receipts = publish_shared(post, delivery_state_path, client,
                                          DiscordWebhookClient(), now_iso=now.isoformat())
            finally:
                # publish_shared checkpoints each platform even on a partial
                # error. Persist editorial recovery mapping for the next run.
                if group is not None:
                    latest_receipt = read_state(delivery_state_path).get(key, {})
                    editorial[group] = revision_record(
                        group, key, version, evidence, latest_receipt,
                        True, now.isoformat())
                    write_state(editorial_path, editorial)
            message_id = receipts.get("telegram_message_id")
            print(f"SHARED DELIVERY {key}: Telegram={bool(receipts.get('delivered'))}, "
                  f"Discord={bool(receipts.get('discord_delivered'))}")
        else:
            message_id = client.send_png(path, article.caption, article.title + (" — PREVIEW" if preview_only else ""), article.gw)
            if preview_only:
                print(f"PREVIEW DELIVERED with Telegram message {message_id}; normal daily delivery state unchanged")
                return 0
            delivery_state[key] = {"delivered": True, "telegram_message_id": message_id, "timestamp": now.isoformat(), "gameweek": article.gw}
            if len(delivery_state) > 150:
                keys = sorted(delivery_state.keys())[-120:]
                delivery_state = {old_key: delivery_state[old_key] for old_key in keys}
            write_state(delivery_state_path, delivery_state)
            if group is not None:
                editorial[group] = revision_record(
                    group, key, version, evidence, delivery_state[key],
                    False, now.isoformat())
                write_state(editorial_path, editorial)
        if slot == "prices":
            write_state(price_state_path, price_snapshot(snapshot))
        if publication_slot == "projections" and not preview_only:
            from .projection_trends import record
            write_state(projection_history_path, record(article, projection_history, now))
        print(f"DELIVERED {key} with message {message_id} and {article.gw=} ({path.name})")
        return 0
    except Exception as error:
        safe_type = type(error).__name__
        safe_message = str(error).replace(os.environ.get("TELEGRAM_BOT_TOKEN", ""), "[REDACTED]") if os.environ.get("TELEGRAM_BOT_TOKEN") else str(error)
        print(f"Delivery failed: {safe_type}: {safe_message[:300]}", file=sys.stderr)
        # GitHub Actions records failed runs; do not spam the audience with retry alerts.
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="FPL Vortex Telegram content delivery")
    parser.add_argument("--slot", default="auto", choices=["auto", "discover", "test", "elite", "comparison", "preview", "news", "prices", "transfer", "captaincy", "review", "evening", "preview-news", "preview-transfer", "preview-prices", "preview-captaincy", "preview-review", "preview-elite", "preview-evening", "buy", "sell", "preview-buy", "preview-sell", "projections", "team_analysis", "transfer_suggestions", "preview-projections", "preview-team_analysis", "preview-transfer_suggestions", "midfielders", "preview-midfielders", "start_bench", "preview-start_bench"])
    args = parser.parse_args()
    return run(args.slot, os.environ.get("SCHEDULED_CRON"))


if __name__ == "__main__":
    raise SystemExit(main())