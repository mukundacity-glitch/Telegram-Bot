"""Minimal Telegram/Discord footer with configured, verified handles."""
from __future__ import annotations

from pathlib import Path
import os

from PIL import Image, ImageDraw, ImageOps

from .publication_rules import required_footer_handles

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "assets" / "references" / "brand_background.png"
# SHA-1 Git blob of the user-confirmed existing FPL VORTEX master at assets/references/brand_background.png.
APPROVED_MASTER_BLOB_SHA = "b0d890a529ad7416a142d3cfbbadfc800eb26bd0"


def verify_exact_master() -> None:
    """Strict publishing uses only the actual supplied master; no substitutes."""
    import hashlib
    if not MASTER.is_file():
        raise FileNotFoundError("Approved original blue master not installed")
    content = MASTER.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
    if blob != APPROVED_MASTER_BLOB_SHA:
        raise RuntimeError("Repository brand background differs from user-approved 59698.png; hold post")



def apply_footer(output: Path, *, verdict: str = "",
                 strict: bool = True) -> Path:
    if strict and os.getenv("FPL_ENRICHED_VISUALS_ENABLED", "false").lower() == "true":
        verify_exact_master()
    telegram, discord = required_footer_handles()
    if not MASTER.is_file():
        raise FileNotFoundError("Approved FPL VORTEX blue broadcast master not installed")
    with Image.open(MASTER) as master:
        if master.width * 9 != master.height * 16:
            raise RuntimeError("Approved blue stadium slide has invalid aspect ratio")
        master_img = master.convert("RGB")
    with Image.open(output) as exported:
        if exported.width * 9 != exported.height * 16:
            raise RuntimeError("Graphic aspect ratio must be 16:9")
        original_size = exported.size
        image = exported.convert("RGB").resize(master_img.size, Image.Resampling.LANCZOS)

    from .minimal_theme import social_footer
    social_footer(image, telegram, discord)
    footer_top = round(image.height * .928)
    from .matchup import _font, _fitted_font
    draw = ImageDraw.Draw(image, "RGBA")
    w = image.width
    if verdict:
        # Replace technical/source/timestamp text below the cards with
        # the user's actionable concise manager guidance.
        clean = verdict.strip().replace("\n", " ")
        if len(clean) > 90:
            clean = clean[:87].rsplit(" ", 1)[0] + "…"
        if any(x in clean.casefold() for x in ("source:", "api", "unverified", "n/a")):
            raise ValueError("Source/technical notes must not appear in graphic verdict")
        top = int(master_img.height * .853)
        draw.rounded_rectangle((71, top, w-71, footer_top-7), radius=11,
                               fill=(9, 22, 54, 255),
                               outline=(51, 217, 238, 220), width=2)
        label = "FPL VORTEX • DECISION"
        draw.text((90, top+8), label, font=_font(23), fill=(239, 247, 255))
        draw.text((475, top+9), clean,
                  font=_fitted_font(draw, clean, w-568, 26, 18),
                  fill=(239, 247, 255))
    tmp = output.with_suffix(".footer.tmp.png")
    image.resize(original_size, Image.Resampling.LANCZOS).save(tmp, format="PNG", optimize=True)
    with Image.open(tmp) as check:
        check.verify()
    tmp.replace(output)
    return output


# Original user-approved artwork, preserved byte-for-byte from the retired
# timetable's brand assets. No timetable generator or schedule is restored.
SELL_LOGO = ROOT / "assets/brand/sell-approved-logo.jpg"
SELL_FOOTER = ROOT / "assets/brand/sell-approved-footer.jpg"

def _approved_asset(path, expected):
    import hashlib
    raw = path.read_bytes()
    digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if digest != expected:
        raise RuntimeError("Approved SELL branding asset changed; hold graphic")
    with Image.open(path) as source:
        return source.convert("RGB")

def approved_sell_logo(canvas, *, box=None, matte='#091636'):
    """Place the exact green/gold lion wordmark in the existing left masthead."""
    logo = _approved_asset(SELL_LOGO, "a6871f20a9a901570df252a24496b445881dd86b")
    w, h = canvas.size
    x, y, right, bottom = box or (0,0,round(w*314/1536),round(h*145/864))
    if not (0 <= x < right <= w and 0 <= y < bottom <= h and right-x > 24 and bottom-y > 16):
        raise ValueError("Invalid branding region")
    box_w, box_h = right-x, bottom-y
    ImageDraw.Draw(canvas).rectangle((x,y,right-1,bottom-1), fill=matte)
    logo = ImageOps.contain(logo, (box_w-24, box_h-16), Image.Resampling.LANCZOS)
    canvas.paste(logo, (x+(box_w-logo.width)//2, y+(box_h-logo.height)//2))
    return canvas

def approved_social_footer(canvas, *, reserved_height=None):
    """Reuse the exact full-width YouTube / X / Telegram / Instagram strip."""
    original = _approved_asset(SELL_FOOTER, "2f78e78c6bf29b02df6b10a505485bca2f95842f")
    w, h = canvas.size
    height = round(w * original.height / original.width)
    if reserved_height is None:
        canvas.paste(original.resize((w,height), Image.Resampling.LANCZOS), (0,h-height))
    else:
        if not 0 < reserved_height <= h:
            raise ValueError("Invalid footer region")
        strip = ImageOps.contain(original, (w,reserved_height), Image.Resampling.LANCZOS)
        ImageDraw.Draw(canvas).rectangle((0,h-reserved_height,w-1,h-1), fill="#091636")
        canvas.paste(strip, ((w-strip.width)//2,h-reserved_height+(reserved_height-strip.height)//2))
    return canvas
