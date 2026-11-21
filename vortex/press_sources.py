"""Discover dated, fixture-specific written briefings on official club websites."""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit, parse_qs, urljoin, unquote
from xml.etree import ElementTree as ET
import gzip
import re
import requests

SITES = {
    'Arsenal':'arsenal.com', 'Aston Villa':'avfc.co.uk', 'Bournemouth':'afcb.co.uk',
    'Brentford':'brentfordfc.com', 'Brighton':'brightonandhovealbion.com', 'Burnley':'burnleyfootballclub.com',
    'Chelsea':'chelseafc.com', 'Crystal Palace':'cpfc.co.uk', 'Everton':'evertonfc.com',
    'Fulham':'fulhamfc.com', 'Leeds':'leedsunited.com', 'Liverpool':'liverpoolfc.com',
    'Man City':'mancity.com', 'Man Utd':'manutd.com', 'Newcastle':'newcastleunited.com',
    "Nott'm Forest":'nottinghamforest.co.uk', 'Sunderland':'safc.com', 'Spurs':'tottenhamhotspur.com',
    'West Ham':'whufc.com', 'Wolves':'wolves.co.uk', 'Coventry':'ccfc.co.uk',
    'Hull':'wearehullcity.co.uk', 'Ipswich':'itfc.co.uk', 'Southampton':'southamptonfc.com',
    'Middlesbrough':'mfc.co.uk', 'Sheffield Utd':'sufc.co.uk', 'Leicester':'lcfc.com',
}
ALIASES = {'Spurs':('Tottenham','Spurs'), 'Man Utd':('Manchester United','Man Utd'),
           'Man City':('Manchester City','Man City'), "Nott'm Forest":('Nottingham Forest','Forest'),
           'Wolves':('Wolverhampton','Wolves'), 'Brighton':('Brighton','Albion')}
PRESS = re.compile(r'press conference|press briefing|pre.match media|spoke to (?:the )?media|faced the media|every word|met (?:with )?the media|told reporters',re.I)
UNRELATED = re.compile(r"post.match|after (?:the|our) (?:win|defeat|draw)|women.?s|under.?\d\d|u\d\d[s ]|champions league|europa league|conference league|carabao|FA cup",re.I)
FUTURE = re.compile(r'how to watch|watch live|will (?:be speaking to|face|speak to|address) the media|press conference times',re.I)
NEWS = re.compile(r'\b(injur\w*|fitness|fully fit|match fit|ruled out|available|training|recover\w*|suspend\w*|selection|minutes|assess\w*|starting|squad|doubtful|return\w*)\b',re.I)
APPOINTMENT = re.compile(r'first (?:[\\w-]+ )?press conference|new manager (?:speaks|interview)|first interview|manager (?:unveiled|appointment)', re.I)

