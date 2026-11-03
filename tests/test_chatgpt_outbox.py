from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pytest
from PIL import Image
from vortex import outbox
from vortex.publishing_window import allowed

NOW = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)


def record(tmp_path):
    image = tmp_path / 'outbox/assets/graphic.png'
    image.parent.mkdir(parents=True)
    Image.new('RGB', (1920, 1080), '#03182a').save(image)
    return {'task': 'task1', 'edition': 'form-targets', 'season': '2026-27',
            'gameweek': 10, 'generated_at': NOW.isoformat(), 'publish_at': NOW.isoformat(),
            'deadline': (NOW+timedelta(days=3)).isoformat(), 'qa_passed': True,
            'sources': ['https://fantasy.premierleague.com/api/bootstrap-static/'],
            'facts': {'player_ids': [12], 'minutes': 800},
            'title': 'FORM TARGETS', 'caption': 'Fact\nNext fixture\nDecision\nHOLD\n#FPL #FPLVortex #GW10 #FPLTips',
            'images': ['outbox/assets/graphic.png']}


def test_window_handles_dst_and_closes_at_8pm():
    assert not allowed(datetime(2026, 11, 3, 9, 59, tzinfo=timezone.utc))
    assert allowed(datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc))
    assert allowed(datetime(2026, 11, 4, 0, 59, tzinfo=timezone.utc))
    assert not allowed(datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc))
    assert allowed(datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc))


def test_stale_and_external_assets_rejected(tmp_path):
    r = record(tmp_path)
    r['generated_at'] = (NOW-timedelta(hours=4)).isoformat()
    with pytest.raises(ValueError, match='stale'):
        outbox.validate(r, tmp_path, NOW)
    r['generated_at'] = NOW.isoformat()
    r['images'] = ['../../secrets.png']
    with pytest.raises(ValueError, match='Only committed'):
        outbox.validate(r, tmp_path, NOW)


def test_cosmetic_change_cannot_create_new_delivery_identity(tmp_path):
    r = record(tmp_path)
    original = outbox.validate(r, tmp_path, NOW)[0]
    r['caption'] = r['caption'].replace('Fact', 'Updated design')
    r['generated_at'] = (NOW-timedelta(minutes=1)).isoformat()
    assert outbox.validate(r, tmp_path, NOW)[0] == original


def test_partial_delivery_retries_only_missing_platform(tmp_path, monkeypatch):
    r = record(tmp_path)
    (tmp_path/'outbox/edition.json').write_text(json.dumps(r))
    monkeypatch.setattr(outbox, 'ROOT', tmp_path)
    monkeypatch.setattr(outbox, 'QUEUE', tmp_path/'outbox')
    monkeypatch.setattr(outbox, 'RECEIPTS', tmp_path/'receipts.json')
    monkeypatch.setattr(outbox, 'STATUS', tmp_path/'status.json')
    sent = []
    class Telegram:
        def send_shared_png(self, *args):
            sent.append('telegram'); return 171
        send_png = send_shared_png
    class Discord:
        fail = True
        def send(self, post):
            if self.fail: raise RuntimeError('temporary destination failure')
            sent.append('discord'); return '456'
    d = Discord()
    assert outbox.run(NOW, Telegram(), d) == 1
    d.fail = False
    assert outbox.run(NOW, Telegram(), d) == 0
    assert outbox.run(NOW, Telegram(), d) == 0
    assert sent == ['telegram', 'discord']


def test_outside_window_never_attempts_transport(tmp_path, monkeypatch):
    monkeypatch.setattr(outbox, 'QUEUE', tmp_path)
    assert outbox.run(datetime(2026, 11, 3, 7, 0, tzinfo=timezone.utc)) == 0
