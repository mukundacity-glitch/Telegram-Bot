"""Regression tests for the compact, fully automated GitHub publishing heartbeat."""
from datetime import datetime, timezone
from pathlib import Path
import json
import pytest
from vortex import scheduled_dispatch as dispatcher

OPEN = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)   # 13:00 EST
CLOSED = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc) # 03:00 EST

def test_heartbeat_is_scheduled_in_america_new_york_not_a_fixed_utc_offset():
    workflow = (Path(__file__).resolve().parents[1] /
                '.github/workflows/telegram-daily.yml').read_text()
    assert workflow.count('- cron:') == 2
    # An IANA zone lets the tz database apply EST/EDT; a hand-converted UTC
    # pair drifts an hour at every DST change.
    assert workflow.count('timezone: "America/New_York"') == 2
    assert "cron: '43 5-22 * * *'" in workflow
    assert "cron: '13 6-22 * * *'" in workflow
    assert 'python -m vortex.scheduled_dispatch' in workflow
    assert 'python -m vortex.autonomous_runner --manual --edition "$MANUAL_EDITION"' in workflow


def _eastern_ticks(local_day):
    """Eastern-time heartbeats that GitHub would fire on ``local_day``.

    The schedule carries its own timezone, so the cron fields are already
    local wall-clock hours; DST needs no conversion here.
    """
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("America/New_York")
    ticks = []
    for hour in range(5, 23):
        ticks.append(datetime(local_day.year, local_day.month, local_day.day,
                              hour, 43, tzinfo=eastern))
    for hour in range(6, 23):
        ticks.append(datetime(local_day.year, local_day.month, local_day.day,
                              hour, 13, tzinfo=eastern))
    return sorted(ticks)


def test_heartbeat_covers_every_eastern_editorial_day_including_dst_days():
    """Both DST regimes must reach 05:30-23:00 with no long blackout."""
    from datetime import date, timedelta
    from zoneinfo import ZoneInfo

    eastern = ZoneInfo("America/New_York")
    # 2026-03-08 spring forward, 2026-11-01 fall back, plus plain summer/winter days.
    for local_day in (date(2026, 3, 8), date(2026, 11, 1),
                      date(2026, 7, 15), date(2026, 11, 11)):
        ticks = [t for t in _eastern_ticks(local_day)
                 if (5, 30) <= (t.hour, t.minute) < (23, 0)]
        assert (ticks[0].hour, ticks[0].minute) == (5, 43)
        assert (ticks[-1].hour, ticks[-1].minute) == (22, 43)
        # :43 covers 5-22, :13 covers 6-22 -> 18 + 17 = 35 ticks inside the
        # window, and every gap is 30 minutes so no slot can be missed.
        assert len(ticks) == 35
        assert all((right - left) == timedelta(minutes=30)
                   for left, right in zip(ticks, ticks[1:]))
        # Each tick is inside the publishing window the dispatcher enforces.
        assert all(dispatcher.allowed(tick) for tick in ticks)
        # The dispatcher must actually accept the first and last tick.
        assert dispatcher.allowed(ticks[0])
        assert dispatcher.allowed(ticks[-1])


def test_posting_window_is_0530_to_2300_new_york_across_dst():
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("America/New_York")

    def at(month, day, hour, minute):
        return datetime(2026, month, day, hour, minute, tzinfo=eastern)

    for when in (at(11, 12, 5, 29), at(11, 12, 23, 0), at(7, 15, 4, 59)):
        assert not dispatcher.allowed(when)
    for when in (at(11, 12, 5, 30), at(11, 12, 22, 59), at(7, 15, 5, 30),
                 at(3, 8, 6, 0), at(11, 1, 22, 59)):
        assert dispatcher.allowed(when)
    # 21:30 EDT and 21:30 EST are different UTC instants but both must publish.
    assert dispatcher.allowed(datetime(2026, 7, 15, 1, 30, tzinfo=timezone.utc))
    assert dispatcher.allowed(datetime(2026, 11, 12, 2, 30, tzinfo=timezone.utc))

def test_off_hours_does_not_attempt_any_delivery(monkeypatch):
    monkeypatch.setattr(dispatcher, 'collect_snapshot',
                        lambda: (_ for _ in ()).throw(AssertionError('offline')))
    assert dispatcher.run(now=CLOSED)['status'] == 'deferred-outside-window'

def test_due_legacy_deduplicates_existing_two_platform_receipts():
    ledger = {'2026-11-10:elite:GW11':
              {'delivered': True, 'discord_delivered': True}}
    due = dispatcher.due_legacy(OPEN, ledger, {})
    assert due is not None and due[1] != 'elite'

def test_schedule_dispatch_reports_telegram_and_discord_delivery(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatcher, 'STATE', tmp_path)
    monkeypatch.setattr(dispatcher, 'REPORT', tmp_path / 'status.json')
    monkeypatch.setattr(dispatcher, 'collect_snapshot', lambda: object())
    monkeypatch.setattr(dispatcher, 'due_specials', lambda *a,**k: [])
    monkeypatch.setattr(dispatcher, 'run_editions', lambda **kw: {
        'editions': [{'edition':'form-minutes-targets','status':'delivered'}],
        'confirmed_edition_deliveries': 1})
    monkeypatch.setattr(dispatcher, 'run_news', lambda **kw: {'sent':0})
    monkeypatch.setattr(dispatcher, 'original_legacy_once',
                        lambda now: {'status':'none-due','sent':0})
    monkeypatch.setattr(dispatcher, 'run_outbox', lambda now: 0)
    monkeypatch.setattr(dispatcher, 'read_state', lambda path: {})
    monkeypatch.setattr(dispatcher, 'write_state',lambda path,data: path.write_text(json.dumps(data)))
    report = dispatcher.run(now=OPEN, cron='43 5-21 * * *')
    assert report['new_posts'] == 1
    assert report['status'] == 'published'
    assert json.loads((tmp_path / 'status.json').read_text())['new_posts'] == 1

def test_schedule_reports_hold_not_successful_post(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatcher, 'STATE', tmp_path)
    monkeypatch.setattr(dispatcher, 'REPORT', tmp_path / 'status.json')
    monkeypatch.setattr(dispatcher, 'collect_snapshot', lambda: object())
    monkeypatch.setattr(dispatcher, 'due_specials', lambda *a,**k: [])
    monkeypatch.setattr(dispatcher, 'run_editions', lambda **kw: {
        'editions':[{'edition':'news','status':'held'}],
        'confirmed_edition_deliveries':0})
    monkeypatch.setattr(dispatcher, 'run_news', lambda **kw: {'sent':0})
    monkeypatch.setattr(dispatcher, 'original_legacy_once',
                        lambda now: {'status':'none-due','sent':0})
    monkeypatch.setattr(dispatcher, 'run_outbox', lambda now: 0)
    monkeypatch.setattr(dispatcher, 'read_state', lambda path: {})
    monkeypatch.setattr(dispatcher, 'write_state',lambda path,data: path.write_text(json.dumps(data)))
    report=dispatcher.run(now=OPEN)
    assert report['status']=='held' and report['new_posts']==0
