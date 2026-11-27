"""Price prediction 16/55: independent, read-only preparation for scheduler migration.

Official FPL bootstrap-static predictions, not confirmed price changes.
The caller supplies the verified next update time; never infer it from a player's data.
"""
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from math import isfinite
from .editorial_inputs import RequiredInput

UK = ZoneInfo("Europe/London")
EDITION = "price-prediction"  # replaces retired confirmed-price-changes at 16/55
SOURCE = "https://fantasy.premierleague.com/api/bootstrap-static/"


def next_published_update(now):
    """PL's published daily midnight UK rule; not a scraped API clock."""
    if now.tzinfo is None:
        raise ValueError("timezone-aware time required")
    local = now.astimezone(UK)
    return datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=UK)


def official_clock(bootstrap, now):
    """Exact live API paths verified in the 26 Nov 2026 read-only audit."""
    if now.tzinfo is None:
        raise ValueError("timezone-aware time required")
    try:
        config=bootstrap["game_config"]
        deadlines=config["settings"]["price_change_deadlines"]
        updated=datetime.fromisoformat(config["status"]["price_change_last_updated"].replace("Z","+00:00"))
        if updated.tzinfo is None or not -timedelta(minutes=2) <= now-updated <= timedelta(minutes=45):
            raise ValueError("stale prediction timestamp")
        if not isinstance(deadlines,list) or not deadlines:
            raise ValueError("missing deadlines")
        parsed=[datetime.fromisoformat(v.replace("Z","+00:00")) for v in deadlines]
        if any(v.tzinfo is None for v in parsed):
            raise ValueError("timezone missing")
        # Offset zero refers to the first source deadline, not the next guessed midnight.
        # Do not advance past a stale first deadline while keeping old projections.
        if parsed != sorted(set(parsed)) or not timedelta(0) < parsed[0]-now <= timedelta(hours=26):
            raise ValueError("invalid/stale first deadline")
        return parsed[0], updated
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError) as exc:
        raise RequiredInput("Official FPL price clock unavailable or stale") from exc


PRICE_LEAD = timedelta(hours=1)
PRICE_RESEARCH_LEAD = timedelta(hours=4, minutes=15)
PRICE_GRACE = timedelta(minutes=15)
RESEARCH_KEY = "_pre_gameweek_price_research"
SETTLEMENT_KEY = "_observed_price_settlement"
COST_SNAPSHOT_KEY = "_consecutive_cost_snapshot"


def price_observation(snapshot):
    """Verified cost and calibrated next-update state, keyed by official player ID."""
    result = {}
    for player in snapshot.players:
        pid, cost = player.get("id"), player.get("now_cost")
        if type(pid) is not int or type(cost) is not int or cost <= 0:
            continue
        if str(pid) in result:
            raise RequiredInput("Duplicate official player identity")
        projection = player.get("price_change_projections")
        rows = [row for row in projection if isinstance(row, dict) and row.get("offset") == 0] if isinstance(projection, list) else []
        projected = numeric(rows[0].get("projected_percent")) if len(rows) == 1 and player.get("price_change_calibrating") is False else None
        band = rows[0].get("likelihood") if projected is not None else None
        result[str(pid)] = {"code": player.get("code"), "cost": cost,
                            "threshold": (1 if projected >= 100 else -1 if projected <= -100 else 0) if projected is not None else None,
                            "band": band if type(band) is int and -5 <= band <= 5 else None,
                            "transfers_in_event": player.get("transfers_in_event"),
                            "transfers_out_event": player.get("transfers_out_event"),
                            "ownership": player.get("selected_by_percent"),
                            "status": player.get("status"), "news": player.get("news")}
    if not result:
        raise RequiredInput("No verified price observation")
    return result


def material_changes(previous, current):
    """Only real cost deltas or a verified threshold/likelihood transition qualify."""
    changes = []
    for pid, new in current.items():
        old = previous.get(pid)
        if not isinstance(old, dict) or old.get("code") != new.get("code"):
            continue
        fields = [key for key in ("cost", "threshold", "band")
                  if old.get(key) is not None and new.get(key) is not None and old[key] != new[key]]
        if fields:
            changes.append({"id": int(pid), "before": {key: old[key] for key in fields},
                            "after": {key: new[key] for key in fields}})
    return changes


