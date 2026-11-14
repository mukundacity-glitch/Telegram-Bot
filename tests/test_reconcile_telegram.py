from datetime import datetime, timedelta, timezone

import pytest

from vortex.reconcile_telegram import reconcile
from vortex.syndication import load_journal, save_journal


def pending_receipt(tmp_path):
    path = tmp_path / "receipts.json"
    earlier = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    save_journal(path, {"exact-edition": {
        "telegram_send_pending": True,
        "telegram_uncertain_at": earlier,
        "discord_delivered": True,
        "discord_message_id": "discord-receipt",
    }})
    return path, earlier


def test_history_match_records_original_receipt(tmp_path):
    path, earlier = pending_receipt(tmp_path)
    checked = datetime.now(timezone.utc).isoformat()
    assert reconcile("exact-edition", observed_at=checked, message_id=124, delivered_at=earlier,
                     journal_path=path) == 124
    row = load_journal(path)["exact-edition"]
    assert row["telegram_message_id"] == 124
    assert row["telegram_delivered_at"] == earlier
    assert row["telegram_verification_source"] == "operator-verified-telegram-history"
    assert row["discord_message_id"] == "discord-receipt"
    assert row["delivered"] and not row.get("telegram_send_pending")


def test_confirmed_absence_sends_only_once_and_checkpoints_first(tmp_path):
    path, earlier = pending_receipt(tmp_path)

    def send():
        assert load_journal(path)["exact-edition"]["telegram_reconciliation_resend_at"]
        return 124

    assert reconcile("exact-edition", observed_at=earlier, resend=send, journal_path=path) == 124
    assert reconcile("exact-edition", observed_at=earlier, resend=lambda: pytest.fail("Duplicate send"),
                     journal_path=path) == 124
    row = load_journal(path)["exact-edition"]
    assert row["telegram_verification_source"] == "telegram-bot-api"
    assert row["telegram_message_id"] == 124 and not row.get("telegram_send_pending")


def test_uncertain_recovery_cannot_retry_blindly(tmp_path):
    path, earlier = pending_receipt(tmp_path)

    def unreadable_receipt():
        raise RuntimeError("Unknown delivery outcome")

    with pytest.raises(RuntimeError, match="Unknown delivery"):
        reconcile("exact-edition", observed_at=earlier, resend=unreadable_receipt, journal_path=path)
    with pytest.raises(ValueError, match="already attempted"):
        reconcile("exact-edition", observed_at=earlier, resend=lambda: pytest.fail("Duplicate send"),
                  journal_path=path)
    row = load_journal(path)["exact-edition"]
    assert not row.get("delivered") and row["telegram_send_pending"]
