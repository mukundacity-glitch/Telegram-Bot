"""Active graphic IDs, compacted after explicitly approved mergers."""
from pathlib import Path
from shutil import copyfile
from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

PRESS_REPORT_KEY = 'verified-press-availability'  # stable edition identity

CATALOG = (
    'elite', 'daily_stats', 'form-minutes-targets', 'defender-watch',
    'goalkeeper-striker-watch', 'player-radar-comparison', 'weekly-analysis',
    'afternoon-rotation', 'scouting-rotation', 'positional-vulnerability',
    'review', 'sell', PRESS_REPORT_KEY, 'monday-defence-watch',
    'vortex-captain', 'price-prediction', 'chip-strategy',
    'passing-creators', 'bonus-magnets', 'top-100k-ownership', 'assists-vs-shot-quality',
    'chance-creators', 'captaincy-comparison', 'value-board', 'start-bench-board',
    'final-gameweek-news', 'market-trends-next-five',
    *(f'weekly-analysis-{day}' for day in range(2, 8)),
    *(f'afternoon-rotation-{day}' for day in range(2, 8)),
    *(f'scouting-rotation-{day}' for day in range(2, 8)),
    'tuesday-set-pieces', 'wednesday-predicted-xg',
    'friday-rotation-planner', 'saturday-fdr-grid', 'sunday-chance-watch',
    'news-rotation-planner',
)


# The two-club Friday board was replaced by the weekly four-club news route.
# Reserve its historical number until the Telegram cleanup; never dispatch it.
RESERVED_CATALOG = frozenset({'friday-rotation-planner'})
ACTIVE_CATALOG = tuple(key for key in CATALOG if key not in RESERVED_CATALOG)

def graphic_key(edition, weekday, series_day=None, page=0):
    if edition == 'goalkeeper-striker-watch' and page != 0:
        return None
    if edition in ('afternoon-rotation', 'scouting-rotation') and weekday:
        return f'{edition}-{weekday + 1}'
    if edition == 'weekly-analysis' and series_day in range(2, 8):
        return f'{edition}-{series_day}'
    return edition if edition in ACTIVE_CATALOG else None


def stamp(path, key, destination=None, *, required=False):
    """Reserve a header above the complete artwork and keep the upload dimensions."""
    path = Path(path)
    # Uncatalogued custom artwork never receives a scheduled edition number.
    if key not in ACTIVE_CATALOG:
        if required:
            raise ValueError(f'No permanent graphic number registered for {key!r}')
        return path
    label = f'{CATALOG.index(key) + 1}/{len(CATALOG)}'
    target = Path(destination) if destination is not None else path
    with Image.open(path) as source:
        if source.info.get('vortex_graphic_number') == label:
            if target != path:
                target.parent.mkdir(parents=True, exist_ok=True)
                copyfile(path, target)
            return target
        width, height = source.size
        band = max(32, round(min(width, height) * .045))
        previous = source.info.get('vortex_graphic_number')
        if previous and isinstance(previous, str):
            # Existing VORTEX numbering already reserved the header. Replace
            # that band in place, never shrink a previously stamped image.
            parts = previous.split('/')
            if len(parts) != 2 or not all(part.isdecimal() for part in parts) or not 1 <= int(parts[0]) <= int(parts[1]):
                raise ValueError('Invalid prior VORTEX graphic number')
            frame = source.convert('RGB')
            ImageDraw.Draw(frame).rectangle((0, 0, width-1, band-1), fill='#090e28')
        else:
            art_height = height - band
            art_width = max(1, round(width * art_height / height))
            frame = Image.new('RGB', source.size, '#090e28')
            art = source.convert('RGBA').resize((art_width, art_height), Image.Resampling.LANCZOS)
            frame.paste(art, ((width-art_width)//2, band), art)
    draw = ImageDraw.Draw(frame)
    font = ImageFont.truetype('DejaVuSans-Bold.ttf', round(band * .70))
    draw.text((width-16, band//2), label, font=font, anchor='rm', fill='#87f9ff')
    info = PngInfo()
    info.add_text('vortex_graphic_number', label)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.save(target, format='PNG', pnginfo=info)
    return target
