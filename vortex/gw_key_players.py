"""One original VORTEX pre-deadline key-player edition per official event."""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
import requests
from .editorial_inputs import RequiredInput
from .low_owned_six import number

INDEX = 'https://www.fantasyfootballfix.com/blog-index/?category=Key%20Players'
EDITION = 'gw-key-players'

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href = None
        self.parts = []
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href = dict(attrs).get('href')
            self.parts = []
    def handle_data(self, data):
        if self.href:
            self.parts.append(data)
    def handle_endtag(self, tag):
        if tag == 'a' and self.href:
            self.links.append((self.href, ' '.join(self.parts)))
            self.href = None

def discover_reference(html, gw):
    """Match event and editorial intent, not an exact headline or fixed URL."""
    parser = Links()
    parser.feed(html)
    event = re.compile(r'\b(?:game\s*week|gw)[\s_-]*(\d{1,2})\b', re.I)
    candidates = []
    for href, label in parser.links:
        url = urljoin(INDEX, href)
        p = urlsplit(url)
        if p.scheme != 'https' or p.hostname != 'www.fantasyfootballfix.com':
            continue
        if not p.path.startswith('/blog-index/') or p.path == '/blog-index/':
            continue
        first = event.search(label) or event.search(p.path.replace('-', ' '))
        if not first or int(first.group(1)) != gw:
            continue
        phrase = (label + ' ' + p.path.replace('-', ' ')).lower()
        if not re.search(r'\b(?:five|5)\b', phrase):
            continue
        if not re.search(r'\b(?:picks|players|targets)\b', phrase):
            continue
        if not re.search(r'\b(?:best|top|key|essential|must|premium|budget)\b', phrase):
            continue
        if re.search(r'\b(?:differentials|captaincy|goalkeepers only)\b', phrase):
            continue
        score = int('key players' in phrase) + int('premium' in phrase) + int('budget' in phrase)
        candidates.append((score, p._replace(query='', fragment='').geturl()))
    return max(candidates, default=(0, None))[1]

def reference(session, gw):
    # Editorial discovery only; no login, no third-party article data ingestion.
    # Never block independent publication when the public index is unavailable.
    if not callable(getattr(session, 'get', None)):
        return None
    try:
        response = session.get(INDEX, timeout=8, allow_redirects=False)
        if response.status_code == 200 and len(response.content) <= 2_000_000:
            return discover_reference(response.text, gw)
    except (requests.RequestException, ValueError):
        pass
    return None

def select(snapshot):
    gw = snapshot.gameweek()
    if type(gw) is not int or not 1 <= gw <= 38 or [e.get('id') for e in snapshot.events if e.get('is_next')] != [gw]:
        raise RequiredInput('Official next-event forecast does not match upcoming gameweek')
    groups = [[], [], []]
    for p in snapshot.players:
        forecast = number(p.get('ep_next'))
        cost = p.get('now_cost')
        pos = p.get('element_type')
        if (forecast is None or forecast <= 0 or type(cost) is not int or cost <= 0
            or p.get('status') != 'a' or p.get('chance_of_playing_next_round') not in (None, 100)
            or pos not in (1, 2, 3, 4) or not snapshot.photo_code(p) or not snapshot.team_code(p)):
            continue
        fixtures = snapshot.fixtures_for_gameweek(p)
        if not fixtures or any(f[2] not in (1, 2, 3, 4, 5) for f in fixtures):
            continue
        fdr = sum(f[2] for f in fixtures)/len(fixtures)
        group = 2 if pos in (1, 2) else 0 if cost >= 75 else 1
        groups[group].append((-forecast, fdr, -(number(p.get('minutes')) or 0), p['id'], p))
    selected = []
    for group, quota in zip(groups, (2, 2, 1)):
        if len(group) < quota:
            raise RequiredInput('Insufficient available players with official forecasts for all three tiers')
        selected.extend(row[-1] for row in sorted(group, key=lambda row: row[:4])[:quota])
    return selected

def build_key_players(slot, snapshot, now, evidence):
    from .autonomous_content import Plan
    gw = snapshot.gameweek()
    players = select(snapshot)
    labels = ['PREMIUM ATTACKER']*2 + ['BUDGET ATTACKER']*2 + ['DEFENSIVE PICK']
    details = {}
    def aggregate(rows, key):
        values = [number(row.get(key)) for row in rows]
        return sum(values) if values and all(v is not None for v in values) else None
    for p in players:
        recent = evidence.recent(p)
        details[str(p['id'])] = {
            'forecast': number(p['ep_next']), 'recent_points': aggregate(recent, 'total_points'),
            'recent_minutes': aggregate(recent, 'minutes'), 'matches': len(recent),
            'xg': number(p.get('expected_goals')), 'xa': number(p.get('expected_assists')),
            'goals': number(p.get('goals_scored')), 'assists': number(p.get('assists')),
            'clean_sheets': number(p.get('clean_sheets')), 'saves': number(p.get('saves')),
            'ownership': number(p.get('selected_by_percent')), 'points': number(p.get('total_points')),
            'form': number(p.get('form')), 'minutes': number(p.get('minutes')),
            'transfers_in': number(p.get('transfers_in_event')),
            'transfers_out': number(p.get('transfers_out_event')),
            'fixtures': snapshot.fixtures_for_gameweek(p),
        }
    # Record a link for internal review only. No Fix selections or figures are used.
    ref = reference(evidence.session, gw)
    names = [snapshot.name(p) for p in players]
    title = f'GW{gw} | FIVE FPL PICKS'
    copy = (f'{title}\nPremium: {names[0]}, {names[1]}.\n'
            f'Budget: {names[2]}, {names[3]}; defensive pick: {names[4]}.\n'
            'Ranked by official next-GW forecast; MONITOR minutes and team news before deadline.\n'
            f'#FPL #GW{gw} #FPLTips #FPLVORTEX')
    return Plan(slot.task, slot.edition, title, copy, gw, players, labels, 'gw_key_players',
                {'details': details, 'editorial_reference': ref, 'forecast_source': 'official FPL ep_next'})

