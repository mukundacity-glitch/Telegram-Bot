"""FPL VORTEX original blue-slide footer: preserve brand, no fabricated handles.

The original artwork at assets/references/brand_background.png is the ONLY
background. We restore its existing branded footer pixels, then add Telegram
and Discord handles from GitHub Actions variables (never guessed).
"""
from __future__ import annotations

from pathlib import Path
import os

from PIL import Image, ImageDraw

from .publication_rules import required_footer_handles

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "assets" / "references" / "brand_background.png"
# SHA-1 Git blob of the exact user-provided 59698.png original broadcast master.
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

    # Restore untouched original branded footer (logo/icon positioning, shape,
    # left-hand social handles). Never reproduce it with AI-generated artwork.
    # Displace only the footer's blank/right-side text to create two new handles.
    footer_top = round(master_img.height * 0.928)
    original_strip = master_img.crop((0, footer_top, master_img.width, master_img.height))
    image.paste(original_strip, (0, footer_top))

    from .matchup import _font, _fitted_font
    draw = ImageDraw.Draw(image, "RGBA")
    w = image.width
    y = footer_top
    # Reserve the existing logo/YouTube/X region; retain its original pixels.
    left = int(w * 0.42)
    draw.rounded_rectangle((left, y + 6, w - 17, image.height - 6),
                           radius=7, fill=(1, 13, 36, 248),
                           outline=(48, 178, 235, 180), width=2)
    draw.text((left + 16, y + 12), "TELEGRAM",
              font=_font(15), fill=(69, 226, 252))
    draw.text((left + 16, y + 30), telegram,
              font=_fitted_font(draw, telegram, int(w * 0.22), 23, 14),
              fill=(248, 252, 255))
    second = int(w * 0.70)
    draw.line((second, y + 12, second, image.height - 12),
              fill=(87, 165, 218, 180), width=2)
    draw.text((second + 15, y + 12), "DISCORD",
              font=_font(15), fill=(146, 178, 253))
    draw.text((second + 15, y + 30), discord,
              font=_fitted_font(draw, discord, int(w * 0.25), 23, 14),
              fill=(248, 252, 255))

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
                               fill=(2, 25, 57, 250),
                               outline=(51, 217, 238, 220), width=2)
        label = "FPL VORTEX • DECISION"
        draw.text((90, top+8), label, font=_font(23), fill=(248, 195, 78))
        draw.text((475, top+9), clean,
                  font=_fitted_font(draw, clean, w-568, 26, 18),
                  fill=(250, 252, 255))
    tmp = output.with_suffix(".footer.tmp.png")
    image.resize(original_size, Image.Resampling.LANCZOS).save(tmp, format="PNG", optimize=True)
    with Image.open(tmp) as check:
        check.verify()
    tmp.replace(output)
    return output