def observe_settlement(snapshot, state):
    """Bound observed cost settlement by actual consecutive snapshot times.

    The API prediction deadline is not an observed settlement timestamp.
    A changed cost only establishes an interval, never an exact minute.
    """
    from .autonomous_schedule import season_id
    if not hasattr(snapshot, "events"):
        return False
    try:
        observed = snapshot.fetched_at
        deadline, _ = official_clock({"game_config": snapshot.game_config}, observed)
        season = season_id(snapshot, observed)
        costs = {pid: {"code": row["code"], "cost": row["cost"]}
                 for pid, row in price_observation(snapshot).items()
                 if type(row["code"]) is int}
        if not costs:
            return False
        previous = state.get(COST_SNAPSHOT_KEY, {})
        if previous.get("season") == season:
            at = datetime.fromisoformat(previous["at"])
            if observed <= at:
                return False
            prior_deadline = datetime.fromisoformat(previous["deadline"])
            if at < prior_deadline <= observed < deadline and observed-at <= timedelta(hours=2):
                changes = material_changes(previous["players"], costs)
                if changes:
                    state[SETTLEMENT_KEY] = {
                        "season": season, "expected_at": prior_deadline.isoformat(),
                        "last_before": at.isoformat(), "first_after": observed.isoformat(),
                        "changes": changes,
                    }
        state[COST_SNAPSHOT_KEY] = {"season": season, "at": observed.isoformat(),
                                   "deadline": deadline.isoformat(), "players": costs}
        return True
    except (RequiredInput, ValueError, KeyError, TypeError, AttributeError):
        return False


def valid_settlement(row, season, now):
    try:
        lower = datetime.fromisoformat(row["last_before"])
        upper = datetime.fromisoformat(row["first_after"])
        expected = datetime.fromisoformat(row["expected_at"])
        return (row["season"] == season and lower < expected <= upper <= now
                and upper-lower <= timedelta(hours=2) and now-upper <= timedelta(days=7)
                and any("cost" in c.get("before", {}) and c["before"]["cost"] != c["after"]["cost"]
                        for c in row["changes"]))
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def research_evidence(snapshot, now, update, state, *, research_at=None, post_at=None):
    """Match verified advance research to the T-1 run; require at least three elapsed hours."""
    from .autonomous_schedule import season_id
    row = state.get(RESEARCH_KEY, {})
    if not isinstance(row, dict) or row.get("update_at") != update.isoformat() or row.get("gw") != snapshot.gameweek() or row.get("season") != season_id(snapshot, now):
        return None
    research_at = research_at or update-PRICE_RESEARCH_LEAD
    post_at = post_at or update-PRICE_LEAD
    try:
        checked = datetime.fromisoformat(row["checked_at"])
        if row.get("research_at") != research_at.isoformat() or row.get("post_at") != post_at.isoformat():
            return None
        if not research_at <= checked < research_at+PRICE_GRACE:
            return None
        from .research_gap import verified_gap
        if snapshot.fetched_at <= checked or not verified_gap(row['checked_at'], post_at) or not verified_gap(row['checked_at'], now):
            return None
        changes = material_changes(row["players"], price_observation(snapshot))
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return {"checked_at": checked.isoformat(), "changes": changes,
            "research_at": research_at.isoformat(), "post_at": post_at.isoformat()}



