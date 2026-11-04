"""Deliver ChatGPT-authored editions through the one credentialed publisher.

Task instructions live verbatim in docs/chatgpt-task-specifications.json.
Only local reviewed PNGs are accepted: no arbitrary URL fetch or executable
instructions from an outbox record. Each page has independent platform receipts.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import re

from PIL import Image

from .bot import ROOT, STATE, read_state, write_state
from .publishing_window import assert_allowed, allowed
from .syndication import NewsPost, DiscordWebhookClient, publish_shared
from .telegram import TelegramClient

QUEUE = ROOT / 'outbox'
RECEIPTS = STATE / 'chatgpt_deliveries.json'
STATUS = STATE / 'chatgpt_outbox_status.json'
TASKS = {'task1', 'task2', 'three_daily', 'press_news', 'price_changes'}


def validate(record, root=ROOT, now=None):
    now = now or datetime.now(timezone.utc)
    if record.get('task') not in TASKS or not re.fullmatch(r'[a-z0-9-]+', str(record.get('edition', ''))):
        raise ValueError('Unrecognized task or edition')
    gw = record.get('gameweek')
    if type(gw) is not int or not 1 <= gw <= 38 or not re.fullmatch(r'20\d{2}-\d{2}', record.get('season', '')):
        raise ValueError('Verified season and GW required')
    generated = datetime.fromisoformat(record['generated_at'].replace('Z', '+00:00'))
    if generated.tzinfo is None or not timedelta(0) <= now-generated <= timedelta(hours=3):
        raise ValueError('Edition is stale or generated timestamp invalid; refresh instead of replaying')
    publish_at = datetime.fromisoformat(record['publish_at'].replace('Z', '+00:00'))
    if publish_at.tzinfo is None or not allowed(publish_at):
        raise ValueError('Requested publication is outside the Eastern posting window')
    deadline = datetime.fromisoformat(record['deadline'].replace('Z', '+00:00'))
    if deadline.tzinfo is None or (record.get('pre_deadline', True) and deadline <= now):
        raise ValueError('Actionable deadline has elapsed')
    if not record.get('qa_passed') or not record.get('sources'):
        raise ValueError('Graphic QA and source evidence are required')
    caption = str(record.get('caption', ''))
    if not caption.strip() or len(caption) > 1024 or len(re.findall(r'(?<!\w)#[\w]+', caption)) != 4:
        raise ValueError('Caption must fit Telegram and contain exactly four hashtags')
    images = record.get('images') or []
    if record.get('edition') == 'four-midfielders' and len(images) != 1:
        raise ValueError('Four midfielders require ONE combined graphic and ONE caption')
    if not 1 <= len(images) <= 6:
        raise ValueError('One to six finished PNG pages required')
    resolved = []
    if not isinstance(record.get('facts'), dict) or not record['facts']:
        raise ValueError('Verified factual content is required for stable cross-run duplicate control')
    digest = hashlib.sha256(json.dumps(record['facts'], sort_keys=True, separators=(',', ':')).encode())
    for relative in images:
        path = (root / relative).resolve()
        if not path.is_relative_to((root / 'outbox' / 'assets').resolve()) or path.suffix != '.png':
            raise ValueError('Only committed outbox/assets PNGs may be published')
        if path.stat().st_size > 8_000_000:
            raise ValueError('PNG upload exceeds safe size')
        with Image.open(path) as image:
            if image.size not in ((1920, 1080), (1080, 1920)):
                raise ValueError('Finished art must be 1920x1080 or 1080x1920')
            image.verify()
        resolved.append(path)
    version = digest.hexdigest()[:20]
    identity = f"chatgpt:{record['season']}:GW{gw}:{record['task']}:{record['edition']}:{version}"
    return identity, resolved, publish_at


def run(now=None, telegram=None, discord=None):
    now = now or datetime.now(timezone.utc)
    if not allowed(now):
        print('OUTBOX DEFERRED: outside 05:00–20:00 ET')
        return 0
    status = read_state(STATUS)
    journal = read_state(RECEIPTS)
    # ONE edition per serialized job. Failed pages resume independently and
    # never cause a successful destination to receive a repeated copy.
    for file in sorted(QUEUE.glob('*.json')):
        # Only an eligible, due, unserved edition is a failed publication.
        # Historical stale queue entries must not make new runs fail.
        delivery_due = False
        try:
            record = json.loads(file.read_text())
            identity, images, due = validate(record, root=ROOT, now=now)
            if due > now:
                continue
            keys = [f'{identity}:page{i+1}' for i in range(len(images))]
            if all(journal.get(k, {}).get('delivered') and journal.get(k, {}).get('discord_delivered') for k in keys):
                continue
            delivery_due = True
            if len(images)>1:
                from .syndication import publish_album
                receipts=publish_album(identity,images,record['caption'],RECEIPTS,
                                        telegram or TelegramClient(),discord or DiscordWebhookClient(),now.isoformat())
                status[file.name]={'status':'delivered','identity':identity,'at':now.isoformat(),'caption_once_album':True}
                write_state(STATUS,status)
                print(f'POSTED BOTH ALBUM {identity}: {len(receipts)} pages, one caption per platform')
                return 0
            for key, image in zip(keys, images):
                assert_allowed()
                post = NewsPost(identity=key, title=record['title'], caption=record['caption'],
                                gameweek=record['gameweek'], image=image)
                result = publish_shared(post, RECEIPTS, telegram or TelegramClient(),
                                        discord or DiscordWebhookClient(), now_iso=now.isoformat())
                print(f"POSTED BOTH {key} Telegram#{result.get('telegram_message_id')} Discord#{result.get('discord_message_id')}")
            status[file.name] = {'status': 'delivered', 'identity': identity, 'at': now.isoformat()}
            write_state(STATUS, status)
            return 0
        except (ValueError, RuntimeError, KeyError, OSError, TypeError) as exc:
            # Retain actionable validation reasons, but never external response
            # strings that might contain credentials.
            reason = str(exc) if isinstance(exc, (ValueError, KeyError)) else type(exc).__name__
            status[file.name] = {'status': 'held', 'reason': reason, 'at': now.isoformat()}
            write_state(STATUS, status)
            print(f'HOLD {file.name}: {reason}')
            if delivery_due:
                # Actual due delivery failed, including missing credentials,
                # rejected uploads, and an unconfirmed transport response.
                # Do not make GitHub Actions show success with zero posts.
                print('::error::An eligible Telegram/Discord edition was not fully delivered')
                return 1
    print('OUTBOX CHECKED: no fresh unserved edition ready')
    return 0


if __name__ == '__main__':
    raise SystemExit(run())
