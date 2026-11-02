"""No real external posting; explicitly prevent single-platform partial delivery."""
import pytest

from vortex.delivery_preflight import assert_dual_destinations


def test_missing_webhook_must_block_both_platforms_before_send(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "INERT-TEST")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    with pytest.raises(RuntimeError, match="SAME Telegram-Bot"):
        assert_dual_destinations()


def test_validated_destination_format_does_not_claim_actual_delivery(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "INERT-TEST")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL",
                       "https://discord.com/api/webhooks/0/inert-unit-test")
    assert assert_dual_destinations() is None


def test_untrusted_webhook_host_or_scheme_is_rejected(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "INERT-TEST")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    for invalid in ("http://discord.com/api/webhooks/1/a",
                    "https://attacker.invalid/api/webhooks/1/a"):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", invalid)
        with pytest.raises(RuntimeError, match="invalid"):
            assert_dual_destinations()
