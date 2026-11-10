"""FPL VORTEX compact automated publishing heartbeat.

GitHub's schedule events are best-effort. Every trigger uses CURRENT New York
time to recover overdue approved slots; an old cron label cannot force a stale
post. Independent channels have durable, per-message delivery receipts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .autonomous_runner import run as run_editions, STATE_FILE
from .autonomous_schedule import ET, due_specials
from .bot import STATE, read_state, write_state, run as run_legacy
from .fpl import collect_snapshot
from .outbox import RECEIPTS, run as run_outbox
from .publishing_window import allowed
from .schedule import SLOT_HOURS, SLOT_CRONS
from .unified_runner import run as run_news

REPORT = STATE / 'scheduled_dispatch_status.json'
LEGACY = STATE / 'scheduled_legacy_attempts.json'
FIRST_RUN_NEWS_MINUTE = 43


def due_legacy(now, ledger, checks):
    """Find one original approved slot already due, without replaying a receipt."""
    local = now.astimezone(ET)
    today = str(local.date())
    for name, (hour, minute) in sorted(SLOT_HOURS.items(), key=lambda row: row[1]):
        if (local.hour, local.minute) < (hour, minute):
            continue
        key = f'{today}:{name}'
        if checks.get(key, {}).get('status') in ('checked', 'delivered'):
            continue
        if checks.get(key, {}).get('attempts', 0) >= 2:
            continue
        related = [v for k,v in ledger.items() if k == key or k.startswith(key + ':GW')]
        if any(v.get('delivered') and v.get('discord_delivered') for v in related):
            continue
        scheduled = next((cron for cron,slot in SLOT_CRONS.items() if slot == name), None)
        if scheduled:
            return key, name, scheduled
    return None


def original_legacy_once(now):
    """Preserve the old scheduled editions while limiting retries and volume."""
    checks = read_state(LEGACY)
    ledger = read_state(STATE / 'deliveries.json')
    due = due_legacy(now, ledger, checks)
    if due is None:
        return {'status': 'none-due', 'sent': 0}
    key, name, cron = due
    result = run_legacy('auto', cron)
    latest = read_state(STATE / 'deliveries.json')
    related = [v for k,v in latest.items() if k == key or k.startswith(key + ':GW')]
    dual = any(v.get('delivered') and v.get('discord_delivered') for v in related)
    partial = any(v.get('delivered') != v.get('discord_delivered') for v in related)
    current = checks.get(key, {})
    status = 'delivered' if dual else 'partial' if partial else 'checked' if result == 0 else 'held'
    checks[key] = {'status': status, 'attempts': current.get('attempts', 0) + 1,
                   'at': now.isoformat()}
    write_state(LEGACY, checks)
    return {'slot': name, 'status': status, 'sent': int(dual),
            'exit_code': result}


def run(now=None, cron=None):
    now = now or datetime.now(timezone.utc)
    if not allowed(now):
        result = {'status': 'deferred-outside-window', 'at': now.isoformat(),
                  'new_posts': 0, 'window': '05:30–22:00 America/New_York'}
        print(json.dumps(result, sort_keys=True))
        return result

    # One official snapshot feeds editorial and news. It is never invented
    # from an outdated outbox graphic or from a previous deadline.
    snapshot = collect_snapshot()
    daily = run_editions(now=now, snapshot=snapshot, due=True, catchup_limit=20)
    daily_rows = daily.get('editions') or []
    posted = daily.get('confirmed_edition_deliveries', 0)
    failures = [r['edition'] for r in daily_rows if r.get('status') == 'queued-or-partial']
    held = [r['edition'] for r in daily_rows if r.get('status') == 'held']

    special = {'status': 'no-special-due', 'confirmed_edition_deliveries': 0}
    try:
        if due_specials(snapshot, now, read_state(STATE_FILE)):
            special = run_editions(now=now, snapshot=snapshot,
                                   cron=f'35 {now.astimezone(ET).hour} * * *')
            posted += special.get('confirmed_edition_deliveries', 0)
            for row in special.get('editions', []):
                if row.get('status') == 'queued-or-partial':
                    failures.append(row['edition'])
                elif row.get('status') == 'held':
                    held.append(row['edition'])
    except (RuntimeError, ValueError, OSError) as exc:
        failures.append('special:' + type(exc).__name__)

    # Original news stream checks once per hour (the :43 cron) and on the
    # explicit repair probe. It can publish a new verified headline, never
    # an unchanged repeated report.
    news = {'sent': 0, 'status': 'not-this-tick'}
    if cron is None or cron.startswith('43 '):
        try:
            news = run_news(snapshot=snapshot, now=now, max_posts=1)
            posted += news.get('sent', 0)
        except (RuntimeError, ValueError, OSError) as exc:
            failures.append('news:' + type(exc).__name__)
            news = {'sent': 0, 'status': 'held'}

    legacy = {'status': 'not-this-tick', 'sent': 0}
    try:
        legacy = original_legacy_once(now)
        posted += legacy.get('sent', 0)
        if legacy.get('status') in ('partial', 'held'):
            held.append('legacy:' + str(legacy.get('slot')))
    except (RuntimeError, ValueError, OSError) as exc:
        held.append('legacy:' + type(exc).__name__)

    before = read_state(RECEIPTS)
    try:
        outbox_exit = run_outbox(now)
    except (RuntimeError, ValueError, OSError) as exc:
        outbox_exit = 1
        failures.append('outbox:' + type(exc).__name__)
    after = read_state(RECEIPTS)
    def confirmed(ledger, key):
        v = ledger.get(key, {})
        return bool(v.get('delivered') and v.get('discord_delivered'))
    outbox_new = sum(confirmed(after, k) and not confirmed(before, k) for k in after)
    posted += outbox_new
    if outbox_exit:
        failures.append('outbox-partial')

    result = {
        'status': 'published' if posted else 'held' if (failures or held)
                  else 'no-new-verified-content',
        'at': now.isoformat(), 'eastern_at': now.astimezone(ET).isoformat(),
        'new_posts': posted, 'daily': daily, 'special': special,
        'news': news, 'legacy': legacy, 'outbox_new': outbox_new,
        'held': held, 'failures': failures,
        'scheduled_cron': cron or 'repair-probe'
    }
    write_state(REPORT, result)
    print('SCHEDULED PUBLISH REPORT ' + json.dumps(result, ensure_ascii=False, default=str))
    if posted:
        print(f'::notice::AUTO PUBLISHED {posted} newly confirmed post(s) to Telegram and Discord')
    elif failures or held:
        print('::error::Auto-post due but held. Inspect report, evidence checks and delivery receipts.')
    else:
        print('::notice::AUTO CHECK COMPLETE: no NEW verified content; nothing repeated')
    return result


def main():
    import os
    try:
        result = run(cron=os.getenv('SCHEDULED_CRON') or None)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f'::error::Automatic FPL publisher could not run: {type(exc).__name__}')
        return 1
    return 1 if result.get('failures') or (result.get('held') and not result.get('new_posts')) else 0


if __name__ == '__main__':
    raise SystemExit(main())
