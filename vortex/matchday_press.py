"""Evidence-only, one 20-club press roundup per official FPL gameweek.

The GitHub Actions heartbeat discovers conference times and checks club sources.
It publishes after the last relevant presser, then edits before the FPL deadline.
No fixtures or managerial quotes are hard-coded.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import subprocess
from unicodedata import normalize
from zoneinfo import ZoneInfo

from .press_sources import ALIASES, lookup
from .press_schedule import conference_times, discover
from .press_graphic import render

UK = ZoneInfo("Europe/London")
NEPAL = ZoneInfo("Asia/Kathmandu")
ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state/matchday_press.json"
SCOUTING_LEAD = timedelta(days=5)
TIMETABLE_INTERVAL = timedelta(minutes=15)
REPORT_GRACE = timedelta(minutes=30)
DEADLINE_FALLBACK = timedelta(minutes=90)
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
        if type(gw) is not int or not 1 <= gw <= 38 or not deadline_text or event.get("finished"):
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
                pairs.setdefault(str(h), a)
                pairs.setdefault(str(a), h)
        if not pairs:
            continue
        local = first.astimezone(UK)
        season = local.year if local.month >= 7 else local.year - 1
        yield {
            "gw": gw, "first": first, "deadline": deadline, "pairs": pairs,
            "date": local.date().isoformat(), "season": season,
            "key": f"{season}:GW{gw}",
        }


def caption_for(day, names, facts, now, *, updated=False):
    """Exactly five Telegram lines, with clickable sources for each club."""
    coverage = f"{len(facts)}/{len(names)} clubs: verified pre-match reports"
    if len(facts) < len(names):
        coverage += "; others awaiting evidence"
    lines = [
        f"GW{day['gw']} | FPL VORTEX PRESS CONFERENCE | {day['season']}/{str(day['season']+1)[-2:]} | "
        + ("UPDATED " if updated else "AS OF ") + now.astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC"),
        coverage,
        "Fantasy deadline: " + day["deadline"].astimezone(NEPAL).strftime("%a %d %b, %I:%M %p NPT"),
        "Report sources: ",
        f"#FPL #FPLVORTEX #GW{day['gw']}",
    ]
    entities = []
    for key in sorted(facts, key=lambda k: names[k]):
        name = names[key]
        proposed = lines[3] + (" · " if lines[3] != "Report sources: " else "") + name
        if len(proposed) > 700:
            break
        if lines[3] != "Report sources: ":
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


def _club_key(name):
    return re.sub(r"[^a-z0-9]", "", normalize("NFKD", name).casefold())


def _scout_reports(timetable, day, names, now):
    """Use only the named clubs in the GW-specific Premier League summary."""
    aliases = {
        _club_key(alias): key
        for key, name in names.items()
        for alias in (name, *ALIASES.get(name, ()), *SCOUT_CLUB_ALIASES.get(name, ()))
    }
    reports = {}
    for date, source in sorted(timetable.items()):
        source_day = clock(f"{date}T00:00:00").replace(tzinfo=UK)
        if source_day > now:
            continue
        for line in source.get("summary", ()):
            club, separator, news = line.partition(":")
            key = aliases.get(_club_key(club))
            if not (key and separator and news.strip()) or re.search(
                    r"coming soon|updates? to follow|awaiting|^\s*(?:tbc|tbd)\b", news, re.I):
                continue
            reports[key] = {
                "club": names[key], "opponent": day["pairs"][key],
                "news": news.strip(), "url": source["url"],
                "published": source_day.isoformat(), "source": "Fantasy Football Scout",
            }
    return reports


SCOUT_CLUB_ALIASES = {
    "Brighton": ("Brighton and Hove Albion", "Brighton & Hove Albion"),
    "Coventry": ("Coventry City",), "Hull": ("Hull City",),
    "Ipswich": ("Ipswich Town",), "Leeds": ("Leeds United",),
    "Newcastle": ("Newcastle United",), "West Ham": ("West Ham United",),
    "Wolves": ("Wolverhampton Wanderers",), "Leicester": ("Leicester City",),
    "Spurs": ("Tottenham Hotspur",),
}


def report_target(deadline, times, clubs):
    if not times:
        return deadline - DEADLINE_FALLBACK
    last = times[-1]
    ready = max(last, min(last + REPORT_GRACE, deadline - REPORT_GRACE))
    if len(times) < clubs:
        ready = max(ready, deadline - DEADLINE_FALLBACK)
    return ready


def _sync_discord(day, row, state, write, factory, path, caption, combined, version):
    """Keep one independently receipted Discord report per official gameweek."""
    if factory is None or row.get("discord_version") == version or row.get("discord_sending"):
        return False
    from .syndication import NewsPost, DeliveryRejected
    from .publishing_window import press_delivery
    sources = []
    for fact in combined.values():
        url = fact["url"]
        if url not in sources:
            sources.append(url)
    content = caption
    for url in sources:
        if len(content)+len(url)+1 > 1950:
            break
        content += "\n" + url
    post = NewsPost(day["key"]+":press", "Press conference", content, day["gw"], path)
    client = factory()
    if not row.get("discord_message"):
        row["discord_sending"] = True
        write(STATE, state)
        if os.getenv("GITHUB_ACTIONS") == "true":
            subprocess.run(["bash", ".github/scripts/persist-publishing-receipts.sh"], cwd=ROOT, check=True)
    try:
        with press_delivery():
            if row.get("discord_message"):
                mid = client.edit_news(row["discord_message"], post)
            else:
                mid = client.send(post)
        if not str(mid).isdigit() or int(mid) <= 0:
            raise RuntimeError("Discord press receipt missing")
    except DeliveryRejected:
        row.pop("discord_sending", None)
        write(STATE, state)
        raise
    row.update(discord_message=str(mid), discord_version=version, discord_sending=False)
    write(STATE, state)
    return True


def run(snapshot, now, read, write, client_factory, fetch=lookup, render_image=render,
        live_clock=None, schedule_lookup=discover, discord_factory=None):
    from .publishing_window import press_delivery
    from .telegram_spacing import blocked_until

    state = read(STATE)
    _retire_incorrect_legacy_post(state, write, client_factory, now)
    for day in matchdays(snapshot, now):
        row = state.setdefault(day["key"], {})
        if row.get("sending"):
            continue  # Uncertain acceptance: do not blindly send a duplicate.
        pairs = day["pairs"]
        names = {key: snapshot.teams[int(key)]["name"] for key in sorted(pairs, key=int)}
        checked_schedule = row.get("schedule_checked")
        if not checked_schedule or now - clock(checked_schedule) >= TIMETABLE_INTERVAL:
            timetable = row.setdefault("timetable", {})
            try:
                timetable.update(schedule_lookup(day["gw"], now, day["deadline"]))
            except (OSError, ValueError, RuntimeError) as error:
                print(f"GW{day['gw']} press timetable source: {type(error).__name__}")
            row["schedule_checked"] = now.isoformat()
            write(STATE, state)
        timetable = row.get("timetable", {})
        times = conference_times(timetable, day["deadline"])
        target = report_target(day["deadline"], times, len(pairs))
        if not row.get("message") and now < target:
            print(f"GW{day['gw']} press roundup waiting until {target.isoformat()} "
                  f"({len(times)}/{len(pairs)} published conference times)")
        facts = {str(k): v for k, v in row.get("facts", {}).items()
                 if str(k) in pairs and isinstance(v, dict)
                 and v.get("opponent") == pairs[str(k)] and v.get("news") and v.get("url")
                 and v.get("published")}
        scout = _scout_reports(timetable, day, names, now)
        checked = row.get("checked")
        due = not checked or now - clock(checked) >= CHECK_INTERVAL
        # Deliver on time if the live league roundup already has enough evidence.
        # Slower official-club lookups can enrich the existing message afterward.
        ready_from_scout = not row.get("message") and now >= target and len(scout) >= min(MIN_CLUBS, len(pairs))
        if due and not ready_from_scout:
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
        combined = dict(scout)
        for key, item in facts.items():
            secondary = scout.get(key)
            if not secondary or clock(item["published"]).astimezone(UK).date() >= clock(secondary["published"]).date():
                combined[key] = item
        current = live_clock() if live_clock else now
        if current >= day["deadline"] or current >= day["first"]:
            continue  # News published after the FPL deadline is not transfer advice.
        if not row.get("message") and current < target:
            continue
        if len(combined) < min(MIN_CLUBS, len(pairs)):
            print(f"GW{day['gw']} press roundup awaiting verified reports ({len(combined)}/{len(pairs)})")
            continue  # Do not publish a 1/20 pseudo-roundup or fabricate quotes.
        version = sha256(json.dumps(
            ["premium-neon-v1", day["first"].isoformat(), day["deadline"].isoformat(), pairs,
             {key: (fact["news"], fact.get("quote"), fact["url"])
              for key, fact in combined.items()}],
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = ROOT / "outbox/assets" / f"press-GW{day['gw']}-{day['season']}.png"
        if row.get("version") == version:
            if discord_factory and row.get("discord_version") != version and path.is_file():
                caption, _ = caption_for(day, names, combined, clock(row.get("posted_at") or current.isoformat()),
                                         updated=bool(row.get("was_update")))
                if _sync_discord(day, row, state, write, discord_factory, path, caption, combined, version):
                    return True
            continue
        updated = bool(row.get("message"))
        render_day = {**day, "data_at": current.astimezone(timezone.utc), "updated": updated,
                      "players": getattr(snapshot, "players", ())}
        render_image(path, render_day, names, combined, False, teams=snapshot.teams)
        caption, entities = caption_for(day, names, combined, current, updated=updated)
        current = live_clock() if live_clock else now
        if current >= day["deadline"]:
            continue
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
        if live_clock and live_clock() >= day["deadline"]:
            if not row.get("message"):
                row.pop("sending", None)
                write(STATE, state)
            continue
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
        row.update(message=mid, version=version, sending=False, facts=facts,
                   posted_at=render_day["data_at"].isoformat(), was_update=updated)
        write(STATE, state)
        _sync_discord(day, row, state, write, discord_factory, path, caption, combined, version)
        return True
    return False
