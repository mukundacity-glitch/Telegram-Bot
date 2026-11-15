"""Eastern-time publication windows, resolved from GitHub's triggering cron."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("America/New_York")
SLOT_CRONS: dict[str, str] = {
    "30 6 * * *": "elite",
    "30 7 * * *": "daily_stats",
    "0 15 * * *": "transfer_suggestions",
    "0 16 * * *": "captaincy",
    "30 17 * * *": "review",
    "30 18 * * *": "sell",
    "0 20 * * *": "evening",
    # Backup schedule checks 15 minutes later; previously delivered slots are skipped.
    "45 6 * * *": "elite",
    "45 7 * * *": "daily_stats",
    "15 15 * * *": "transfer_suggestions",
    "15 16 * * *": "captaincy",
    "45 17 * * *": "review",
    "45 18 * * *": "sell",
    "15 20 * * *": "evening",
}
SLOT_HOURS: dict[str, tuple[int, int]] = {
    "elite": (6, 30),
    "daily_stats": (7, 30),
    "transfer_suggestions": (15, 0),
    "captaincy": (16, 0),
    "review": (17, 30),
    "sell": (18, 30),
    "evening": (20, 0),
}


def resolve_slot(requested: str, scheduled_cron: str | None, current: datetime) -> str:
    if requested != "auto":
        permitted = set(SLOT_HOURS) | {"preview-news", "preview-midfielders", "preview-team_analysis", "preview-prices", "buy", "preview-buy", "comparison", "preview-comparison", "start_bench", "preview-start_bench", "test", "discover", "preview", "projections", "preview-projections"} | {f"preview-{slot}" for slot in SLOT_HOURS}
        if requested not in permitted:
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
