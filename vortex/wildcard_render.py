"""Render the Wildcard CSS pitch with a matching five-gameweek fixture panel."""
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from html import escape
from io import BytesIO
from pathlib import Path
from shutil import which
from subprocess import TimeoutExpired, run
from tempfile import TemporaryDirectory

from .autonomous_schedule import ET
from .editorial_inputs import RequiredInput
from .matchup import _media
from .minimal_theme import extra_social_handles
from .publication_rules import required_footer_handles
from .vortex_style import LION
from .wildcard import POSITION_LABEL

CSS = Path(__file__).with_name('wildcard.css')


def png_uri(image):
    buffer = BytesIO()
    image.thumbnail((180, 180))
    image.save(buffer, 'PNG')
    return 'data:image/png;base64,' + b64encode(buffer.getvalue()).decode('ascii')


def build_html(plan, snapshot, session):
    data = plan.extra
    players = {p['id']: p for p in plan.players}
    with ThreadPoolExecutor(max_workers=8) as pool:
        portraits = dict(zip(players, pool.map(
            lambda p: _media(session, snapshot.photo_code(p), 'photo', {}), players.values())))
    if any(image is None for image in portraits.values()):
        raise RequiredInput('Official player portrait unavailable for the Wildcard graphic')
    telegram, discord = required_footer_handles()
    youtube, x_handle = extra_social_handles()
    logo = b64encode((LION.parent / 'midfield-watch-logo.png').read_bytes()).decode('ascii')

    def card(pid):
        p = players[pid]
        badge = ('<em>C</em>' if data['captain'] == pid else '<em>VC</em>' if data['vice'] == pid else '')
        return (f'<article class="player">{badge}<img src="{png_uri(portraits[pid])}" alt="">'
                f'<strong>{escape(snapshot.name(p))}</strong><small>'
                f'{escape(snapshot.team(p))} · {escape(snapshot.price(p))}</small></article>')

    pitch = ''.join('<div class="line">' + ''.join(card(pid) for pid in data['xi']
                   if players[pid]['element_type'] == position) + '</div>' for position in POSITION_LABEL)
    bench = ''.join(card(pid) for pid in data['bench'])
    columns = f"grid-template-columns: 174px repeat({len(data['weeks'])}, minmax(0, 1fr))"
    headers = '<div class="row labels"><span>PLAYER</span>' + ''.join(
        f'<span>GW{week}</span>' for week in data['weeks']) + '</div>'
    table = []
    for pid in data['xi'] + data['bench']:
        p = players[pid]
        cells = []
        for week in data['weeks']:
            fixtures = [f for f in data['fixtures'][str(pid)] if f['gw'] == week]
            tiles = ''.join(
                '<div class="blank">BLANK</div>' if f['blank'] else
                f'<div class="fdr fdr-{f["fdr"]}"><span>{escape(f["opponent"])} ({escape(f["venue"])})</span>'
                f'<b>{f["fdr"]}</b></div>' for f in fixtures
            )
            cells.append(f'<div class="matches">{tiles}</div>')
        table.append(f'<div class="row"><span class="name">{escape(snapshot.name(p))}</span>'
                     + ''.join(cells) + '</div>')
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<style>{CSS.read_text()} .row {{ {columns}; }}</style>
<body><header><img src="data:image/png;base64,{logo}" alt="FPL VORTEX">
<div><p>FIVE-GAMEWEEK SQUAD PLANNER</p><h1>{escape(plan.title)}</h1></div>
<aside><small>SQUAD COST</small><strong>£{data['cost']/10:.1f}m</strong></aside></header>
<main><section><h2>STARTING XI <span>{escape(data['formation'])}</span></h2>
<div class="pitch"><div class="field"></div>{pitch}</div>
<h2>BENCH <span>GK + SUBS</span></h2><div class="bench">{bench}</div></section>
<section class="fixtures"><h2>FIXTURE DIFFICULTY <span>OFFICIAL FPL FDR</span></h2>
{headers}{''.join(table)}
<p class="legend"><b>1</b> EASIEST <b>5</b> HARDEST · H HOME · A AWAY</p></section></main>
<footer><span>TELEGRAM t.me/{escape(telegram.lstrip('@'))}<br>{escape('YOUTUBE ' + youtube) if youtube else ''}</span>
<div>{escape(data['method'])}<small>{snapshot.fetched_at.astimezone(ET):%d %b %Y · %H:%M %Z}
{' · Forecasts are estimates' if data['model'] else ''}</small></div>
<span>DISCORD {escape(discord)}<br>{escape('X ' + x_handle) if x_handle else ''}</span></footer></body></html>"""


def render_wildcard(plan, snapshot, output, session):
    browser = next((path for name in ('google-chrome', 'chromium', 'chromium-browser')
                    if (path := which(name))), None)
    if browser is None:
        raise RequiredInput('Chrome or Chromium is required for the Wildcard CSS graphic')
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='fpl-wildcard-') as directory:
        root = Path(directory)
        source = root / 'wildcard.html'
        screenshot = root / 'wildcard.png'
        source.write_text(build_html(plan, snapshot, session), encoding='utf-8')
        try:
            result = run([browser, '--headless', '--no-sandbox', '--disable-dev-shm-usage',
                          '--disable-background-networking', '--hide-scrollbars', '--force-device-scale-factor=1',
                          f'--user-data-dir={root / "profile"}', '--window-size=1920,1080',
                          f'--screenshot={screenshot}', source.as_uri()],
                         capture_output=True, timeout=45)
        except TimeoutExpired as exc:
            raise RequiredInput('Chrome timed out rendering Wildcard pitch') from exc
        if result.returncode or not screenshot.is_file():
            raise RequiredInput(f'Chrome did not render Wildcard pitch (exit {result.returncode})')
        output.write_bytes(screenshot.read_bytes())
    return output
