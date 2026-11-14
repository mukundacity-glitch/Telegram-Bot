"""One-time Telegram deletion must never delete unrelated messages or alter cron."""
import json
from datetime import datetime, timezone
from pathlib import Path

from vortex.retire_status_messages import TARGETS, retire_rejected_status_cards


class FakeBot:
    chat_id = "dummy-private-chat"
    def __init__(self, kind="private"):
        self.kind = kind
        self.deleted = []
    def get_bot_username(self):
        return "FPLVortexDailyBot"
    def _post(self, method, payload):
        if method == "getChat":
            return {"result": {"type": self.kind}}
        assert method == "deleteMessage"
        self.deleted.append(payload["message_id"])
        return {"result": True}


def _setup(tmp_path):
    receipts = tmp_path / "news_deliveries.json"
    ledger = tmp_path / "status_message_retirements.json"
    rows = {
        identity: {
            "delivered": True, "discord_delivered": True,
            "source": "Official FPL", "timestamp": timestamp,
            "telegram_message_id": i + 15
        }
        for i, (_, (identity, timestamp)) in enumerate(TARGETS.items())
    }
    rows["availability:unrelated"] = {
        "delivered": True, "source": "Official FPL",
        "timestamp": "2026-11-11T13:31:37.155524+00:00",
        "telegram_message_id": 123456
    }
    receipts.write_text(json.dumps(rows))
    return receipts, ledger


def test_exact_two_confirmed_user_rejected_messages_only(tmp_path):
    receipts, ledger = _setup(tmp_path)
    bot = FakeBot()
    now = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)
    first = retire_rejected_status_cards(
        now, telegram=bot, receipts_path=receipts, state_path=ledger)
    assert first == {"status": "completed", "deleted": 2}
    assert sorted(bot.deleted) == [15, 16]
    state = json.loads(ledger.read_text())
    assert all(state[identity]["deleted"] for identity, _ in TARGETS.values())
    second = retire_rejected_status_cards(
        now, telegram=bot, receipts_path=receipts, state_path=ledger)
    assert second["deleted"] == 0 and len(bot.deleted) == 2


def test_never_delete_from_changed_channel_or_unverified_receipt(tmp_path):
    receipts, ledger = _setup(tmp_path)
    now = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)
    channel = FakeBot(kind="channel")
    report = retire_rejected_status_cards(
        now, telegram=channel, receipts_path=receipts, state_path=ledger)
    assert report["deleted"] == 0 and not channel.deleted
    content = json.loads(receipts.read_text())
    identity = next(iter(TARGETS.values()))[0]
    content[identity]["timestamp"] = "2026-01-01T00:00:00+00:00"
    receipts.write_text(json.dumps(content))
    private = FakeBot()
    report = retire_rejected_status_cards(
        now, telegram=private, receipts_path=receipts, state_path=ledger)
    assert report["deleted"] == 1 and len(private.deleted) == 1


def test_expired_status_cards_not_deleted(tmp_path):
    receipts, ledger = _setup(tmp_path)
    bot = FakeBot()
    report = retire_rejected_status_cards(
        datetime(2026, 11, 14, tzinfo=timezone.utc),
        telegram=bot, receipts_path=receipts, state_path=ledger)
    assert report["deleted"] == 0
    assert bot.deleted == []


def test_schedule_and_other_lanes_still_present():
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/telegram-daily.yml").read_text()
    assert "cron: '43 * * * *'" in workflow
    assert "cron: '13 * * * *'" in workflow
    assert 'timezone:' not in workflow
    assert "python -m vortex.scheduled_dispatch" in workflow