def price_schedule(snapshot, now, update, state):
    """Prefer the original T-1 window; otherwise select an earlier free check.

    Use the actual API deadline and the existing heartbeat, never move other
    editions. No same-day slot is promised when all options are occupied.
    """
    from .autonomous_schedule import ET, SLOTS, eligible_on, slot_start, special_triggers, publication_key, season_id, retryable
    from .schedule import SLOT_HOURS
    from .daily_cutover import slots as daily_slots
    from .publishing_window import allowed
    from .telegram_spacing import GAP

    preferred = update-PRICE_LEAD
    day = preferred.astimezone(ET)
    posts = []
    research = []
    for offset in (-1, 0, 1):
        local = day+timedelta(days=offset)
        posts.extend((s.edition, slot_start(s,local)) for s in SLOTS if eligible_on(s,local))
        posts.extend((s.edition, slot_start(s,local)) for s in daily_slots(local))
        posts.extend((name,local.replace(hour=h,minute=m,second=0,microsecond=0)) for name,(h,m) in SLOT_HOURS.items())
        if local.weekday()==4:
            posts.append(("rotation-planner",local.replace(hour=20,minute=0,second=0,microsecond=0)))
        # Existing documented research starts, never move these workflows.
        ranges = [("transfer-research",1,13,17),("desk-research",4,13,15),
                  ("radar-research",5,58,12)]
        if local.weekday() in (4,5):
            ranges.append(("matrix-research",15,28,12))
        if local.weekday()==0:
            ranges.extend([("legacy-position-research",9,30,60),("legacy-monday-research",19,0,60)])
        if local.weekday()==1:
            ranges.append(("legacy-wildcard-research",14,30,60))
        research.extend((name,local.replace(hour=h,minute=m,second=0,microsecond=0),timedelta(minutes=length))
                        for name,h,m,length in ranges)
    for other, at in special_triggers(snapshot, now):
        if at is not None and retryable(state.get(publication_key(other,now,snapshot.gameweek(),season_id(snapshot,now)),{})):
            posts.append((other.edition,at))
    def conflicts(check, post):
        reasons=[]
        for name,at in posts:
            if check-GAP < at < check+PRICE_GRACE or post-GAP < at < post+GAP+PRICE_GRACE:
                reasons.append((name,at.isoformat()))
        for name,at,length in research:
            if at < check+PRICE_GRACE and check < at+length or at < post+PRICE_GRACE and post < at+length:
                reasons.append((name,at.isoformat()))
        return sorted(set(reasons))
    check=update-PRICE_RESEARCH_LEAD
    original=conflicts(check,preferred)
    if not original and allowed(preferred):
        return check,preferred,[]
    # Only earlier, already configured half-hour heartbeats in the same ET
    # date; a dedicated overnight check provides at least three elapsed hours.
    candidate_check=day.replace(hour=2,minute=43,second=0,microsecond=0)
    for hour in range(day.hour,-1,-1):
        for minute in (30,0):
            post=day.replace(hour=hour,minute=minute,second=0,microsecond=0)
            if not allowed(post) or post>=preferred or post-candidate_check < timedelta(hours=3,minutes=15):
                continue
            if not conflicts(candidate_check,post):
                return candidate_check,post,original
    return None,None,original


def opportunity(snapshot, now, state):
    """Find a verified pre-change opportunity without moving other slots."""
    from .autonomous_schedule import ET, Slot, publication_key, season_id, retryable
    from .fpl import upcoming_deadline
    update, updated = official_clock({"game_config": snapshot.game_config}, max(now, snapshot.fetched_at))
    update = update.astimezone(timezone.utc)
    research_at, trigger, conflicts = price_schedule(snapshot, now, update, state)
    info = {"post": EDITION, "update_at": update.isoformat(), "source_updated_at": updated.isoformat(),
            "conflicts": conflicts}
    if trigger is None:
        return None, {**info, "status":"skipped-schedule-conflict"}
    # Normalize to UTC for durable comparisons and DST-safe elapsed durations.
    trigger, research_at = trigger.astimezone(timezone.utc), research_at.astimezone(timezone.utc)
    info.update(trigger=trigger.isoformat(), research_at=research_at.isoformat())
    local = trigger.astimezone(ET)
    slot = Slot("price_changes", EDITION, local.hour, local.minute,
                display_name="Price Change Prediction", price_update_at=update.isoformat())
    season = season_id(snapshot, now)
    key = publication_key(slot, now, snapshot.gameweek(), season)
    target_deadline = upcoming_deadline(snapshot)
    if not snapshot.gameweek() or target_deadline is None or now >= target_deadline or trigger >= target_deadline:
        return None, {**info, "status":"no-actionable-gameweek"}
    existing = state.get(key, {})
    if existing.get("identity") or not retryable(existing):
        return None, {**info, "status":"closed"}
    if now >= trigger+PRICE_GRACE:
        return None, {**info, "status":"skipped-schedule-conflict" if conflicts else "missed-window"}
    if research_at <= now < research_at+PRICE_GRACE:
        prior = state.get(RESEARCH_KEY,{})
        if prior.get("update_at") != update.isoformat() or prior.get("post_at") != trigger.isoformat() or prior.get("gw") != snapshot.gameweek() or prior.get("season") != season:
            state[RESEARCH_KEY] = {"update_at":update.isoformat(),"gw":snapshot.gameweek(),
                                   "season":season,"checked_at":max(now,snapshot.fetched_at).isoformat(),
                                   "fetched_at":snapshot.fetched_at.isoformat(),"players":price_observation(snapshot),
                                   "research_at":research_at.isoformat(),"post_at":trigger.isoformat()}
        return None, {**info,"status":"research-verified"}
    if now < trigger:
        return None, {**info,"status":"waiting"}
    proof=research_evidence(snapshot,now,update,state,research_at=research_at,post_at=trigger)
    if proof is None:
        return None,{**info,"status":"research-missing"}
    if not proof["changes"]:
        return None,{**info,"status":"no-new-facts"}
    observed=state.get(SETTLEMENT_KEY,{})
    if not valid_settlement(observed,season,now):
        return None,{**info,"status":"settlement-unverified"}
    proof["observed_settlement"]=observed
    return slot,{**info,"status":"due","research":proof}


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if isfinite(n) else None


