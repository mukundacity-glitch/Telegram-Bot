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
    from PIL import Image,ImageDraw
    from .comparison_board import text,contain
    from .brand_footer import MASTER,verify_exact_master,apply_footer
    verify_exact_master()
    bg='#0B1420';card='#142130';rule='#2B3A48';white='#F3F3EE';muted='#A7B4BF';accent='#B4D9C8'
    canvas=Image.new('RGB',(1536,864),bg)
    with Image.open(MASTER) as master:
        master=master.convert('RGB').resize((1536,864))
        canvas.paste(master.crop((0,0,238,63)),(0,0))
        canvas.paste(master.crop((1362,0,1536,64)),(1362,0))
    d=ImageDraw.Draw(canvas,'RGBA')
    text(d,plan.title,270,8,1050,38,white,30,center=True)
    text(d,f'GW{plan.gw}  /  UNDER 10% OWNED  /  NEXT GAMEWEEK',270,57,1050,18,muted,16,center=True)
    d.line((30,96,1506,96),fill=rule,width=1)
    cache={}
    for i,p in enumerate(plan.players):
        x=30+(i%3)*496;y=119+(i//3)*336;w=484;h=320
        detail=plan.extra['details'][str(p['id'])];metrics=detail['metrics']
        d=ImageDraw.Draw(canvas,'RGBA');d.rounded_rectangle((x,y,x+w,y+h),radius=14,fill=card,outline=rule,width=1)
        position={1:'GK',2:'DEF',3:'MID',4:'FWD'}[p['element_type']]
        text(d,f'{i+1:02d}   {position} / {snapshot.team(p)}',x+16,y+12,w-85,17,muted,15)
        text(d,snapshot.name(p).upper(),x+16,y+41,w-85,28,white,21)
        portrait,badge=assets(snapshot,p,session,cache)
        contain(canvas,portrait,(x+8,y+89,130,170),bottom=True,crop_alpha=True)
        contain(canvas,badge,(x+w-60,y+16,39,39));d=ImageDraw.Draw(canvas,'RGBA')
        text(d,f"{detail['fpl_ep_next']:.2f}",x+155,y+77,140,38,accent,32)
        text(d,'FPL FORECAST',x+155,y+121,145,13,muted,12)
        text(d,snapshot.price(p),x+328,y+85,140,25,white,20)
        text(d,str(p['selected_by_percent'])+'% OWNED',x+328,y+119,140,14,muted,12)
        d.line((x+151,y+149,x+w-16,y+149),fill=rule,width=1)
        if p['element_type']==1:
            role=[('SAVES',metrics.get('SAVES','—')),('CLEAN SHEETS',metrics.get('CS','—'))]
        elif p['element_type']==2:
            role=[('CLEAN SHEETS',metrics.get('CS','—')),('DC ACTIONS',metrics.get('DC ACTIONS','—'))]
        else:
            minutes=number(p.get('minutes'));xg=number(p.get('expected_goals'));xa=number(p.get('expected_assists'))
            role=[('xG / 90',f'{xg/minutes*90:.2f}' if minutes and xg is not None else '—'),
                  ('xA / 90',f'{xa/minutes*90:.2f}' if minutes and xa is not None else '—')]
        count=detail['appearances']
        rows=[('FORM',metrics['FORM']),('SEASON PTS',metrics['TOTAL PTS']),
              (f'LAST {count} PTS' if count else 'RECENT PTS',f"{detail['l3_points']:.0f}" if detail['l3_points'] is not None else '—'),
              (f'LAST {count} MIN' if count else 'RECENT MIN',f"{detail['l3_minutes']:.0f}" if detail['l3_minutes'] is not None else '—')]+role
        for n,(label,value) in enumerate(rows):
            left=x+155+(n%2)*164;top=y+158+(n//2)*39
            text(d,label,left,top,155,12,muted,11)
            text(d,value,left,top+14,155,21,white,17)
        text(d,metrics['MINUTES']+' SEASON MIN',x+12,y+263,135,13,muted,11,center=True)
        d.line((x+14,y+288,x+w-14,y+288),fill=rule,width=1)
        fixtures=detail['fixtures']
        opponent=' / '.join(f'{opp}({venue})' for opp,venue,_,_ in fixtures)
        fdr=' / '.join(str(r[2]) for r in fixtures)
        text(d,'NEXT '+opponent+'   /   FDR '+fdr,x+16,y+296,w-32,16,white,13)
    output.parent.mkdir(parents=True,exist_ok=True)
    canvas.resize((1920,1080),Image.Resampling.LANCZOS).save(output,'PNG',optimize=True)
    return apply_footer(output)
