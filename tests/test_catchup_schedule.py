"""05:30–22:00 ET time-based catch-up: a late, cancelled or dropped run loses nothing."""
from datetime import datetime, timezone
import pytest

from vortex import autonomous_runner as runner
from vortex.autonomous_schedule import (SLOTS, CATCHUP_CRONS, Slot, catchup_slots,
                                        publication_key, slot_start, MAX_ATTEMPTS)
from test_autonomous_engine import world  # noqa: F401  (shared synthetic FPL snapshot)

DAY_NOON = datetime(2026, 11, 9, 17, 10, tzinfo=timezone.utc)   # 12:10 EST
DAY_LATE = datetime(2026, 11, 10, 2, 10, tzinfo=timezone.utc)   # 21:10 EST


def test_every_slot_is_inside_the_window_and_unique():
    times = [(s.hour, s.minute) for s in SLOTS]
    assert times == sorted(times)
    assert times[0] == (5, 30) and times[-1] < (22, 0)
    keys = {publication_key(s, DAY_NOON, 10, '2026-27') for s in SLOTS}
    assert len(keys) == len(SLOTS)  # two press slots still get separate records


def test_catchup_crons_cover_the_window_without_leaving_it():
    assert '40 5 * * *' in CATCHUP_CRONS and '10 5 * * *' not in CATCHUP_CRONS
    assert '40 21 * * *' in CATCHUP_CRONS and '10 22 * * *' not in CATCHUP_CRONS


def test_nothing_due_before_first_slot_and_oldest_first_after():
    early = datetime(2026, 11, 9, 10, 29, tzinfo=timezone.utc)  # 05:29 EST
    assert catchup_slots(early, {}, 10, '2026-27') == []
    due = catchup_slots(DAY_NOON, {}, 10, '2026-27', limit=99)
    assert [s.hour for s in due] == [5, 6, 7, 8, 9, 10, 11, 12][:len(due)]
    assert due[0].edition == 'availability-transfer-decisions'


def test_closed_and_exhausted_slots_are_skipped_but_held_ones_retry():
    first, second, third = sorted(SLOTS, key=lambda s: (s.hour, s.minute))[:3]
    state = {
        publication_key(first, DAY_NOON, 10, '2026-27'): {'status': 'delivered'},
        publication_key(second, DAY_NOON, 10, '2026-27'): {'status': 'held', 'attempts': MAX_ATTEMPTS},
        publication_key(third, DAY_NOON, 10, '2026-27'): {'status': 'held', 'attempts': 1},
    }
    due = catchup_slots(DAY_NOON, state, 10, '2026-27', limit=99)
    assert first not in due and second not in due and third in due


def test_a_dropped_day_is_recovered_by_a_late_run_in_oldest_first_batches():
    due = catchup_slots(DAY_LATE, {}, 10, '2026-27')
    assert len(due) == 3 and due[0] == SLOTS[0]
    assert slot_start(SLOTS[-1], DAY_LATE).hour == 21


def _drive(monkeypatch, world, state, cron_now):
    s, now, e, feed = world
    writes = {}
    receipts = {'test-identity:page1': {'delivered': True, 'discord_delivered': True}}
    prices = {'as_of_utc': 'x', 'prices': {'1': 50}}

    def read(path):
        if path == runner.STATE_FILE:
            return state
        if path == runner.RECEIPTS:
            return receipts
        return prices if path.name == 'prices.json' else {}

    monkeypatch.setattr(runner, 'allowed', lambda when: True)
    monkeypatch.setattr(runner, 'Evidence', lambda snapshot, when: e)
    monkeypatch.setattr(runner, 'read_state', read)
    monkeypatch.setattr(runner, 'write_state', lambda path, data: writes.__setitem__(path.name, dict(data)))
    monkeypatch.setattr(runner, 'stage', lambda *a, **k: (runner.ROOT / 'outbox/t.json', 'test-identity', 1))
    monkeypatch.setattr(runner, 'publish_outbox', lambda when: 0)
    return runner.run(cron='10 12 * * *', now=cron_now, snapshot=s), writes


def test_runner_posts_the_oldest_due_edition_and_keeps_price_baseline(monkeypatch, world):
    state = {}
    result, writes = _drive(monkeypatch, world, state, DAY_NOON)
    assert result['confirmed_edition_deliveries'] == 1
    assert result['editions'][0]['edition'] == 'availability-transfer-decisions'
    assert 'prices.json' not in writes  # non-price runs no longer overwrite the baseline
    assert any(v.get('status') == 'delivered' for v in writes['autonomous_editions.json'].values())


def test_first_catchup_run_at_0540_posts_the_0530_slot(monkeypatch, world):
    first_run = datetime(2026, 11, 9, 10, 40, tzinfo=timezone.utc)  # 05:40 EST
    result, _ = _drive(monkeypatch, world, {}, first_run)
    assert result['editions'][0]['edition'] == 'availability-transfer-decisions'


def test_runs_outside_0530_2200_are_deferred_with_the_real_window():
    for when in (datetime(2026, 11, 9, 10, 29, tzinfo=timezone.utc),   # 05:29 EST
                 datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)):   # 22:00 EST
        assert runner.run(cron='10 12 * * *', now=when)['status'] == 'deferred-outside-window'
