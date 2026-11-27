"""Process the due Telegram queue in trigger order on each existing heartbeat."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from .autonomous_content import Evidence
from .autonomous_runner import run as run_editions, STATE_FILE
from .autonomous_schedule import (
    ET, SLOTS, catchup_slots, eligible_on, publication_key, retryable, season_id, slot_start,
    special_triggers, SERIES, EVENING_WATCH_SLOTS, weekly_analysis_slot, schedule_catalogue,
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


def record_price_ownership(snapshot, editorial):
    """Keep spaced observations and return a baseline old enough for comparison."""
    from .price_prediction_board import ownership_snapshot, observe_settlement

    if observe_settlement(snapshot, editorial):
        write_state(STATE_FILE, editorial)
    latest = editorial.get('_price_ownership') or {}
    try:
        elapsed = snapshot.fetched_at - datetime.fromisoformat(latest['at'])
    except (KeyError, TypeError, ValueError):
        elapsed = None
    if elapsed is not None and elapsed < timedelta(minutes=5):
        return editorial.get('_price_ownership_previous', {})

    observation = ownership_snapshot(snapshot)
    if not any(value is not None for value in observation['players'].values()):
        return latest
    editorial['_price_ownership_previous'] = latest
    editorial['_price_ownership'] = observation
    write_state(STATE_FILE, editorial)
    return latest


def observe_during_deferral(snapshot):
    if getattr(snapshot, 'game_config', None) is not None:
        record_price_ownership(snapshot, read_state(STATE_FILE))


def exclusive_cutover_jobs(jobs, now, research_due=False):
    """A guarded publication must own its run; do not displace other due jobs.

    Idle rotation polling is not a publication. Preserve every unrelated real
    job and hold guarded editions if another job actually competes for this run.
    """
    from .unified_runner import rotation_due
    def guarded(job):
        return ((job[1] == 'editorial' and job[3].edition in {
            'price-prediction', 'player-radar-comparison', 'saturday-fdr-grid',
            'most-transferred-in', 'team-decision-desk', 'weekly-position-watch', 'post-gameweek-shot-origins'})
            or (job[1] == 'news' and rotation_due(now)))
    if research_due or any(guarded(job) for job in jobs):
        jobs = [job for job in jobs if job[1] != 'news' or rotation_due(now)]
    if len(jobs) > 1:
        return [job for job in jobs if not guarded(job)]
    return jobs


def run(now=None, cron=None, snapshot=None):
    injected_time = now is not None
    now = now or datetime.now(timezone.utc)
    schedule_catalogue()
    from .daily_cutover import slots as daily_slots, research_window, prepare as prepare_daily
    research_slots = [slot for slot in daily_slots(now) if research_window(slot, now)]
    if research_slots:
        from .outbox import QUEUE
        try:
            snapshot = snapshot or retry_source(collect_snapshot)
            state = read_state(STATE_FILE)
            if getattr(snapshot, 'game_config', None) is not None:
                record_price_ownership(snapshot, state)
            if len(research_slots) == 1 and prepare_daily(research_slots[0], snapshot, now, state, QUEUE,
                    read_state(STATE / 'cutover_featured_players.json'),
                    (lambda: now) if injected_time else (lambda: datetime.now(timezone.utc))):
                write_state(STATE_FILE, state)
                return {'status': 'research-verified', 'new_posts': 0, 'edition': research_slots[0].edition}
        except (RuntimeError, ValueError, KeyError, TypeError, OSError):
            pass
        return {'status': 'no-new-verified-content', 'new_posts': 0}
    if not allowed(now):
        # Slot 7 research can fall overnight. Existing press/legacy priority
        # in main runs before this branch; no publication is allowed here.
        from .position_watch import RELEASE_VERIFIED, prepare as prepare_watch
        if RELEASE_VERIFIED and snapshot is not None:
            state = read_state(STATE_FILE)
            if not list(queued_files(now)) and not read_state(NEWS_PENDING):
                try:
                    if prepare_watch(snapshot,now,state,Evidence(snapshot,now),
                                     (lambda:now) if injected_time else (lambda:datetime.now(timezone.utc))):
                        write_state(STATE_FILE,state)
                        return {'status':'research-verified','new_posts':0,'edition':'weekly-position-watch'}
                except (RuntimeError,ValueError,KeyError,TypeError,OSError):
                    pass
        # Earlier price check is a read-only branch on the existing heartbeat.
        # Never publish outside the approved window.
        if snapshot is not None and getattr(snapshot, 'game_config', None) is not None:
            from .price_prediction_board import opportunity, RESEARCH_KEY
            from .editorial_inputs import RequiredInput
            state = read_state(STATE_FILE)
            record_price_ownership(snapshot, state)
            try:
                _, info = opportunity(snapshot, now, state)
                if info.get('status') == 'research-verified':
                    write_state(STATE_FILE, state)
                    return {'status': 'research-verified', 'new_posts': 0, 'edition': 'price-prediction'}
            except RequiredInput:
                pass
        result = {'status': 'deferred-outside-window', 'at': now.isoformat(),
                  'new_posts': 0, 'window': WINDOW_LABEL, 'queue_enumerated': False}
        print(json.dumps(result, sort_keys=True))
        return result

    previous_report = read_state(REPORT) if spacing_enabled() else {}
    from .autonomous_schedule import radar_research_due, fdr_phase
    from .unified_runner import rotation_research_due
    dedicated_research = radar_research_due(now) or rotation_research_due(now) or fdr_phase(now) == 'research'
    if (until := blocked_until(now)) and not dedicated_research:
        observe_during_deferral(snapshot)
        result = {**previous_report, 'status': 'deferred-telegram-spacing',
                  'at': now.isoformat(), 'eastern_at': now.astimezone(ET).isoformat(),
                  'scheduled_cron': cron, 'next_telegram_at': until.isoformat(),
                  'new_posts': 0, 'telegram_messages_sent': 0}
        for field in ('posts_generated', 'posts_retried', 'posts_failed', 'posts_retry_pending'):
            result[field] = 0
        result.update(queue_enumerated=False, posts_due=None, posts_processed=0,
                      queue_items_unprocessed=None,
                      next_due={'post': 'due-queue', 'trigger': until.isoformat()})
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
    candidate_price_research = None
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
            from .price_prediction_board import opportunity
            from .editorial_inputs import RequiredInput
            evidence.price_previous = record_price_ownership(snapshot, editorial)
            try:
                from .price_prediction_board import RESEARCH_KEY
                candidate_state = dict(editorial)
                price_slot, price_status = opportunity(snapshot, now, candidate_state)
                if price_status.get('status') == 'research-verified':
                    candidate_price_research = candidate_state.get(RESEARCH_KEY)
                if price_slot is not None:
                    evidence.price_research = price_status['research']
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
        from .autonomous_schedule import finalized_radar_slot
        radar = finalized_radar_slot(snapshot, now, editorial)
        from .autonomous_schedule import radar_research_valid
        if radar is not None and radar_research_valid(editorial, radar, snapshot, now):
            jobs.append((slot_start(radar, now), 'editorial',
                         publication_key(radar, now, gw, season), radar))
        from .daily_cutover import eligible as daily_eligible, day_key, RESEARCH_STATE, claimed_ids
        from .outbox import QUEUE
        for daily in daily_slots(now):
            if daily_eligible(daily, snapshot, now, editorial):
                evidence.daily_research = editorial[RESEARCH_STATE][daily.edition]
                try:
                    evidence.daily_excluded = claimed_ids(snapshot, now, QUEUE, read_state(STATE / 'cutover_featured_players.json'))
                except (RuntimeError, ValueError, KeyError, TypeError, OSError):
                    continue  # Unsafe historical state must not block unrelated slots.
                jobs.append((slot_start(daily, now), 'editorial', day_key(daily, now), daily))
        from .position_watch import eligible as position_eligible, STATE_KEY as POSITION_STATE
        position = position_eligible(snapshot,now,editorial)
        if position is not None:
            evidence.position_watch_research = editorial[POSITION_STATE]
            jobs.append((datetime.fromisoformat(editorial[POSITION_STATE]['post_at']),
                         'editorial', publication_key(position,now,gw,season),position))
        from .post_gameweek_zones import eligible as zones_eligible, STATE_KEY as ZONES_STATE
        zones = zones_eligible(snapshot,now,editorial)
        if zones is not None:
            evidence.shot_origins_research = editorial[ZONES_STATE]
            jobs.append((datetime.fromisoformat(editorial[ZONES_STATE]['post_at']),
                         'editorial',publication_key(zones,now,gw,season),zones))
        series = weekly_analysis_slot(snapshot, now, editorial)
        if series is not None:
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
        from .unified_runner import rotation_due
        if check_news or news_pending or rotation_due(now):
            check_news = check_news or rotation_due(now)
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
    # Research occupies its own heartbeat, never a competing publication run.
    from .autonomous_schedule import radar_research_due, fdr_phase
    from .unified_runner import rotation_research_due
    research_window = (candidate_price_research is not None or radar_research_due(now)
                       or rotation_research_due(now) or fdr_phase(now) == 'research')
    original_jobs = jobs
    jobs = exclusive_cutover_jobs(jobs, now, research_window)
    if price_status.get('status') == 'due' and not any(
            lane == 'editorial' and payload.edition == 'price-prediction' for _, lane, _, payload in jobs):
        price_status['status'] = 'skipped-schedule-conflict'
    # Do not begin research on a run that had another real publication queued,
    # even when the exclusivity guard removed it.
    from .unified_runner import rotation_due
    real_jobs = [job for job in original_jobs if job[1] != 'news' or rotation_due(now)]
    research_allowed = snapshot is not None and not real_jobs
    # The cooldown prevents a second send, not an isolated read-only check.
    if dedicated_research and blocked_until(now):
        jobs = []
    if candidate_price_research is not None:
        if research_allowed:
            from .price_prediction_board import RESEARCH_KEY
            editorial[RESEARCH_KEY] = candidate_price_research
            write_state(STATE_FILE, editorial)
        else:
            price_status['status'] = 'skipped-schedule-conflict'
    if research_allowed and candidate_price_research is None:
        from .autonomous_schedule import prepare_radar_research
        from .unified_runner import prepare_rotation_research
        clock = (lambda: now) if injected_time else (lambda: datetime.now(timezone.utc))
        try:
            if prepare_radar_research(snapshot, now, editorial, evidence, clock):
                write_state(STATE_FILE, editorial)
            prepare_rotation_research(snapshot, now, clock=clock)
            from .position_watch import prepare as prepare_watch
            if prepare_watch(snapshot,now,editorial,evidence,clock):
                write_state(STATE_FILE,editorial)
            elif not dedicated_research:
                from .post_gameweek_zones import prepare as prepare_zones
                if prepare_zones(snapshot,now,editorial,evidence,clock):
                    write_state(STATE_FILE,editorial)
        except (RuntimeError, ValueError, KeyError, TypeError, OSError):
            pass
    # FDR is a strict weekly phase, not a generic late catch-up.
    from .autonomous_schedule import SATURDAY_FDR_GRID, FDR_RESEARCH_STATE, fdr_phase, fdr_research_valid
    phase = fdr_phase(now)
    if research_allowed and candidate_price_research is None and phase == 'research':
        from .evening_intelligence import build_evening
        try:
            build_evening(SATURDAY_FDR_GRID, snapshot, now, evidence)
            editorial[FDR_RESEARCH_STATE] = {
                'date': local.date().isoformat(), 'gw': snapshot.gameweek(),
                'season': season_id(snapshot, now), 'verified': True,
                'fetched_at': snapshot.fetched_at.isoformat(),
                'checked_at': (now if injected_time else datetime.now(timezone.utc)).isoformat(),
            }
            write_state(STATE_FILE, editorial)
        except (RuntimeError, ValueError, KeyError, TypeError, OSError):
            pass  # No verified research means no post.
    if phase == 'post':
        other_due = any(lane != 'editorial' or payload != SATURDAY_FDR_GRID
                        for _, lane, _, payload in jobs)
        if other_due or snapshot is None or not fdr_research_valid(editorial, snapshot, now):
            jobs = [job for job in jobs if job[1] != 'editorial' or job[3] != SATURDAY_FDR_GRID]
    rows = []
    processed_jobs = 0
    deferred = None
    # The 8 PM edition gets the next open send window once it is due.
    for trigger, lane, key, payload in sorted(jobs, key=lambda item: (
        item[3] not in EVENING_WATCH_SLOTS, item[0], item[1], item[2]
    )):
        if until := blocked_until(now if injected_time else datetime.now(timezone.utc)):
            deferred = (upcoming_editorial(payload, until) if lane == 'editorial' else
                        {'post': payload[0] if lane == 'legacy' else lane, 'trigger': until.isoformat()})
            break
        live_now = now if injected_time else datetime.now(timezone.utc)
        if lane == 'editorial' and payload.edition in ('most-transferred-in', 'team-decision-desk'):
            from .daily_cutover import eligible as daily_eligible
            if not daily_eligible(payload, snapshot, live_now, read_state(STATE_FILE)):
                continue
        if lane == 'editorial' and payload.edition == 'post-gameweek-shot-origins':
            from .post_gameweek_zones import eligible as zones_eligible
            if zones_eligible(snapshot,live_now,read_state(STATE_FILE)) != payload:
                continue
        if lane == 'editorial' and payload.edition == 'weekly-position-watch':
            from .position_watch import eligible as position_eligible
            if position_eligible(snapshot,live_now,read_state(STATE_FILE)) != payload:
                continue
        if lane == 'editorial' and payload.edition == 'player-radar-comparison':
            from .autonomous_schedule import radar_post_due
            if not radar_post_due(live_now):
                continue
        if lane == 'editorial' and payload.edition == 'saturday-fdr-grid' and fdr_phase(live_now) != 'post':
            continue
        if lane == 'news' and rotation_due(now) and not rotation_due(live_now):
            continue
        if lane == 'editorial' and payload.edition == 'price-prediction':
            from .price_prediction_board import PRICE_GRACE
            live_now = now if injected_time else datetime.now(timezone.utc)
            if live_now >= trigger + PRICE_GRACE:
                price_status['status'] = 'missed-window'
                continue
        processed_jobs += 1
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
                         audit_rows=news_rows, live_clock=(lambda: now) if injected_time else (lambda: datetime.now(timezone.utc)))
                if payload:
                    last_news_scan = run_key
            else:
                if run_outbox(now if injected_time else datetime.now(timezone.utc),
                              target_file=payload, telegram_primary=True):
                    entry = read_state(OUTBOX_STATUS).get(payload.name, {})
                    error = entry.get('reason') or 'Outbox delivery incomplete'
                    attempts = entry.get('attempts', 0)
        except DeliveryDeferred as exc:
            processed_jobs -= 1
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
                for slot in (*SLOTS, *daily_slots(now)) if slot_start(slot, now) > now
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
        'queue_enumerated': True, 'posts_due': len(jobs), 'posts_processed': len(rows),
        'queue_items_unprocessed': len(jobs) - processed_jobs,
        'posts_generated': sum(row['generated'] for row in rows),
        'new_posts': posted, 'telegram_messages_sent': messages, 'posts_retried': sum(row['attempts'] > 1 for row in rows),
        'posts_failed': counts['FAILED'], 'posts_retry_pending': counts['RETRY'],
        'posts_pending_trigger': len(pending), 'pending_triggers': pending, 'next_due': deferred or min(upcoming, key=lambda item: datetime.fromisoformat(item['trigger']), default=None),
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
    if os.getenv('GITHUB_EVENT_NAME') in ('schedule', 'push', 'workflow_dispatch'):
        from .matchday_press import run as press_run
        from .telegram import TelegramClient
        from .syndication import DiscordWebhookClient
        try:
            snapshot = retry_source(collect_snapshot)
            now = datetime.now(timezone.utc)
            if press_run(snapshot, now, read_state, write_state, TelegramClient,
                         live_clock=lambda: datetime.now(timezone.utc),
                         discord_factory=DiscordWebhookClient if os.getenv('DISCORD_WEBHOOK_URL') else None):
                try:
                    observe_during_deferral(snapshot)
                except (RuntimeError, ValueError, OSError) as error:
                    print('Price ownership research: ' + failure_reason(error))
                    return 1
                print('Matchday press roundup has publication priority on this pass')
                return 0
            # Existing weekly research gets its own overnight heartbeat;
            # the publication lane is not executed on the same pass.
            from . import weekly_position_watch, weekly_wildcard_vulnerability, monday_intelligence
            for module in (weekly_position_watch, weekly_wildcard_vulnerability, monday_intelligence):
                now = datetime.now(timezone.utc)
                if module.research_due(now):
                    record_price_ownership(snapshot, read_state(STATE_FILE))
                    module.prepare_research(snapshot, now, clock=lambda: datetime.now(timezone.utc))
                    return 0
        except (RuntimeError, ValueError, OSError) as error:
            print('Matchday press check: ' + failure_reason(error))
            press_error = True
    result = run(cron=os.getenv('SCHEDULED_CRON') or None, snapshot=snapshot)
    return int(bool(press_error or result.get('source_error') or result.get('posts_failed') or
                    result.get('posts_retry_pending')))


if __name__ == '__main__':
    raise SystemExit(main())
