"""One clock boundary for scheduled and manual production delivery."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import os

ZONE = ZoneInfo('America/New_York')
OPEN_MINUTE = 5 * 60 + 30   # 05:30 ET inclusive
CLOSE_MINUTE = 22 * 60      # 22:00 ET exclusive


def allowed(now=None):
    local = (now or datetime.now(timezone.utc)).astimezone(ZONE)
    return OPEN_MINUTE <= local.hour * 60 + local.minute < CLOSE_MINUTE


def assert_allowed(now=None):
    if os.getenv('FPL_PUBLISH_WINDOW_ENFORCED', 'false').lower() == 'true' and not allowed(now):
        raise RuntimeError('Outside 05:30–22:00 America/New_York; retain pending edition for next window')
