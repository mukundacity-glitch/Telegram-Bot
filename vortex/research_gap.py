"""Shared minimum elapsed research-to-publication gate for cutover editions."""
from datetime import datetime, timedelta

MIN_RESEARCH_GAP = timedelta(hours=3)


def verified_gap(checked_at, post_at):
    """Fail closed for missing, naive, future or too-recent research timestamps."""
    try:
        checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        return (checked.tzinfo is not None and post_at.tzinfo is not None
                and post_at - checked >= MIN_RESEARCH_GAP)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return False