def ownership_snapshot(snapshot):
    """Aggregate public ownership only; no authenticated manager data."""
    return {"at": snapshot.fetched_at.isoformat(), "players": {
        str(p["code"]): numeric(p.get("selected_by_percent"))
        for p in snapshot.players if type(p.get("code")) is int
    }}


def ownership_trend(snapshot, previous, player):
    """Measured percentage-point delta over the recorded interval, not a forecast."""
    if not isinstance(previous, dict) or not isinstance(previous.get("players"), dict):
        return None
    try:
        at = datetime.fromisoformat(previous["at"])
        elapsed = snapshot.fetched_at - at
    except (KeyError, TypeError, ValueError):
        return None
    if not timedelta(minutes=5) <= elapsed <= timedelta(hours=26):
        return None
    old = numeric(previous["players"].get(str(player.get("code"))))
    current = numeric(player.get("selected_by_percent"))
    return round(current-old, 2) if old is not None and current is not None else None


def select_rows(snapshot, update_at, previous=None):
    if update_at.tzinfo is None:
        raise ValueError("timezone-aware update required")
    rows = []
    seen = set()
    for p in snapshot.players:
        pid = p.get("id")
        if type(pid) is not int or pid in seen or p.get("price_change_calibrating") is not False:
            continue
        if p.get("can_transact") is False:
            continue
        locked = p.get("price_change_locked_until")
        if locked:
            try:
                lock = datetime.fromisoformat(locked.replace("Z", "+00:00"))
                if lock.tzinfo is None or lock > update_at:
                    continue
            except (ValueError, TypeError, AttributeError):
                continue
        projections = p.get("price_change_projections")
        if not isinstance(projections, list):
            continue
        next_rows = [r for r in projections if isinstance(r, dict) and type(r.get("offset")) is int and r["offset"] == 0]
        if len(next_rows) != 1:
            continue
        projected = numeric(next_rows[0].get("projected_percent"))
        progress = numeric(p.get("price_change_percent"))
        band = next_rows[0].get("likelihood")
        cost = p.get("now_cost")
        if (projected is None or projected == 0 or progress is None or type(band) is not int
                or not -5 <= band <= 5 or type(cost) is not int or cost <= 0
                or p.get("element_type") not in (1,2,3,4)
                or not snapshot.photo_code(p) or not snapshot.team_code(p)):
            continue
        seen.add(pid)
        rows.append(dict(player=p, projected=projected, progress=progress, likelihood=band,
                         hourly_rate=numeric(p.get("price_change_hourly_rate")),
                         owned=numeric(p.get("selected_by_percent")),
                         ownership_delta=ownership_trend(snapshot, previous, p)))
    rises = sorted((r for r in rows if r["projected"] > 0), key=lambda r:(-r["projected"],-r["progress"],r["player"]["id"]))[:10]
    falls = sorted((r for r in rows if r["projected"] < 0), key=lambda r:(r["projected"],r["progress"],r["player"]["id"]))[:10]
    if not rises and not falls:
        raise RequiredInput("No verified next-update predictions")
    return rises, falls


