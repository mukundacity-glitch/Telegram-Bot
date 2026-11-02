"""Permitted public FPL Core Insights dataset adapter (no browser scraping).

Source: github.com/olbauday/FPL-Core-Insights, data/2026-2027/
Use only a genuinely *finished* Premier League GW, join via official FPL ID
and team code, never substitute its stale player prices/status for official FPL.
The public project permits reuse and requests attribution; record it internally.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
import logging
import re
from typing import Any
from urllib.parse import quote

import requests

LOGGER = logging.getLogger(__name__)
REPO = "olbauday/FPL-Core-Insights"
SEASON = "2026-2027"
ROOT = f"https://raw.githubusercontent.com/{REPO}/main/data/{SEASON}"
COMMIT_API = f"https://api.github.com/repos/{REPO}/commits"
VALID_FIELDS = {"tackles", "clearances_blocks_interceptions", "recoveries",
                "defensive_contribution", "minutes", "goals_scored", "assists",
                "expected_goals", "expected_assists"}


def _csv_from_source(client: requests.Session, path: str,
                     *, max_bytes: int = 1_200_000) -> list[dict[str, str]]:
    if not re.fullmatch(r"[A-Za-z0-9 _/.-]+\.csv", path):
        raise ValueError("Invalid data path")
    url = f"{ROOT}/{quote(path, safe='/')}"
    resp = client.get(url, headers={"Accept": "text/csv"}, timeout=14, allow_redirects=False)
    resp.raise_for_status()
    if len(resp.content) > max_bytes:
        raise ValueError("FPL Core CSV is unexpectedly large")
    return list(csv.DictReader(StringIO(resp.content.decode("utf-8-sig"))))


def latest_completed_event(snapshot: Any) -> int | None:
    eligible = []
    for e in snapshot.events:
        gw = e.get("id")
        if not type(gw) is int or not e.get("finished"):
            continue
        fixtures = [f for f in snapshot.fixtures if f.get("event") == gw]
        if fixtures and all(f.get("finished") is True for f in fixtures):
            eligible.append(gw)
    return max(eligible) if eligible else None


def completed_gw_enrichment(snapshot: Any, session: requests.Session | None = None,
                            now: datetime | None = None) -> dict[int, dict[str, Any]]:
    """Enrich last completed GW; never use unfinished/postponed partial rows.

    Historical source files may not include a timestamp. Check GitHub's latest
    path commit and require that it falls after the gameweek deadline and no
    later than the current execution time. Missing proof -> skip enrichment.
    """
    last_gw = latest_completed_event(snapshot)
    if last_gw is None:
        return {}
    now = now or datetime.now(timezone.utc)
    client = session or requests.Session()
    rel = f"By Gameweek/GW{last_gw}/player_gameweek_stats.csv"
    try:
        commits = client.get(COMMIT_API,
                             params={"path": f"data/{SEASON}/{rel}", "per_page": 1},
                             timeout=12, allow_redirects=False)
        commits.raise_for_status()
        history = commits.json()
        stamp = history[0]["commit"]["committer"]["date"]
        published = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        deadline = next(
            (datetime.fromisoformat(str(e["deadline_time"]).replace("Z", "+00:00"))
             for e in snapshot.events if e.get("id") == last_gw), None)
        if (deadline is None or published.tzinfo is None or not
                deadline <= published <= now or now-published > timedelta(days=21)):
            LOGGER.info("Skipping outdated or unverified FPL Core GW%d snapshot", last_gw)
            return {}
        identities = _csv_from_source(client, "players.csv", max_bytes=150_000)
        records = _csv_from_source(client, rel)
    except (requests.RequestException, KeyError, IndexError, TypeError,
            ValueError, UnicodeDecodeError, csv.Error) as exc:
        LOGGER.warning("FPL Core optional historical feed unavailable: %s", type(exc).__name__)
        return {}

    player_code_map = {}
    for item in identities:
        try:
            pid = int(item["player_id"])
            player_code_map[pid] = (int(item["player_code"]), int(item["team_code"]))
        except (KeyError, TypeError, ValueError):
            continue

    official = {p.get("id"): p for p in snapshot.players if type(p.get("id")) is int}
    selected: dict[int, dict[str, Any]] = {}
    for record in records:
        try:
            pid, csv_gw = int(record["id"]), int(record["gw"])
        except (KeyError, ValueError, TypeError):
            continue
        player = official.get(pid)
        if player is None or csv_gw != last_gw:
            continue
        codes = player_code_map.get(pid)
        if codes != (snapshot.photo_code(player), snapshot.team_code(player)):
            continue  # transfers / recycled IDs / stale identities
        enriched: dict[str, Any] = {"last_completed_gw": last_gw,
                                    "source_commit_time": published.isoformat()}
        for field in VALID_FIELDS:
            value = record.get(field)
            if value is None or not value.strip():
                continue
            try:
                n = float(value)
            except ValueError:
                continue
            if 0 <= n <= 10_000 and n == n:
                enriched[f"gw_{field}"] = n
        if len(enriched) > 2:
            selected[pid] = enriched
    LOGGER.info("Verified FPL Core GW%d supplemental rows: %d", last_gw, len(selected))
    return selected
