"""Process the due Telegram queue in trigger order on each existing heartbeat."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from .autonomous_content import Evidence
from .autonomous_runner import run as run_editions, STATE_FILE
from .autonomous_schedule import (
    ET, SLOTS, catchup_slots, publication_key, retryable, season_id, slot_start,
    special_triggers,
)
from .bot import STATE, read_state, write_state, run as run_legacy
from .fpl import collect_snapshot
from .outbox import RECEIPTS, STATUS as OUTBOX_STATUS, queued_files, run as run_outbox
from .publishing_window import WINDOW_LABEL, allowed
from .queue_retry import ATTEMPTS, failure_reason, retry_source
from .schedule import SLOT_HOURS, SLOT_CRONS
from .unified_runner import PENDING as NEWS_PENDING, RECEIPTS as NEWS_RECEIPTS, run as run_news

REPORT = STATE / 'scheduled_dispatch_status.json'
AUDIT = STATE / 'publishing_audit.json'
LEGACY = STATE / 'scheduled_legacy_attempts.json'
FIRST_RUN_NEWS_MINUTE = 43
LEGACY_RECEIPTS = STATE / 'deliveries.json'


def legacy_jobs(now, ledger, checks):
    local = now.astimezone(ET)
    for name, (hour, minute) in SLOT_HOURS.items():
        trigger = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        key = f'{local.date()}:{name}'
        if trigger > now or not retryable(checks.get(key, {})):
            continue
        related = [v for k, v in ledger.items() if k == key or k.startswith(key + ':GW')]
        if any(v.get('delivered') for v in related):
            continue
        cron = next((cron for cron, slot in SLOT_CRONS.items() if slot == name), None)
        if cron:
            yield trigger, key, name, cron


def due_legacy(now, ledger, checks):
    """Return the earliest original slot for callers that only inspect one."""
    job = min(legacy_jobs(now, ledger, checks), default=None)
    return job[1:] if job else None


def legacy_delivery(now, snapshot, key, cron, checks):
    audit = {}
    result = run_legacy('auto', cron, snapshot=snapshot, now=now, audit=audit)
    checks[key] = {
        'status': 'held' if result else 'checked',
        'attempts': checks.get(key, {}).get('attempts', 0) + 1,
        'at': now.isoformat(),
        **audit,
    }
    write_state(LEGACY, checks)
    return audit.get('generated', False), audit.get('error') or (
        'Legacy publisher returned exit code ' + str(result) if result else None
    )


def telegram_ids(path):
    return {row['telegram_message_id'] for row in read_state(path).values()
            if row.get('delivered') and row.get('telegram_message_id') is not None}


def run(now=None, cron=None):
    injected_time = now is not None
    now = now or datetime.now(timezone.utc)
    if not allowed(now):
        result = {'status': 'deferred-outside-window', 'at': now.isoformat(),
                  'new_posts': 0, 'window': WINDOW_LABEL}
        print(json.dumps(result, sort_keys=True))
        return result

    editorial = read_state(STATE_FILE)
    checks = read_state(LEGACY)
    legacy = read_state(LEGACY_RECEIPTS)
    outbox_state = read_state(OUTBOX_STATUS)
    news_pending = read_state(NEWS_PENDING)
    cutoff = (now - timedelta(days=14)).isoformat()
    audit = {key: row for key, row in read_state(AUDIT).items()
             if row.get('timestamp', '') >= cutoff}
    ledger_paths = (LEGACY_RECEIPTS, RECEIPTS, NEWS_RECEIPTS)
    known_ids = set().union(*(telegram_ids(path) for path in ledger_paths))
    run_key = now.isoformat()
    local = now.astimezone(ET)
    jobs = [(trigger, 'legacy', key, (name, scheduled))
            for trigger, key, name, scheduled in legacy_jobs(now, legacy, checks)]
    pending = []
    source_error = None
    try:
        snapshot = retry_source(collect_snapshot)
    except (RuntimeError, ValueError, OSError) as exc:
        snapshot = None
        source_error = failure_reason(exc)
    if snapshot is None:
        for slot in SLOTS:
            trigger = slot_start(slot, now)
            if trigger <= now:
                jobs.append((trigger, 'editorial', f'{local.date()}:{slot.edition}:snapshot', slot))
    else:
        gw, season = snapshot.gameweek(), season_id(snapshot, now)
        evidence = Evidence(snapshot, now)
        for slot in catchup_slots(now, editorial, gw, season, limit=None):
            jobs.append((slot_start(slot, now), 'editorial',
                         publication_key(slot, now, gw, season), slot))
        for slot, trigger in special_triggers(snapshot, now):
            key = publication_key(slot, now, gw, season)
            if retryable(editorial.get(key, {})):
                if trigger is None or trigger > now:
                    pending.append({'post': slot.edition, 'trigger': trigger.isoformat() if trigger else None})
                else:
                    jobs.append((trigger, 'editorial', key, slot))
        check_news = cron is None or cron.startswith(f'{FIRST_RUN_NEWS_MINUTE} ')
        if check_news or news_pending:
            retry_times = [datetime.fromisoformat(item['queued_at']) for item in news_pending.values()
                           if item.get('queued_at') and item.get('attempts', 0) < ATTEMPTS]
            jobs.append((min(retry_times, default=now), 'news', f'{run_key}:news', check_news))

    owned_files = {row.get('file') for row in editorial.values()}
    for trigger, file in queued_files(now):
        prior = outbox_state.get(file.name, {})
        if prior.get('status') == 'delivered' or prior.get('attempts', 0) >= ATTEMPTS:
            continue
        if f'outbox/{file.name}' not in owned_files:
            jobs.append((trigger, 'outbox', file.name, file))
    rows = []
    for trigger, lane, key, payload in sorted(jobs, key=lambda item: (item[0], item[1], item[2])):
        post = payload.edition if lane == 'editorial' else payload[0] if lane == 'legacy' else key
        row = {'post_id': key, 'type': post, 'trigger': trigger.isoformat(),
               'timestamp': run_key, 'status': 'PENDING', 'attempts': 0}
        audit[key] = row
        write_state(AUDIT, audit)
        error, generated, attempts = None, False, 0
        news_rows = []
        try:
            if lane == 'legacy':
                if snapshot is None:
                    raise RuntimeError(source_error)
                generated, error = legacy_delivery(now, snapshot, key, payload[1], checks)
                attempts = checks[key]['attempts']
            elif lane == 'editorial':
                if snapshot is None:
                    raise RuntimeError(source_error)
                edition = run_editions(now=now, snapshot=snapshot, selected_slots=[payload],
                                       evidence=evidence).get('editions', [{}])[0]
                generated, attempts = edition.get('generated', False), edition.get('attempts', 0)
                if edition.get('status') in ('held', 'queued-or-partial'):
                    error = edition.get('reason') or 'Telegram delivery incomplete; see outbox receipt'
            elif lane == 'news':
                run_news(now=now, snapshot=snapshot, drain=True, pending_only=not payload,
                         audit_rows=news_rows)
            else:
                if run_outbox(now if injected_time else datetime.now(timezone.utc),
                              target_file=payload, telegram_primary=True):
                    entry = read_state(OUTBOX_STATUS).get(payload.name, {})
                    error = entry.get('reason') or 'Outbox delivery incomplete'
                    attempts = entry.get('attempts', 0)
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            error = failure_reason(exc)
            if lane == 'legacy' and snapshot is not None:
                attempts = checks.get(key, {}).get('attempts', 0) + 1
                checks[key] = {'status': 'held', 'reason': error, 'attempts': attempts, 'at': run_key}
                write_state(LEGACY, checks)
            if lane == 'editorial' and snapshot is not None:
                current = read_state(STATE_FILE)
                prior = current.get(key, {})
                attempts = prior.get('attempts', 0) + 1
                current[key] = {**prior, 'status': 'held', 'reason': error, 'attempts': attempts}
                write_state(STATE_FILE, current)
        current_ids = set().union(*(telegram_ids(path) for path in ledger_paths))
        new_ids = sorted(current_ids - known_ids)
        known_ids.update(current_ids)
        receipt_rows = read_state(LEGACY_RECEIPTS) if lane == 'legacy' else {}
        receipt_ids = [item.get('telegram_message_id') for identity, item in receipt_rows.items()
                       if (identity == key or identity.startswith(key + ':GW')) and item.get('delivered')]
        row.update(confirmed_telegram_message_ids=receipt_ids or new_ids, status='FAILED' if error and attempts >= ATTEMPTS else 'RETRY' if error
                   else 'POSTED' if new_ids else 'CHECKED',
                   generated=generated, telegram_message_ids=new_ids, error=error, attempts=attempts,
                   completed_at=datetime.now(timezone.utc).isoformat())
        for item in news_rows:
            item['telegram_message_ids'] = ([item['telegram_message_id']]
                                            if item.get('telegram_message_id') in new_ids else [])
            if item['status'] == 'POSTED' and not item['telegram_message_ids']:
                item['status'] = 'CHECKED'
            audit[item['post_id']] = item
        write_state(AUDIT, audit)
        rows.extend(news_rows or [row])
        print(json.dumps(row, ensure_ascii=False))

    upcoming = [{'post': slot.edition, 'trigger': slot_start(slot, now).isoformat()}
                for slot in SLOTS if slot_start(slot, now) > now]
    for name, (hour, minute) in SLOT_HOURS.items():
        trigger = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if trigger > now:
            upcoming.append({'post': name, 'trigger': trigger.isoformat()})
    upcoming.extend(item for item in pending if item['trigger'])
    if not upcoming:
        tomorrow = local + timedelta(days=1)
        upcoming = [{'post': slot.edition, 'trigger': slot_start(slot, tomorrow).isoformat()}
                    for slot in SLOTS]
    audit[run_key] = {'status': 'RUN', 'timestamp': run_key, 'posts': rows}
    write_state(AUDIT, audit)
    counts = Counter(row['status'] for row in rows)
    posted = sum(bool(row['telegram_message_ids']) for row in rows)
    messages = sum(len(row['telegram_message_ids']) for row in rows)
    result = {
        'status': 'published' if posted else 'held' if counts['RETRY'] or counts['FAILED'] or source_error
                  else 'no-new-verified-content',
        'at': run_key, 'eastern_at': local.isoformat(), 'scheduled_cron': cron,
        'posts_due': len(rows), 'posts_generated': sum(row['generated'] for row in rows),
        'new_posts': posted, 'telegram_messages_sent': messages, 'posts_retried': sum(row['attempts'] > 1 for row in rows),
        'posts_failed': counts['FAILED'], 'posts_retry_pending': counts['RETRY'],
        'posts_pending_trigger': len(pending), 'pending_triggers': pending, 'next_due': min(upcoming, key=lambda item: datetime.fromisoformat(item['trigger'])),
        'source_error': source_error,
    }
    write_state(REPORT, result)
    print('SCHEDULED PUBLISH REPORT ' + json.dumps(result, ensure_ascii=False))
    return result


def main():
    import os
    result = run(cron=os.getenv('SCHEDULED_CRON') or None)
    return int(bool(result.get('source_error') or result.get('posts_failed') or
                    result.get('posts_retry_pending')))


if __name__ == '__main__':
    raise SystemExit(main())
