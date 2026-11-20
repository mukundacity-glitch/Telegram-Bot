from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
from zoneinfo import ZoneInfo
from vortex import matchday_press as press
from vortex.press_sources import evidence
from vortex.publishing_window import is_press_delivery

def clock(day,hour): return datetime(2026,11,day,hour,tzinfo=timezone.utc)

class MatchdayPress(TestCase):
    def setUp(self):
        teams={i:{'name':f'Club {i}'} for i in range(1,21)}
        fixtures=[dict(event=11,kickoff_time=clock(day,13).isoformat(),team_h=i,team_a=i+1)
                  for i,day in zip(range(1,20,2),[21]*7+[22]*2+[24])]
        self.snap=SimpleNamespace(teams=teams,fixtures=fixtures,
                                  events=[dict(id=11,deadline_time=clock(21,11).isoformat())])
        self.state={};self.sent=[];self.covered={'Club 1'}
    def fetch(self,club,opponent,now,since):
        if club['name'] in self.covered:
            return dict(club=club['name'],news='A player has returned to training.',title='Press conference',
                        quote='',url='https://example.org/fixture')
    def send_shared_png(self,*args,**kwargs):
        assert is_press_delivery();self.sent.append(args[1]);return 101
    def edit_shared_png(self,path,caption,mid,**kwargs):
        assert mid==101;self.sent.append(caption);return mid
    def check(self,now):
        return press.run(self.snap,now,lambda _:self.state,lambda *args:None,lambda:self,
                         fetch=self.fetch,render_image=lambda *args:None)
    def test_one_deadline_three_matchdays(self):
        for date,clubs in [(21,14),(22,4),(24,2)]:
            day,=press.matchdays(self.snap,clock(date,7))
            assert len(day['pairs'])==clubs
            if date==21:
                assert day['target'].astimezone(ZoneInfo('Asia/Kathmandu')).strftime('%H:%M')=='14:45'
            else: assert day['target'] is None
        assert not list(press.matchdays(self.snap,clock(23,7)))
    @mock.patch.dict('os.environ',{'GITHUB_ACTIONS':'false'})
    def test_partial_edit_and_later_wait(self):
        self.check(clock(21,6));assert not self.sent
        self.check(clock(21,9));assert len(self.sent)==1
        self.covered.update(t['name'] for t in self.snap.teams.values())
        self.check(clock(21,10));assert len(self.sent)==2
        self.check(clock(21,10)+timedelta(minutes=20));assert len(self.sent)==2
        self.covered={'Club 15'}
        self.check(clock(22,5));assert len(self.sent)==2
        self.covered.update(['Club 16','Club 17','Club 18'])
        self.check(clock(22,6));assert 'Gameweek locked' in self.sent[-1]
    def test_official_evidence_rejects_placeholders(self):
        html='<meta property="article:published_time" content="2026-11-20T09:00:00Z"><h1>Team news before Brentford</h1><p>Our manager held his press conference ahead of Brentford.</p><p>Smith is available for selection.</p>'
        check=lambda body:evidence(body,'https://www.arsenal.com/news/team-news','Arsenal',['Brentford'],clock(21,8),clock(18,8))
        assert check(html)['news']=='Smith is available for selection.'
        assert check(html.replace('held his','will host a')) is None
        assert check(html.replace('Brentford','Chelsea')) is None