def render_key_players(plan, snapshot, output, session):
    from PIL import Image, ImageDraw
    from .autonomous_render import _base, _save
    from .comparison_board import contain, text, WHITE, CYAN
    from .minimal_theme import social_footer
    from .publication_rules import required_footer_handles
    from .matchup import _image_from_url, _media
    if len(plan.players) != 5 or len({p['id'] for p in plan.players}) != 5 or plan.gw != snapshot.gameweek():
        raise RequiredInput('Five unique players for the official upcoming gameweek required')
    canvas = _base(plan.title, plan.gw, 'TWO PREMIUM  /  TWO BUDGET  /  ONE DEFENSIVE PICK')
    cache = {}
    def display(v, digits=0):
        return '—' if v is None else f'{v:.{digits}f}'
    for i, p in enumerate(plan.players):
        x = 22 + i*502 if i < 3 else 273 + (i-3)*502
        y = 107 if i < 3 else 449
        w, h = 488, 329
        d = ImageDraw.Draw(canvas, 'RGBA')
        accent = '#19dff5' if i % 2 == 0 else '#b368ff'
        d.rounded_rectangle((x,y,x+w,y+h),radius=17,fill='#091735',outline=accent,width=3)
        m = plan.extra['details'][str(p['id'])]
        text(d,plan.labels[i],x+12,y+9,w-24,19,CYAN,14,center=True)
        name = ' '.join(str(p.get(k) or '') for k in ('first_name','second_name')).strip() or snapshot.name(p)
        text(d,name,x+12,y+35,w-85,29,WHITE,15)
        code = snapshot.photo_code(p)
        urls = (
            f'https://resources.premierleague.com/premierleague25/photos/players/250x250/{code}.png',
            f'https://resources.premierleague.com/premierleague25/photos/players/110x140/{code}.png',
            f'https://resources.premierleague.com/premierleague25/photos/players/250x250/p{code}.png',
            f'https://resources.premierleague.com/premierleague/photos/players/250x250/p{code}.png',
            f'https://resources.premierleague.com/premierleague/photos/players/110x140/p{code}.png',
            f'https://images.fantasy.premierleague.com/premierleague/photos/players/250x250/p{code}.png',
        )
        photo = next((v for url in urls if (v := _image_from_url(session,url)) is not None),None)
        crest = _media(session,snapshot.team_code(p),'crest',cache)
        if photo is None or crest is None:
            raise RequiredInput('Authentic player portrait or club crest missing')
        contain(canvas,photo,(x+10,y+75,147,190),bottom=True,crop_alpha=True)
        contain(canvas,crest,(x+w-63,y+29,49,49))
        d = ImageDraw.Draw(canvas,'RGBA')
        text(d,snapshot.price(p)+'  /  '+display(m['ownership'],1)+'% OWNED',x+162,y+72,310,19,WHITE,13)
        text(d,'FPL FORECAST  '+display(m['forecast'],1),x+162,y+99,310,28,CYAN,19)
        stats = [
            ('SEASON PTS',m['points'],0),('FORM',m['form'],1),
            ('SEASON MIN',m['minutes'],0),('LAST '+str(m['matches'])+' PTS',m['recent_points'],0),
            ('xG',m['xg'],2),('xA',m['xa'],2),
            ('GOALS',m['goals'],0),('ASSISTS',m['assists'],0),
            ('CLEAN SHEETS',m['clean_sheets'],0),('LAST MIN',m['recent_minutes'],0),
            ('GW TRANSFERS IN',m['transfers_in'],0),('GW TRANSFERS OUT',m['transfers_out'],0),
        ]
        if p['element_type'] == 1:
            stats[6] = ('SAVES',m['saves'],0)
        for j,(label,value,dp) in enumerate(stats):
            xx=x+163+(j%2)*155; yy=y+137+(j//2)*23
            text(d,label,xx,yy,101,11,WHITE,9)
            text(d,display(value,dp),xx+100,yy-2,53,16,CYAN,10)
        fixtures = ' / '.join(f'{opp}({venue}) FDR {fdr}' for opp,venue,fdr,_ in m['fixtures'])
        text(d,'NEXT: '+fixtures,x+13,y+287,w-26,22,WHITE,13,center=True)
    telegram,discord = required_footer_handles()
    social_footer(canvas,telegram,discord)
    return _save(canvas,output,footer=False)
