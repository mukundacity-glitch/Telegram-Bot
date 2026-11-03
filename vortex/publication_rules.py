"""Verified FPL VORTEX editorial contract for *every* publication type.

Never copy FPL Core screenshots as live data. Use live official FPL identities,
current fixtures, and optional source-confirmed FPL Core CSV enrichment.
Keep source/verification metadata out of audience-facing image pixels.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import requests

FDR_COLORS = {1: "#00be86", 2: "#6bcf9c", 3: "#ffd477",
              4: "#f3a36d", 5: "#ef6975"}
FORBIDDEN = re.compile(r"(?i)(?:\bN/?A\b|data unavailable|source:|official fpl availability|shared caption)")
USABLE_ACTIONS = {"BUY", "HOLD", "SELL", "CAPTAIN", "BENCH", "MONITOR", "START"}


def five_gw_fixtures(snapshot: Any, player: dict[str, Any],
                     xpts: dict[tuple[int, int], dict[str, Any]] | None = None
                     ) -> tuple[dict[str, Any], ...]:
    """Five successive official gameweek slots, with blank/double correctness.

    Every known fixture has its own record and optional *independently verified*
    xPts directly tied to official player, event and fixture IDs. Blank GWs are
    explicit fixture markers, never disguised as zero projected points.
    """
    current = snapshot.gameweek()
    if not current or not isinstance(current, int):
        raise ValueError("No current upcoming FPL event")
    pid, team_id = player.get("id"), player.get("team")
    if not isinstance(pid, int) or not isinstance(team_id, int):
        raise ValueError("Missing official player/team ID")
    known = {e.get("id") for e in snapshot.events if isinstance(e.get("id"), int)}
    result: list[dict[str, Any]] = []
    for gw in range(current, min(current + 5, 39)):
        if gw not in known:
            raise ValueError(f"FPL Gameweek {gw} metadata not verified")
        rows = sorted(
            (item for item in snapshot.fixtures
             if item.get("event") == gw and team_id in (item.get("team_h"), item.get("team_a"))
             and not item.get("finished")),
            key=lambda item: (item.get("kickoff_time") or "9999", item.get("id") or 0))
        if not rows:
            result.append({"gw": gw, "blank": True, "opponent": "BLANK", "venue": "",
                           "fdr": None, "xpts": None, "fixture_id": None})
            continue
        for fixture in rows:
            home = fixture.get("team_h") == team_id
            opp_id = fixture.get("team_a") if home else fixture.get("team_h")
            opponent = snapshot.teams.get(opp_id, {})
            fdr = fixture.get("team_h_difficulty" if home else "team_a_difficulty")
            if (not opponent.get("short_name") or not isinstance(fdr, int)
                    or fdr not in FDR_COLORS or not isinstance(fixture.get("id"), int)
                    or not fixture.get("kickoff_time")):
                raise ValueError("Incomplete official FPL future fixture metadata")
            fi = fixture["id"]
            verified_projection = (xpts or {}).get((pid, fi), {})
            point_value = verified_projection.get("xpts")
            if point_value is not None and (
                verified_projection.get("gw") != gw
                or type(point_value) not in (int, float)
                or not 0 <= point_value <= 40
            ):
                raise ValueError("Projected points not verified for official fixture and player")
            result.append({"gw": gw, "blank": False,
                           "opponent": opponent["short_name"],
                           "venue": "H" if home else "A",
                           "fdr": fdr, "xpts": point_value, "fixture_id": fi,
                           "double": len(rows) > 1})
    return tuple(result)


def verified_xpts_snapshot(payload: Any, now: datetime,
                           player_ids: set[int], fixture_ids: set[int]
                           ) -> dict[tuple[int, int], dict[str, Any]]:
    """Optional external model output; absence is normal, never invent xPts.

    Require model identity/version, retrieval timestamp and direct fixture join.
    This intentionally does not interpret official ep_next as per-fixture xPts.
    """
    if not isinstance(payload, dict) or not payload.get("model_version"):
        return {}
    stamp = payload.get("generated_at")
    try:
        generated = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return {}
    if generated.tzinfo is None or not timedelta(0) <= now-generated <= timedelta(hours=30):
        return {}
    results = {}
    for item in payload.get("projections", []):
        if not isinstance(item, dict):
            continue
        pid, fid, gw = item.get("player_id"), item.get("fixture_id"), item.get("gw")
        xpts = item.get("xpts")
        if (type(pid) is int and pid in player_ids and type(fid) is int
            and fid in fixture_ids and type(gw) is int
            and type(xpts) in (int, float) and 0 <= xpts <= 40):
            results[(pid, fid)] = {"gw": gw, "xpts": round(float(xpts), 2),
                                   "model": payload["model_version"]}
    return results


def fetch_verified_xpts(now: datetime, snapshot: Any,
                        session: requests.Session | None = None) -> dict:
    """Only an explicit trusted HTTPS URL; never expose credentials or fabricate."""
    url = os.getenv("FPL_XPTS_SNAPSHOT_URL", "").strip()
    if not url:
        return {}
    parts = urlsplit(url)
    hosts = {"raw.githubusercontent.com", "github.com"}
    if parts.scheme != "https" or parts.hostname not in hosts or parts.username:
        raise ValueError("xPts source must be a reviewed GitHub HTTPS file")
    client = session or requests.Session()
    response = client.get(url, timeout=12, allow_redirects=False)
    response.raise_for_status()
    if len(response.content) > 1_500_000:
        raise ValueError("Oversized external xPts snapshot")
    return verified_xpts_snapshot(
        response.json(), now,
        {p["id"] for p in snapshot.players if isinstance(p.get("id"), int)},
        {f["id"] for f in snapshot.fixtures if isinstance(f.get("id"), int)})


def player_metrics(snapshot: Any, player: dict[str, Any],
                   recent_history: list[dict[str, Any]] | None = None
                   ) -> dict[str, str]:
    """Respect position scoring. DC action count is NOT awarded FPL points."""
    position = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}.get(player.get("element_type"))
    if position is None:
        raise ValueError("Invalid FPL position")
    required = ("id", "code", "team", "now_cost", "selected_by_percent",
                "minutes", "total_points", "form", "status")
    if any(player.get(k) is None for k in required):
        raise ValueError("Missing a mandatory official player field")
    result: dict[str, str] = {
        "POSITION": position, "PRICE": snapshot.price(player),
        "OWNERSHIP": f"{float(player['selected_by_percent']):.1f}%",
        "TOTAL PTS": str(int(player["total_points"])),
        "FORM": f"{float(player['form']):.1f}",
        "MINUTES": str(int(player["minutes"])),
        "AVAILABILITY": str(player["status"]).upper(),
    }
    base = {
        "GOALS": "goals_scored", "ASSISTS": "assists",
        "xG": "expected_goals", "xA": "expected_assists",
        "xGI": "expected_goal_involvements",
        "CS": "clean_sheets", "GC": "goals_conceded",
        "SAVES": "saves", "DC ACTIONS": "defensive_contribution",
        "xGC": "expected_goals_conceded",
    }
    selected = {"GK": ("SAVES", "CS", "GC", "xGC"),
                "DEF": ("CS", "GC", "DC ACTIONS", "xGC", "GOALS", "ASSISTS", "xG", "xA", "xGI"),
                "MID": ("GOALS", "ASSISTS", "xG", "xA", "xGI", "DC ACTIONS"),
                "FWD": ("GOALS", "ASSISTS", "xG", "xA", "xGI")}[position]
    for label in selected:
        field = base[label]
        value = player.get(field)
        if value is not None and str(value).strip() not in ("", "N/A"):
            result[label] = str(value)
    if recent_history:
        played = [m for m in recent_history if m.get("minutes", 0) and
                  type(m.get("total_points")) in (int, float)]
        if played:
            result["LAST 3 RETURNS"] = " / ".join(
                str(int(match["total_points"])) for match in played[-3:])
    return result


def choose_manager_action(player: dict[str, Any],
                          fixture_rows: tuple[dict[str, Any], ...],
                          last_three: list[dict[str, Any]] | None = None) -> tuple[str, str]:
    """Transparent action, based on known form/fixture and injury risk, not xPts."""
    status = player.get("status")
    if status != "a":
        return "MONITOR", "Official FPL flag: check team news before transfers"
    games = [r for r in fixture_rows if not r["blank"]]
    if not games:
        return "BENCH", "No next-GW fixture"
    minutes = [m.get("minutes", 0) for m in (last_three or [])[-3:]]
    if len(minutes) == 3 and sum(n >= 60 for n in minutes) <= 1:
        return "MONITOR", "Recent playing time is uncertain"
    try:
        form = float(player.get("form"))
    except (TypeError, ValueError):
        return "MONITOR", "Current form data missing"
    first_gw = games[0]["gw"]
    first = [r for r in games if r["gw"] == first_gw]
    difficulty = sum(r["fdr"] for r in first) / len(first)
    if form >= 5 and difficulty <= 3:
        return "HOLD", "Strong current form and favorable next fixture"
    if form < 2 and difficulty >= 4:
        return "SELL", "Poor form and difficult next fixture; assess alternatives"
    return "HOLD", "Keep if team structure, minutes and fixtures suit"


def semantic_fingerprint(content: Any) -> str:
    """Stable across the same facts on different dates/timestamps."""
    if not is_dataclass(content):
        raise TypeError("Content must be a dataclass")
    data = asdict(content)
    for ephemeral in ("data_at", "footer", "source", "kicker"):
        data.pop(ephemeral, None)
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def publication_group(content: Any) -> str:
    """A topic/gameweek identifier for dedup across daily repeat schedules."""
    data = asdict(content)
    cards = data.get("cards") or []
    relevant = (data.get("team_analysis") or {}).get("team")
    identities = [
        (str(card.get("team_code")) + ":" + str(card.get("photo_code")))
        for card in cards if card.get("photo_code")
    ]
    if not identities:
        identities = [f"{r.get('id')}:{r.get('advice')}"
                      for r in (data.get("start_bench") or [])]
    if relevant:
        identities.append(str(relevant))
    if not identities:
        identities = ["general"]
    return f"{data.get('kind')}:{data.get('gw')}:{'|'.join(identities)}"


def required_footer_handles() -> tuple[str, str]:
    """No hardcoded Telegram/Discord usernames. Fail before publishing."""
    result = []
    for variable in ("FPL_TELEGRAM_HANDLE", "FPL_DISCORD_HANDLE"):
        value = os.getenv(variable, "").strip()
        if not re.fullmatch(r"@[A-Za-z0-9_.-]{2,50}", value):
            raise RuntimeError(f"Missing verified public footer handle: {variable}")
        result.append(value)
    return tuple(result)  # type: ignore[return-value]


def should_publish(previous: dict[str, Any] | None, fingerprint: str,
                   platforms: tuple[str, ...]) -> bool:
    if previous and previous.get("version") == fingerprint and previous.get("confirmed"):
        return False
    return True
