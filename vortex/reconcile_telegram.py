"""Reconcile a single pending outbox photo after an operator checks Telegram history."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from .outbox import RECEIPTS, validate
from .syndication import _receipt_lock, load_journal, record_telegram_receipt, save_journal
from .telegram import TelegramClient


def reconcile(post_id, *, observed_at, message_id=None, delivered_at=None, resend=None,
              journal_path=RECEIPTS):
    """Record a history match or perform one verified-absence resend under the receipt lock."""
    with _receipt_lock(journal_path):
        journal = load_journal(journal_path)
        entry = journal.get(post_id, {})
        if entry.get("telegram_message_id") and entry.get("delivered"):
            if message_id is not None and message_id != entry["telegram_message_id"]:
                raise ValueError("Ledger already confirms a different Telegram message ID")
            return entry["telegram_message_id"]
        if not entry.get("telegram_send_pending") or entry.get("telegram_message_id"):
            raise ValueError("Reconciliation requires a pending photo with no Telegram message ID")
        checked_at = datetime.fromisoformat(observed_at)
        if checked_at.tzinfo is None or not (
            datetime.fromisoformat(entry["telegram_uncertain_at"]) <= checked_at <= datetime.now(timezone.utc)
        ):
            raise ValueError("History check timestamp must cover the uncertain send and include its timezone")
        if resend is not None:
            if entry.get("telegram_reconciliation_resend_at"):
                raise ValueError("Reconciliation resend already attempted. Check Telegram history again")
            entry.update(telegram_history_checked_at=observed_at,
                         telegram_reconciliation_resend_at=datetime.now(timezone.utc).isoformat())
            save_journal(journal_path, journal)
            message_id = resend()
            record_telegram_receipt(entry, message_id)
        else:
            posted_at = datetime.fromisoformat(delivered_at)
            if posted_at.tzinfo is None or posted_at > checked_at:
                raise ValueError("Telegram message timestamp must precede the history check and include its timezone")
            record_telegram_receipt(entry, message_id, delivered_at=delivered_at,
                                    verification_source="operator-verified-telegram-history")
            entry["telegram_history_checked_at"] = observed_at
        save_journal(journal_path, journal)
        return message_id


def archived_photo(root, revision, filename, post_id):
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or not re.fullmatch(r"[a-z0-9-]+\.json", filename):
        raise ValueError("Use a full commit SHA and a single outbox JSON filename")

    def read(path):
        return subprocess.check_output(["git", "show", f"{revision}:{path}"])

    record = json.loads(read(f"outbox/{filename}"))
    if len(record.get("images", [])) != 1:
        raise ValueError("This reconciliation command supports one photo")
    relative = Path(record["images"][0])
    if relative.parent != Path("outbox/assets") or relative.suffix != ".png":
        raise ValueError("Archived graphic must be a single outbox PNG")
    image = root / relative
    image.parent.mkdir(parents=True)
    image.write_bytes(read(relative.as_posix()))
    original_time = datetime.fromisoformat(record["generated_at"])
    identity, images, _ = validate(record, root=root, now=original_time)
    if f"{identity}:page1" != post_id:
        raise ValueError("Archive identity does not match the pending receipt")
    return record, images[0]


def main():
    evidence = json.loads(os.environ["TELEGRAM_RECONCILIATION"])
    post_id = evidence["post_id"]
    checked_at = evidence["history_checked_at"]
    if evidence["outcome"] == "found":
        message_id = reconcile(post_id, observed_at=checked_at,
                               message_id=evidence["message_id"], delivered_at=evidence["delivered_at"])
    elif evidence["outcome"] == "absent":
        with TemporaryDirectory() as archive:
            record, image = archived_photo(Path(archive), evidence["revision"], evidence["outbox_file"], post_id)
            telegram = TelegramClient()
            if telegram.destination_type() != "channel":
                raise ValueError("Configured Telegram destination must be the verified channel for a recovery send")

            def resend():
                return telegram.send_shared_png(image, record["caption"], record["title"], record["gameweek"])

            message_id = reconcile(post_id, observed_at=checked_at, resend=resend)
    else:
        raise ValueError("Telegram history outcome must be found or absent")
    print(f"Confirmed Telegram message ID {message_id}")


if __name__ == "__main__":
    main()
