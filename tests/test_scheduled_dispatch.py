"""Regression tests for the compact, fully automated GitHub publishing heartbeat."""
from datetime import datetime, timezone
from pathlib import Path
import json
import pytest
from vortex import scheduled_dispatch as dispatcher
from vortex.autonomous_schedule import CLOCK_CRON

OPEN = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)   # 13:00 EST
CLOSED = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc) # 03:00 EST

def test_heartbeat_covers_all_utc_hours_with_eastern_runtime_guard():
    workflow = (Path(__file__).resolve().parents[1] /
                '.github/workflows/telegram-daily.yml').read_text()
    assert workflow.count('- cron:') == 5
    assert f"cron: '{CLOCK_CRON}'" in workflow
    assert 'timezone:' not in workflow
    assert "cron: '43 * * * *'" in workflow
    assert "cron: '13 * * * *'" in workflow
    assert 'python -m vortex.scheduled_dispatch' in workflow
    assert 'python -m vortex.autonomous_runner --manual --edition "$MANUAL_EDITION"' in workflow


def _eastern_ticks(local_day):
    """Expand the actual UTC workflow clocks across the Eastern day."""
    import re
    from datetime import timedelta

    workflow = (Path(__file__).resolve().parents[1] /
                '.github/workflows/telegram-daily.yml').read_text()
    minutes = [int(value) for value in re.findall(r"- cron: '(\d+) \* \* \* \*'", workflow)]
    first = datetime.combine(local_day, datetime.min.time(), dispatcher.ET).astimezone(timezone.utc)
    ticks = ((first + timedelta(hours=hour, minutes=minute)).astimezone(dispatcher.ET)
             for hour in range(25) for minute in minutes)
    return sorted(tick for tick in ticks if tick.date() == local_day)


def test_heartbeat_covers_every_eastern_editorial_day_including_dst_days():
    """Both DST regimes must reach 05:30-23:00 with no long blackout."""
    from datetime import date, timedelta
    # 2026-03-08 spring forward, 2026-11-01 fall back, plus plain summer/winter days.
    for local_day in (date(2026, 3, 8), date(2026, 11, 1),
                      date(2026, 7, 15), date(2026, 11, 11)):
        ticks = [t for t in _eastern_ticks(local_day)
                 if (5, 30) <= (t.hour, t.minute) < (23, 0)]
        assert (ticks[0].hour, ticks[0].minute) == (5, 43)
        assert (ticks[-1].hour, ticks[-1].minute) == (22, 58)
        # The Eastern guard admits exactly 70 polls at quarter-hour intervals.
        assert len(ticks) == 70
        assert all((right - left) == timedelta(minutes=15)
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
    report = dispatcher.run(now=OPEN, cron='13 * * * *')
    assert calls == ['legacy', 'outbox', 'editorial']
    assert report['new_posts'] == report['posts_generated'] == report['posts_retry_pending'] == 1
    assert report['posts_due'] == 3
    assert report['pending_triggers'][0]['post'] == 'special'
    assert state['audit']['later.json']['telegram_message_ids'] == [123]
    assert state['audit']['legacy-id']['error'] == 'Required data missing'


def test_cooldown_persists_between_publishers_and_skips_data_fetch(monkeypatch, tmp_path):
    from datetime import timedelta
    from vortex import telegram_spacing, telegram

    monkeypatch.setenv("FPL_TELEGRAM_SPACING", "true")
    monkeypatch.setattr(telegram_spacing, "STATE", tmp_path)
    monkeypatch.setattr(telegram_spacing, "COOLDOWN", tmp_path / "spacing.json")
    monkeypatch.setattr(dispatcher, "REPORT", tmp_path / "report.json")
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(dispatcher, "allowed", lambda now: True)
    monkeypatch.setattr(dispatcher, "collect_snapshot", lambda: pytest.fail("Cooldown must skip network reads"))
    send_calls = []

    def send(method, data, files):
        send_calls.append(method)
        return {"ok": True, "result": {"message_id": 101}}

    first = telegram.TelegramClient("test", "test")
    monkeypatch.setattr(first, "_request", send)
    assert first.send_text("One") == 101
    second = telegram.TelegramClient("test", "test")
    monkeypatch.setattr(second, "_request", send)
    with pytest.raises(telegram_spacing.DeliveryDeferred):
        second.send_text("Two")
    assert send_calls == ["sendMessage"]
    report = dispatcher.run(now=now + timedelta(minutes=15))
    assert report["status"] == "deferred-telegram-spacing"
    assert report["posts_failed"] == report["posts_retry_pending"] == 0
    assert datetime.fromisoformat(report["next_telegram_at"]) >= now + timedelta(minutes=45)
    assert telegram_spacing.blocked_until(datetime.fromisoformat(report["next_telegram_at"])) is None


def test_exact_check_is_configured_for_all_fixed_slots_across_dst():
    from datetime import date
    from vortex.autonomous_schedule import SLOTS
    from vortex.schedule import SLOT_HOURS

    hours = {0, 1, 2, 3, *range(9, 24)}
    configured = set(SLOT_HOURS.values()) | {(s.hour, s.minute) for s in SLOTS}
    for day in (date(2026, 11, 17), date(2027, 7, 20)):
        for hour, minute in configured:
            trigger = datetime(day.year, day.month, day.day, hour, minute,
                               tzinfo=dispatcher.ET).astimezone(timezone.utc)
            assert trigger.hour in hours and trigger.minute in (0, 30)


def test_followup_wait_obeys_cooldown_and_publishing_window():
    now = datetime(2026, 11, 17, 2, 30, tzinfo=timezone.utc)
    latest = {'at': now.isoformat(),
              'next_due': {'trigger': datetime(2026, 11, 17, 2, 40, tzinfo=timezone.utc).isoformat()}}
    cooldown = datetime(2026, 11, 17, 3, 15, tzinfo=timezone.utc)
    assert dispatcher.followup_wait(latest, now, now, cooldown) == 2701
    assert dispatcher.followup_wait(latest, now, cooldown) == 0
    closed = datetime(2026, 11, 17, 4, 0, tzinfo=timezone.utc)
    assert dispatcher.followup_wait(latest, now, now, closed) == 0
    assert dispatcher.followup_wait({}, datetime(2026, 11, 17, 10, tzinfo=timezone.utc), now) == 1801


def test_fixed_times_leave_telegram_spacing_on_each_weekday():
    from vortex.autonomous_schedule import SLOTS, eligible_on, slot_start
    from vortex.schedule import SLOT_HOURS
    from vortex.telegram_spacing import GAP

    for day in range(16, 23):
        now = datetime(2026, 11, day, 12, tzinfo=dispatcher.ET)
        editorial = [slot_start(slot, now) for slot in SLOTS if eligible_on(slot, now)]
        legacy = [now.replace(hour=hour, minute=minute) for hour, minute in SLOT_HOURS.values()]
        slots = sorted(editorial + legacy)
        assert all(right - left >= GAP for left, right in zip(slots, slots[1:]))
