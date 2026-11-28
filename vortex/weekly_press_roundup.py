"""Slot 20 candidate: evidence-first weekly pre-deadline press roundup.

No publisher or cron is registered here. Global release remains closed.
The existing press route and historical receipts are preserved.
"""
from datetime import timedelta, timezone
from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor
import json

from .position_watch import clock, heartbeat, target, WINDOW
from .research_gap import verified_gap, fresh_research_source
from .publishing_window import allowed
from .press_sources import lookup, official, SITES
from .autonomous_schedule import season_id

EDITION = "weekly-pre-deadline-press-roundup"
STATE_KEY = "_weekly_pre_deadline_press"
RELEASE_VERIFIED = False
LEAD = timedelta(hours=3)


def scope(snapshot, now):
    gw, kickoff, deadline = target(snapshot)
    if now >= deadline - LEAD:
        raise ValueError("Slot 20 pre-deadline cutoff reached")
    matches = [f for f in snapshot.fixtures if f.get("event") == gw]
    if len({f["id"] for f in matches}) != len(matches):
        raise ValueError("Duplicate official fixtures")
    pairs = {}
    for f in matches:
        h, a = f["team_h"], f["team_a"]
        if h == a or h not in snapshot.teams or a not in snapshot.teams:
            raise ValueError("Unverified official club identity")
        pairs.setdefault(str(h), set()).add(a)
        pairs.setdefault(str(a), set()).add(h)
    return {"season": season_id(snapshot, now), "gw": gw,
            "deadline": deadline.isoformat(), "kickoff": kickoff.isoformat(),
            "pairs": {k: sorted(v) for k, v in sorted(pairs.items())},
            "fixture_ids": sorted(f["id"] for f in matches)}


def receipt_key(expected):
    return f"{expected['season']}:GW{expected['gw']}:{EDITION}"


def legacy_claimed(press_state, expected):
    # Match the existing season/GW press journal, including uncertain sends.
    start = expected["season"].split("-")[0]
    row = press_state.get(f"{start}:GW{expected['gw']}", {})
    return bool(any(row.get(k) for k in
                    ("message", "discord_message", "sending", "discord_sending")))


def free(start, end, busy):
    return all(a.tzinfo is not None and b.tzinfo is not None and a < b
               and not (start < b and a < end) for _, a, b in busy)


def choose_schedule(deadline, busy, *, inventory_verified=False):
    """Latest eligible existing heartbeat, allowing a full ten-minute window.

    Unknown/incomplete reservation inventory is a hard hold, never an empty calendar.
    """
    if not inventory_verified or deadline.tzinfo is None:
        return None
    cutoff = deadline.astimezone(timezone.utc) - LEAD
    end = (cutoff-WINDOW).replace(second=0, microsecond=0)
    for offset in range(24*60):
        post = end-timedelta(minutes=offset)
        if not (heartbeat(post) and allowed(post) and allowed(post+WINDOW)
                and free(post, post+WINDOW, busy)):
            continue
        for lead in range(195, 361, 15):
            research = post-timedelta(minutes=lead)
            if heartbeat(research) and free(research, research+WINDOW, busy):
                return research, post
    return None


def find_reports(snapshot, expected, now, fetch=lookup):
    """Actively discover opponent-specific reports through the official-club adapter.

    A fixture timetable alone is never report evidence. The existing adapter
    validates occurrence and article time. Quotes without named attribution
    are omitted rather than presented as manager statements.
    """
    first = clock(expected["kickoff"])
    def find(key):
        team = snapshot.teams[int(key)]
        domain = SITES.get(team["name"])
        if not domain:
            return key, []
        past = [clock(f["kickoff_time"]) for f in snapshot.fixtures
                if f.get("kickoff_time") and int(key) in (f.get("team_h"), f.get("team_a"))
                and clock(f["kickoff_time"]) < first]
        since = max([first-timedelta(days=6), *past])
        reports = []
        for opponent_id in expected["pairs"][key]:
            try:
                item = fetch(team, snapshot.teams[opponent_id], now, since)
                if not (item and item.get("club") == team["name"]
                        and str(item.get("news", "")).strip()
                        and official(item.get("url", ""), domain)
                        and since <= clock(item["published"]) <= now):
                    continue
                manager = str(item.get("manager") or "").strip()
                quote = str(item.get("quote") or "").strip()
                reports.append({"club": team["name"], "opponent": opponent_id,
                                "news": item["news"], "url": item["url"],
                                "published": clock(item["published"]).isoformat(),
                                "manager": manager if item.get("manager_verified") is True else "",
                                "quote": quote if manager and item.get("manager_verified") is True
                                and item.get("quote_verified") is True else ""})
            except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError):
                continue
        return key, reports
    with ThreadPoolExecutor(max_workers=6) as pool:
        return {key: reports for key, reports in pool.map(find, expected["pairs"]) if reports}


def digest(reports):
    return sha256(json.dumps(reports, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode()).hexdigest()


def proof_valid(proof, expected, reports, now, busy, *, inventory_verified=False, posting=True):
    try:
        if not inventory_verified or proof.get("scope") != expected or not reports:
            return False
        r, p = clock(proof["research_at"]), clock(proof["post_at"])
        checked = clock(proof["checked_at"])
        if not (heartbeat(r) and heartbeat(p) and r <= checked < r+WINDOW
                and checked <= now and verified_gap(proof["checked_at"], p)
                and p-(r+WINDOW) >= LEAD
                and fresh_research_source(proof["source_at"], proof["checked_at"])
                and p+WINDOW <= clock(expected["deadline"])-LEAD
                and allowed(p) and allowed(p+WINDOW)
                and free(r, r+WINDOW, busy) and free(p, p+WINDOW, busy)
                and proof["data_digest"] == digest(reports)):
            return False
        for key, rows in reports.items():
            if key not in expected["pairs"] or not rows:
                return False
            for row in rows:
                if (row["opponent"] not in expected["pairs"][key]
                        or not row["news"].strip() or not row["url"].startswith("https://")
                        or not clock(expected["kickoff"])-timedelta(days=6)
                        <= clock(row["published"]) <= checked
                        or (row.get("quote") and not row.get("manager"))):
                    return False
        return (not posting or (p <= now < p+WINDOW and allowed(now)
                                and now <= clock(expected["deadline"])-LEAD
                                and verified_gap(proof["checked_at"], now)))
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return False


def eligible(proof, expected, reports, now, busy, press_state, claims, *, inventory_verified=False):
    # No production activation until actual settlement, global reservations,
    # source attribution, renderer QA and timed platform delivery are verified.
    return (RELEASE_VERIFIED and not legacy_claimed(press_state, expected)
            and not claims.get(receipt_key(expected))
            and proof_valid(proof, expected, reports, now, busy,
                            inventory_verified=inventory_verified))
