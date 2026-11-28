"""Slot 25: separate, gated weekly chip-uplift board.

Reuses the existing chip scenario engine, but never its fixed-club shortlist.
No cron or publisher is registered. Existing 17/51 receipts are retained.
"""
from datetime import timedelta, timezone
from hashlib import sha256
import json

from .autonomous_schedule import Slot, season_id
from .chip_strategy import build_chip_strategy
from .editorial_inputs import RequiredInput
from .position_watch import clock, heartbeat, target, WINDOW
from .publishing_window import allowed
from .research_gap import verified_gap, fresh_research_source
from .telegram_spacing import GAP

EDITION = "weekly-chip-strategy"
STATE_KEY = "_weekly_chip_strategy"
RELEASE_VERIFIED = False
LEAD = timedelta(hours=3)


def scope(snapshot, now):
    gw, kickoff, deadline = target(snapshot)
    if now.tzinfo is None or now >= deadline:
        raise RequiredInput("Slot 25 requires an unexpired official deadline")
    return {"season": season_id(snapshot, now), "gw": gw,
            "deadline": deadline.isoformat(), "kickoff": kickoff.isoformat()}


def key(expected):
    return f"{expected['season']}:GW{expected['gw']}:task2:{EDITION}"


def free(start, end, busy):
    return all(a.tzinfo is not None and b.tzinfo is not None and a < b
               and not (start < b and a < end) for _, a, b in busy)


def choose_schedule(deadline, now, busy, *, inventory_verified=False):
    """Latest conflict-free existing heartbeat, within seven days of deadline."""
    if not inventory_verified or deadline.tzinfo is None or now.tzinfo is None:
        return None
    deadline = deadline.astimezone(timezone.utc)
    floor = max(now.astimezone(timezone.utc), deadline-timedelta(days=7))
    last = (deadline-WINDOW).replace(second=0, microsecond=0)
    for offset in range(7*24*60):
        p = last-timedelta(minutes=offset)
        if p < floor:
            break
        if not (heartbeat(p) and allowed(p) and allowed(p+WINDOW)
                and free(p-GAP,p+WINDOW+GAP,busy)):
            continue
        for minutes in range(195,361,15):
            r = p-timedelta(minutes=minutes)
            if r >= floor and heartbeat(r) and free(r,r+WINDOW,busy):
                return r,p
    return None


def digest(extra):
    return sha256(json.dumps(extra,sort_keys=True,separators=(",",":"),
                             allow_nan=False).encode()).hexdigest()


def build(snapshot, now, session):
    expected = scope(snapshot, now)
    plan = build_chip_strategy(Slot("task2",EDITION,0,0),snapshot,now,session,
                               dynamic_targets=True)
    if plan.gw != expected["gw"]:
        raise RequiredInput("Chip forecast event differs from official target")
    plan.kind = EDITION
    plan.extra = {**plan.extra, "scope":expected,
                  "retrieved_at":snapshot.fetched_at.astimezone(timezone.utc).isoformat()}
    return plan


def proof_valid(proof, expected, extra, now, busy, *, inventory_verified=False, posting=True):
    try:
        if not inventory_verified or proof.get("scope") != expected or extra.get("scope") != expected:
            return False
        r,p = clock(proof["research_at"]),clock(proof["post_at"])
        checked = clock(proof["checked_at"])
        deadline = clock(expected["deadline"])
        if not (heartbeat(r) and heartbeat(p) and r <= checked < r+WINDOW
                and checked <= now and r >= deadline-timedelta(days=7)
                and verified_gap(proof["checked_at"],p) and p-r-WINDOW >= LEAD
                and fresh_research_source(extra["retrieved_at"],proof["checked_at"])
                and p+WINDOW <= deadline and allowed(p) and allowed(p+WINDOW)
                and free(r,r+WINDOW,busy) and free(p-GAP,p+WINDOW+GAP,busy)
                and proof["data_digest"] == digest(extra)):
            return False
        return not posting or (p <= now < p+WINDOW and now < deadline
                               and allowed(now) and verified_gap(proof["checked_at"],now))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        return False


def eligible(proof, expected, extra, now, busy, claims, *, inventory_verified=False,
             legacy_reconciled=False):
    # An operator must reconcile the existing 17/51 receipt/uncertain-send
    # history before migration; absence of an explicit claim is not evidence.
    return (RELEASE_VERIFIED and legacy_reconciled and not claims.get(key(expected))
            and proof_valid(proof,expected,extra,now,busy,
                            inventory_verified=inventory_verified))
