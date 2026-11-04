"""Deadline decisions from current official evidence; no fixed GW/player names."""
from datetime import datetime
from textwrap import shorten
from math import isfinite
from zoneinfo import ZoneInfo

from .autonomous_content import Plan
from .autonomous_schedule import ET
from .editorial_inputs import RequiredInput
from .fpl import upcoming_deadline

UK = ZoneInfo('Europe/London')


def clock(value, zone):
    local = value.astimezone(zone)
    return local.strftime('%a, %b %d, %I:%M %p %Z').replace(' 0', ' ')


def fixture_text(snapshot, player):
    return ' / '.join(f'{opp} ({venue})' for opp, venue, _, _ in snapshot.fixtures_for_gameweek(player))


def risk_text(snapshot, player, limit=65):
    chance = player.get('chance_of_playing_next_round')
    chance_text = f'{chance}% chance' if type(chance) is int and 0 <= chance <= 100 else 'chance unconfirmed'
    note = shorten(str(player.get('news') or 'Return not confirmed by official FPL.'), width=limit, placeholder='…')
    return f"{snapshot.name(player)} ({snapshot.team(player)}): {chance_text}; {note}"


def verified_selection_fields(snapshot, player):
    try:
        ownership = float(player["selected_by_percent"])
        return (type(player["now_cost"]) is int and player["now_cost"] > 0
                and isfinite(ownership) and 0 <= ownership <= 100
                and type(player.get("code")) is int and player["code"] > 0
                and player.get("team") in snapshot.teams and snapshot.name(player) != "Unknown")
    except (KeyError, TypeError, ValueError):
        return False


def build_deadline_watch(slot, snapshot, now, evidence):
    deadline = upcoming_deadline(snapshot)
    if deadline is None or deadline <= now:
        raise RequiredInput('Future official FPL deadline required for deadline watch')
    qualified = evidence.qualified(30)
    eligible = [p for p in qualified if p.get('status') == 'a'
                and p.get('chance_of_playing_next_round') in (None, 100)
                and p.get('element_type') in (2, 3, 4)
                and verified_selection_fields(snapshot,p)
                and snapshot.fixtures_for_gameweek(p)]
    attackers = [p for p in eligible if p['element_type'] in (3, 4)]
    if not attackers:
        raise RequiredInput('No verified available reliable-minute captain candidate')
    main = max(attackers, key=lambda p: (float(p['selected_by_percent']), evidence.rank(p)))
    alternatives = sorted([p for p in eligible if p['id'] != main['id']
                           and float(p['selected_by_percent']) < float(main['selected_by_percent'])],
                          key=evidence.rank, reverse=True)
    if len(alternatives) < 2:
        raise RequiredInput('Two available lower-owned captain alternatives required')
    # A defender is an optional contrast, never a fixed named selection.
    defenders = []
    for p in alternatives:
        if p['element_type'] != 2:
            continue
        try:
            xgi = float(p['expected_goals']) + float(p['expected_assists'])
            minutes = int(p['minutes'])
            if isfinite(xgi) and xgi >= 0 and minutes > 0:
                defenders.append((xgi / minutes * 90, evidence.rank(p), p))
        except (KeyError, TypeError, ValueError):
            continue
    # Defender contrast prioritises observed attacking involvement, so clean
    # sheet points alone cannot make a defender the captain alternative.
    defender = max(defenders,key=lambda item:item[:2])[2] if defenders else None
    attack = next((p for p in alternatives if p['element_type'] in (3, 4)), None)
    chosen = [defender, attack] if defender and attack else alternatives[:2]
    players = [main] + chosen
    risks = sorted([p for p in snapshot.players if p.get('status') in ('d', 'i', 's', 'u')
                    and p.get('code') and p.get('team') in snapshot.teams
                    and snapshot.fixtures_for_gameweek(p)],
                   key=lambda p: (float(p.get('selected_by_percent') or 0), int(p.get('transfers_out_event') or 0)),
                   reverse=True)[:3]
    labels = ['MAINSTREAM CAPTAIN', 'DIFFERENTIAL 1', 'DIFFERENTIAL 2']
    if risks:
        players.append(risks[0]); labels.append('INJURY / STATUS WATCH')
    else:
        watch = next((p for p in alternatives if p not in chosen), None)
        if watch:
            players.append(watch); labels.append('TEAM NEWS WATCH')
    gw = snapshot.gameweek()
    title = f'GW{gw} DEADLINE WATCH • CAPTAIN DECISION'
    options = '\n'.join(f"{snapshot.name(p)} | {snapshot.price(p)} | {p['selected_by_percent']}% owned | {fixture_text(snapshot,p)}" for p in players[:3])
    plan = (f"PLAN: Wait for verified team news. Mainstream: {snapshot.name(main)}. "
            f"Differentials: {snapshot.name(chosen[0])} / {snapshot.name(chosen[1])}. Avoid flagged captains. Forecast picks, not guaranteed returns.")
    for limit in (65, 45, 25, 15):
        risk_lines = '\n'.join(risk_text(snapshot,p,limit) for p in risks) if risks else 'No official flags among the featured captain options.'
        caption = (f"⏰ GW{gw} DEADLINE WATCH | {clock(now,ET)}\n"
                   f"Deadline: {clock(deadline,ET)} | {clock(deadline,UK)}\n"
                   f"BIG DECISION: {snapshot.name(main)} or a differential?\n"
                   f"OPTIONS\n{options}\nINJURY RISKS\n{risk_lines}\n{plan}\n"
                   f"#FPL #FPLVortex #GW{gw} #FPLTips")
        if len(caption) <= 1024:
            break
    else:
        raise RequiredInput('Verified deadline-watch caption cannot fit the shared platform limit')
    return Plan(slot.task,slot.edition,title,caption,gw,players,labels,kind='deadline',extra={
        'deadline':deadline.isoformat(), 'first_kickoff':min((f['kickoff_time'] for f in snapshot.fixtures
            if f.get('event')==gw and f.get('kickoff_time')), default=None),
        'generated_at':now.astimezone(ET).isoformat(), 'retrieved_at':snapshot.fetched_at.astimezone(ET).isoformat(),
        'risks':[{k:p.get(k) for k in ('id','team','status','news','chance_of_playing_next_round','transfers_out_event')} for p in risks],
        'recent':{str(p['id']):evidence.recent(p) for p in players},
        'method':'Mainstream by selected-by ownership; alternatives by observed recent form and official fixtures. Ownership is not EO.'})
