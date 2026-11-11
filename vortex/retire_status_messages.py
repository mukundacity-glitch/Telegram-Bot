"""One-time, narrowly scoped removal of two user-rejected STATUS CHANGE images.

Only the two confirmed existing Telegram messages are eligible. No bulk deletion,
no channel-wide cleanup, no chat-id/message-id values in source or logs, and
NO changes to publishing schedules or any other editorial pipeline.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .syndication import load_journal, save_journal
from .telegram import TelegramClient, TelegramDeliveryError

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = ROOT / "state" / "news_deliveries.json"
RETIRED = ROOT / "state" / "status_message_retirements.json"

# Stable receipt identities are SHA-256 fingerprints of the official FPL
# player IDs and injury flags; these correspond exactly to the user screenshots.
# The timestamps prevent mismatched or reassigned receipt data being acted on.
TARGETS = {
    "Brobbey": ("availability:116eb19e62857b3b42e4f86a",
                "2026-11-10T23:41:46.625047+00:00"),
    "Belloumi": ("availability:82ac1dd8950172ce57655042",
                 "2026-11-11T13:31:37.155524+00:00"),
}


def retire_rejected_status_cards(now: datetime | None = None, *,
                                 telegram=None, receipts_path=None,
                                 state_path=None) -> dict:
    """Delete these TWO posts only if age, receipt and private-chat ID all match."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Deletion audit needs an aware UTC timestamp")
    if telegram is None and not (
        os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")
    ):
        return {"status": "not-configured", "deleted": 0}
    receipts_path = Path(receipts_path or RECEIPTS)
    state_path = Path(state_path or RETIRED)
    receipts = load_journal(receipts_path)
    retired = load_journal(state_path)
    eligible = []
    for name, (identity, expected_timestamp) in TARGETS.items():
        entry = receipts.get(identity, {})
        when = datetime.fromisoformat(expected_timestamp)
        if (retired.get(identity, {}).get("deleted") is True
                or not entry.get("delivered")
                or entry.get("source") != "Official FPL"
                or entry.get("timestamp") != expected_timestamp
                or type(entry.get("telegram_message_id")) is not int
                or not timedelta(0) <= now - when < timedelta(hours=47)):
            continue
        eligible.append((name, identity, entry["telegram_message_id"]))
    if not eligible:
        return {"status": "no-eligible-messages", "deleted": 0}
    bot = telegram or TelegramClient()
    # Only the original bot's verified private chat is allowed, never a channel
    # or a newly configured destination of a different type.
    if bot.get_bot_username().casefold() != "fplvortexdailybot":
        return {"status": "bot-identity-mismatch", "deleted": 0}
    chat = bot._post("getChat", {"chat_id": bot.chat_id}).get("result", {})
    if chat.get("type") != "private" or (
        str(chat.get("username") or "").casefold() == "fplvortexdailybot"
    ):
        return {"status": "destination-not-original-private-chat", "deleted": 0}
    deleted = 0
    for name, identity, message_id in eligible:
        try:
            response = bot._post(
                "deleteMessage", {"chat_id": bot.chat_id, "message_id": message_id}
            )
            if response.get("result") is not True:
                raise TelegramDeliveryError("Telegram did not confirm deletion")
            retired[identity] = {"deleted": True, "player": name,
                                 "at": now.isoformat(), "scope": "Telegram private"}
            save_journal(state_path, retired)  # each success is durable
            deleted += 1
        except (TelegramDeliveryError, RuntimeError, ValueError, OSError):
            # Never roll back another message's confirmed success or retry it.
            # No IDs, chat info, token or Telegram payload are logged.
            print("::warning::One targeted retired-status deletion could not be confirmed")
    if deleted:
        print(f"::notice::Removed {deleted} explicitly rejected old STATUS CHANGE Telegram image(s)")
    return {"status": "completed" if deleted == len(eligible) else "partial",
            "deleted": deleted}
