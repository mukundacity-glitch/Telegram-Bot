"""Official FPL ingestion, deterministic insights and fail-closed verification."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

FPL_BASE = "https://fantasy.premierleague.com/api"


@dataclass(frozen=True)
class FplSnapshot:
    players: list[dict[str, Any]]
    teams: dict[int, dict[str, Any]]
    events: list[dict[str, Any]]
    fixtures: list[dict[str, Any]]
    fetched_at: datetime
    live: dict[str, Any] | None = None

    def gameweek(self) -> int:
        upcoming = next((event for event in self.events if event.get("is_next")), None)
        current = next((event for event in self.events if event.get("is_current")), None)
        selected = upcoming or current or next((event for event in self.events if not event.get("finished")), None)
        if selected is None:
            return int(self.events[-1]["id"]) if self.events else 0
        return int(selected["id"])

    def name(self, player: dict[str, Any]) -> str:
        return str(player.get("web_name") or player.get("second_name") or "Unknown")

    def team(self, player: dict[str, Any]) -> str:
        record = self.teams.get(int(player.get("team") or 0), {})
        return str(record.get("short_name") or record.get("name") or "PL")

    def team_code(self, player: dict[str, Any]) -> int | None:
        team = self.teams.get(int(player.get("team") or 0), {})
        code = team.get("code")
        return int(code) if isinstance(code, int) else None

    def photo_code(self, player: dict[str, Any]) -> int | None:
        code = player.get("code")
        return int(code) if isinstance(code, int) and code > 0 else None

    def price(self, player: dict[str, Any]) -> str:
        return f"£{int(player.get('now_cost') or 0) / 10:.1f}m"

    def fixtures_for(self, player: dict[str, Any], limit: int = 5) -> list[tuple[str, int]]:
        club = int(player.get("team") or 0)
        future = [f for f in self.fixtures if not f.get("finished") and (f.get("team_h") == club or f.get("team_a") == club)]
        future.sort(key=lambda f: (f.get("kickoff_time") or "9999", int(f.get("id") or 0)))
        results: list[tuple[str, int]] = []
        for fixture in future[:limit]:
            home = fixture.get("team_h") == club
            other = fixture.get("team_a") if home else fixture.get("team_h")
            opp = self.teams.get(int(other or 0), {}).get("short_name", "TBD")
            fdr = fixture.get("team_h_difficulty") if home else fixture.get("team_a_difficulty")
            results.append((f"{opp} ({'H' if home else 'A'})", int(fdr or 0)))
        return results


def _fetch_json(session: requests.Session, suffix: str, timeout: int = 22) -> Any:
    response = session.get(f"{FPL_BASE}/{suffix}", timeout=timeout, headers={"Accept": "application/json", "User-Agent": "FPL-VORTEX-Telegram/1.0"})
    response.raise_for_status()
    return response.json()


def collect_snapshot(session: requests.Session | None = None) -> FplSnapshot:
    client = session or requests.Session()
    bootstrap = _fetch_json(client, "bootstrap-static/")
    fixtures = _fetch_json(client, "fixtures/")
    if not isinstance(bootstrap, dict) or not isinstance(fixtures, list):
        raise ValueError("FPL returned unexpected bootstrap/fixture structure")
    for key in ("elements", "teams", "events"):
        if not isinstance(bootstrap.get(key), list) or not bootstrap[key]:
            raise ValueError(f"FPL data missing required field: {key}")
    players = [p for p in bootstrap["elements"] if isinstance(p, dict) and isinstance(p.get("id"), int)]
    if len(players) < 100:
        raise ValueError("FPL returned too few registered players")
    teams = {int(t["id"]): t for t in bootstrap["teams"] if isinstance(t, dict) and isinstance(t.get("id"), int)}
    if len(teams) != 20:
        raise ValueError("Expected 20 current Premier League clubs")
    events = bootstrap["events"]
    if not events:
        raise ValueError("FPL gameweek list is empty")
    return FplSnapshot(players, teams, events, fixtures, datetime.now(timezone.utc))


def current_players(snapshot: FplSnapshot, min_minutes: int = 1) -> list[dict[str, Any]]:
    return [player for player in snapshot.players if int(player.get("minutes") or 0) >= min_minutes and player.get("status") == "a"]


def score(player: dict[str, Any]) -> float:
    return (float(player.get("form") or 0) * 1.7 + float(player.get("points_per_game") or 0) + float(player.get("ep_next") or 0) * 0.3 + min(5, int(player.get("minutes") or 0) / 300))


def choose_comparison(snapshot: FplSnapshot) -> list[dict[str, Any]]:
    ranked = sorted(current_players(snapshot, 180), key=score, reverse=True)
    if len(ranked) < 2:
        raise ValueError("Not enough eligible active players")
    # The highest-ranked player may be unusually expensive; find the strongest viable pair.
    for index, lead in enumerate(ranked):
        alternatives = [
            player for player in ranked[index + 1:]
            if player.get("element_type") == lead.get("element_type")
            and player.get("team") != lead.get("team")
            and abs(int(player.get("now_cost") or 0) - int(lead.get("now_cost") or 0)) <= 30
        ]
        if alternatives:
            return [lead, alternatives[0]]
    raise ValueError("No two active same-position players from different clubs within £3.0m")


def choose_elite(snapshot: FplSnapshot) -> dict[str, Any]:
    choices = [p for p in current_players(snapshot, 180) if float(p.get("selected_by_percent") or 100) <= 15]
    if not choices:
        raise ValueError("No under-owned players qualify")
    return max(choices, key=score)


def choose_creators(snapshot: FplSnapshot) -> list[dict[str, Any]]:
    choices = [p for p in current_players(snapshot, 90) if int(p.get("element_type") or 0) in (3, 4)]
    choices.sort(key=lambda p: (int(p.get("assists") or 0), float(p.get("expected_assists") or 0)), reverse=True)
    return choices[:4]


def choose_captains(snapshot: FplSnapshot) -> list[dict[str, Any]]:
    ranked = current_players(snapshot, 180)
    ranked.sort(key=lambda player: score(player) - 1.1 * (min(5, (snapshot.fixtures_for(player, 1) or [("", 3)])[0][1]) - 3), reverse=True)
    if len(ranked) < 4:
        raise ValueError("Not enough eligible captaincy candidates")
    return ranked[:4]


def choose_news(snapshot: FplSnapshot, current: datetime) -> list[dict[str, Any]]:
    threshold = current - timedelta(hours=72)
    dated: list[tuple[datetime, dict[str, Any]]] = []
    for player in snapshot.players:
        news = str(player.get("news") or "").strip()
        timestamp = player.get("news_added")
        if not news or not isinstance(timestamp, str):
            continue
        try:
            added = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if added.tzinfo is None:
            added = added.replace(tzinfo=timezone.utc)
        if threshold <= added <= current:
            dated.append((added, player))
    dated.sort(key=lambda item: item[0], reverse=True)
    return [player for _, player in dated[:4]]


def confirmed_price_changes(snapshot: FplSnapshot, previous_prices: dict[str, Any]) -> list[tuple[dict[str, Any], int, int]]:
    old_prices = previous_prices.get("prices")
    if not isinstance(old_prices, dict):
        return []
    changes: list[tuple[dict[str, Any], int, int]] = []
    for player in snapshot.players:
        key = str(player["id"])
        old = old_prices.get(key)
        current = player.get("now_cost")
        if isinstance(old, int) and isinstance(current, int) and old != current:
            changes.append((player, old, current))
    changes.sort(key=lambda item: abs(item[2] - item[1]), reverse=True)
    return changes[:8]


def price_snapshot(snapshot: FplSnapshot) -> dict[str, Any]:
    return {"as_of_utc": snapshot.fetched_at.isoformat(), "prices": {str(p["id"]): p["now_cost"] for p in snapshot.players if isinstance(p.get("now_cost"), int)}}


def latest_completed_gw(snapshot: FplSnapshot) -> int | None:
    done = [int(e["id"]) for e in snapshot.events if e.get("finished") and isinstance(e.get("id"), int)]
    return max(done) if done else None


def previous_gw_top_players(snapshot: FplSnapshot, session: requests.Session | None = None) -> list[tuple[dict[str, Any], int]]:
    latest = latest_completed_gw(snapshot)
    if latest is None:
        return []
    client = session or requests.Session()
    payload = _fetch_json(client, f"event/{latest}/live/")
    raw_elements = payload.get("elements") if isinstance(payload, dict) else None
    if isinstance(raw_elements, list):
        elements = {str(item["id"]): item for item in raw_elements
                    if isinstance(item, dict) and isinstance(item.get("id"), int)}
    elif isinstance(raw_elements, dict):
        elements = raw_elements
    else:
        raise ValueError("Live GW response missing element records")
    records: list[tuple[dict[str, Any], int]] = []
    for player in snapshot.players:
        row = elements.get(str(player["id"]), {})
        stats = row.get("stats", {}) if isinstance(row, dict) else {}
        points = stats.get("total_points") if isinstance(stats, dict) else None
        if isinstance(points, int):
            records.append((player, points))
    records.sort(key=lambda item: item[1], reverse=True)
    return records[:5]