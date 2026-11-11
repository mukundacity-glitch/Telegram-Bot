"""06:20 edition: official FPL forecasts, strictly under ten percent owned."""
from math import isfinite
from .editorial_inputs import RequiredInput


def number(value):
    if isinstance(value,bool):return None
    try:
        result=float(value)
        return result if isfinite(result) else None
    except (TypeError,ValueError):
        return None


def build_low_owned(slot,snapshot,now,evidence):
    from .autonomous_content import Plan
    from .publication_rules import player_metrics
    gw=snapshot.gameweek()
    next_events=[event for event in snapshot.events if event.get('is_next') is True]
    if len(next_events)!=1 or next_events[0].get('id')!=gw:
        raise RequiredInput('Official ep_next event does not match the upcoming deadline GW')
    candidates=[]
    for p in snapshot.players:
        own=number(p.get('selected_by_percent'));forecast=number(p.get('ep_next'))
        if (own is None or not 0<=own<10 or forecast is None or forecast<=0
            or p.get('status')!='a' or p.get('chance_of_playing_next_round') not in (None,100)
            or type(p.get('now_cost')) is not int or p['now_cost']<=0
            or type(p.get('code')) is not int or p['code']<=0 or p.get('team') not in snapshot.teams
            or p.get('element_type') not in (1,2,3,4)):
            continue
        fixtures=snapshot.fixtures_for_gameweek(p)
        if not fixtures or any(r[2] not in (1,2,3,4,5) for r in fixtures):
            continue
        fdr=sum(r[2] for r in fixtures)/len(fixtures)
        candidates.append((forecast,fdr,int(p.get('minutes') or 0),p))
    # ep_next is already a gameweek forecast. Keep its source value intact,
    # including doubles; use official fixture difficulty only to break ties.
    candidates.sort(key=lambda row:(-row[0],row[1],-row[2],row[3]['id']))
    if len(candidates)<6:
        raise RequiredInput('Six available under-10%-owned players with positive official ep_next and verified fixtures required')
    selected=candidates[:6];players=[r[3] for r in selected];details={}
    for forecast,fdr,_,p in selected:
        recent=evidence.recent(p)
        metrics=player_metrics(snapshot,p,recent)
        points=[number(r.get('total_points')) for r in recent]
        minutes=[number(r.get('minutes')) for r in recent]
        details[str(p['id'])]={'fpl_ep_next':forecast,'fixture_fdr':fdr,'metrics':metrics,
            'recent':recent,'l3_points':sum(points) if points and all(x is not None for x in points) else None,
            'l3_minutes':sum(minutes) if minutes and all(x is not None for x in minutes) else None,
            'appearances':len(recent),'fixtures':snapshot.fixtures_for_gameweek(p)}
    names=' / '.join(snapshot.name(p) for p in players)
    lead=players[0];gw=snapshot.gameweek()
    caption=(f"GW{gw}: six players under 10% ownership.\n{names}.\n"
             f"Top FPL forecast: {snapshot.name(lead)} {selected[0][0]:.2f} points; {snapshot.price(lead)}; {lead['selected_by_percent']}% owned.\n"
             'Ranked by official FPL ep_next; fixture difficulty breaks ties. MONITOR starts before buying; forecasts are not guaranteed.\n'
             f'#FPL #FPLVortex #GW{gw} #FPLDifferentials')
    if len(caption)>1024:raise RequiredInput('Six-player caption exceeds shared platform limit')
    return Plan(slot.task,slot.edition,'SIX DIFFERENTIALS',caption,gw,players,
                [f'RANK {i+1}' for i in range(6)],kind='low_owned_six',extra={
                    'details':details,'forecast_source':'official FPL bootstrap-static ep_next',
                    'ranking':'ep_next descending; mean official next-GW FDR ascending; minutes descending; official ID',
                    'ownership_filter':'selected_by_percent < 10; status a; chance null or 100',
                    'generated_at':now.isoformat()})


