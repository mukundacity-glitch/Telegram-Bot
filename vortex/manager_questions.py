"""Read public dated manager questions as topic evidence, never player news."""
from datetime import datetime,timedelta,timezone
import xml.etree.ElementTree as ET
import requests
from .editorial_inputs import RequiredInput

URL='https://www.reddit.com/r/FantasyPL/new/.rss'


def recent_question(now,session=None):
    try:
        r=(session or requests.Session()).get(URL,timeout=15,headers={'User-Agent':'FPLVortexEditorial/1.0'})
        r.raise_for_status();root=ET.fromstring(r.content)
        ns={'a':'http://www.w3.org/2005/Atom'}
        for item in root.findall('a:entry',ns):
            title=item.findtext('a:title','',ns)
            stamp=datetime.fromisoformat(item.findtext('a:updated','',ns).replace('Z','+00:00'))
            if not timedelta(0)<=now-stamp<=timedelta(hours=48):continue
            if any(word in title.lower() for word in ('question','rmt','transfer','hit','wildcard','minutes','bench')):
                link=item.find('a:link',ns)
                return {'title':title[:180],'url':link.get('href',''),'published_at':stamp.isoformat(),
                        'scope':'One observed discussion; no community-consensus claim'}
    except (requests.RequestException,ValueError,ET.ParseError):
        pass
    raise RequiredInput('Fresh dated manager-question evidence inaccessible; no invented Reddit research')
