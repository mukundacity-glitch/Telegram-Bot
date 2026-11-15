"""Shared cooldown for the serialized GitHub Telegram publisher."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from .syndication import load_journal, save_journal

GAP = timedelta(minutes=45)
# Reserve extra time before the API call in case the runner stops mid-upload.
IN_FLIGHT = timedelta(minutes=5)
STATE = Path(__file__).resolve().parents[1] / "state"
COOLDOWN = STATE / "telegram_spacing.json"
LEDGERS = ("deliveries.json", "chatgpt_deliveries.json", "news_deliveries.json",
           "telegram_news_deliveries.json")


class DeliveryDeferred(Exception):
    def __init__(self, until):
        self.until = until
        super().__init__(f"Telegram cooldown until {until.isoformat()}")


def enabled():
    return os.getenv("FPL_TELEGRAM_SPACING", "").lower() == "true"


def blocked_until(now):
    if not enabled():
        return None
    clock = load_journal(COOLDOWN).get("telegram", {})
    deadline = clock.get("next_eligible_at")
    if deadline:
        until = datetime.fromisoformat(deadline)
        return until if now < until else None
    # Seed from existing receipts when the feature first deploys.
    recent = []
    for file in LEDGERS:
        for row in load_journal(STATE / file).values():
            stamp = row.get("telegram_delivered_at") or row.get("timestamp")
            if stamp and row.get("delivered") and row.get("telegram_message_id"):
                recent.append(datetime.fromisoformat(stamp))
    until = max(recent, default=now-GAP) + GAP
    return until if now < until else None


def require_ready(now=None):
    if until := blocked_until(now or datetime.now(timezone.utc)):
        raise DeliveryDeferred(until)


def checkpoint(now, extra=timedelta(0)):
    save_journal(COOLDOWN, {"telegram": {"next_eligible_at": (now+GAP+extra).isoformat()}})