def render_low_owned(plan,snapshot,output,session,assets):
    """Image-2-grade neon broadcast design; all content is current official FPL.

    Player names, photographs, badges, GW, order, forecast, and statistics are
    provided by the model/snapshot for this run. No example data is embedded.
    """
    import os
    from pathlib import Path
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    from .brand_footer import MASTER,verify_exact_master
    from .comparison_board import contain
    from .publication_rules import required_footer_handles

    verify_exact_master()
    telegram,discord=required_footer_handles()
    if (len(plan.players)!=6 or len({p['id'] for p in plan.players})!=6
            or snapshot.gameweek()!=plan.gw):
        raise RequiredInput('Premium differential edition requires six distinct official current-GW players')
    W,H=1536,864
    CYAN=(20,232,249);PURPLE=(177,66,254);WHITE=(247,250,255)
    SOFT=(181,204,229);DARK=(5,15,42);GREEN=(90,240,110)
    canvas=Image.new('RGBA',(W,H),(3,11,33,255))
    # Reusable studio lighting makes the image as rich as the neon reference.
    glow=Image.new('RGBA',(W,H))
    gd=ImageDraw.Draw(glow)
    gd.polygon([(0,0),(370,0),(0,280)],fill=(0,112,240,58))
    gd.polygon([(W,0),(1140,0),(W,290)],fill=(166,30,255,60))
    gd.polygon([(0,H),(300,H),(0,710)],fill=(97,27,255,40))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(17)))

    def font(n):
        for name in ('DejaVuSansCondensed-Bold','DejaVuSans-Bold'):
            try:return ImageFont.truetype('/usr/share/fonts/truetype/dejavu/'+name+'.ttf',n)
            except OSError:pass
        return ImageFont.load_default()

    def writing(draw,value,x,y,width,size,shade=WHITE,min_size=11,align='left'):
        value=str(value)
        for n in range(size,min_size-1,-1):
            face=font(n)
            if draw.textbbox((0,0),value,font=face)[2]<=width:break
        else:
            raise RequiredInput('Visible official text does not fit premium graphic: '+value[:60])
        tw=draw.textbbox((0,0),value,font=face)[2]
        if align=='center':x+=(width-tw)/2
        elif align=='right':x+=width-tw
        draw.text((round(x),round(y)),value,font=face,fill=shade)

    def box(x0,y0,x1,y1,outline=CYAN,fill=DARK,rad=12,blur=6,thick=2):
        halo=Image.new('RGBA',(W,H))
        ImageDraw.Draw(halo).rounded_rectangle((x0,y0,x1,y1),radius=rad,
                           outline=(*outline,255),width=max(3,thick))
        canvas.alpha_composite(halo.filter(ImageFilter.GaussianBlur(blur)))
        d=ImageDraw.Draw(canvas,'RGBA')
        d.rounded_rectangle((x0,y0,x1,y1),radius=rad,
                            fill=(*fill,255),outline=(*outline,255),width=thick)
        return d

    d=box(22,8,1514,109,PURPLE,(3,12,37),24,11)
    d.line((33,108,1503,108),fill=CYAN,width=2)
    with Image.open(MASTER) as origin:
        master=origin.convert('RGBA').resize((W,H))
        canvas.alpha_composite(master.crop((0,0,238,63)),(26,19))
        canvas.alpha_composite(master.crop((1362,0,1536,64)),(1350,20))
    d=ImageDraw.Draw(canvas,'RGBA')
    d.line((310,21,310,93),fill=(*CYAN,200),width=2)
    d.line((1317,21,1317,93),fill=(*PURPLE,200),width=2)
    writing(d,plan.title.upper(),340,12,960,55,WHITE,32,'center')
    writing(d,f'GW{plan.gw}  /  UNDER 10% OWNED  /  NEXT GAMEWEEK',
            400,74,845,22,CYAN,16,'center')
    cache={}
    positions={1:'GK',2:'DEF',3:'MID',4:'FWD'}

    for idx,p in enumerate(plan.players):
        x=19+(idx%3)*504;y=130+(idx//3)*326;w=489
        detail=plan.extra['details'].get(str(p['id']))
        if not isinstance(detail,dict):
            raise RequiredInput('No current FPL forecast/statistics for selected player')
        stats=detail['metrics'];fpl=number(detail.get('fpl_ep_next'))
        own=number(p.get('selected_by_percent'))
        if (fpl is None or fpl<=0 or own is None or not 0<=own<10
                or p.get('status')!='a'):
            raise RequiredInput('Differential board now contains an ineligible player')
        d=box(x,y,x+w,y+310,CYAN if idx%2==0 else PURPLE,(6,19,48),16,7)
        d.rounded_rectangle((x+12,y+9,x+195,y+38),radius=13,
              fill=(18,8,53,255),outline=(*PURPLE,250),width=2)
        writing(d,f'{idx+1:02d}  {positions[p["element_type"]]} / {snapshot.team(p)}',
                x+20,y+11,171,19,WHITE,13)
        writing(d,snapshot.name(p).upper(),x+17,y+39,w-92,29,WHITE,17)
        portrait,crest=assets(snapshot,p,session,cache)
        contain(canvas,portrait,(x+7,y+85,144,208),bottom=True,crop_alpha=True)
        contain(canvas,crest,(x+w-69,y+16,53,53))
        d=ImageDraw.Draw(canvas,'RGBA')
        d=box(x+153,y+78,x+305,y+149,PURPLE,(7,18,50),9,5,1)
        writing(d,'FPL FORECAST',x+163,y+83,132,15,WHITE,12,'center')
        writing(d,f'{fpl:.2f}',x+161,y+101,136,37,CYAN,25,'center')
        d=box(x+313,y+78,x+w-12,y+149,CYAN,(6,23,51),9,5,1)
        writing(d,snapshot.price(p),x+318,y+82,w-338,30,WHITE,20,'center')
        writing(d,f'{own:.1f}% OWNED',x+319,y+119,w-341,17,(255,155,242),12,'center')
        d=ImageDraw.Draw(canvas,'RGBA')
        d.rounded_rectangle((x+153,y+159,x+w-12,y+262),radius=8,
              fill=(4,18,44,255),outline=(*CYAN,195),width=1)
        d.line((x+312,y+166,x+312,y+258),fill=(*CYAN,125),width=1)
        if p['element_type']==1:
            roles=[('SAVES',stats.get('SAVES','—')),('CLEAN SHEETS',stats.get('CS','—'))]
        elif p['element_type']==2:
            roles=[('CLEAN SHEETS',stats.get('CS','—')),('DC ACTIONS',stats.get('DC ACTIONS','—'))]
        else:
            mins=number(p.get('minutes'));xg=number(p.get('expected_goals'))
            xa=number(p.get('expected_assists'))
            roles=[('xG / 90',f'{xg/mins*90:.2f}' if mins and xg is not None else '—'),
                   ('xA / 90',f'{xa/mins*90:.2f}' if mins and xa is not None else '—')]
        recent=detail['appearances']
        cells=[(('FORM',stats['FORM']),('SEASON PTS',stats['TOTAL PTS'])),
               ((f'LAST {recent} PTS' if recent else 'RECENT PTS',
                 str(round(detail['l3_points'])) if detail['l3_points'] is not None else '—'),
                (f'LAST {recent} MIN' if recent else 'RECENT MIN',
                 str(round(detail['l3_minutes'])) if detail['l3_minutes'] is not None else '—')),
               (roles[0],roles[1])]
        for row,pair in enumerate(cells):
            ty=y+165+row*32
            if row:d.line((x+162,ty-3,x+w-20,ty-3),fill=(68,119,174,140),width=1)
            for col,(name,value) in enumerate(pair):
                xx=x+162+col*160
                writing(d,name,xx,ty,100,12,SOFT,10)
                writing(d,value,xx+101,ty,53,19,WHITE,11,'right')
        d=box(x+10,y+267,x+146,y+301,CYAN,(5,26,57),8,5,1)
        writing(d,str(stats['MINUTES'])+' SEASON MIN',
                x+16,y+275,123,17,WHITE,11,'center')
        fixtures=detail['fixtures']
        if not fixtures:raise RequiredInput('Next GW fixture absent')
        opponents=' / '.join(f'{opp}({home})' for opp,home,_,_ in fixtures)
        fdrl=[int(t[2]) for t in fixtures]
        if any(v not in (1,2,3,4,5) for v in fdrl):
            raise RequiredInput('Invalid official next-GW FDR')
        color=GREEN if max(fdrl)<=3 else (255,215,66) if max(fdrl)==4 else (255,111,125)
        d=box(x+151,y+267,x+w-12,y+301,CYAN,(6,26,57),8,5,1)
        writing(d,'NEXT '+opponents+' /',x+158,y+272,220,18,WHITE,11)
        d.rounded_rectangle((x+w-108,y+272,x+w-17,y+296),radius=6,fill=(*color,255))
        writing(d,'FDR '+ '/'.join(map(str,fdrl)),x+w-106,y+273,87,18,(4,22,31),11,'center')

    d=box(24,788,1512,852,PURPLE,(3,13,42),20,10)
    d.line((768,799,768,842),fill=(*CYAN,195),width=2)
    d.ellipse((91,803,130,842),fill=(*CYAN,255))
    d.polygon([(99,820),(125,808),(117,832),(111,823),(105,830)],fill=(*WHITE,255))
    writing(d,'TELEGRAM',144,803,155,27,CYAN,18)
    writing(d,'t.me/'+telegram.lstrip('@'),301,807,440,24,WHITE,15)
    d.ellipse((869,803,909,843),fill=(*PURPLE,255))
    writing(d,'DISCORD',922,803,142,27,CYAN,18)
    writing(d,discord,1068,807,412,24,WHITE,15)
    # Do not call apply_footer: that legacy helper overpaints this neon
    # footer with an opaque white bar, exactly the regression in Image 1.
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_suffix('.neon.tmp.png')
    canvas.convert('RGB').resize((1920,1080),Image.Resampling.LANCZOS).save(
        temp,'PNG',optimize=True)
    with Image.open(temp) as check:
        if check.size!=(1920,1080):raise RuntimeError('Invalid final six-up dimension')
        check.verify()
    temp.replace(output)
    return output
