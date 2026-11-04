"""Optional strict independent model/EO feed. Fetching never refreshes its age.

This is an explicit data contract, not an approximation of the user's math.
Stale imported CSV benchmarks are deliberately ineligible.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
import os
import requests


class NoUpdate(RuntimeError):
    pass


class RequiredInput(RuntimeError):
    pass


def verified_feed(snapshot, now, session=None, payload=None):
    if payload is None:
        url = os.getenv('FPL_EDITORIAL_MODEL_URL', '').strip()
        if not url:
            # Calculate the original Day 3 math against freshly verified FPL
            # and FPL Core evidence; never pretend this also supplies EO/xPts.
            from .editorial_live_model import build_live_team_feed
            payload = build_live_team_feed(snapshot, now, session=session)
        else:
            parts = urlsplit(url)
            if parts.scheme != 'https' or parts.username or parts.hostname not in {
                'fplvortex.onrender.com', 'raw.githubusercontent.com'}:
                raise RequiredInput('Editorial model source must be the reviewed VORTEX/GitHub HTTPS feed')
            try:
                response = (session or requests.Session()).get(url, timeout=20)
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError):
                raise RequiredInput('Verified editorial model feed is unreachable') from None
    try:
        stamp = datetime.fromisoformat(payload['generated_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None or not timedelta(0) <= max(now, snapshot.fetched_at, datetime.now(timezone.utc))-stamp <= timedelta(hours=3):
            raise ValueError('stale')
        if payload['gw'] != snapshot.gameweek() or not payload.get('model_version') or not payload.get('methodology_url'):
            raise ValueError('unverified model/GW')
        if payload.get('sourceFile') or payload.get('imported'):
            raise ValueError('unverified imported benchmark age')
    except (KeyError, TypeError, ValueError):
        raise RequiredInput('Editorial model feed is stale or lacks verified provenance/GW') from None
    return payload


def eo_for(feed, player_id):
    meta = feed.get('eo_meta') or {}
    row = (feed.get('players') or {}).get(str(player_id), {})
    value = row.get('eo')
    if meta.get('gw')!=feed.get('gw') or not meta.get('population') or not meta.get('methodology') or type(value) not in (float, int) or not 0 <= value <= 300:
        raise RequiredInput('GW-specific captaincy-weighted EO and population not verified; selected-by ownership is not EO')
    return float(value)
