"""User-requested in-place merge of the two verified GW10 midfielder posts.

No new audience posts. Edit the first message on each platform, checkpoint,
then remove only the second message whose IDs match the saved receipts.
"""
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import json
import requests

from .bot import ROOT, STATE, read_state, write_state
from .outbox import validate
from .publishing_window import assert_allowed
from .telegram import TelegramClient
from .syndication import DiscordWebhookClient

IDENTITY = 'chatgpt:2026-27:GW10:task2:four-midfielders:2ccfe73e1055162653f9'
EXPECTED = ((170, '1567191388896894996'), (171, '1567191400477495338'))
REVISION = 'one-four-player-graphic-v1'


def discord_change(client, message_id, image=None, caption=None):
    parts = urlsplit(client.url)
    url = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/')+'/messages/'+message_id, '', ''))
    try:
        if image:
            with image.open('rb') as source:
                response = client.session.patch(url, timeout=50,
                    data={'payload_json': json.dumps({'content': caption, 'attachments': [],
                                                       'allowed_mentions': {'parse': []}})},
                    files={'files[0]': (image.name, source, 'image/png')})
            if response.status_code != 200 or str(response.json().get('id')) != message_id:
                raise RuntimeError('Discord did not confirm the edited original message')
        else:
            response = client.session.delete(url, timeout=30)
            if response.status_code not in (204, 404):
                raise RuntimeError('Discord did not confirm redundant message removal')
    except (requests.RequestException, ValueError):
        raise RuntimeError('Discord correction request failed; no new post attempted') from None


def run(telegram=None, discord=None, root=ROOT, receipt_path=None):
    assert_allowed()
    receipt_path = receipt_path or STATE/'chatgpt_deliveries.json'
    ledger = read_state(receipt_path)
    keys = [IDENTITY+':page1', IDENTITY+':page2']
    for key, (telegram_id, discord_id) in zip(keys, EXPECTED):
        row = ledger.get(key, {})
        if (row.get('telegram_message_id'), row.get('discord_message_id')) != (telegram_id, discord_id):
            raise RuntimeError('Original verified message receipts differ; no edits/deletions attempted')
    record = json.loads((root/'outbox/gw10-four-midfielders.json').read_text())
    new_identity, images, _ = validate(record, root=root)
    if len(images) != 1:
        raise ValueError('Correction requires exactly one combined graphic')
    first, second = (ledger[k] for k in keys)
    telegram = telegram or TelegramClient()
    discord = discord or DiscordWebhookClient()
    if first.get('telegram_layout_revision') != REVISION:
        telegram.edit_shared_png(images[0], record['caption'], EXPECTED[0][0])
        first['telegram_layout_revision'] = REVISION
        write_state(receipt_path, ledger)
    if first.get('discord_layout_revision') != REVISION:
        discord_change(discord, EXPECTED[0][1], images[0], record['caption'])
        first['discord_layout_revision'] = REVISION
        write_state(receipt_path, ledger)
    # Fresh verification can change ownership/transfer figures and therefore
    # the factual identity. Point that version at the EDITED originals so the
    # regular outbox cannot publish another copy after this correction.
    ledger[new_identity+':page1'] = dict(first)
    write_state(receipt_path, ledger)
    # Never remove a page before BOTH originals have the replacement image.
    if not second.get('telegram_removed_after_merge'):
        result = telegram._post('deleteMessage', {'chat_id': telegram.chat_id,
                                                  'message_id': EXPECTED[1][0]})
        if result.get('result') is not True:
            raise RuntimeError('Telegram did not confirm redundant message removal')
        second['telegram_removed_after_merge'] = True
        write_state(receipt_path, ledger)
    if not second.get('discord_removed_after_merge'):
        discord_change(discord, EXPECTED[1][1])
        second['discord_removed_after_merge'] = True
        write_state(receipt_path, ledger)
    print('COMBINED BOTH: Telegram#170 and Discord#1567191388896894996 updated; second pages removed')
    return 0


if __name__ == '__main__':
    raise SystemExit(run())
