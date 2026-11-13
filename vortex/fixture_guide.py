"""Build the daily six-gameweek fixture guide from official FPL data."""
from __future__ import annotations

from math import isfinite

from .content import Card, Content
from .fpl import FplSnapshot
from .recommendations import number
from .schedule import TIMEZONE

KIND = "fixture_guide"
TITLE = "FPL GAMEWEEK {gw} FIXTURE GUIDE"


def build(snapshot: FplSnapshot) -> Content:
    gw = snapshot.gameweek()
    if not gw:
        raise ValueError("No verified upcoming gameweek for the fixture guide")
    events = sorted({e["id"] for e in snapshot.events
                     if type(e.get("id")) is int and e["id"] >= gw and not e.get("finished")})[:6]
    if not events:
        raise ValueError("Official gameweek calendar is missing")
    ranked = []
    for club_id, club in snapshot.teams.items():
        if not club.get("name") or not club.get("code"):
            continue
        tiles = []
        for event in events:
            matches = snapshot.fixtures_for_gameweek({"team": club_id}, event)
            if any(opp == "TBD" or fdr is None or code is None for opp, _, fdr, code in matches):
                break
            tiles.extend((f"{event} {opp}", venue, fdr, code)
                         for opp, venue, fdr, code in matches)
            if not matches:
                tiles.append((f"{event} BLANK", "", 0, None))
        else:
            played = [tile for tile in tiles if tile[2]]
            if played:
                average = sum(tile[2] for tile in played) / len(played)
                ranked.append((average, -len(played), club_id, club, tuple(tiles)))

    if len(ranked) < 6:
        raise ValueError("Fewer than six clubs have verified fixtures and difficulty ratings")
    ranked.sort(key=lambda row: row[:3])
    cards = []
    for index, (average, matches, club_id, club, tiles) in enumerate(
        [*ranked[:3], *reversed(ranked[-3:])]
    ):
        candidates = []
        for player in snapshot.players:
            form = number(player.get("form"))
            points = number(player.get("total_points"))
            if (player.get("team") == club_id and player.get("status") == "a"
                    and player.get("web_name") and (number(player.get("minutes")) or 0) > 0
                    and player.get("element_type") in (2, 3, 4)
                    and form is not None and isfinite(form)
                    and points is not None and isfinite(points)):
                candidates.append((form, points, -player["id"], player))
        selected = max(candidates, default=(0, 0, 0, None), key=lambda row: row[:3])
        form, points, _, player = selected
        name = snapshot.name(player) if player else ""
        note = f"{form:.1f} form • {points:.0f} FPL pts" if player else "Club fixture run"
        home = sum(venue == "H" for _, venue, _, _ in tiles)
        cards.append(Card(
            club["name"], name, "TARGET" if index < 3 else "CAUTION",
            (f"{average:.2f} avg FDR", f"{home} home / {-matches} fixtures", note),
            snapshot.photo_code(player) if player else None, club["code"],
            {"matches": -matches, "home": home}, tiles,
        ))

    day = snapshot.fetched_at.astimezone(TIMEZONE).date()
    span = f"GW{gw}–{events[-1]}" if events[-1] != gw else f"GW{gw}"
    target, caution = cards[0], cards[3]
    target_label = target.headline + (f" ({target.subtitle})" if target.subtitle else "")
    caption = "\n".join([
        f"📊 FPL GW{gw} Fixture Guide | {day:%d %b}",
        f"✅ Target {target_label} · {target.fields[0]}",
        f"⚠️ Tough run for {caution.headline} · {caution.fields[0]}",
        "👇 Who makes your transfer shortlist?",
        f"#FPL #FPLCommunity #GW{gw} #FPLVORTEX #FantasyPremierLeague",
    ])
    verdict = f"Target {target.headline}  •  Think twice on {caution.headline}"
    return Content(KIND, TITLE.format(gw=gw), span, tuple(cards), verdict, caption,
                   snapshot.fetched_at.isoformat(), gw, "")
