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
from .fpl import collect_snapshot, price_snapshot
from .render import render
from .schedule import resolve_slot
from .telegram import TelegramClient

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
    publication_slot = "comparison" if slot == "preview" else slot.removeprefix("preview-") if preview_only else slot
    delivery_state_path = STATE / "deliveries.json"
    price_state_path = STATE / "prices.json"
    delivery_state = read_state(delivery_state_path)
    key = f"{now.astimezone(ZoneInfo('America/New_York')).date()}:{slot}"
    if scheduled_cron and not preview_only and delivery_state.get(key, {}).get("delivered"):
        print(f"ALREADY DELIVERED {key}; skipping duplicate")
        return 0

    try:
        snapshot = collect_snapshot()
        previous_prices = read_state(price_state_path)
        article = generate(publication_slot, snapshot, now, previous_prices)
        path = OUTPUT / f"FPLVortex_GW{article.gw}_{slot}.png"
        render(article, path)
        message_id = client.send_png(path, article.caption, article.title + (" — PREVIEW" if preview_only else ""), article.gw)
        if preview_only:
            print(f"PREVIEW DELIVERED with Telegram message {message_id}; normal daily delivery state unchanged")
            return 0
        delivery_state[key] = {"delivered": True, "telegram_message_id": message_id, "timestamp": now.isoformat(), "gameweek": article.gw}
        if len(delivery_state) > 150:
            keys = sorted(delivery_state.keys())[-120:]
            delivery_state = {old_key: delivery_state[old_key] for old_key in keys}
        write_state(delivery_state_path, delivery_state)
        if slot == "prices":
            write_state(price_state_path, price_snapshot(snapshot))
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
    parser.add_argument("--slot", default="auto", choices=["auto", "discover", "test", "elite", "comparison", "preview", "news", "prices", "transfer", "captaincy", "review", "evening", "preview-news", "preview-transfer", "preview-prices", "preview-captaincy", "preview-review", "preview-elite", "preview-evening"])
    args = parser.parse_args()
    return run(args.slot, os.environ.get("SCHEDULED_CRON"))


if __name__ == "__main__":
    raise SystemExit(main())