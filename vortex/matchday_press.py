"""Evidence-only, one 20-club press roundup per official FPL gameweek.

The existing GitHub Actions heartbeat calls this module. It checks club sources
at most once an hour, starts 72h before the first fixture, publishes around
six hours before kickoff and edits the SAME Telegram message before deadline.
No fixtures or managerial quotes are hard-coded.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import subprocess
from zoneinfo import ZoneInfo

from .press_sources import lookup
from .press_graphic import render

UK = ZoneInfo("Europe/London")
NEPAL = ZoneInfo("Asia/Kathmandu")
ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state/matchday_press.json"
SCOUTING_LEAD = timedelta(hours=72)
SEND_LEAD = timedelta(hours=6)
CHECK_INTERVAL = timedelta(hours=1)
MIN_CLUBS = 4


def clock(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def matchdays(snapshot, now):
    """Yield ALL scheduled clubs in each approaching official GW, not a day slice.

    The authoritative fixture feed and FPL deadlines handle postponements,
    Friday/midweek starts, doubles and gameweeks 11-38 automatically.
    """
    for event in sorted(snapshot.events, key=lambda e: e.get("id", 999)):
        gw = event.get("id")
        deadline_text = event.get("deadline_time")
        if type(gw) is not int or not 1 <= gw <= 38 or not deadline_text:
            continue
        deadline = clock(deadline_text)
        if not now < deadline:
            continue
        fixtures = sorted(
            (f for f in snapshot.fixtures if f.get("event") == gw and f.get("kickoff_time")
             and not f.get("finished")),
            key=lambda f: f["kickoff_time"],
        )
        if not fixtures:
            continue
        first = clock(fixtures[0]["kickoff_time"])
        if not first - SCOUTING_LEAD <= now < first:
            continue
        pairs = {}
        for f in fixtures:
            h, a = f.get("team_h"), f.get("team_a")
            if h in snapshot.teams and a in snapshot.teams:
                pairs[str(h)] = a
                pairs[str(a)] = h
        if not pairs:
            continue
        local = first.astimezone(UK)
        season = local.year if local.month >= 7 else local.year - 1
        yield {
            "gw": gw, "first": first, "deadline": deadline, "pairs": pairs,
            "date": local.date().isoformat(), "season": season,
            "key": f"{season}:GW{gw}",
        }


def caption_for(day, names, facts, now):
    """Exactly five Telegram lines, with clickable official-club source names."""
    lines = [
        f"GW{day['gw']} | FPL VORTEX PRESS CONFERENCE | {day['season']}/{str(day['season']+1)[-2:]}",
        f"{len(facts)}/{len(names)} clubs: verified pre-match reports; others awaiting evidence",
        "Fantasy deadline: " + day["deadline"].astimezone(NEPAL).strftime("%a %d %b, %I:%M %p NPT"),
        "Club sources: ",
        f"#FPL #FPLVORTEX #GW{day['gw']}",
    ]
    entities = []
    for key in sorted(facts, key=lambda k: names[k]):
        name = names[key]
        proposed = lines[3] + (" · " if lines[3] != "Club sources: " else "") + name
        if len(proposed) > 700:
            break
        if lines[3] != "Club sources: ":
            lines[3] += " · "
        offset = len("\n".join(lines[:3]).encode("utf-16-le")) // 2 + 1 + len(lines[3].encode("utf-16-le")) // 2
        lines[3] += name
        entities.append({"type": "text_link", "offset": offset,
                         "length": len(name.encode("utf-16-le")) // 2, "url": facts[key]["url"]})
    if not entities:
        lines[3] += "see verified club reports"
    return "\n".join(lines), entities


def _retire_incorrect_legacy_post(state, write, client_factory, now):
    """Delete ONLY the identified false-positive GW11 Palace coaching interview.

    State ties the previous press graphic to Telegram message 521. Never delete
    the separate schedule post (522), or a message without this exact receipt.
    """
    old = state.get("11:2026-11-21")
    if not isinstance(old, dict) or old.get("removed") or old.get("message") != 521:
        return
    fact = old.get("facts", {}).get("8", {})
    if fact.get("title") != "Every word from Thomas Frank's first Palace press conference":
        return
    if old.get("delete_checked") and now - clock(old["delete_checked"]) < CHECK_INTERVAL:
        return
    old["delete_checked"] = now.isoformat()
    write(STATE, state)
    try:
        client_factory().delete_shared_message(521)
    except Exception as error:
        # Failure to delete a historical post must not interrupt other editions.
        print("GW11 incorrect press graphic removal deferred: " + type(error).__name__)
        return
    old["removed"] = True
    write(STATE, state)
    print("Incorrect GW11 press graphic removed from its original Telegram message.")


def run(snapshot, now, read, write, client_factory, fetch=lookup, render_image=render,
        live_clock=None):
    from .publishing_window import press_delivery
    from .telegram_spacing import blocked_until

    state = read(STATE)
    _retire_incorrect_legacy_post(state, write, client_factory, now)
    for day in matchdays(snapshot, now):
        row = state.setdefault(day["key"], {})
        if row.get("sending"):
            continue  # Uncertain acceptance: do not blindly send a duplicate.
        pairs = day["pairs"]
        facts = {str(k): v for k, v in row.get("facts", {}).items()
                 if str(k) in pairs and isinstance(v, dict)
                 and v.get("opponent") == pairs[str(k)] and v.get("news") and v.get("url")}
        checked = row.get("checked")
        due = not checked or now - clock(checked) >= CHECK_INTERVAL
        if due:
            def find(key):
                club = snapshot.teams[int(key)]
                opponent = snapshot.teams[pairs[key]]
                previous = [
                    clock(f["kickoff_time"]) for f in snapshot.fixtures
                    if f.get("kickoff_time") and int(key) in (f.get("team_h"), f.get("team_a"))
                    and clock(f["kickoff_time"]) < day["first"]
                ]
                since = max([day["first"] - timedelta(days=6), *previous])
                try:
                    result = fetch(club, opponent, now, since)
                except (OSError, ValueError, RuntimeError):
                    return key, None
                return key, result
            with ThreadPoolExecutor(max_workers=6) as pool:
                for key, item in pool.map(find, sorted(pairs, key=int)):
                    if not item or not item.get("news") or not item.get("url"):
                        continue
                    old = facts.get(key)
                    if old and old.get("published", "") > item.get("published", ""):
                        continue
                    facts[key] = {**item, "opponent": pairs[key]}
            row.update(facts=facts, checked=now.isoformat())
            write(STATE, state)
        current = live_clock() if live_clock else now
        if current >= day["deadline"] or current >= day["first"]:
            continue  # News published after the FPL deadline is not transfer advice.
        if current < day["first"] - SEND_LEAD:
            continue
        if len(facts) < min(MIN_CLUBS, len(pairs)):
            continue  # Do not publish a 1/20 pseudo-roundup or fabricate quotes.
        version = sha256(json.dumps(
            [day["first"].isoformat(), day["deadline"].isoformat(), pairs, facts],
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if row.get("version") == version:
            continue
        names = {key: snapshot.teams[int(key)]["name"] for key in sorted(pairs, key=int)}
        path = ROOT / "outbox/assets" / f"press-GW{day['gw']}-{day['season']}.png"
        render_image(path, day, names, facts, False, teams=snapshot.teams)
        caption, entities = caption_for(day, names, facts, current)
        if len(caption) > 1024:
            raise ValueError("Press roundup caption exceeds Telegram size")
        if not row.get("message") and blocked_until(current):
            continue  # Honour Telegram spacing; existing scheduled checks will retry.
        client = client_factory()
        if not row.get("message"):
            row["sending"] = True
            write(STATE, state)
            if os.getenv("GITHUB_ACTIONS") == "true":
                subprocess.run(["bash", ".github/scripts/persist-publishing-receipts.sh"],
                               cwd=ROOT, check=True)
        try:
            with press_delivery():
                if row.get("message"):
                    mid = client.edit_shared_png(path, caption, row["message"], entities=entities)
                else:
                    mid = client.send_shared_png(path, caption, "Press conference", day["gw"],
                                                 entities=entities)
        except Exception as error:
            if getattr(error, "confirmed_rejection", False):
                row.pop("sending", None)
                write(STATE, state)
            raise
        row.update(message=mid, version=version, sending=False, facts=facts)
        write(STATE, state)
        return True
    return False
