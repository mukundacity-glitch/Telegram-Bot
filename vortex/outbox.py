"""Deliver ChatGPT-authored editions through the one credentialed publisher.

Task instructions live verbatim in docs/chatgpt-task-specifications.json.
Only local reviewed PNGs are accepted: no arbitrary URL fetch or executable
instructions from an outbox record. Each page has independent platform receipts.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import re

from PIL import Image

from .graphic_numbers import graphic_key, stamp
from .autonomous_schedule import ET, RETIRED_EDITIONS
from .bot import ROOT, STATE, read_state, write_state
from .publishing_window import WINDOW_LABEL, assert_allowed, allowed
from .syndication import NewsPost, DiscordWebhookClient, publish_shared
from .telegram import TelegramClient
from .queue_retry import ATTEMPTS, failure_reason

QUEUE = ROOT / 'outbox'
RECEIPTS = STATE / 'chatgpt_deliveries.json'
STATUS = STATE / 'chatgpt_outbox_status.json'
TASKS = {'task1', 'task2', 'three_daily', 'press_news', 'price_changes'}


def retired_record(record):
    # Reject legacy/custom submissions from the former price_changes task,
    # regardless of which edition slug an external generator supplied.
    return (record.get('edition') == 'striker-watch'
            or (record.get('edition') == 'goalkeeper-striker-watch' and
                not (record.get('facts') or {}).get('extra', {}).get('combined_weekly'))
            or (record.get('edition') == 'positional-vulnerability' and
                not (record.get('facts') or {}).get('extra', {}).get('combined_wildcard'))
            or (record.get('edition') == 'monday-defence-watch' and
                not (record.get('facts') or {}).get('extra', {}).get('combined_monday'))
            or record.get('edition') in RETIRED_EDITIONS
            or (record.get('task') == 'price_changes' and record.get('edition') != 'price-prediction'))


def validate(record, root=ROOT, now=None, *, allow_outside_window=False, preview=False):
    now = now or datetime.now(timezone.utc)
    if record.get('task') not in TASKS or not re.fullmatch(r'[a-z0-9-]+', str(record.get('edition', ''))):
        raise ValueError('Unrecognized task or edition')
    if record.get('edition') == 'confirmed-price-changes' or (record.get('task') == 'price_changes' and record.get('edition') != 'price-prediction'):
        raise ValueError('Retired edition cannot publish')
    gw = record.get('gameweek')
    if type(gw) is not int or not 1 <= gw <= 38 or not re.fullmatch(r'20\d{2}-\d{2}', record.get('season', '')):
        raise ValueError('Verified season and GW required')
    generated = datetime.fromisoformat(record['generated_at'].replace('Z', '+00:00'))
    if generated.tzinfo is None or not timedelta(0) <= now-generated <= timedelta(hours=3):
        raise ValueError('Edition is stale or generated timestamp invalid; refresh instead of replaying')
    publish_at = datetime.fromisoformat(record['publish_at'].replace('Z', '+00:00'))
    if publish_at.tzinfo is None or (not allow_outside_window and not allowed(publish_at)):
        raise ValueError('Requested publication is outside the Eastern posting window')
    deadline = datetime.fromisoformat(record['deadline'].replace('Z', '+00:00'))
    if deadline.tzinfo is None or (record.get('pre_deadline', True) and deadline <= now):
        raise ValueError('Actionable deadline has elapsed')
    if record.get('edition') == 'price-prediction':
        from .price_prediction_board import PRICE_LEAD, PRICE_GRACE
        if record.get('task') != 'price_changes' or allow_outside_window or not deadline-PRICE_LEAD <= now < deadline-PRICE_LEAD+PRICE_GRACE:
            raise ValueError('Price prediction outside its verified one-hour lead window')
        if not deadline-PRICE_LEAD <= publish_at < deadline-PRICE_LEAD+PRICE_GRACE:
            raise ValueError('Invalid price prediction publication time')
        facts = record.get('facts') or {}
        if datetime.fromisoformat(facts['update_at']) != deadline:
            raise ValueError('Price prediction deadline mismatch')
        updated = datetime.fromisoformat(facts['source_updated_at'])
        if updated.tzinfo is None or not -timedelta(minutes=2) <= now-updated <= timedelta(minutes=45):
            raise ValueError('Price prediction source stale')
    if not record.get('qa_passed') or not record.get('sources'):
        raise ValueError('Graphic QA and source evidence are required')
    caption = str(record.get('caption', ''))
    if not caption.strip() or len(caption) > 1024 or not 3 <= len(re.findall(r'(?<!\w)#[\w]+', caption)) <= 6:
        raise ValueError('Caption must fit Telegram and contain three to six hashtags')
    images = record.get('images') or []
    if record.get('edition') == 'four-midfielders' and len(images) != 1:
        raise ValueError('Four midfielders require ONE combined graphic and ONE caption')
    if record.get('edition') == 'goalkeeper-striker-watch':
        from .weekly_position_watch import publication_due
        if (len(images) != 1 or not (record.get('facts') or {}).get('extra', {}).get('combined_weekly')
                or (not preview and (allow_outside_window or not publication_due(now)
                or not publication_due(publish_at)
                or publish_at.astimezone(ET).date() != now.astimezone(ET).date()))):
            raise ValueError('Combined weekly position watch requires one Monday graphic at or after 10:30 ET')
    if record.get('edition') == 'positional-vulnerability':
        from .weekly_wildcard_vulnerability import publication_due
        if (len(images) != 1 or not (record.get('facts') or {}).get('extra', {}).get('combined_wildcard')
                or (not preview and (allow_outside_window or not publication_due(now)
                or not publication_due(publish_at)
                or publish_at.astimezone(ET).date() != now.astimezone(ET).date()))):
            raise ValueError('Combined Wildcard requires one Tuesday graphic at or after 15:30 ET')
    if record.get('edition') == 'monday-defence-watch':
        from .monday_intelligence import publication_due
        if (len(images) != 1 or not (record.get('facts') or {}).get('extra', {}).get('combined_monday')
                or (not preview and (allow_outside_window or not publication_due(now)
                or not publication_due(publish_at)
                or publish_at.astimezone(ET).date() != now.astimezone(ET).date()))):
            raise ValueError('Monday intelligence requires one Monday graphic at or after 20:00 ET')
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
    if record.get('edition') == 'price-prediction':
        # One publication per update even if forecasts or the current GW change.
        identity = f"chatgpt:{record['season']}:price_changes:price-prediction:{deadline.astimezone(timezone.utc).isoformat()}"
    return identity, resolved, publish_at


def queued_files(now):
    """Read due times for queue ordering; validation remains at delivery."""
    for file in sorted(QUEUE.glob('*.json')):
        try:
            row = json.loads(file.read_text())
            if retired_record(row) or row.get('edition') == 'price-prediction':
                continue
            due = datetime.fromisoformat(row['publish_at'].replace('Z', '+00:00'))
            if due.tzinfo and due <= now:
                yield due, file
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            print(f"{file.name}: {failure_reason(exc)}")


def run(now=None, telegram=None, discord=None, *, manual=False, target_file=None, telegram_primary=False):
    now = now or datetime.now(timezone.utc)
    if manual and target_file is None:
        raise ValueError('Manual delivery must target one generated outbox file')
    if not manual and not allowed(now):
        print('OUTBOX DEFERRED: outside ' + WINDOW_LABEL)
        return 0
    status = read_state(STATUS)
    files = ([Path(target_file)] if target_file is not None
             else [file for _, file in sorted(queued_files(now))])
    failed = False
    for file in files:
        if target_file is not None and (not file.is_file() or file.resolve().parent != QUEUE.resolve()):
            raise ValueError('Manual target must be an existing file directly in the outbox')
        # Only an eligible, due, unserved edition is a failed publication.
        # Historical stale queue entries must not make new runs fail.
        delivery_due = False
        previous = status.get(file.name, {})
        try:
            record = json.loads(file.read_text())
            if retired_record(record):
                continue
            identity, images, due = validate(record, root=ROOT, now=now,
                                             allow_outside_window=manual)
            if not manual and (due > now or (
                previous.get('identity') == identity and previous.get('attempts', 0) >= ATTEMPTS
            )):
                continue
            journal = read_state(RECEIPTS)
            keys = [f'{identity}:page{i+1}' for i in range(len(images))]
            if all(journal.get(k, {}).get('delivered') and journal.get(k, {}).get('discord_delivered') for k in keys):
                continue
            delivery_due = True
            telegram = telegram or TelegramClient()
            if discord is None:
                try:
                    discord = DiscordWebhookClient()
                except ValueError:
                    if not telegram_primary:
                        raise
                    print("Discord credential unavailable; continuing Telegram delivery")
            with TemporaryDirectory() as tmp:
                local_day = due.astimezone(ET).weekday()
                extra = record['facts'].get('extra') or {}
                series_day = extra.get('day') if isinstance(extra, dict) else None
                images = [
                    stamp(path, graphic_key(record['edition'], local_day, series_day, index),
                          Path(tmp) / f'{index}-{path.name}')
                    for index, path in enumerate(images)
                ]
                if len(images)>1:
                    from .syndication import publish_album
                    receipts=publish_album(identity,images,record['caption'],RECEIPTS,
                                            telegram,discord,now.isoformat())
                    status[file.name]={'status':'delivered','identity':identity,'at':now.isoformat(),'caption_once_album':True}
                    write_state(STATUS,status)
                    print(f'POSTED BOTH ALBUM {identity}: {len(receipts)} pages, one caption per platform')
                    continue
                for key, image in zip(keys, images):
                    assert_allowed()
                    post = NewsPost(identity=key, title=record['title'], caption=record['caption'],
                                    gameweek=record['gameweek'], image=image)
                    result = publish_shared(post, RECEIPTS, telegram, discord,
                                            send_discord=discord is not None, now_iso=now.isoformat())
                    print(f"POSTED BOTH {key} Telegram#{result.get('telegram_message_id')} Discord#{result.get('discord_message_id')}")
            status[file.name] = {'status': 'delivered', 'identity': identity, 'at': now.isoformat()}
            write_state(STATUS, status)
        except (ValueError, RuntimeError, KeyError, OSError, TypeError) as exc:
            reason = failure_reason(exc)
            if delivery_due:
                attempts = previous.get('attempts', 0) if previous.get('identity') == identity else 0
                status[file.name] = {'status': 'held', 'reason': reason, 'identity': identity,
                                     'attempts': attempts + 1, 'at': now.isoformat()}
                write_state(STATUS, status)
                failed = True
            elif previous.get('status') != 'held' or previous.get('reason') != reason:
                status[file.name] = {'status': 'held', 'reason': reason, 'at': now.isoformat()}
                write_state(STATUS, status)
            print(f'HOLD {file.name}: {reason}')
    print('OUTBOX CHECKED: no fresh unserved edition ready')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(run())
