"""One clock boundary for scheduled and manual production delivery.

The window is always resolved in America/New_York through ``zoneinfo`` so that
EST/EDT transitions are handled by the tz database rather than by a fixed UTC
offset. The approved publishing day is 05:30 inclusive to 23:00 exclusive.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import os

ZONE = ZoneInfo('America/New_York')
OPEN_MINUTE = 5 * 60 + 30   # 05:30 ET inclusive
CLOSE_MINUTE = 23 * 60      # 23:00 ET exclusive
WINDOW_LABEL = '05:30–23:00 America/New_York'


def allowed(now=None):
    local = (now or datetime.now(timezone.utc)).astimezone(ZONE)
    return OPEN_MINUTE <= local.hour * 60 + local.minute < CLOSE_MINUTE


def assert_allowed(now=None):
    if os.getenv('FPL_PUBLISH_WINDOW_ENFORCED', 'false').lower() == 'true' and not allowed(now):
        raise RuntimeError(f'Outside {WINDOW_LABEL}; retain pending edition for next window')
