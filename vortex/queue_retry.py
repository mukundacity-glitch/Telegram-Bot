"""Bounded retries and safe diagnostics for scheduled publishing."""
import os
import re
from time import sleep

import requests

from .editorial_inputs import RequiredInput

ATTEMPTS = 3


def failure_reason(error):
    message = str(error)
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL",
                "THE_ODDS_API_KEY", "ODDS_API_KEY"):
        value = os.getenv(key)
        if value:
            message = message.replace(value, "[REDACTED]")
    message = re.sub(r"https?://[^\s'\"]+", "[URL]", message)
    return f"{type(error).__name__}: {message[:350]}"


def retry_source(fetch, *, required=False):
    for attempt in range(ATTEMPTS):
        try:
            return fetch()
        except (requests.RequestException, OSError, RequiredInput) as exc:
            if isinstance(exc, RequiredInput) and not required:
                raise
            print(f"Source attempt {attempt + 1}/{ATTEMPTS}: {failure_reason(exc)}")
            if attempt + 1 == ATTEMPTS:
                raise
            sleep(1)


def verified_caption(title, caption):
    """Keep usable verified lines and the edition's configured hashtags."""
    blocked = re.compile(r"(?i)\b(?:TODO|N/A|coming soon|data unavailable)\b")
    lines = [line.strip() for line in caption.splitlines()
             if line.strip() and not blocked.search(line)]
    if len(lines) < 2 or not lines[-1].startswith("#"):
        raise RequiredInput("Verified caption or hashtags missing")
    tags = lines.pop()
    if not 3 <= len(re.findall(r"(?<!\w)#[\w]+", tags)) <= 6:
        raise RequiredInput("Caption requires three to six relevant hashtags")
    if blocked.search(title):
        raise RequiredInput("Post title contains an unverified placeholder")
    normalized_title = re.sub(r"[^\w]+", "", title).casefold()
    normalized_hook = re.sub(r"[^\w]+", "", lines[0]).casefold()
    if normalized_title and normalized_title not in normalized_hook:
        lines.insert(0, title)
    result = "\n".join([*lines, "", tags])
    if len(result) > 1024:
        raise RequiredInput("Caption exceeds Telegram's 1024-character limit")
    return result