class Article(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.field = self.date = self.title = ''
        self.parts, self.paragraphs = [], []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('p','h1','title'):
            self.field, self.parts = tag, []
        if tag=='meta':
            key = a.get('property') or a.get('name')
            if key in ('article:published_time','datePublished','parsely-pub-date'):
                self.date = a.get('content','')
            if key=='og:title': self.title = a.get('content','')
    def handle_data(self, data):
        if self.field: self.parts.append(data)
    def handle_endtag(self, tag):
        if tag != self.field: return
        line = ' '.join(''.join(self.parts).split())
        if tag=='p' and line: self.paragraphs.append(line)
        if tag=='h1' or (tag=='title' and not self.title): self.title = line
        self.field = ''

def official(url, domain):
    host = (urlsplit(url).hostname or '').lower()
    return urlsplit(url).scheme=='https' and (host==domain or host.endswith('.'+domain))

def get(session, url, domain):
    for _ in range(4):
        if not official(url, domain): raise ValueError('Unexpected source host')
        with session.get(url, timeout=(3,5), allow_redirects=False, stream=True) as r:
            if r.is_redirect:
                url = urljoin(url, r.headers['Location'])
                continue
            r.raise_for_status()
            data = bytearray()
            for chunk in r.iter_content(65536):
                data.extend(chunk)
                if len(data)>5_000_000: raise ValueError('Source too large')
            return bytes(data)
    raise ValueError('Too many redirects')

def evidence(html, url, club, opponents, now, since):
    doc = Article()
    doc.feed(html)
    stamp = doc.date or next(iter(re.findall(r'"datePublished"\s*:\s*"([^"]+)"',html)), '')
    try: published=datetime.fromisoformat(stamp.replace('Z','+00:00'))
    except ValueError: return
    if not published.tzinfo or not since <= published <= now: return
    intro=' '.join([doc.title,*doc.paragraphs[:8]])
    # A new coach's introductory interview is not an opponent-specific pre-match
    # presser. In particular, do not confuse 'good fit for Palace' with player fitness.
    if APPOINTMENT.search(doc.title): return
    if UNRELATED.search(url+' '+intro[:900]) or FUTURE.search(intro[:900]) or not PRESS.search(intro): return
    held = re.search(r'held|spoke|faced|met the media|told|speaking (?:at|to)|was asked|has confirmed|discussed|revealed|said|every word|transcript',intro,re.I)
    if not held: return
    if not any(re.search(r'\b'+re.escape(n)+r'\b',intro,re.I) for n in opponents): return
    if not re.search(r'ahead of|before|pre.match|pre.game|preview|build.up|looking ahead',intro,re.I): return
    def suitable(line):
        return (14 <= len(line) <= 230 and '?' not in line
                and not re.search(r'cookies|subscribe|sign up|tickets|copyright|\\bwelcome\\b|\\bgood fit for\\b',line,re.I))
    facts=[p for p in doc.paragraphs if suitable(p) and NEWS.search(p)]
    if not facts: return None  # No filler, empty or speculative press-report cards.
    quotes=[q for p in doc.paragraphs for q in re.findall(r'[“"]([^”"]{12,150})[”"]',p)
            if suitable(q) and NEWS.search(q)]
    return dict(club=club,title=doc.title,news=facts[0],quote=next(iter(quotes),''),
                url=url,published=published.isoformat())

def candidates(session, domain, opponents, now):
    terms = ['press-conference','team-news','every-word','press-briefing',
             *(n.lower().replace(' ','-') for n in opponents)]
    # Fresh official article discovery through news search, then the club's own sitemap.
    try:
        rsp=session.get('https://www.bing.com/news/search',params={'q':f'site:{domain} "{opponents[0]}" press conference team news','format':'rss'},timeout=5)
        for item in ET.fromstring(rsp.content).iter('item'):
            link=item.findtext('link','')
            target=parse_qs(urlsplit(link).query).get('url',[link])[0]
            if official(target,domain): yield target
    except (requests.RequestException,ET.ParseError): pass
    base='https://www.'+domain
    try: robots=get(session,base+'/robots.txt',domain).decode(errors='replace')
    except (ValueError,requests.RequestException): robots=''
    maps=re.findall(r'^sitemap:\s*(https://\S+)',robots,re.M|re.I) or [base+'/sitemap.xml']
    visited=set()
    while maps and len(visited)<7:
        url=maps.pop(0)
        if url in visited: continue
        visited.add(url)
        try:
            data=get(session,url,domain)
            if data.startswith(b'\x1f\x8b'): data=gzip.decompress(data)
            root=ET.fromstring(data)
        except (ValueError,OSError,requests.RequestException,ET.ParseError): continue
        entries=[(el.findtext('{*}lastmod',''),el.findtext('{*}loc','')) for el in root]
        if root.tag.endswith('sitemapindex'):
            maps=sorted((u for _,u in entries if official(u,domain)),key=lambda u:('news' in u,u),reverse=True)+maps
        else:
            matches=[(date,u) for date,u in entries if official(u,domain) and any(t in unquote(u).lower() for t in terms)]
            for _,u in sorted(matches,reverse=True)[:14]: yield u

def lookup(team, opponent, now, since):
    domain=SITES.get(team['name'])
    if not domain: return None
    opponents=ALIASES.get(opponent['name'],(opponent['name'],))
    with requests.Session() as s:
        s.headers['User-Agent']='FPL-Vortex matchday press reader/1.0'
        seen=set()
        for url in candidates(s,domain,opponents,now):
            if url in seen: continue
            seen.add(url)
            if len(seen)>18: break
            try: html=get(s,url,domain).decode('utf-8',errors='replace')
            except (requests.RequestException,ValueError): continue
            if item:=evidence(html,url,team['name'],opponents,now,since): return item
    return None
