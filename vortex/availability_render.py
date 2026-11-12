"""Approved VORTEX master, five-tier 05:30 broadcast graphic (1920 x 1080).

Every portrait, crest, price and fixture belongs to a live FPL player ID.
All model xPts fields are blank unless the complete verified fixture join exists.
"""
from __future__ import annotations

import os

from PIL import ImageDraw

from .comparison_board import text, contain, WHITE, CYAN
from .minimal_theme import action_fill
from .autonomous_render import _assets, _base, _save

TIER_COLORS = {
    "MUST HAVES": "#F17B84",
    "STRONG BUYS": "#FFB96D",
    "SMART PICKS": "#FADD82",
    "VALUE PLAYS": "#E0EE83",
    "PUNTS": "#A0F28A",
}
FDR = {1: "#00D894", 2: "#60DDA9", 3: "#E4D5A0",
       4: "#EF9B73", 5: "#ED577A"}
ACTIONS = {"MUST HAVES": "PRIORITY", "STRONG BUYS": "BUY",
           "SMART PICKS": "CONSIDER", "VALUE PLAYS": "VALUE",
           "PUNTS": "DIFFERENTIAL"}


def render_availability(plan, snapshot, now, output, client):
    """Single 16:9 page, never increases the number of live posts."""
    canvas = _base(plan.title, plan.gw)
    d = ImageDraw.Draw(canvas, "RGBA")
    # Keep existing top-left logo/top-right league mark and original footer.
    text(d, "NEXT GW PRIORITY  /  FIVE GW OUTLOOK  /  VERIFIED PLAYER DATA",
         330, 79, 880, 16, CYAN, 13, center=True)
    tiers = plan.extra["tiers"]
    detail = plan.extra["rows"]
    cache = {}
    card_w, gap, base_x = 251, 7, 222
    row_h, top = 133, 112
    for t, tier in enumerate(TIER_COLORS):
        y = top + row_h*t
        label_color = TIER_COLORS[tier]
        d.rounded_rectangle((33, y+1, 211, y+127), radius=13,
                            fill=label_color, outline=(238, 248, 255, 255), width=2)
        label = tier.replace(" ", "\n", 1) if tier in ("MUST HAVES", "STRONG BUYS", "SMART PICKS", "VALUE PLAYS") else tier
        line_count = 2 if "\n" in label else 1
        for n, line in enumerate(label.split("\n")):
            text(d, line, 42, y+42+n*32-(16 if line_count == 2 else 0),
                 160, 31, "#06132A", 22, center=True)
        ids = tiers[tier]
        if not ids:
            d.rounded_rectangle((base_x, y+2, 1504, y+127), radius=9,
                                fill=(11, 31, 66, 246), outline=(49, 184, 230, 230), width=2)
            text(d, "NO VERIFIED PLAYER MEETS THIS CATEGORY'S THRESHOLD",
                 base_x+12, y+50, 1220, 25, WHITE, 17, center=True)
        for i, pid in enumerate(ids):
            x = base_x + i*(card_w+gap)
            r = detail[str(pid)]
            p = r["player"]
            d.rounded_rectangle((x, y+1, x+card_w, y+128), radius=9,
                                fill=(9, 30, 66, 250), outline=(40, 218, 247, 255), width=2)
            portrait, badge = _assets(snapshot, p, client, cache)
            contain(canvas, portrait, (x+8, y+6, 77, 82), bottom=True, crop_alpha=True)
            contain(canvas, badge, (x+80, y+51, 23, 23))
            d = ImageDraw.Draw(canvas, "RGBA")
            d.rounded_rectangle((x+174, y+7, x+card_w-7, y+29), radius=4,
                                fill=(225, 240, 250, 255))
            text(d, snapshot.price(p), x+175, y+10, 64, 16, "#102244", 14, center=True)
            label1 = f"xPts1 {r['xpts1']:.1f}" if r["xpts1"] is not None else "xPts1 —"
            label5 = f"xPts5 {r['xpts5']:.1f}" if r["xpts5"] is not None else "xPts5 —"
            text(d, label1, x+108, y+35, 130, 17, WHITE, 13, center=True)
            text(d, label5, x+108, y+55, 130, 17, CYAN, 13, center=True)
            d.rounded_rectangle((x+111, y+77, x+card_w-8, y+95), radius=5,
                                fill=action_fill(ACTIONS[tier]))
            text(d, ACTIONS[tier], x+113, y+78, 126, 15, "#081830", 11, center=True)
            d.rounded_rectangle((x+5, y+97, x+card_w-5, y+113), radius=3,
                                fill=(17, 48, 88, 255))
            text(d, snapshot.name(p), x+8, y+97, card_w-16, 15, WHITE, 14, center=True)
            # Five GAMEWEEK chips, not five fixtures. Double GW displays both
            # opponents; blank Gameweeks are explicit.
            for j, gw in enumerate(range(plan.gw, plan.gw+5)):
                matches = [f for f in r["fixtures"] if f["gw"] == gw and not f["blank"]]
                label = "/".join(m["opponent"] for m in matches) or "BLK"
                difficulties = [m["fdr"] for m in matches if m["fdr"] in FDR]
                shade = FDR[max(difficulties)] if difficulties else "#68738C"
                chip_x = x+6+j*49
                d.rounded_rectangle((chip_x, y+115, chip_x+46, y+126),
                                    radius=2, fill=shade)
                text(d, label, chip_x+1, y+115, 44, 11, "#0A1A37", 9, center=True)
    # The requested reference footer also carries YouTube/X and the channel
    # tagline. Keep the verified Telegram/Discord footer rendered by _save.
    youtube = os.getenv("FPL_YOUTUBE_HANDLE", "FPLVORTEX").strip().lstrip("@")
    x_handle = os.getenv("FPL_X_HANDLE", "FPLVORTEXM").strip().lstrip("@")
    brand_line = (f"YOUTUBE @{youtube}    |    X @{x_handle}    |    "
                  "DATA  |  DECISION  |  POINT  |  RANK CLIMB")
    text(d, brand_line, 70, 780, 1395, 17, "#FFCF75", 13, center=True)
    # Approved original footer is rendered by _save/apply_footer.
    return _save(canvas, output)
