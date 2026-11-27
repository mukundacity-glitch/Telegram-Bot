"""Retire exactly the user-rejected Calvert-Lewin GW12 player-news photo.

Historical pending queue at 59ed48586678b4669e1c25da88c266f3c042ab21
identifies the player and RSS story; the durable delivery ledger identifies
the two destination receipts. No other historical post is eligible.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os

from .syndication import load_journal, save_journal, DiscordWebhookClient
from .telegram import TelegramClient

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = ROOT / "state" / "news_deliveries.json"
RETIRED = ROOT / "state" / "status_message_retirements.json"
IDENTITY = "rss:dffa3e48075aa013952125f1"
STAMP = "2026-11-27T03:02:40.493729+00:00"
CAPTION_HASH = "8182fd92026786d24d326a03fcbce8e1ea58ef005f523025cf5b53044fdfca1d"
TELEGRAM_ID = 641
DISCORD_ID = "1575708423645823107"


def retire_calvert_lewin(now, *, telegram=None, discord=None, receipts_path=RECEIPTS, state_path=RETIRED):
    if now.tzinfo is None:
        raise ValueError("Retirement time must include timezone")
    receipts = load_journal(receipts_path)
    row = receipts.get(IDENTITY, {})
    if not (row.get("delivered") and row.get("discord_delivered")
            and row.get("gameweek") == 12 and row.get("timestamp") == STAMP
            and row.get("source") == "media.bbc_sport"
            and row.get("caption_sha256") == CAPTION_HASH
            and row.get("telegram_message_id") == TELEGRAM_ID
            and row.get("discord_message_id") == DISCORD_ID):
        return {"status": "receipt-mismatch"}
    retired = load_journal(state_path)
    result = retired.setdefault(IDENTITY, {})
    age = now - datetime.fromisoformat(STAMP)
    if not result.get("telegram_deleted") and timedelta(0) <= age < timedelta(hours=48):
        try:
            if telegram is not None or (os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")):
                bot = telegram or TelegramClient()
                if bot.get_bot_username().casefold() == "fplvortexdailybot":
                    chat = bot._post("getChat", {"chat_id": bot.chat_id}).get("result", {})
                    if chat.get("type") == "private" and bot.delete_shared_message(TELEGRAM_ID) is True:
                        result.update(telegram_deleted=True, telegram_deleted_at=now.isoformat())
                        save_journal(state_path, retired)
        except Exception:
            print("::warning::Exact retired player Telegram deletion not confirmed")
    if not result.get("discord_deleted") and (discord is not None or os.getenv("DISCORD_WEBHOOK_URL")):
        try:
            client = discord or DiscordWebhookClient()
            url = client.url.split("?", 1)[0].rstrip("/") + "/messages/" + DISCORD_ID
            # Discord's webhook endpoint only retrieves messages owned by that webhook.
            response = client.session.get(url, timeout=15)
            if response.status_code == 200:
                payload = response.json()
                if (str(payload.get("id")) == DISCORD_ID
                        and "Calvert-Lewin" in payload.get("content", "")
                        and payload.get("attachments")):
                    removed = client.session.delete(url, timeout=15)
                    if removed.status_code == 204:
                        result.update(discord_deleted=True, discord_deleted_at=now.isoformat())
                        save_journal(state_path, retired)
        except Exception:
            print("::warning::Exact retired player Discord deletion not confirmed")
    return dict(result)