def build_board(snapshot, update_at, previous=None):
    if update_at <= snapshot.fetched_at:
        raise RequiredInput("Prediction update is not in the future")
    rises, falls = select_rows(snapshot, update_at, previous)
    label = update_at.astimezone(UK).strftime("%H:%M UK")
    caption = (
        "⏱ PRICE CHANGE PREDICTION\n"
        f"MONITOR {label}\n\n"
        f"📈 {len(rises)} rise candidates • 📉 {len(falls)} fall candidates\n"
        "Official FPL projections. Moves are not guaranteed.\n\n"
        "#FPL #PriceChanges #FPLTips #FantasyPremierLeague #FPLVORTEX #FPLUpdates"
    )
    return dict(rises=rises, falls=falls, update_at=update_at.isoformat(), caption=caption)


PRICE_ART_SIZE = (1600, 1200)


def render_board(snapshot, board, output, session):
    """The supplied 4:3 two-panel price reference, with current official data."""
    from PIL import Image, ImageDraw
    from .brand_footer import MASTER, verify_exact_master
    from .comparison_board import contain, text
    from .matchup import _image_from_url, _media

    verify_exact_master()
    W, H = PRICE_ART_SIZE
    purple, ink, muted = "#37003C", "#201A29", "#535366"
    white, cyan, emerald = "#FFFFFF", "#04F5FF", "#00FF87"
    green, red = "#008553", "#B91F45"
    canvas = Image.new("RGB", (W, H), purple)
    d = ImageDraw.Draw(canvas)
    with Image.open(MASTER) as original:
        master = original.convert("RGB").resize((1536,864))
        canvas.paste(master.crop((0,0,310,80)).resize((158,41),Image.Resampling.LANCZOS),(34,37))
    def label(value, x, y, width, size, color=white, center=False, minimum=14):
        text(d, value, x, y, width, size=size, color=color, minimum=minimum, center=center)

    update = datetime.fromisoformat(board["update_at"])
    local = snapshot.fetched_at.astimezone(UK)
    label("PRICE CHANGE PREDICTIONS", 220, 26, 1340, 52)
    label(local.strftime("%A, %d %B %Y"), 220, 83, 1340, 29, emerald)
    label("Fantasy Premier League • daily price movement watch", 220, 119, 1340, 21)
    cache = {}
    def side(rows, x, accent, heading, pale):
        width = 756
        d.rounded_rectangle((x,160,x+width,1122),radius=20,fill=white,outline=cyan,width=2)
        d.rounded_rectangle((x,160,x+width,216),radius=18,fill=accent)
        d.rectangle((x,192,x+width,216),fill=accent)
        label(heading,x+22,171,width-44,31)
        label("PLAYER / CLUB",x+87,225,360,20,ink)
        label("LIKELIHOOD",x+443,225,142,17,ink,True)
        label("PREDICTION",x+598,225,145,17,ink,True)
        if not rows:
            label("No verified candidates",x+25,280,width-50,24,muted,True)
        for index, row in enumerate(rows[:10]):
            p = row["player"]
            y = 260 + index*84
            d.rounded_rectangle((x+12,y,x+width-12,y+76),radius=11,fill=pale,outline="#DDD6E0",width=1)
            d.rectangle((x+12,y,x+19,y+76),fill=accent)
            code = snapshot.photo_code(p)
            urls = (
                f"https://resources.premierleague.com/premierleague25/photos/players/250x250/{code}.png",
                f"https://resources.premierleague.com/premierleague25/photos/players/110x140/{code}.png",
                f"https://resources.premierleague.com/premierleague/photos/players/250x250/p{code}.png",
                f"https://images.fantasy.premierleague.com/premierleague/photos/players/250x250/p{code}.png",
            )
            photo = next((img for url in urls if (img := _image_from_url(session,url)) is not None),None)
            crest = _media(session,snapshot.team_code(p),"crest",cache)
            if crest is None:
                raise RequiredInput(f"Authentic club crest missing for official player {p['id']}")
            if photo is not None:
                contain(canvas,photo,(x+25,y+4,66,69),bottom=True,crop_alpha=True)
            else:
                contain(canvas,crest,(x+33,y+7,48,48))
                label("NO PHOTO",x+23,y+56,70,11,muted,True,10)
            label(snapshot.name(p),x+102,y+5,327,29,ink)
            contain(canvas,crest,(x+103,y+43,23,23))
            label(f"{snapshot.team(p)}  •  {snapshot.price(p)}",x+132,y+43,300,19,muted)
            d.rounded_rectangle((x+446,y+25,x+583,y+54),radius=14,fill="#E2F5EA" if accent==green else "#FBE2E8")
            # Official signed likelihood band; no invented probability/word mapping.
            label(f"BAND {row['likelihood']:+d}",x+450,y+29,129,17,accent,True)
            label("TARGET %",x+600,y+7,139,14,muted,True,12)
            label(f"{abs(row['projected']):.1f}%",x+599,y+28,140,29,accent,True)
    side(board["rises"],28,green,"▲ PRICE RISES","#F9FCFA")
    side(board["falls"],816,red,"▼ PRICE DROPS","#FFF9FA")
    label("FPL VORTEX • Official FPL projections • Target progress, not probability • Likelihood: official signed band",
          30,1136,1540,19,white,True)
    label("Expected update: "+update.astimezone(UK).strftime("%H:%M UK")+" • Price movements are not guaranteed",
          30,1166,1540,17,emerald,True)
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output,"PNG",optimize=True)
    return output


