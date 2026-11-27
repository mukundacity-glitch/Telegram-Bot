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


def approved_social_footer(canvas):
    """Use the approved original social icon/handle artwork, not typed substitutes.

    The four original lockups are distributed across the footer without
    stretching their logos or altering the player's cards and fixture bands.
    """
    asset = ROOT / "assets" / "brand" / "midfield-watch-footer.png"
    if not asset.is_file():
        raise FileNotFoundError("Approved logo-and-handle footer artwork missing")
    w, h = canvas.size
    y = round(h * .928)
    band = h - y
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, y, w, h), fill="#090e28")
    inset = max(4, round(w * .014))
    draw.rounded_rectangle((inset, y+2, w-inset, h-3), radius=max(7, band//3),
                           fill="#100b28", outline="#f7b946", width=max(1, w//640))
    with Image.open(asset) as source:
        original = source.convert("RGB")
        # Exact source artwork: Telegram, YouTube, Discord, X (846 x 83).
        spans = ((19, 282), (299, 468), (484, 638), (653, 828))
        for index, (left, right) in enumerate(spans):
            cell_left = inset + (w-2*inset)*index//4
            cell_right = inset + (w-2*inset)*(index+1)//4
            crop = original.crop((round(left*original.width/846),
                                  round(19*original.height/83),
                                  round(right*original.width/846),
                                  round(63*original.height/83)))
            lockup = ImageOps.contain(crop, (cell_right-cell_left-12, max(1,band-15)),
                                       Image.Resampling.LANCZOS)
            canvas.paste(lockup, ((cell_left+cell_right-lockup.width)//2,
                                  y+(band-lockup.height)//2))
            if index:
                draw.line((cell_left, y+band//5, cell_left, h-band//5),
                          fill="#f7b946", width=max(1,w//950))
    return canvas
