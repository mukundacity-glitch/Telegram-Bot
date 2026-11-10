"""FPL VORTEX purple/gold broadcast style for portrait (1080x1920) market boards.

Pure drawing helpers: no network, no hard-coded handles, no invented data.
Everything is drawn at 2x and downsampled so rounded edges are smooth.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H, SS = 1080, 1920, 2
ROOT = Path(__file__).resolve().parents[1]
LION = ROOT / "assets" / "brand" / "vortex-lion.png"

GOLD = (255, 200, 72)
GOLD_DARK = (176, 118, 18)
INK = (24, 10, 52)
WHITE = (255, 255, 255)
PURPLE_PANEL = ((70, 26, 132), (30, 9, 66))

PILLS = {
    "BUY": ((38, 176, 92), (22, 128, 62), WHITE),
    "SELL": ((226, 54, 70), (168, 24, 40), WHITE),
    "HOLD": ((74, 132, 232), (46, 92, 190), WHITE),
    "MONITOR": ((236, 170, 40), (190, 124, 14), WHITE),
    "WATCHLIST": ((236, 170, 40), (190, 124, 14), WHITE),
}
# FDR scale used by the sample board: easy < 3.0, medium < 4.0, hard >= 4.0.
FDR_EASY, FDR_HARD = 3.0, 4.0


def _s(v: float) -> int:
    return int(round(v * SS))


def font(size: float, bold: bool = True) -> ImageFont.FreeTypeFont:
    names = (("DejaVuSansCondensed-Bold", "DejaVuSans-Bold", "LiberationSans-Bold") if bold
             else ("DejaVuSansCondensed", "DejaVuSans", "LiberationSans-Regular"))
    for name in names:
        for directory in ("dejavu", "liberation2", "liberation"):
            try:
                return ImageFont.truetype(f"/usr/share/fonts/truetype/{directory}/{name}.ttf", _s(size))
            except OSError:
                continue
    return ImageFont.load_default(size=_s(size))


def fit(draw: ImageDraw.ImageDraw, value: str, width: float, size: float, minimum: float = 14,
        bold: bool = True) -> ImageFont.FreeTypeFont:
    while size > minimum and draw.textlength(value, font=font(size, bold)) > _s(width):
        size -= 1
    return font(size, bold)


def clip_text(draw: ImageDraw.ImageDraw, value: str, face, width: float) -> str:
    value = " ".join(str(value).split())
    while value and draw.textlength(value, font=face) > _s(width):
        value = value[:-2].rstrip("… ") + "…" if len(value) > 2 else ""
    return value


def gradient(size: tuple[int, int], top, bottom) -> Image.Image:
    w, h = size
    column = Image.new("RGB", (1, h))
    column.putdata([tuple(round(top[i] + (bottom[i] - top[i]) * y / max(1, h - 1)) for i in range(3))
                    for y in range(h)])
    return column.resize((w, h))


def _glow(layer: Image.Image, radius: float, strength: float = 1.0) -> Image.Image:
    blurred = layer.filter(ImageFilter.GaussianBlur(_s(radius)))
    if strength != 1.0:
        alpha = blurred.getchannel("A").point(lambda a: min(255, int(a * strength)))
        blurred.putalpha(alpha)
    return blurred


def background() -> Image.Image:
    canvas = gradient((_s(W), _s(H)), (58, 18, 112), (12, 4, 30)).convert("RGBA")
    streaks = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(streaks)
    for pts, alpha in (
        ([(0, 330), (330, 0), (470, 0), (0, 470)], 70),
        ([(1080, 120), (1080, 420), (780, 0), (940, 0)], 85),
        ([(0, 1500), (0, 1920), (420, 1920)], 46),
        ([(1080, 1380), (1080, 1920), (700, 1920)], 52),
    ):
        d.polygon([(_s(x), _s(y)) for x, y in pts], fill=(150, 90, 230, alpha))
    canvas.alpha_composite(streaks.filter(ImageFilter.GaussianBlur(_s(14))))
    spark = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(spark)
    for cx, cy, r in ((1010, 150, 70), (60, 1860, 90), (1040, 1780, 60)):
        d.ellipse((_s(cx - r), _s(cy - r), _s(cx + r), _s(cy + r)), fill=(255, 214, 120, 120))
    canvas.alpha_composite(_glow(spark, 40))
    return canvas


def _italic(canvas: Image.Image, center: tuple[float, float], value: str, face, fill, shear: float = 0.2,
            shadow: tuple | None = None) -> None:
    probe = ImageDraw.Draw(canvas)
    box = probe.textbbox((0, 0), value, font=face)
    w, h = box[2] - box[0], box[3] - box[1]
    pad = _s(20)
    layer = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    if shadow:
        ld.text((pad - box[0] + _s(2), pad - box[1] + _s(3)), value, font=face, fill=shadow)
    ld.text((pad - box[0], pad - box[1]), value, font=face, fill=fill)
    layer = layer.transform(layer.size, Image.AFFINE, (1, shear, -shear * layer.height / 2, 0, 1, 0),
                            resample=Image.Resampling.BICUBIC)
    canvas.alpha_composite(layer, (round(_s(center[0]) - layer.width / 2), round(_s(center[1]) - layer.height / 2)))


def _hex_ribbon(box, notch: float):
    x0, y0, x1, y1 = box
    mid = (y0 + y1) / 2
    return [(x0 + notch, y0), (x1 - notch, y0), (x1, mid), (x1 - notch, y1), (x0 + notch, y1), (x0, mid)]


def ribbon(canvas: Image.Image, box, value: str, *, light: bool, size: float, minimum: float = 24) -> None:
    pts = [(_s(x), _s(y)) for x, y in _hex_ribbon(box, (box[3] - box[1]) * 0.34)]
    x0, y0, x1, y1 = (_s(v) for v in box)
    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    fill = (gradient((x1 - x0, y1 - y0), (252, 252, 255), (196, 192, 222)) if light
            else gradient((x1 - x0, y1 - y0), (60, 20, 118), (34, 10, 72)))
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(fill, (x0, y0))
    layer.putalpha(mask)
    outline = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(outline).line(pts + [pts[0]], fill=GOLD + (255,), width=_s(5), joint="curve")
    canvas.alpha_composite(_glow(outline, 8, 1.6))
    canvas.alpha_composite(layer)
    canvas.alpha_composite(outline)
    width = (box[2] - box[0]) * 0.80
    probe = ImageDraw.Draw(canvas)
    face = fit(probe, value, width, size, minimum)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2 - 1
    if light:
        _italic(canvas, (cx, cy), value, face, INK + (255,), 0.18, shadow=(120, 90, 190, 90))
    else:
        _italic(canvas, (cx, cy), value, face, WHITE + (255,), 0.14)


def header(canvas: Image.Image, title: str, subtitle: str) -> None:
    d = ImageDraw.Draw(canvas)
    if LION.is_file():
        lion = Image.open(LION).convert("RGBA")
        lion = lion.resize((_s(lion.width * 0.92), _s(lion.height * 0.92)), Image.Resampling.LANCZOS)
        canvas.alpha_composite(lion, (_s(318), _s(26)))
    face = font(58)
    fx = _s(416)
    d.text((fx, _s(30)), "FPL", font=face, fill=WHITE)
    fpl_w = d.textlength("FPL ", font=face)
    d.text((fx + fpl_w, _s(30)), "VORTEX", font=face, fill=GOLD)
    ribbon(canvas, (36, 122, 1044, 232), title, light=True, size=70, minimum=34)
    ribbon(canvas, (74, 246, 1006, 310), subtitle, light=False, size=34, minimum=22)


def deadline_strip(canvas: Image.Image, value: str) -> None:
    d = ImageDraw.Draw(canvas)
    face = fit(d, value, 960, 27, 17)
    w = d.textlength(value, font=face) / SS
    x0 = (W - w) / 2 - 26
    d.rounded_rectangle((_s(x0), _s(322), _s(x0 + w + 52), _s(358)), radius=_s(18), fill=(20, 6, 44, 235),
                        outline=GOLD, width=_s(2))
    d.text((_s((W - w) / 2), _s(327)), value, font=face, fill=GOLD)


def fdr_colors(value: float | None):
    if value is None:
        return (200, 200, 215), (150, 150, 170), INK
    if value < FDR_EASY:
        return (140, 214, 255), (74, 164, 244), (8, 38, 92)
    if value < FDR_HARD:
        return (255, 156, 200), (240, 104, 164), (92, 8, 52)
    return (226, 30, 40), (168, 0, 12), WHITE


def _rounded_gradient(canvas, box, radius, top, bottom, outline=None, width=0):
    x0, y0, x1, y1 = (_s(v) for v in box)
    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((x0, y0, x1, y1), radius=_s(radius), fill=255)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(gradient((x1 - x0, y1 - y0), top, bottom), (x0, y0))
    layer.putalpha(mask)
    canvas.alpha_composite(layer)
    if outline:
        ImageDraw.Draw(canvas).rounded_rectangle((x0, y0, x1, y1), radius=_s(radius), outline=outline, width=_s(width))


def pill(canvas: Image.Image, x: float, y: float, label: str, height: float = 42, size: float = 26) -> float:
    top, bottom, ink = PILLS.get(label.upper(), PILLS["MONITOR"])
    d = ImageDraw.Draw(canvas)
    face = font(size)
    w = d.textlength(label, font=face) / SS + 34
    _rounded_gradient(canvas, (x, y, x + w, y + height), height / 2, top, bottom, outline=(255, 255, 255, 120), width=2)
    d.text((_s(x + 17), _s(y + (height - size * 1.18) / 2)), label, font=face, fill=ink)
    return w


def fdr_chip(canvas: Image.Image, box, value: float | None) -> None:
    top, bottom, ink = fdr_colors(value)
    label = "FDR —" if value is None else f"FDR {value:.1f}"
    _rounded_gradient(canvas, box, 9, top, bottom, outline=(255, 255, 255, 150), width=2)
    d = ImageDraw.Draw(canvas)
    face = fit(d, label, box[2] - box[0] - 8, 26, 14)
    tw = d.textlength(label, font=face) / SS
    d.text((_s(box[0] + (box[2] - box[0] - tw) / 2), _s(box[1] + (box[3] - box[1] - 26 * 1.1) / 2)), label,
           font=face, fill=ink)


def fixture_tile(canvas: Image.Image, x: float, y: float, w: float, h: float, gw: int, opponent: str,
                 venue: str, fdr: float | None) -> None:
    d = ImageDraw.Draw(canvas)
    head = h * 0.30
    _rounded_gradient(canvas, (x, y, x + w, y + h), 12, (255, 255, 255), (232, 224, 250), outline=(120, 84, 180, 255), width=2)
    _rounded_gradient(canvas, (x, y, x + w, y + head), 12, (92, 40, 160), (56, 20, 110))
    d.rectangle((_s(x), _s(y + head - 12), _s(x + w), _s(y + head)), fill=(56, 20, 110))
    label = f"GW{gw}"
    face = font(22)
    d.text((_s(x + (w - d.textlength(label, font=face) / SS) / 2), _s(y + 3)), label, font=face, fill=WHITE)
    text = f"{opponent}({venue})"
    face = fit(d, text, w - 10, 28, 16)
    tw = d.textlength(text, font=face) / SS
    d.text((_s(x + (w - tw) / 2), _s(y + head + 4)), text, font=face, fill=INK)
    fdr_chip(canvas, (x + 7, y + h - 38, x + w - 7, y + h - 6), fdr)


def _paste_contained(canvas: Image.Image, source: Image.Image, box, bottom: bool = False) -> None:
    image = source.convert("RGBA")
    bounds = image.getchannel("A").getbbox()
    if bounds:
        image = image.crop(bounds)
    x, y, w, h = (_s(v) for v in box)
    ratio = min(w / image.width, h / image.height)
    image = image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
                         Image.Resampling.LANCZOS)
    ty = y + h - image.height if bottom else y + (h - image.height) // 2
    canvas.alpha_composite(image, (round(x + (w - image.width) / 2), round(ty)))


def player_card(canvas: Image.Image, box, *, portrait, badge, name: str, price: str, own: str, verdict: str,
                gw_flow: str, evidence: str, reason: str, fixtures: list[dict]) -> None:
    x0, y0, x1, y1 = box
    h = y1 - y0
    k = min(1.6, max(0.8, h / 337))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((_s(x0), _s(y0), _s(x1), _s(y1)), radius=_s(30), fill=GOLD + (210,))
    canvas.alpha_composite(_glow(shadow, 10, 1.1))
    _rounded_gradient(canvas, box, 30, (252, 249, 255), (224, 212, 246), outline=GOLD, width=5)
    # portrait panel with a slanted gold edge
    panel_w = 252
    panel = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    px0, py0, px1, py1 = _s(x0 + 4), _s(y0 + 4), _s(x0 + panel_w), _s(y1 - 4)
    pmask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(pmask).polygon([(px0, py0), (px1, py0), (px1 - _s(34), py1), (px0, py1)], fill=255)
    cmask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(cmask).rounded_rectangle((_s(x0 + 2), _s(y0 + 2), _s(x1 - 2), _s(y1 - 2)), radius=_s(28), fill=255)
    panel.paste(gradient((px1 - px0, py1 - py0), *PURPLE_PANEL), (px0, py0))
    panel.putalpha(ImageChops.multiply(pmask, cmask))
    canvas.alpha_composite(panel)
    ImageDraw.Draw(canvas).line([(px1, py0), (px1 - _s(34), py1)], fill=GOLD, width=_s(4))
    _paste_contained(canvas, portrait, (x0 + 8, y0 + 14, panel_w - 24, h - 18), bottom=True)

    d = ImageDraw.Draw(canvas)
    tx = x0 + panel_w + 22
    crest = 108 * k ** 0.6
    _paste_contained(canvas, badge, (x1 - crest - 22, y0 + 14, crest, crest))
    width = x1 - tx - crest - 40
    face = fit(d, name, width, 58 * k, 30)
    d.text((_s(tx), _s(y0 + 8 * k)), clip_text(d, name, face, width), font=face, fill=INK)
    row2 = y0 + 78 * k
    info = f"{price} • OWN {own}"
    face = fit(d, info, width - 150, 34 * k, 22)
    d.text((_s(tx), _s(row2)), info, font=face, fill=INK)
    pill(canvas, tx + d.textlength(info, font=face) / SS + 14, row2 - 2, verdict, height=42 * k, size=25 * k)
    row3 = y0 + 124 * k
    face = fit(d, gw_flow, x1 - tx - 24, 27 * k, 18)
    d.text((_s(tx), _s(row3)), gw_flow, font=face, fill=(58, 40, 96))
    face = fit(d, evidence, x1 - tx - 24, 24 * k, 15)
    d.text((_s(tx), _s(row3 + 31 * k)), evidence, font=face, fill=(58, 40, 96))
    if reason:
        face = fit(d, reason, x1 - tx - 24, 22 * k, 14)
        d.text((_s(tx), _s(row3 + 60 * k)), reason, font=face, fill=(110, 40, 170))
    tile_h = min(150, 98 * k)
    count = max(1, len(fixtures[:5]))
    gap = 9
    tile_w = (x1 - tx - 20 - gap * (count - 1)) / count
    for i, row in enumerate(fixtures[:5]):
        fixture_tile(canvas, tx + i * (tile_w + gap), y1 - tile_h - 14, tile_w, tile_h, row["gw"], row["opponent"],
                     row["venue"], row.get("fdr"))


def legend(canvas: Image.Image, y: float) -> None:
    d = ImageDraw.Draw(canvas)
    items = (("FDR", None, ""), ("EASY < 3.0", 2.5, ""), ("MEDIUM 3.0–3.9", 3.5, ""), ("HARD 4.0+", 4.5, ""))
    face = font(21)
    widths = [d.textlength(label, font=face) / SS + (30 if v is not None else 0) for label, v, _ in items]
    total = sum(widths) + 22 * (len(items) - 1)
    x = (W - total) / 2
    for (label, value, _), w in zip(items, widths):
        if value is not None:
            top, bottom, _ink = fdr_colors(value)
            _rounded_gradient(canvas, (x, y + 3, x + 22, y + 25), 6, top, bottom)
            d.text((_s(x + 30), _s(y)), label, font=face, fill=(235, 226, 255))
        else:
            d.text((_s(x), _s(y)), label, font=face, fill=GOLD)
        x += w + 22


def notes_panel(canvas: Image.Image, box, title: str, lines: list[str]) -> None:
    x0, y0, x1, y1 = box
    _rounded_gradient(canvas, box, 26, (50, 18, 100), (28, 8, 62), outline=GOLD, width=4)
    d = ImageDraw.Draw(canvas)
    d.text((_s(x0 + 30), _s(y0 + 18)), title, font=font(32), fill=GOLD)
    y = y0 + 74
    for line in lines:
        d.ellipse((_s(x0 + 32), _s(y + 11), _s(x0 + 46), _s(y + 25)), fill=GOLD)
        face = fit(d, line, x1 - x0 - 110, 28, 16)
        d.text((_s(x0 + 62), _s(y)), line, font=face, fill=WHITE)
        y += 46


def _icon_telegram(d, cx, cy, r):
    d.ellipse((_s(cx - r), _s(cy - r), _s(cx + r), _s(cy + r)), fill=(40, 168, 232))
    d.polygon([(_s(cx - r * .55), _s(cy + r * .02)), (_s(cx + r * .6), _s(cy - r * .5)), (_s(cx + r * .32), _s(cy + r * .55)),
               (_s(cx + r * .02), _s(cy + r * .2)), (_s(cx - r * .12), _s(cy + r * .5)), (_s(cx - r * .14), _s(cy + r * .16))],
              fill=WHITE)


def _icon_youtube(d, cx, cy, r):
    d.rounded_rectangle((_s(cx - r), _s(cy - r * .72), _s(cx + r), _s(cy + r * .72)), radius=_s(r * .35), fill=(232, 30, 36))
    d.polygon([(_s(cx - r * .25), _s(cy - r * .36)), (_s(cx - r * .25), _s(cy + r * .36)), (_s(cx + r * .42), _s(cy))], fill=WHITE)


def _icon_discord(d, cx, cy, r):
    d.rounded_rectangle((_s(cx - r), _s(cy - r * .78), _s(cx + r), _s(cy + r * .78)), radius=_s(r * .5), fill=(88, 101, 242))
    for ex in (-.34, .34):
        d.ellipse((_s(cx + r * ex - r * .2), _s(cy - r * .16), _s(cx + r * ex + r * .2), _s(cy + r * .28)), fill=WHITE)


def _icon_x(d, cx, cy, r):
    d.ellipse((_s(cx - r), _s(cy - r), _s(cx + r), _s(cy + r)), fill=(12, 12, 16), outline=(120, 120, 130), width=_s(1.5))
    d.line([(_s(cx - r * .42), _s(cy - r * .42)), (_s(cx + r * .42), _s(cy + r * .42))], fill=WHITE, width=_s(3.4))
    d.line([(_s(cx + r * .42), _s(cy - r * .42)), (_s(cx - r * .42), _s(cy + r * .42))], fill=WHITE, width=_s(3.4))


def footer(canvas: Image.Image, items: Iterable[tuple[str, str]], y: float = 1826, height: float = 70) -> None:
    """items: (kind, label) with kind in telegram/youtube/discord/x; unknown kinds are skipped."""
    icons = {"telegram": _icon_telegram, "youtube": _icon_youtube, "discord": _icon_discord, "x": _icon_x}
    items = [(k, v) for k, v in items if k in icons and v]
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((_s(26), _s(y), _s(W - 26), _s(y + height)), radius=_s(height / 2), fill=(22, 7, 48, 245),
                        outline=GOLD, width=_s(3))
    if not items:
        return
    avail = W - 90
    size = 25
    while size > 13:
        face = font(size)
        widths = [d.textlength(label, font=face) / SS + 70 for _, label in items]
        if sum(widths) <= avail:
            break
        size -= 1
    face = font(size)
    widths = [d.textlength(label, font=face) / SS + 70 for _, label in items]
    extra = max(0.0, avail - sum(widths)) / len(items)
    left = 45.0
    for i, ((kind, label), w) in enumerate(zip(items, widths)):
        slot = w + extra
        icons[kind](d, left + 22, y + height / 2, 21)
        d.text((_s(left + 52), _s(y + height / 2 - size * 0.62)), label, font=face, fill=WHITE)
        if i:
            d.line([(_s(left - 6), _s(y + 14)), (_s(left - 6), _s(y + height - 14))], fill=GOLD + (170,), width=_s(2))
        left += slot


def finish(canvas: Image.Image) -> Image.Image:
    return canvas.convert("RGB").resize((W, H), Image.Resampling.LANCZOS)