def preview():
    """Never writes outbox, receipts, or calls a publishing client."""
    import json
    from .fpl import collect_snapshot
    from .autonomous_content import retrying_session
    from .graphic_numbers import stamp
    session=retrying_session()
    snapshot=collect_snapshot(session)
    folder=Path("output/price-prediction-preview")
    folder.mkdir(parents=True,exist_ok=True)
    # Audit public clock metadata without exporting player lists or any private data.
    from .fpl import _fetch_json
    boot=_fetch_json(session,"bootstrap-static/")
    metadata={}
    def inspect(obj,path=""):
        if not isinstance(obj,dict):
            return
        for key,value in obj.items():
            if key in ("elements","events","teams"):
                continue
            location=f"{path}.{key}" if path else key
            if any(word in key.lower() for word in ("price_change","price_update","cutoff","countdown")):
                metadata[location]=value
            elif isinstance(value,dict):
                inspect(value,location)
    inspect(boot)
    print("PRICE CLOCK METADATA:",json.dumps(metadata,default=str)[:5000])
    (folder/"clock-audit.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    update_at, refreshed_at=official_clock(boot,datetime.now(timezone.utc))
    # Use the same response for ranking and timing, preventing mixed-feed data.
    from dataclasses import replace
    snapshot=replace(snapshot,players=boot["elements"],fetched_at=datetime.now(timezone.utc))
    import os
    prior_path=os.getenv("PRICE_PREVIEW_PRIOR")
    prior=None
    if prior_path:
        try:
            prior=json.loads(Path(prior_path).read_text(encoding="utf-8"))
        except (OSError,ValueError):
            pass
    board=build_board(snapshot,update_at,prior)
    board["source_updated_at"]=refreshed_at.isoformat()
    board["clock_source"]="game_config.settings.price_change_deadlines[0]"
    board["ownership_baseline_at"]=prior.get("at") if isinstance(prior,dict) else None
    (folder/"ownership-snapshot.json").write_text(json.dumps(ownership_snapshot(snapshot)),encoding="utf-8")
    # Invalidate stale art before replacing evidence; never pair different snapshots.
    (folder/"graphic-16.png").unlink(missing_ok=True)
    # Save source evidence even if an authentic portrait cannot be fetched.
    (folder/"facts.json").write_text(json.dumps(board,indent=2,ensure_ascii=False),encoding="utf-8")
    (folder/"caption.txt").write_text(board["caption"],encoding="utf-8")
    path=render_board(snapshot,board,folder/"graphic-16.png",session)
    stamp(path,EDITION)
    print(board["caption"])

if __name__=="__main__":
    preview()
