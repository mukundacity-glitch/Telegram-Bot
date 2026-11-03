import json
from pathlib import Path
import pytest
from vortex import combine_midfielder_posts as correction


def test_wrong_message_receipts_stop_before_any_external_change(tmp_path):
    path = tmp_path/'receipts.json'
    path.write_text('{}')
    with pytest.raises(RuntimeError, match='receipts differ'):
        correction.run(root=tmp_path, receipt_path=path)


def test_first_posts_updated_before_second_posts_removed_and_no_repeat(tmp_path, monkeypatch):
    ledger = {correction.IDENTITY+f':page{i+1}': {'telegram_message_id': pair[0],
              'discord_message_id': pair[1]} for i, pair in enumerate(correction.EXPECTED)}
    path = tmp_path/'receipts.json'; path.write_text(json.dumps(ledger))
    (tmp_path/'outbox').mkdir()
    (tmp_path/'outbox/gw10-four-midfielders.json').write_text(json.dumps({'caption': 'approved caption'}))
    monkeypatch.setattr(correction, 'validate', lambda *a, **k: ('identity', [tmp_path/'graphic.png'], None))
    calls = []
    class Telegram:
        chat_id = 'inert-test-destination'
        def edit_shared_png(self, image, caption, message_id):
            calls.append(('telegram_edit', message_id)); return message_id
        def _post(self, method, data):
            calls.append(('telegram_remove', data['message_id'])); return {'result': True}
    def discord(client, message_id, image=None, caption=None):
        calls.append(('discord_edit' if image else 'discord_remove', message_id))
    monkeypatch.setattr(correction, 'discord_change', discord)
    correction.run(Telegram(), object(), tmp_path, path)
    correction.run(Telegram(), object(), tmp_path, path)
    assert [x[0] for x in calls] == ['telegram_edit', 'discord_edit', 'telegram_remove', 'discord_remove']


def test_four_midfielder_outbox_rejects_split_pages(tmp_path):
    from test_chatgpt_outbox import record, NOW
    from vortex.outbox import validate
    item = record(tmp_path)
    item['edition'] = 'four-midfielders'
    item['images'] *= 2
    with pytest.raises(ValueError, match='ONE combined graphic'):
        validate(item, tmp_path, NOW)
