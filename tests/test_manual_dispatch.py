"""Manual workflow dispatch publishes exactly one verified edition immediately."""
from datetime import datetime, timedelta, timezone
import json
from PIL import Image
from vortex import outbox, autonomous_runner as runner

EARLY_ET = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)  # 04:00 EST

def _prepare(tmp_path, monkeypatch):
    folder = tmp_path / 'outbox'
    assets = folder / 'assets'
    assets.mkdir(parents=True)
    Image.new('RGB', (1920, 1080), '#03182a').save(assets / 'post.png')
    data = {
        'task': 'task2', 'edition': 'four-midfielders',
        'season': '2026-27', 'gameweek': 10,
        'generated_at': EARLY_ET.isoformat(),
        'publish_at': EARLY_ET.isoformat(),
        'deadline': (EARLY_ET + timedelta(days=3)).isoformat(),
        'qa_passed': True,
        'sources': ['https://fantasy.premierleague.com/api/bootstrap-static/'],
        'facts': {'player_ids': [1, 2, 3, 4]},
        'title': 'VERIFIED FOUR MIDFIELDERS',
        'caption': 'Verified FPL players\n#FPL #FPLVortex #GW10 #FPLTips',
        'images': ['outbox/assets/post.png']
    }
    target = folder / 'publish.json'
    target.write_text(json.dumps(data))
    (folder / 'a-older.json').write_text(json.dumps(dict(data, edition='rank-booster')))
    monkeypatch.setattr(outbox, 'ROOT', tmp_path)
    monkeypatch.setattr(outbox, 'QUEUE', folder)
    monkeypatch.setattr(outbox, 'RECEIPTS', tmp_path / 'receipts.json')
    monkeypatch.setattr(outbox, 'STATUS', tmp_path / 'status.json')
    monkeypatch.setenv('FPL_PUBLISH_WINDOW_ENFORCED', 'false')
    return target

def test_manual_delivery_bypasses_window_only_for_explicit_target(tmp_path, monkeypatch):
    target = _prepare(tmp_path, monkeypatch)
    assert outbox.run(EARLY_ET) == 0
    class Telegram:
        def send_shared_png(self, *args):
            return 123
        send_png = send_shared_png
    class Discord:
        def send(self, post):
            return '456'
    assert outbox.run(EARLY_ET, Telegram(), Discord(), manual=True, target_file=target) == 0
    journal = json.loads((tmp_path / 'receipts.json').read_text())
    assert len(journal) == 1
    assert all(row['delivered'] and row['discord_delivered'] for row in journal.values())
    assert outbox.run(EARLY_ET, Telegram(), Discord(), manual=True, target_file=target) == 0
    assert len(json.loads((tmp_path / 'receipts.json').read_text())) == 1

def test_manual_rejection_fails_instead_of_reporting_green(tmp_path, monkeypatch):
    target = _prepare(tmp_path, monkeypatch)
    class FailedTelegram:
        def send_shared_png(self, *args):
            raise RuntimeError('fake upstream error')
        send_png = send_shared_png
    class FailedDiscord:
        def send(self, post):
            raise RuntimeError('fake webhook rejection')
    assert outbox.run(EARLY_ET, FailedTelegram(), FailedDiscord(),
                      manual=True, target_file=target) == 1

def test_runner_manual_bypasses_due_filter_and_targets_exact_file(monkeypatch):
    from test_publication_contract import snap
    s = snap()
    monkeypatch.setattr(runner, 'allowed', lambda _: False)
    monkeypatch.setattr(runner, 'Evidence', lambda *args: object())
    monkeypatch.setattr(runner, 'write_state', lambda *args: None)
    monkeypatch.setattr(runner, 'stage', lambda *args, **kwargs:
                        (runner.ROOT / 'outbox/manual.json', 'unit-id', 1))
    published = []
    def read_state(path):
        if path == runner.RECEIPTS:
            return {'unit-id:page1': {'delivered': True, 'discord_delivered': True}} if published else {}
        return {}
    monkeypatch.setattr(runner, 'read_state', read_state)
    def fake_publish(now, *, manual=False, target_file=None):
        published.append((manual, target_file))
        return 0
    monkeypatch.setattr(runner, 'publish_outbox', fake_publish)
    result = runner.run(edition='four-midfielders', manual=True,
                        now=EARLY_ET, snapshot=s)
    assert result['confirmed_edition_deliveries'] == 1
    assert published == [(True, runner.ROOT / 'outbox/manual.json')]
    assert runner.run(edition='four-midfielders', manual=False, now=EARLY_ET,
                      snapshot=s)['status'] == 'deferred-outside-window'

def test_workflow_manual_input_is_not_a_due_only_noop():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] /
                '.github/workflows/telegram-daily.yml').read_text()
    assert 'python -m vortex.autonomous_runner --manual --edition "$MANUAL_EDITION"' in workflow
    assert "FPL_MANUAL_PUBLISH:" in workflow

def test_prior_day_receipt_is_not_mistaken_for_new_manual_upload(monkeypatch):
    from test_publication_contract import snap
    s = snap()
    monkeypatch.setattr(runner, 'allowed', lambda _: False)
    monkeypatch.setattr(runner, 'Evidence', lambda *args: object())
    monkeypatch.setattr(runner, 'write_state', lambda *args: None)
    monkeypatch.setattr(runner, 'stage', lambda *args, **kwargs:
                        (runner.ROOT / 'outbox/manual.json', 'unit-id', 1))
    def already_delivered(path):
        if path == runner.RECEIPTS:
            return {'unit-id:page1': {'delivered': True, 'discord_delivered': True}}
        return {}
    monkeypatch.setattr(runner, 'read_state', already_delivered)
    monkeypatch.setattr(runner, 'publish_outbox', lambda *args, **kwargs: 0)
    result = runner.run(edition='four-midfielders', manual=True,
                        now=EARLY_ET, snapshot=s)
    assert result['confirmed_edition_deliveries'] == 0
    assert result['editions'][0]['status'] == 'already-delivered'

def test_manual_cli_does_not_report_green_when_nothing_new_was_published(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'argv', ['autonomous_runner', '--manual', '--edition', 'four-midfielders'])
    monkeypatch.setattr(runner, 'run', lambda **kwargs: {
        'confirmed_edition_deliveries': 0,
        'editions': [{'status': 'already-delivered', 'edition': 'four-midfielders'}],
    })
    assert runner.main() == 1
