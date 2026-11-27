"""Shared minimum elapsed research-to-publication gate for cutover editions."""
from datetime import datetime, timedelta, timezone

MIN_RESEARCH_GAP = timedelta(hours=3)


def verified_gap(checked_at, post_at):
    """Fail closed for missing, naive, future or too-recent research timestamps."""
    try:
        checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        return (checked.tzinfo is not None and post_at.tzinfo is not None
                and post_at.astimezone(timezone.utc) - checked.astimezone(timezone.utc) >= MIN_RESEARCH_GAP)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return False


def verify_settled_or_weekly_record(record, now, publish_at):
    """Final outbox gate: no direct/manual/late replay of research-gated slots."""
    from .autonomous_schedule import ET, radar_post_due, fdr_phase, slot_start, SATURDAY_FDR_GRID
    edition = record["edition"]
    facts = record.get("facts") or {}
    proof = facts.get("research") or {}
    local = publish_at.astimezone(ET)
    same_day = now.astimezone(ET).date() == local.date()
    if edition == "player-radar-comparison":
        target = local.replace(hour=11, minute=30, second=0, microsecond=0)
        completed = (facts.get("extra") or {}).get("completed_gw")
        valid = radar_post_due(now) and radar_post_due(publish_at) and type(completed) is int and completed == proof.get("completed_gw")
        identity = f"chatgpt:{record['season']}:GW{completed}:task1:player-radar-comparison"
    elif edition == "saturday-fdr-grid":
        target = slot_start(SATURDAY_FDR_GRID, publish_at)
        valid = (fdr_phase(now) == "post" and fdr_phase(publish_at) == "post"
                 and proof.get("verified") is True and proof.get("gw") == record["gameweek"])
        year, week, _ = local.isocalendar()
        identity = f"chatgpt:{record['season']}:{year}-W{week:02d}:task2:saturday-fdr-grid"
    else:
        raise ValueError("Unknown research-gated edition")
    if (not valid or not same_day or proof.get("date") != local.date().isoformat()
            or proof.get("season") != record["season"]
            or not verified_gap(proof.get("checked_at"), target)
            or not verified_gap(proof.get("checked_at"), now)):
        raise ValueError("Verified three-hour research and exact publication window required")
    return identity
