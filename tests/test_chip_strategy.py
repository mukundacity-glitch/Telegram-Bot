from datetime import datetime, timezone

from vortex.autonomous_schedule import CHIP_STRATEGY, ET, catchup_slots, publication_key
from vortex.chip_strategy import CHIPS, chip_usage, chip_windows, recommendations
from vortex.fpl import FplSnapshot


def windows():
    return chip_windows([
        {'name': chip, 'start_event': start, 'stop_event': end}
        for chip in CHIPS for start, end in ((2 if chip in ('freehit', 'wildcard') else 1, 19), (20, 38))
    ])


def test_tuesday_slot_recurs_and_closes_after_delivery():
    for year, month, day in ((2026, 11, 17), (2026, 11, 24), (2027, 6, 1)):
        due = datetime(year, month, day, 16, 30, tzinfo=ET)
        assert CHIP_STRATEGY in catchup_slots(due, {}, 12, limit=40)
        assert CHIP_STRATEGY not in catchup_slots(due.replace(minute=29), {}, 12, limit=40)
        key = publication_key(CHIP_STRATEGY, due, 12)
        assert CHIP_STRATEGY not in catchup_slots(due, {key: {'status': 'delivered'}}, 12, limit=40)
    assert CHIP_STRATEGY not in catchup_slots(datetime(2026, 11, 22, 17, tzinfo=ET), {}, 12, limit=40)


def test_usage_uses_current_set_and_registered_entries():
    now = datetime(2027, 1, 6, tzinfo=timezone.utc)
    plays = [{'id': gw, 'finished': True, 'data_checked': True,
              'chip_plays': [{'chip_name': 'freehit', 'num_played': count}]}
             for gw, count in ((19, 4), (20, 2), (21, 1))]
    snapshot = FplSnapshot([], {}, plays, [], now, total_entries=10)
    assert chip_usage(snapshot, 'freehit', (20, 38), 22) == (30., 21)
    plays[-1]['chip_plays'] = []
    assert chip_usage(snapshot, 'freehit', (20, 38), 22) == (None, 21)


def test_end_of_chip_set_and_one_chip_per_week():
    now = datetime(2026, 12, 28, tzinfo=timezone.utc)
    snapshot = FplSnapshot([], {}, [], [], now, total_entries=100)
    rows = {chip: [{'gw': gw, 'xpts': uplift} for gw, uplift in [(18, 1), (19, 2), (20, 100)]]
            for chip in CHIPS}
    cards = recommendations(snapshot, rows, windows(), 18)
    selected = [card['pick']['gw'] for card in cards.values() if card['pick']]
    assert sorted(selected) == [18, 19]
    assert all(card['expires'] == 19 for card in cards.values())
    assert windows()['freehit'] == [(2, 19), (20, 38)]
    assert cards['freehit']['usage'] == 0
