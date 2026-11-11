"""Regression tests for the compact, fully automated GitHub publishing heartbeat."""
from datetime import datetime, timezone
from pathlib import Path
import json
import pytest
from vortex import scheduled_dispatch as dispatcher

OPEN = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)   # 13:00 EST
CLOSED = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc) # 03:00 EST

def test_compact_cron_and_every_late_slot_still_due():
    workflow = (Path(__file__).resolve().parents[1] /
                '.github/workflows/telegram-daily.yml').read_text()
    assert workflow.count('- cron:') == 2
    assert "cron: '43 9-23,0-2 * * *'" in workflow
    assert "cron: '13 10-23,0-2 * * *'" in workflow
    assert "timezone: America/New_York" not in workflow
    assert 'python -m vortex.scheduled_dispatch' in workflow
    assert 'python -m vortex.autonomous_runner --manual --edition "$MANUAL_EDITION"' in workflow

def test_utc_heartbeat_reaches_early_and_late_editions_in_est_and_edt():
    """UTC checks must cover the entire Eastern editorial day after DST switches."""
    from datetime import date, timedelta
    from zoneinfo import ZoneInfo

    eastern = ZoneInfo("America/New_York")
    for local_day in (date(2026, 7, 15), date(2026, 11, 11)):
        ticks = []
        for offset in (-1, 0, 1):
            utc_day = local_day + timedelta(days=offset)
            for hour in (*range(9, 24), *range(3)):
                for minute in (13, 43):
                    if hour == 9 and minute == 13:
                        continue
                    when = datetime(utc_day.year, utc_day.month, utc_day.day,
                                    hour, minute, tzinfo=timezone.utc).astimezone(eastern)
                    if when.date() == local_day and (5, 30) <= (when.hour, when.minute) < (22, 0):
                        ticks.append(when)
        ticks.sort()
        assert (ticks[0].hour, ticks[0].minute) == (5, 43)
        assert (ticks[-1].hour, ticks[-1].minute) == (21, 43)
        assert all((right - left) <= timedelta(minutes=30)
                   for left, right in zip(ticks, ticks[1:]))

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
