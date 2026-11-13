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

def test_dispatch_orders_all_due_lanes_and_continues_after_failure(monkeypatch, tmp_path):
    from datetime import timedelta
    from types import SimpleNamespace
    from vortex.autonomous_schedule import Slot

    state = {}
    calls = []
    legacy_slot = OPEN - timedelta(hours=2)
    outbox_slot = OPEN - timedelta(hours=1)
    paths = {'REPORT': 'report', 'AUDIT': 'audit', 'LEGACY': 'checks',
             'LEGACY_RECEIPTS': 'legacy', 'STATE_FILE': 'editorial',
             'NEWS_PENDING': 'news-pending', 'NEWS_RECEIPTS': 'news',
             'OUTBOX_STATUS': 'outbox-status', 'RECEIPTS': 'receipts'}
    for name, filename in paths.items():
        monkeypatch.setattr(dispatcher, name, tmp_path / filename)
    monkeypatch.setattr(dispatcher, 'read_state', lambda path: state.get(path.name, {}).copy())
    monkeypatch.setattr(dispatcher, 'write_state', lambda path, data: state.update({path.name: data.copy()}))
    monkeypatch.setattr(dispatcher, 'collect_snapshot',
                        lambda: SimpleNamespace(gameweek=lambda: 11, events=[]))
    monkeypatch.setattr(dispatcher, 'Evidence', lambda *args: object())
    monkeypatch.setattr(dispatcher, 'catchup_slots', lambda *a, **k: [Slot('task1', 'edition', 12, 30)])
    monkeypatch.setattr(dispatcher, 'special_triggers',
                        lambda *a: [(Slot('task1', 'special', 0), OPEN + timedelta(hours=1))])
    monkeypatch.setattr(dispatcher, 'legacy_jobs',
                        lambda *a: [(legacy_slot, 'legacy-id', 'legacy', 'test')])
    monkeypatch.setattr(dispatcher, 'queued_files',
                        lambda *a: [(outbox_slot, tmp_path / 'later.json')])

    def legacy(*args, **kwargs):
        calls.append('legacy')
        kwargs['audit']['error'] = 'Required data missing'
        return 1

    def outbox(*args, **kwargs):
        calls.append('outbox')
        state['receipts'] = {'new': {'delivered': True, 'telegram_message_id': 123}}
        return 0

    def edition(**kwargs):
        calls.append('editorial')
        assert kwargs['selected_slots'][0].edition == 'edition'
        return {'editions': [{'status': 'generated', 'generated': True}]}

    monkeypatch.setattr(dispatcher, 'run_legacy', legacy)
    monkeypatch.setattr(dispatcher, 'run_outbox', outbox)
    monkeypatch.setattr(dispatcher, 'run_editions', edition)
    report = dispatcher.run(now=OPEN, cron='13 6-22 * * *')
    assert calls == ['legacy', 'outbox', 'editorial']
    assert report['new_posts'] == report['posts_generated'] == report['posts_retry_pending'] == 1
    assert report['posts_due'] == 3
    assert report['pending_triggers'][0]['post'] == 'special'
    assert state['audit']['later.json']['telegram_message_ids'] == [123]
    assert state['audit']['legacy-id']['error'] == 'Required data missing'
