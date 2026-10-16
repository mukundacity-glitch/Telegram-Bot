"""Eight Eastern-time publishing windows, resolved from GitHub's triggering cron."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("America/New_York")
SLOT_CRONS: dict[str, str] = {
    "30 6 * * *": "elite",
    "0 8 * * *": "comparison",
    "0 10 * * *": "news",
    "0 12 * * *": "prices",
    "0 14 * * *": "transfer",
    "0 16 * * *": "captaincy",
    "30 17 * * *": "review",
    "0 20 * * *": "evening",
    # Backup schedule checks 15 minutes later; previously delivered slots are skipped.
    "45 6 * * *": "elite",
    "15 8 * * *": "comparison",
    "15 10 * * *": "news",
    "15 12 * * *": "prices",
    "15 14 * * *": "transfer",
    "15 16 * * *": "captaincy",
    "45 17 * * *": "review",
    "15 20 * * *": "evening",
}
SLOT_HOURS: dict[str, tuple[int, int]] = {
    "elite": (6, 30),
    "comparison": (8, 0),
    "news": (10, 0),
    "prices": (12, 0),
    "transfer": (14, 0),
    "captaincy": (16, 0),
    "review": (17, 30),
    "evening": (20, 0),
}


def resolve_slot(requested: str, scheduled_cron: str | None, current: datetime) -> str:
    if requested != "auto":
        if requested not in set(SLOT_HOURS) | {"test", "discover"}:
            raise ValueError(f"Unknown requested slot: {requested}")
        return requested
    if scheduled_cron:
        try:
            return SLOT_CRONS[scheduled_cron.strip()]
        except KeyError as error:
            raise ValueError("Unrecognized workflow schedule; refusing ambiguous delivery") from error
    eastern = current.astimezone(TIMEZONE)
    for slot, hour_minute in SLOT_HOURS.items():
        if (eastern.hour, eastern.minute) == hour_minute:
            return slot
    raise ValueError("Manual auto run is outside a configured posting time; choose a slot")


def captaincy_due(events: list[dict], current: datetime) -> bool:
    """Publish on the day before the next real FPL deadline, using Eastern dates."""
    tomorrow = current.astimezone(TIMEZONE).date() + timedelta(days=1)
    for event in events:
        if not isinstance(event, dict) or event.get("finished"):
            continue
        deadline = event.get("deadline_time")
        if not isinstance(deadline, str):
            continue
        try:
            parsed = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.astimezone(TIMEZONE).date() == tomorrow and parsed > current:
            return True
    return False