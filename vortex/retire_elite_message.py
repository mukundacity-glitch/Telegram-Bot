"""Remove the one Vuskovic Elite FPL Edge graphic identified by the user."""
from datetime import datetime, timedelta

from .syndication import load_journal, save_journal
from .telegram import TelegramDeliveryError

IDENTITY = "2026-11-12:elite"
SENT_AT = "2026-11-12T21:27:52.539344+00:00"


def retire_replaced_elite(client, journal_path, now: datetime) -> None:
    if not timedelta(0) <= now - datetime.fromisoformat(SENT_AT) < timedelta(hours=48):
        return
    ledger = load_journal(journal_path)
    receipt = ledger.get(IDENTITY, {})
    message_id = receipt.get("telegram_message_id")
    if (receipt.get("telegram_deleted") or receipt.get("timestamp") != SENT_AT
            or not receipt.get("delivered") or receipt.get("source") != "Official FPL"
            or type(message_id) is not int):
        return

    try:
        client.verify_destination()
        result = client._post("deleteMessage", {"chat_id": client.chat_id, "message_id": message_id})
        if result.get("result") is not True:
            raise TelegramDeliveryError("Telegram did not acknowledge the targeted deletion")
    except (RuntimeError, ValueError, OSError):
        print("::warning::Telegram deletion of the replaced Elite graphic was not confirmed")
        return

    receipt["telegram_deleted"] = True
    save_journal(journal_path, ledger)
    print("::notice::Telegram confirmed deletion of the replaced Elite graphic")
