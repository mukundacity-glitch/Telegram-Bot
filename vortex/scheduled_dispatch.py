"""Process the due Telegram queue in trigger order on each existing heartbeat."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from .autonomous_content import Evidence
from .autonomous_runner import run as run_editions, STATE_FILE
from .autonomous_schedule import (
    ET, SLOTS, catchup_slots, eligible_on, publication_key, retryable, season_id, slot_start,
    special_triggers, SERIES, SERIES_STATE, EVENING_WATCH_SLOTS, weekly_analysis_slot,
)
from .bot import STATE, read_state, write_state, run as run_legacy
from .fpl import collect_snapshot
from .outbox import RECEIPTS, STATUS as OUTBOX_STATUS, queued_files, run as run_outbox
from .publishing_window import OPEN_MINUTE, WINDOW_LABEL, allowed
from .queue_retry import ATTEMPTS, failure_reason, retry_source
from .schedule import SLOT_HOURS, SLOT_CRONS
from .telegram_spacing import DeliveryDeferred, blocked_until, enabled as spacing_enabled
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



def upcoming_editorial(slot, trigger):
    result = {'post': slot.edition, 'trigger': trigger.isoformat()}
    if slot.display_name:
        result['display_name'] = slot.display_name
    return result


def run(now=None, cron=None, snapshot=None):
    injected_time = now is not None
    now = now or datetime.now(timezone.utc)
    if not allowed(now):
        result = {'status': 'deferred-outside-window', 'at': now.isoformat(),
                  'new_posts': 0, 'window': WINDOW_LABEL}
        print(json.dumps(result, sort_keys=True))
        return result

    previous_report = read_state(REPORT) if spacing_enabled() else {}
    if until := blocked_until(now):
        result = {**previous_report, 'status': 'deferred-telegram-spacing',
                  'at': now.isoformat(), 'eastern_at': now.astimezone(ET).isoformat(),
                  'scheduled_cron': cron, 'next_telegram_at': until.isoformat(),
                  'new_posts': 0, 'telegram_messages_sent': 0}
        for field in ('posts_due', 'posts_generated', 'posts_retried', 'posts_failed', 'posts_retry_pending'):
            result[field] = 0
        result['source_error'] = None
        write_state(REPORT, result)
        print('SCHEDULED PUBLISH REPORT ' + json.dumps(result, ensure_ascii=False))
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
    last_news_scan = previous_report.get("last_news_scan")
    source_error = None
    price_status = {'status': 'unavailable'}
    try:
        snapshot = snapshot or retry_source(collect_snapshot)
    except (RuntimeError, ValueError, OSError) as exc:
        snapshot = None
        source_error = failure_reason(exc)
    if snapshot is None:
        for slot in SLOTS:
            if slot == SERIES or not eligible_on(slot, now):
                continue
            trigger = slot_start(slot, now)
            if trigger <= now:
                jobs.append((trigger, 'editorial', f'{local.date()}:{slot.edition}:snapshot', slot))
    else:
        gw, season = snapshot.gameweek(), season_id(snapshot, now)
        evidence = Evidence(snapshot, now)
        if getattr(snapshot, 'game_config', None) is not None:
            from .price_prediction_board import opportunity, ownership_snapshot
            from .editorial_inputs import RequiredInput
            try:
                price_slot, price_status = opportunity(snapshot, now, editorial)
                prior = editorial.get('_price_ownership', {})
                evidence.price_previous = prior
                try:
                    elapsed = snapshot.fetched_at - datetime.fromisoformat(prior['at'])
                except (KeyError, ValueError, TypeError):
                    elapsed = timedelta(hours=27)
                if elapsed >= timedelta(minutes=5):
                    editorial['_price_ownership'] = ownership_snapshot(snapshot)
                    write_state(STATE_FILE, editorial)
                if price_slot is not None:
                    trigger = datetime.fromisoformat(price_status['trigger'])
                    if trigger > now:
                        pending.append(upcoming_editorial(price_slot, trigger))
                    else:
                        jobs.append((trigger, 'editorial', publication_key(price_slot, now, gw, season), price_slot))
            except RequiredInput as exc:
                price_status = {'status': 'unavailable', 'reason': str(exc)}
        for slot in catchup_slots(now, editorial, gw, season, limit=None):
            jobs.append((slot_start(slot, now), 'editorial',
                         publication_key(slot, now, gw, season), slot))
        old_series = editorial.get(SERIES_STATE)
        series = weekly_analysis_slot(snapshot, now, editorial)
        if series is not None:
            if old_series != editorial.get(SERIES_STATE):
                write_state(STATE_FILE, editorial)
            key = publication_key(series, now, gw, season)
            if retryable(editorial.get(key, {})):
                jobs.append((slot_start(series, now), 'editorial', key, series))
        for slot, trigger in special_triggers(snapshot, now):
            key = publication_key(slot, now, gw, season)
            if retryable(editorial.get(key, {})):
                if trigger is None or trigger > now:
                    pending.append({'post': slot.edition, 'trigger': trigger.isoformat() if trigger else None})
                else:
                    jobs.append((trigger, 'editorial', key, slot))
        check_news = cron is None or cron.startswith(f'{FIRST_RUN_NEWS_MINUTE} ')
        if spacing_enabled():
            check_news = not last_news_scan or now - datetime.fromisoformat(last_news_scan) >= timedelta(hours=1)
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
    deferred = None
    # The 8 PM edition gets the next open send window once it is due.
    for trigger, lane, key, payload in sorted(jobs, key=lambda item: (
        item[3] not in EVENING_WATCH_SLOTS, item[0], item[1], item[2]
    )):
        if until := blocked_until(now if injected_time else datetime.now(timezone.utc)):
            deferred = (upcoming_editorial(payload, until) if lane == 'editorial' else
                        {'post': payload[0] if lane == 'legacy' else lane, 'trigger': until.isoformat()})
            break
        if lane == 'editorial' and payload.edition == 'price-prediction':
            from .price_prediction_board import PRICE_GRACE
            live_now = now if injected_time else datetime.now(timezone.utc)
            if live_now >= trigger + PRICE_GRACE:
                price_status['status'] = 'missed-window'
                continue
        post = payload.edition if lane == 'editorial' else payload[0] if lane == 'legacy' else key
        row = {'post_id': key, 'type': post, 'trigger': trigger.isoformat(),
               'timestamp': run_key, 'status': 'PENDING', 'attempts': 0}
        if lane == 'editorial' and payload.display_name:
            row['display_name'] = payload.display_name
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
                if payload:
                    last_news_scan = run_key
            else:
                if run_outbox(now if injected_time else datetime.now(timezone.utc),
                              target_file=payload, telegram_primary=True):
                    entry = read_state(OUTBOX_STATUS).get(payload.name, {})
                    error = entry.get('reason') or 'Outbox delivery incomplete'
                    attempts = entry.get('attempts', 0)
        except DeliveryDeferred as exc:
            deferred = {'post': post, 'trigger': exc.until.isoformat()}
            row['status'] = 'DEFERRED'
            audit[key] = row
            for item in news_rows:
                audit[item['post_id']] = item
            write_state(AUDIT, audit)
            rows.extend(news_rows)
            break
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

    upcoming = [upcoming_editorial(slot, slot_start(slot, now))
                for slot in SLOTS if slot_start(slot, now) > now
                and eligible_on(slot, now)]
    for name, (hour, minute) in SLOT_HOURS.items():
        trigger = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if trigger > now:
            upcoming.append({'post': name, 'trigger': trigger.isoformat()})
    retry_at = now + timedelta(minutes=15)
    if allowed(retry_at):
        retry_editions = {row['type'] for row in rows if row['status'] == 'RETRY'}
        upcoming.extend(upcoming_editorial(slot, retry_at) for slot in EVENING_WATCH_SLOTS
                        if slot.edition in retry_editions)
    upcoming.extend(item for item in pending if item['trigger'])
    if not upcoming:
        tomorrow = local + timedelta(days=1)
        upcoming = [upcoming_editorial(slot, slot_start(slot, tomorrow))
                    for slot in SLOTS if slot_start(slot, tomorrow) > now
                    and eligible_on(slot, tomorrow)]
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
        'posts_pending_trigger': len(pending), 'pending_triggers': pending, 'next_due': deferred or min(upcoming, key=lambda item: datetime.fromisoformat(item['trigger'])),
        'source_error': source_error,
        'price_prediction': price_status,
        'last_news_scan': last_news_scan,
        'next_telegram_at': deferred['trigger'] if deferred else None,
    }
    write_state(REPORT, result)
    print('SCHEDULED PUBLISH REPORT ' + json.dumps(result, ensure_ascii=False))
    return result


def followup_wait(report, now, started_at, cooldown=None):
    """Return seconds until another useful dispatch within this publishing day."""
    local = now.astimezone(ET)
    if not allowed(now):
        hour, minute = divmod(OPEN_MINUTE, 60)
        target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    else:
        timestamp = report.get('at')
        next_due = (report.get('next_due') or {}).get('trigger')
        if not timestamp or not next_due or datetime.fromisoformat(timestamp) < started_at:
            return 0
        target = max(datetime.fromisoformat(next_due), cooldown or now)
    delay = (target - now).total_seconds()
    if 0 < delay <= 65 * 60 and target.astimezone(ET).date() == local.date() and allowed(target):
        return int(delay) + 1
    return 0


def main():
    import os
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--followup-wait':
        now = datetime.now(timezone.utc)
        started = datetime.fromtimestamp(int(sys.argv[2]), timezone.utc)
        print(followup_wait(read_state(REPORT), now, started, blocked_until(now)))
        return 0
    snapshot = None
    press_error = False
    if os.getenv('GITHUB_EVENT_NAME') == 'schedule':
        from .matchday_press import run as press_run
        from .telegram import TelegramClient
        try:
            snapshot = retry_source(collect_snapshot)
            now = datetime.now(timezone.utc)
            if press_run(snapshot, now, read_state, write_state, TelegramClient,
                         live_clock=lambda: datetime.now(timezone.utc)):
                print('Matchday press roundup has publication priority on this pass')
                return 0
        except (RuntimeError, ValueError, OSError) as error:
            print('Matchday press check: ' + failure_reason(error))
            press_error = True
        if snapshot is not None:
            from .press_schedule import run as schedule_run
            try:
                if schedule_run(snapshot, datetime.now(timezone.utc), read_state, write_state,
                                TelegramClient, live_clock=lambda: datetime.now(timezone.utc)):
                    print('Published press conference timetable')
            except (RuntimeError, ValueError, OSError) as error:
                print('Press conference timetable check: ' + failure_reason(error))
                press_error = True
    result = run(cron=os.getenv('SCHEDULED_CRON') or None, snapshot=snapshot)
    return int(bool(press_error or result.get('source_error') or result.get('posts_failed') or
                    result.get('posts_retry_pending')))


if __name__ == '__main__':
    raise SystemExit(main())
