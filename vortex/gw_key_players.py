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
    title = f'GW{gw} | FIVE ELITE FPL PICKS'
    copy = (f'🎯 {title}\n\n'
            f'💎 Premium: {names[0]} • {names[1]}\n'
            f'💰 Value: {names[2]} • {names[3]}\n'
            f'🛡️ Defence: {names[4]}\n\n'
            '📊 Ranked by projected points.\n'
            '⚠️ Monitor expected minutes and team news.\n\n'
            f'#FPL #GW{gw} #FPLTips #FPLVORTEX')
    return Plan(slot.task, slot.edition, title, copy, gw, players, labels, 'gw_key_players',
                {'details': details, 'editorial_reference': ref, 'forecast_source': 'official FPL ep_next'})

def render_key_players(plan, snapshot, output, session):
    """Reference-inspired broadcast board, entirely data-driven and isolated to 55/55."""
    from PIL import Image, ImageDraw, ImageFilter
    from .autonomous_render import _save
    from .brand_footer import MASTER, verify_exact_master
    from .comparison_board import contain, text, WHITE, CYAN, GOLD
    from .minimal_theme import extra_social_handles
    from .publication_rules import required_footer_handles
    from .matchup import _image_from_url, _media
    if len(plan.players) != 5 or len({p['id'] for p in plan.players}) != 5 or plan.gw != snapshot.gameweek():
        raise RequiredInput('Five unique players for the official upcoming gameweek required')
    verify_exact_master()
    W,H = 1536,864
    navy = (5,13,38)
    muted = (165,198,232)
    # Reference style: blue stadium-light beams, violet edge glow, gold angled ribbons.
    canvas = Image.new('RGB',(W,H),navy)
    beam = Image.new('RGBA',(W,H))
    bd = ImageDraw.Draw(beam)
    for pts,col in [
        ([(0,0),(385,0),(0,325)],(0,108,255,150)),
        ([(0,45),(270,0),(0,242)],(0,210,255,120)),
        ([(W,0),(W-380,0),(W,345)],(31,89,255,140)),
        ([(0,H),(0,H-240),(300,H)],(43,75,255,150)),
        ([(W,H),(W,H-280),(W-325,H)],(147,36,255,125))]:
        bd.polygon(pts,fill=col)
    canvas.paste(beam.filter(ImageFilter.GaussianBlur(24)),(0,0),beam.filter(ImageFilter.GaussianBlur(24)))
    d=ImageDraw.Draw(canvas,'RGBA')
    for pts,col in [
        ([(0,0),(200,0),(0,185)],(15,82,202,175)),
        ([(0,22),(105,0),(0,120)],(12,167,255,160)),
        ([(W,0),(W-175,0),(W,160)],(20,110,255,150)),
        ([(0,H-180),(0,H),(180,H)],(25,100,235,160)),
        ([(W,H-185),(W,H),(W-185,H)],(63,63,220,150))]:
        d.polygon(pts,fill=col)
    for line in [(0,208,225,0),(0,166,175,0),(W-220,0,W,210),(0,680,180,H),(W-175,H,W,680)]:
        d.line(line,fill=(40,205,255,205),width=3)
    # Retain original approved masthead marks, rather than inventing new brand logos.
    with Image.open(MASTER) as original:
        master=original.convert('RGB').resize((W,H))
        canvas.paste(master.crop((0,0,310,80)).resize((248,64),Image.Resampling.LANCZOS),(18,10))
        canvas.paste(master.crop((1336,0,1536,80)).resize((160,64),Image.Resampling.LANCZOS),(1350,10))
    d=ImageDraw.Draw(canvas,'RGBA')
    text(d,f'GW{plan.gw} | FIVE ELITE FPL PICKS',270,3,1060,45,WHITE,30,center=True)
    text(d,'PROJECTED POINTS  •  PRICE  •  FORM  •  FIXTURES',285,57,990,20,GOLD,16,center=True)
    d.line((270,88,1266,88),fill=GOLD,width=2)

    def ribbon(bounds, label, accent):
        x0,y0,x1,y1=bounds
        d.polygon([(x0+15,y0),(x1,y0),(x1-15,y1),(x0,y1)],
                  fill=(14,30,61,255),outline=accent,width=2)
        text(d,label,x0+20,y0+5,x1-x0-40,25,WHITE,17,center=True)

    ribbon((42,99,755,137),'PREMIUM  •  £7.5m+',GOLD)
    ribbon((781,99,1494,137),'VALUE  •  UNDER £7.5m',CYAN)
    cache={}
    def display(v, digits=0):
        return '—' if v is None else f'{v:,.{digits}f}'

    def card(i,x,y,w,h,wide=False):
        p=plan.players[i]
        m=plan.extra['details'][str(p['id'])]
        accent=GOLD if i<2 else CYAN if i<4 else (116,241,176)
        d.rounded_rectangle((x,y,x+w,y+h),radius=15,fill=(8,23,55,255),outline=accent,width=2)
        d.line((x+16,y+h-1,x+w-16,y+h-1),fill=(53,196,255,200),width=2)
        code=snapshot.photo_code(p)
        urls=(
            f'https://resources.premierleague.com/premierleague25/photos/players/250x250/{code}.png',
            f'https://resources.premierleague.com/premierleague25/photos/players/110x140/{code}.png',
            f'https://resources.premierleague.com/premierleague25/photos/players/250x250/p{code}.png',
            f'https://resources.premierleague.com/premierleague/photos/players/250x250/p{code}.png',
            f'https://resources.premierleague.com/premierleague/photos/players/110x140/p{code}.png',
            f'https://images.fantasy.premierleague.com/premierleague/photos/players/250x250/p{code}.png',
        )
        photo=next((v for url in urls if (v:=_image_from_url(session,url)) is not None),None)
        crest=_media(session,snapshot.team_code(p),'crest',cache)
        if photo is None or crest is None:
            raise RequiredInput('Authentic player portrait or club crest missing')
        contain(canvas,photo,(x+12,y+8,146,h-38),bottom=True,crop_alpha=True)
        contain(canvas,crest,(x+6,y+5,42,42))
        name=' '.join(str(p.get(k) or '') for k in ('first_name','second_name')).strip() or snapshot.name(p)
        x0=x+166
        forecast=display(m['forecast'],1)
        badge_w=153
        badge_x=x+w-badge_w-10
        d.polygon([(badge_x+9,y+6),(x+w-10,y+6),(x+w-19,y+53),(badge_x,y+53)],fill=GOLD)
        text(d,'FPL FORECAST',badge_x+10,y+9,badge_w-20,13,navy,11,center=True)
        text(d,forecast,badge_x+10,y+22,badge_w-20,25,navy,20,center=True)
        text(d,name.upper(),x0,y+5,badge_x-x0-10,26,WHITE,17)
        own=display(m['ownership'],1)
        role='DEFENCE  /  ' if i==4 else ''
        text(d,role+snapshot.price(p)+'  •  '+(own+'% OWNED' if own!='—' else 'OWNERSHIP —'),
             x0,y+35,badge_x-x0-10,17,accent,13)
        stats=[
            ('SEASON PTS',m['points'],0),('FORM',m['form'],1),('SEASON MIN',m['minutes'],0),
            (f'LAST {m["matches"]} PTS',m['recent_points'],0),('RECENT MIN',m['recent_minutes'],0),
            ('GOALS',m['goals'],0),('ASSISTS',m['assists'],0),('xG',m['xg'],2),('xA',m['xa'],2),
            ('CLEAN SHEETS',m['clean_sheets'],0),('GW IN',m['transfers_in'],0),('GW OUT',m['transfers_out'],0),
        ]
        if p['element_type']==1:
            stats[5]=('SAVES',m['saves'],0)
        cols=6 if wide else 3
        available=w-180
        cell_w=available/cols
        cell_h=25 if wide else 24
        for j,(label,value,dp) in enumerate(stats):
            xx=x0+(j%cols)*cell_w
            yy=y+58+(j//cols)*cell_h
            d.rounded_rectangle((round(xx),yy,round(xx+cell_w-4),yy+cell_h-3),radius=4,
                                fill=(12,39,77,255),outline=(38,95,153,255),width=1)
            label_w=cell_w*.56
            text(d,label,xx+5,yy+4,label_w-5,12,muted,9)
            text(d,display(value,dp),xx+label_w,yy+2,cell_w-label_w-7,16,WHITE,10,center=True)
        # Every fixture in a double GW is shown, with its own FDR.
        fy=y+h-30
        d.rounded_rectangle((x+9,fy,x+w-9,y+h-6),radius=7,fill=(5,15,34,255),outline=(31,121,184,255))
        text(d,snapshot.team(p),x+14,fy+4,133,15,GOLD,10,center=True)
        text(d,'NEXT  /  '+'  •  '.join(f'{opp} ({venue})  FDR {fdr}' for opp,venue,fdr,_ in m['fixtures']),
             x0,fy+3,w-180,17,WHITE,12,center=True)

    # Same two-column visual hierarchy as the approved fixture-guide reference.
    card(0,42,144,713,190)
    card(1,42,342,713,190)
    card(2,781,144,713,190)
    card(3,781,342,713,190)
    ribbon((42,540,1494,573),'DEFENSIVE PICK  •  GOALKEEPER OR DEFENDER',(116,241,176))
    card(4,42,580,1452,146,True)
    d.polygon([(72,737),(1464,737),(1490,762),(1464,792),(72,792),(46,762)],
              fill=(8,23,55,255),outline=GOLD,width=3)
    text(d,'VORTEX VERDICT',77,748,295,25,GOLD,18,center=True)
    d.line((385,746,385,782),fill=GOLD,width=2)
    text(d,'Compare projected points by price tier  •  Monitor expected minutes and team news',
         402,751,1055,24,WHITE,17,center=True)

    # Restore the social platform icons visible in the supplied reference;
    # no additional VORTEX/league logo in the footer, only channel identifiers.
    telegram,discord=required_footer_handles()
    youtube,x_handle=extra_social_handles()
    d.rectangle((0,803,W,H),fill=(4,11,31,255))
    d.line((18,803,W-18,803),fill=GOLD,width=2)
    items=[('youtube',youtube),('x',x_handle),('telegram','t.me/'+telegram.lstrip('@')),('discord',discord)]
    items=[(k,v) for k,v in items if v]
    width=(W-28)/len(items)
    for idx,(kind,value) in enumerate(items):
        x=14+idx*width
        iy=819
        if idx:
            d.line((round(x),816,round(x),850),fill=GOLD,width=2)
        ix=round(x+11)
        if kind=='youtube':
            d.rounded_rectangle((ix,iy,ix+38,iy+25),radius=6,fill='#ff1735')
            d.polygon([(ix+15,iy+5),(ix+15,iy+20),(ix+27,iy+12)],fill='white')
        elif kind=='x':
            d.line((ix+5,iy+1,ix+32,iy+27),fill='white',width=3)
            d.line((ix+30,iy+1,ix+3,iy+27),fill='white',width=2)
        elif kind=='telegram':
            d.ellipse((ix,iy-3,ix+32,iy+29),fill='#29a9ec')
            d.polygon([(ix+5,iy+10),(ix+27,iy+2),(ix+21,iy+23),(ix+15,iy+17),(ix+10,iy+21),(ix+12,iy+13)],fill='white')
        else:
            d.rounded_rectangle((ix,iy,ix+36,iy+25),radius=8,fill='#5865f2')
            d.ellipse((ix+8,iy+8,ix+14,iy+14),fill='white')
            d.ellipse((ix+22,iy+8,ix+28,iy+14),fill='white')
            d.arc((ix+9,iy+10,ix+27,iy+21),0,180,fill='white',width=2)
        text(d,value,ix+46,iy+1,width-66,20,WHITE,13,center=True)
    return _save(canvas,output,footer=False)
