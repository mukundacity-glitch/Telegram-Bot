"""Stage the approved four-MID edition with official data and real media.

Uses current position-price quantiles for three premium + one value picks.
Recent three completed appearances must each reach 70 minutes; this is
evidence of minutes reliability, never a claim of guaranteed future minutes.
"""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import json
import os
from statistics import median, quantiles
import requests

from .bot import ROOT
from .fpl import collect_snapshot, upcoming_deadline, score
from .recommendations import get_history, completed_rounds
from .chatgpt_task_editions import _make_cards
from .content import Content
from .publish_checks import render_checked
from .publication_rules import five_gw_fixtures


def main():
    snapshot = collect_snapshot()
    gw = snapshot.gameweek()
    now = datetime.now(timezone.utc)
    mids = [p for p in snapshot.players if p.get('element_type') == 3]
    prices = [p['now_cost'] for p in mids if p.get('now_cost')]
    premium = quantiles(prices, n=4)[2]
    budget = median(prices)
    completed = set(completed_rounds(snapshot, 4))
    client = requests.Session()
    histories = {}
    def select(pool, quota):
        chosen = []
        for p in sorted(pool, key=score, reverse=True):
            if p.get('status') != 'a' or not snapshot.fixtures_for_gameweek(p):
                continue
            history = [h for h in get_history(p['id'], client) if h.get('round') in completed][-3:]
            if len(history) != 3 or any(int(h.get('minutes') or 0) < 70 for h in history):
                continue
            chosen.append(p); histories[p['id']] = history
            if len(chosen) == quota: return chosen
        raise RuntimeError('Insufficient four-MID candidates with verified 70+ recent minutes')
    picks = select([p for p in mids if p.get('now_cost', 0) >= premium], 3)
    picks += select([p for p in mids if p.get('now_cost', 999) <= budget and p not in picks], 1)
    cards = _make_cards(snapshot, picks, ['PREMIUM', 'PREMIUM', 'PREMIUM', 'BUDGET VALUE'])
    names = ', '.join(snapshot.name(p) for p in picks)
    caption = (f'GW{gw} midfield decisions.\n{names}: each reached 70+ minutes in their last three completed appearances.\n'
               'Compare next-GW fixtures, price and attacking form.\nMONITOR team news; prioritise secure starters.\n'
               f'#FPL #FPLVortex #GW{gw} #FPLTips')
    base = Content(kind='ported_task', title='FOUR MIDFIELDERS • THREE PREMIUM + ONE VALUE',
                   kicker='NEXT GW', cards=cards, verdict='MONITOR TEAM NEWS BEFORE BUYING',
                   caption=caption, data_at=snapshot.fetched_at.isoformat(), gw=gw,
                   footer='Verified official FPL snapshot; forecasts are not guaranteed')
    pages = []
    for index in range(2):
        file = ROOT/'outbox/assets'/f'gw{gw}-four-midfielders-{index+1}.png'
        render_checked(replace(base, cards=cards[index*2:index*2+2]), snapshot, file)
        pages.append(str(file.relative_to(ROOT)))
    facts = {'players': [{k: p.get(k) for k in (
        'id', 'code', 'team', 'now_cost', 'status', 'selected_by_percent', 'minutes',
        'total_points', 'form', 'expected_goals', 'expected_assists')} | {
        'recent': [{k: h.get(k) for k in ('fixture', 'round', 'minutes', 'total_points')}
                   for h in histories[p['id']]],
        'fixtures': list(five_gw_fixtures(snapshot, p))} for p in picks]}
    record = {'task': 'task2', 'edition': 'four-midfielders', 'season': '2026-27',
              'gameweek': gw, 'title': base.title, 'generated_at': now.isoformat(),
              'publish_at': now.isoformat(), 'deadline': upcoming_deadline(snapshot).isoformat(),
              'pre_deadline': True, 'caption': caption, 'images': pages, 'facts': facts,
              'qa_passed': False, 'sources': [
                  'https://fantasy.premierleague.com/api/bootstrap-static/',
                  'https://fantasy.premierleague.com/api/fixtures/'] + [
                  f"https://fantasy.premierleague.com/api/element-summary/{p['id']}/" for p in picks]}
    path = ROOT/'outbox'/f'gw{gw}-four-midfielders.json'
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({'record': str(path), 'players': names, 'pages': pages, 'qa_passed': False}))


if __name__ == '__main__':
    main()
