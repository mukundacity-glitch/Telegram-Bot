from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from .graphic_numbers import stamp

ASSETS=Path(__file__).resolve().parents[1]/'assets/press'

def render(path, day, names, facts, locked):
    im=Image.new('RGB',(1920,1080),'#0e0920')
    d=ImageDraw.Draw(im)
    def font(size): return ImageFont.truetype('DejaVuSans.ttf',size)
    def text(x,y,s,size=29,color='white'):
        d.text((x,y),s,font=font(size),fill=color)
    def wrap(s,width,size,limit):
        words=s.split(); lines=['']
        for w in words:
            test=(lines[-1]+' '+w).strip()
            if d.textlength(test,font=font(size))>width and lines[-1]:
                lines.append(w)
            else: lines[-1]=test
        if len(lines)>limit: lines[limit-1]=lines[limit-1].rstrip('.,;')+'…'
        return lines[:limit]
    with Image.open(ASSETS/'logo.jpg') as logo:
        logo=ImageOps.contain(logo,(310,140));im.paste(logo,(16,(148-logo.height)//2))
    text(360,15,'PRESS CONFERENCE',59)
    text(365,96,f"GAMEWEEK {day['gw']}   •   {day['date']}   •   {len(facts)}/{len(names)} clubs verified",33,'#93f5ed')
    d.line((18,155,1902,155),fill='#aa58ff',width=4)
    def panel(x,y,w,h,title,items,limit):
        d.rounded_rectangle((x,y,x+w,y+h),radius=17,fill='#1b1230',outline='#8355bd',width=3)
        text(x+22,y+15,title,36,'#d5b6ff')
        yy=y+78
        for name,line in items:
            lines=wrap(line,w-54,29,limit)
            if yy+36*(1+len(lines))>y+h-8: break
            text(x+23,yy,name,26,'#72edc7'); yy+=36
            for l in lines: text(x+23,yy,l); yy+=36
            yy+=18
    news=[(v['club'],v['news']) for v in facts.values() if v['news']]
    quotes=[(v['club'],'“'+v['quote']+'”') for v in facts.values() if v['quote']]
    panel(16,175,600,778,'LATEST NEWS',news or [('Verified club briefing',next(iter(facts.values()))['title'])],5)
    panel(632,175,590,480,'KEY QUOTES',quotes or [('Source coverage','See the linked club briefings for full remarks.')],5)
    panel(632,672,590,281,"MANAGER’S NOTES",[('Fantasy deadline','Squads are locked for this gameweek.' if locked else 'Review confirmed availability before the gameweek deadline.'),next(((v['club'],v['news']) for v in reversed(list(facts.values())) if v['news']),('Coverage',f'{len(facts)}/{len(names)} clubs verified.'))],2)
    d.rounded_rectangle((1238,175,1904,953),radius=17,fill='#18112d',outline='#8355bd',width=3)
    text(1260,193,'CLUB-BY-CLUB ROUNDUP',35,'#d5b6ff')
    step=min(72,675//len(names))
    for i,(key,name) in enumerate(names.items()):
        y=262+i*step
        status='Verified' if key in facts else 'Pending'
        text(1260,y,name,min(28,step-5))
        if key in facts:
            summary=facts[key]['news'] or facts[key]['title']
            detail=wrap(summary,360,min(23,step-7),1)[0]
            text(1520,y+2,detail,min(23,step-7),'#8af2ca')
        else:
            text(1520,y+2,'Awaiting briefing',min(23,step-7),'#efcb78')
    with Image.open(ASSETS/'footer.jpg') as footer: im.paste(footer.resize((1920,96)),(0,984))
    path.parent.mkdir(parents=True,exist_ok=True);im.save(path)
    stamp(path,'verified-press-availability')
