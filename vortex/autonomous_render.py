"""Deterministic branded art from verified plans. No LLM/image prompt needed."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageOps
import requests

from .comparison_board import text,paragraph,panel,contain,compact_table,WHITE,GOLD,CYAN,NAVY,TABLE_INK,font
from .brand_footer import MASTER,apply_footer,verify_exact_master
from .matchup import _media
from .publication_rules import five_gw_fixtures,player_metrics,required_footer_handles
from .publish_checks import render_checked
from .autonomous_content import as_content
from .editorial_inputs import eo_for, RequiredInput


def _eo_label(plan, player):
    try:
        return f"{eo_for(plan.extra["model"], player["id"]):.1f}%"
    except RequiredInput:
        return "Unavailable"


def _base(title,gw):
    verify_exact_master()
    with Image.open(MASTER) as source: canvas=source.convert('RGB').resize((1536,864))
    d=ImageDraw.Draw(canvas,'RGBA')
    text(d,title,300,7,1055,34,WHITE,20,center=True)
    text(d,f'GW{gw} • VERIFIED MINUTES • FIXTURES • DECISIONS',340,55,1030,19,CYAN,16,center=True)
    return canvas


def _assets(snapshot,p,client,cache):
    portrait=_media(client,snapshot.photo_code(p),'photo',cache)
    badge=_media(client,snapshot.team_code(p),'crest',cache)
    if portrait is None or badge is None: raise RuntimeError('Verified portrait/club crest unavailable for official player '+str(p['id']))
    return portrait,badge


def _save(canvas,path,footer=True):
    path.parent.mkdir(parents=True,exist_ok=True)
    canvas.resize((1920,1080),Image.Resampling.LANCZOS).save(path,'PNG',optimize=True)
    return apply_footer(path) if footer else path


def _strip(draw,rows,x,y,width):
    weeks=sorted(set(r['gw'] for r in rows))[:5]
    colors={1:'#00be86',2:'#6bcf9c',3:'#ffd477',4:'#f3a36d',5:'#ef6975'}
    for i,gw in enumerate(weeks):
        items=[r for r in rows if r['gw']==gw]
        label='/'.join(r['opponent'] for r in items)
        venue='/'.join(r['venue'] for r in items)
        fdr=[r['fdr'] for r in items if r.get('fdr') in colors]
        left=x+i*width/5;cw=width/5-4
        draw.rounded_rectangle((left,y,left+cw,y+49),radius=4,fill=NAVY,outline=colors[max(fdr)] if fdr else '#718096',width=2)
        text(draw,f'GW{gw}',left+3,y+2,cw-6,13,WHITE,10,center=True)
        text(draw,label,left+3,y+17,cw-6,16,WHITE,10,center=True)
        text(draw,venue,left+3,y+35,cw-6,11,WHITE,9,center=True)


def _six(plan,snapshot,now,output,client):
    canvas=_base(plan.title,plan.gw);cache={}
    for i,p in enumerate(plan.players):
        x=32+(i%3)*494;y=115+(i//3)*337
        d=ImageDraw.Draw(canvas,'RGBA');panel(d,(x,y,x+480,y+325),GOLD if i<4 else CYAN)
        text(d,plan.labels[i],x+12,y+8,456,21,GOLD,17,center=True)
        text(d,snapshot.name(p),x+12,y+38,456,27,WHITE,21,center=True)
        photo,badge=_assets(snapshot,p,client,cache)
        contain(canvas,photo,(x+8,y+79,155,181),bottom=True,crop_alpha=True)
        contain(canvas,badge,(x+117,y+75,43,43))
        d=ImageDraw.Draw(canvas,'RGBA');m=player_metrics(snapshot,p)
        rows=[('PRICE / OWN',m['PRICE']+' / '+m['OWNERSHIP']),('MIN / PTS',m['MINUTES']+' / '+m['TOTAL PTS']),
              ('FORM',m['FORM'])]
        if 'xG' in m and 'xA' in m:rows.append(('xG / xA',str(m['xG'])+' / '+str(m['xA'])))
        elif 'SAVES' in m:rows.append(('SAVES',m['SAVES']))
        elif 'CS' in m:rows.append(('CLEAN SHEETS',m['CS']))
        compact_table(d,rows,(x+171,y+87,x+466,y+226))
        text(d,'MONITOR • VERIFY TEAM NEWS',x+166,y+235,300,17,CYAN,13,center=True)
        _strip(d,five_gw_fixtures(snapshot,p),x+12,y+264,456)
    return _save(canvas,output)


def _teams(plan,snapshot,output,client):
    canvas=_base(plan.title,plan.gw);cache={}
    for i,row in enumerate(plan.extra['teams']):
        x=32+i*374;d=ImageDraw.Draw(canvas,'RGBA');panel(d,(x,120,x+358,790),CYAN if i<2 else GOLD)
        text(d,plan.extra['categories'][i]+' TARGET',x+10,132,338,22,GOLD,18,center=True)
        club=row['club'];badge=_media(client,club['code'],'crest',cache)
        if badge is None:raise RuntimeError('Verified team crest unavailable')
        contain(canvas,badge,(x+132,175,92,92));d=ImageDraw.Draw(canvas,'RGBA')
        text(d,club['name'],x+12,280,334,26,WHITE,20,center=True)
        current=row['current'];goals=sum(r['projected_goals'] for r in current)
        cs=sum(r['clean_sheet_pct'] for r in current)/len(current)
        rows=[('PROJECTED GOALS',f'{goals:.2f}'),('CLEAN SHEET',f'{cs:.1f}%'),
              ('ATTACK FDR',f"{sum(r['attacking_fdr'] for r in current)/len(current):.2f}"),
              ('DEFENCE FDR',f"{sum(r['defensive_fdr'] for r in current)/len(current):.2f}")]
        compact_table(d,rows,(x+12,328,x+346,480))
        text(d,'NEXT FIVE • CUSTOM FDR',x+12,500,334,20,CYAN,16,center=True)
        for n,r in enumerate(row['fixtures'][:7]):
            opponent=snapshot.teams[r['opponent_id']]['short_name']
            value=r['attacking_fdr' if i<2 else 'defensive_fdr']
            text(d,f"GW{r['gw']} {opponent} ({r['venue']}) • {value:.2f}",x+18,535+n*28,322,20,WHITE,15)
        paragraph(d,'TARGET ATTACKERS' if i<2 else 'MONITOR DEFENDERS / GK',(x+15,750,328),19,GOLD,1)
    return _save(canvas,output)


def _surgery(plan,snapshot,output,client):
    canvas=_base(plan.title,plan.gw);cache={}
    for i,p in enumerate(plan.players):
        x=30+i*375;d=ImageDraw.Draw(canvas,'RGBA');panel(d,(x,120,x+360,790),CYAN if i%2 else GOLD)
        text(d,plan.labels[i],x+12,133,336,24,GOLD,18,center=True)
        photo,badge=_assets(snapshot,p,client,cache)
        contain(canvas,photo,(x+86,180,180,160),bottom=True,crop_alpha=True)
        contain(canvas,badge,(x+284,190,48,48));d=ImageDraw.Draw(canvas,'RGBA')
        text(d,snapshot.name(p),x+12,350,336,25,WHITE,18,center=True)
        fixtures=five_gw_fixtures(snapshot,p);nextf=fixtures[0]
        evidence=[f"{snapshot.price(p)} • OWN {p['selected_by_percent']}%",f"FORM {p['form']} • {p['minutes']} season minutes",
                  f"NEXT {nextf['opponent']} ({nextf['venue']}) • FDR {nextf['fdr']}"]
        for n,line in enumerate(evidence):text(d,line,x+14,392+n*31,332,18,WHITE,14)
        answers=[
            'BUY only if this improves your own squad and fits your bank. Check the confirmed lineup before moving.',
            'HOLD a fit starter with a favourable run. ROLL if the alternative is marginal; keep transfer flexibility.',
            'A transfer hit costs 4 points. No verified incremental forecast means this board cannot justify a hit. Use a free transfer or wait.',
            'PLAN the next five fixtures. Preserve budget and position balance; check blanks/doubles before using a chip.']
        paragraph(d,answers[i],(x+16,510,328),21,WHITE,7)
        _strip(d,fixtures,x+12,730,336)
    return _save(canvas,output)


def _targets(plan,snapshot,output,client):
    canvas=_base(plan.title,plan.gw);cache={}
    for i,p in enumerate(plan.players):
        x=31+i*374;d=ImageDraw.Draw(canvas,'RGBA');panel(d,(x,120,x+358,790),CYAN if i%2 else GOLD)
        text(d,plan.labels[i]+' • '+snapshot.name(p),x+12,132,334,25,GOLD,18,center=True)
        photo,badge=_assets(snapshot,p,client,cache)
        contain(canvas,photo,(x+75,175,200,140),bottom=True,crop_alpha=True)
        contain(canvas,badge,(x+283,180,54,54));d=ImageDraw.Draw(canvas,'RGBA')
        recent=plan.extra['recent'][str(p['id'])]
        rows=[('POSITION',{1:'GK',2:'DEF',3:'MID',4:'FWD'}[p['element_type']]),('PRICE',snapshot.price(p)),
              ('OWNERSHIP',str(p['selected_by_percent'])+'%'),('EFFECTIVE OWN',f"{plan.extra['eo'][str(p['id'])]:.1f}%"),
              ('SEASON MIN',str(p['minutes'])),('LAST 3 PTS',str(sum(int(r.get('total_points')or 0) for r in recent)))]
        compact_table(d,rows,(x+12,333,x+346,516))
        metrics=player_metrics(snapshot,p)
        if p['element_type']==1: keys=('SAVES','CS','xGC')
        elif p['element_type']==2: keys=('DC ACTIONS','CS','xG','xA')
        else: keys=('GOALS','ASSISTS','xG','xA')
        role=[(key,metrics[key]) for key in keys if key in metrics]
        if p['element_type'] in (3,4):
            minutes=float(p['minutes'])
            if p.get('expected_goals') is None or p.get('expected_assists') is None:
                raise RequiredInput('Verified expected goals/assists unavailable for role table')
            role=[('xG / 90',f"{float(p['expected_goals'])/minutes*90:.2f}"),
                  ('xA / 90',f"{float(p.get('expected_assists')or 0)/minutes*90:.2f}"),
                  ('xGI / 90',f"{(float(p.get('expected_goals')or 0)+float(p.get('expected_assists')or 0))/minutes*90:.2f}")]
        if not role: raise RequiredInput('Verified position-specific role metrics unavailable')
        compact_table(d,role,(x+12,539,x+346,685))
        text(d,'NEXT FIVE FIXTURES',x+12,701,334,18,CYAN,14,center=True)
        _strip(d,five_gw_fixtures(snapshot,p),x+12,731,334)
    return _save(canvas,output)


def _market(plan,snapshot,output,client):
    pages=[];cache={};by_id={p['id']:p for p in plan.players};labels=dict(zip([p['id'] for p in plan.players],plan.labels))
    for group_index,ids in enumerate(plan.extra['groups']):
        with Image.open(MASTER) as src: master=src.convert('RGB').resize((1536,864))
        canvas=Image.new('RGB',(1080,1920),'#03172d')
        # Background is cropped, never stretched; original header/footer
        # logos are pasted with a uniform scale.
        texture=ImageOps.fit(master.crop((300,180,1230,760)),(1080,1788))
        canvas.paste(texture,(0,85));canvas.paste(master.crop((0,0,1536,120)).resize((1080,84)),(0,0))
        canvas.paste(master.crop((0,800,1536,864)).resize((1080,45)),(0,1875))
        d=ImageDraw.Draw(canvas,'RGBA');d.rectangle((210,0,925,82),fill='#03172d')
        text(d,'MARKET VERDICTS • '+('GK','DEF','MID','FWD')[group_index],220,18,690,29,WHITE,23,center=True)
        text(d,f'GW{plan.gw} • VERIFIED TRANSFERS • NEXT FIVE',35,102,1010,30,GOLD,24,center=True)
        row_height=1660/len(ids)
        for i,pid in enumerate(ids):
            p=by_id[pid];top=160+i*row_height;height=row_height-16
            if len(ids)==1:
                d=ImageDraw.Draw(canvas,'RGBA');panel(d,(24,top,1056,top+height),GOLD)
                text(d,snapshot.name(p),55,top+22,970,54,WHITE,40,center=True)
                photo,badge=_assets(snapshot,p,client,cache)
                contain(canvas,photo,(285,top+128,510,660),bottom=True,crop_alpha=True)
                contain(canvas,badge,(850,top+150,115,115));d=ImageDraw.Draw(canvas,'RGBA')
                rows=[('PRICE',snapshot.price(p)),('OWNERSHIP',str(p['selected_by_percent'])+'%'),
                      ('EFFECTIVE OWN',_eo_label(plan,p)),('MINUTES',str(p['minutes'])),
                      ('CLEAN SHEETS',str(p['clean_sheets']) if p.get('clean_sheets') is not None else 'N/A'),
                      ('SAVES',str(p['saves']) if p.get('saves') is not None else 'N/A'),('VERDICT',labels[pid])]
                compact_table(d,rows,(90,top+845,990,top+1165))
                text(d,f"GW IN {p.get('transfers_in_event',0):,} • OUT {p.get('transfers_out_event',0):,}",70,top+1200,940,31,GOLD,25,center=True)
                rows=plan.extra['model']['teams'][str(p['team'])]['fixtures']
                for n,r in enumerate(rows[:5]):
                    opp=snapshot.teams[r['opponent_id']]['short_name'];left=60+n*194
                    text(d,f"GW{r['gw']} {opp}({r['venue']})",left,top+1290,185,26,WHITE,19,center=True)
                    text(d,f"FDR {r['defensive_fdr']:.2f}",left,top+1330,185,27,CYAN,21,center=True)
                paragraph(d,'MONITOR availability and the next five fixtures before changing goalkeeper.',(75,top+1440,930),30,WHITE,3)
                continue
            d=ImageDraw.Draw(canvas,'RGBA');panel(d,(24,top,1056,top+height),CYAN)
            photo,badge=_assets(snapshot,p,client,cache)
            contain(canvas,photo,(40,top+56,170,min(height-84,250)),bottom=True,crop_alpha=True)
            contain(canvas,badge,(960,top+24,66,66));d=ImageDraw.Draw(canvas,'RGBA')
            text(d,snapshot.name(p),225,top+18,710,38,WHITE,28)
            text(d,f"{snapshot.price(p)} • OWN {p['selected_by_percent']}% • {labels[pid]}",225,top+72,710,27,GOLD,22)
            text(d,f"GW IN {int(p.get('transfers_in_event')or 0):,} • OUT {int(p.get('transfers_out_event')or 0):,}",225,top+116,775,24,WHITE,19)
            text(d,'LAST 3: 70+ MIN EACH • EO '+_eo_label(plan,p),225,top+154,775,21,WHITE,17)
            rows=(plan.extra['model']['teams'][str(p['team'])]['fixtures'])
            key='defensive_fdr' if p['element_type'] in (1,2) else 'attacking_fdr'
            for n,r in enumerate(rows[:5]):
                opp=snapshot.teams[r['opponent_id']]['short_name'];left=225+n*155
                text(d,f"GW{r['gw']} {opp}({r['venue']})",left,top+205,150,19,WHITE,14,center=True)
                text(d,f"FDR {r[key]:.2f}",left,top+236,150,22,CYAN,17,center=True)
        telegram,discord=required_footer_handles();d=ImageDraw.Draw(canvas,'RGBA')
        d.rectangle((0,1810,1080,1875),fill='#03172d')
        text(d,'TELEGRAM t.me/'+telegram.lstrip('@')+'  •  DISCORD '+discord,22,1826,1036,26,WHITE,18,center=True)
        path=output.with_name(output.stem+f'-{group_index+1}.png');path.parent.mkdir(parents=True,exist_ok=True)
        canvas.save(path,'PNG',optimize=True);pages.append(path)
    return pages


def _value(plan,snapshot,output,client):
    canvas=_base(plan.title,plan.gw);cache={}
    for pos in (1,2,3,4):
        x=30+(pos-1)*375;d=ImageDraw.Draw(canvas,'RGBA');panel(d,(x,120,x+360,790),CYAN if pos%2 else GOLD)
        text(d,('GK','DEF','MID','FWD')[pos-1],x+12,136,336,28,GOLD,22,center=True)
        players=[p for p in plan.players if p['element_type']==pos]
        for i,p in enumerate(players):
            top=185+i*193;photo,badge=_assets(snapshot,p,client,cache)
            contain(canvas,photo,(x+12,top+24,100,145),bottom=True,crop_alpha=True)
            contain(canvas,badge,(x+305,top+8,38,38));d=ImageDraw.Draw(canvas,'RGBA')
            text(d,snapshot.name(p),x+122,top+6,216,23,WHITE,17)
            forecast=plan.extra['values'][str(p['id'])]
            rows=[('PRICE',snapshot.price(p)),('MODEL xPTS',f"{forecast['xpts']:.2f}"),('CUSTOM FDR',f"{forecast['fdr']:.2f}"),('OWN',str(p['selected_by_percent'])+'%')]
            compact_table(d,rows,(x+122,top+45,x+344,top+166))
    return _save(canvas,output)


def _market15(plan,snapshot,output,client):
    canvas=_base(plan.title,plan.gw);d=ImageDraw.Draw(canvas,'RGBA');cache={}
    columns=[('PLAYER',270),('CLUB',70),('PRICE',100),('OWN %',100),('GW IN',150),('GW OUT',150),('NEXT',230),('VERDICT',200)]
    x0=40;top=124;row_h=41
    from .comparison_board import TABLE_YELLOW,TABLE_RULE
    d.rectangle((x0,top,1495,top+row_h*16),fill=TABLE_YELLOW)
    for i,(label,width) in enumerate(columns):
        x=x0+sum(w for _,w in columns[:i]);text(d,label,x+5,top+9,width-10,19,TABLE_INK,14)
    for row,(p,label) in enumerate(zip(plan.players,plan.labels)):
        y=top+(row+1)*row_h;d.line((x0,y,1495,y),fill=TABLE_RULE,width=1)
        fixtures=snapshot.fixtures_for_gameweek(p)
        next_text='/'.join(f'{opp}({venue})' for opp,venue,_,_ in fixtures)
        values=[snapshot.name(p),'',snapshot.price(p),str(p['selected_by_percent']),f"{p['transfers_in_event']:,}",f"{p['transfers_out_event']:,}",next_text,label]
        for i,((_,width),value) in enumerate(zip(columns,values)):
            x=x0+sum(w for _,w in columns[:i]);text(d,value,x+5,y+8,width-10,21,TABLE_INK,14)
        badge=_media(client,snapshot.team_code(p),'crest',cache)
        if badge is None:raise RuntimeError('Verified market-board crest unavailable')
        contain(canvas,badge,(315,y+3,32,32));d=ImageDraw.Draw(canvas,'RGBA')
    text(d,'POPULARITY IS A SIGNAL • CHECK MINUTES, AVAILABILITY AND THE NEXT FIVE FIXTURES',42,799,1445,18,GOLD,14,center=True)
    return _save(canvas,output)


def _deadline(plan,snapshot,output,client):
    from datetime import datetime
    from .deadline_watch import clock,ET,UK
    from .comparison_board import comparison_board,current_fixture
    cache={};profiles=[]
    for p,label in zip(plan.players,plan.labels):
        photo,badge=_assets(snapshot,p,client,cache)
        recent=plan.extra['recent'][str(p['id'])]
        metrics=player_metrics(snapshot,p,recent)
        fixtures=five_gw_fixtures(snapshot,p)
        profile={'name':snapshot.name(p),'club':snapshot.teams[p['team']]['name'],
                 'position':metrics['POSITION'],'metrics':metrics,'fixtures':fixtures,
                 'portrait':photo,'badge':badge,'label':label,'action':'MONITOR',
                 'reason':str(p.get('news') or 'Confirm the latest lineup before deadline.')}
        if p.get('status')!='a':
            chance=p.get('chance_of_playing_next_round')
            opponent,fdr=current_fixture(fixtures,plan.gw)
            profile['summary_rows']=[('PRICE',snapshot.price(p)),('STATUS',{'i':'INJURED','d':'DOUBTFUL','s':'SUSPENDED','u':'UNAVAILABLE'}.get(p['status'],'MONITOR')),
                ('NEXT GW CHANCE',str(chance)+'%' if type(chance) is int else 'Unconfirmed'),
                ('FIXTURE',opponent),('FDR',fdr)]
        profiles.append(profile)
    with Image.open(MASTER) as source:
        canvas=comparison_board(source,plan.title,plan.gw,profiles,
            verdict='WAIT FOR VERIFIED TEAM NEWS • CONFIRM THE ARMBAND BEFORE DEADLINE')
    deadline=datetime.fromisoformat(plan.extra['deadline'])
    d=ImageDraw.Draw(canvas,'RGBA');d.rectangle((300,46,1340,74),fill=NAVY)
    text(d,'DEADLINE: '+clock(deadline,ET)+'  |  '+clock(deadline,UK),310,49,1020,19,CYAN,15,center=True)
    return _save(canvas,output)


def render(plan,snapshot,now,output,session=None):
    client=session or requests.Session()
    if plan.kind=='deadline':return [_deadline(plan,snapshot,output,client)]
    if plan.kind=='six':return [_six(plan,snapshot,now,output,client)]
    if plan.kind=='teams':return [_teams(plan,snapshot,output,client)]
    if plan.kind=='surgery':return [_surgery(plan,snapshot,output,client)]
    if plan.kind=='targets':return [_targets(plan,snapshot,output,client)]
    if plan.kind=='market':return _market(plan,snapshot,output,client)
    if plan.kind=='value':return [_value(plan,snapshot,output,client)]
    if plan.kind=='market15':return [_market15(plan,snapshot,output,client)]
    if plan.kind=='legacy':
        from .extra_posts import ExtraPost
        return [render_checked(ExtraPost(**plan.extra['content']),snapshot,output,session=client)]
    article=as_content(plan,snapshot,now)
    return [render_checked(article,snapshot,output,session=client)]
