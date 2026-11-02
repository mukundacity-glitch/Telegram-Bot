"""Stop BEFORE first network delivery unless both real posting destinations exist.

No secrets printed and no per-platform partial posting caused by missing
credentials. This validates presence and format, NOT an end-to-end delivery
permission; production activation still requires actual successful receipts.
"""
from __future__ import annotations
import os
from urllib.parse import urlsplit


def assert_dual_destinations() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not token or not chat:
        raise RuntimeError("Telegram bot token and target chat must be configured in GitHub Actions secrets")
    if not webhook:
        raise RuntimeError("Discord webhook must be configured in the SAME Telegram-Bot repository")
    parsed = urlsplit(webhook)
    if (parsed.scheme != "https" or
        parsed.hostname not in ("discord.com", "discordapp.com") or
        not parsed.path.startswith("/api/webhooks/") or parsed.username or parsed.fragment):
        raise RuntimeError("Discord webhook has invalid destination format")


def enable_production_flags() -> bool:
    return all(os.getenv(name, "false").lower() == "true" for name in
               ("DUAL_PUBLISH_ENABLED", "FPL_ENRICHED_VISUALS_ENABLED",
                "FPL_PORTED_TASKS_ENABLED"))
