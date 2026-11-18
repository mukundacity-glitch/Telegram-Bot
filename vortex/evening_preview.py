"""Read-only official-data previews; never stages an outbox or publishes.

python -m vortex.evening_preview --editions tuesday-set-pieces saturday-fdr-grid
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from PIL import Image, ImageStat

from .autonomous_schedule import EVENING_WATCH_SLOTS, ET
from .autonomous_content import Evidence
from .evening_intelligence import KINDS, build_evening
from .evening_intelligence_render import render_evening
from .editorial_inputs import RequiredInput
from .fpl import collect_snapshot
from .sunday_chances import build_sunday_chances, build_monday_defence
from .sunday_chances_render import render_sunday_chances


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verified no-send PNG previews")
    parser.add_argument("--editions", nargs="+", required=True,
                        choices=sorted(slot.edition for slot in EVENING_WATCH_SLOTS))
    parser.add_argument("--output", default="output/evening-intelligence")
    args = parser.parse_args(argv)
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    snapshot = collect_snapshot()
    now = datetime.now(timezone.utc)
    evidence = Evidence(snapshot, now)
    by_name = {slot.edition: slot for slot in EVENING_WATCH_SLOTS}
    report = {
        "mode": "read-only / no publishing",
        "data_at": snapshot.fetched_at.astimezone(ET).isoformat(),
        "gameweek": snapshot.gameweek(),
        "editions": [],
    }
    for name in args.editions:
        slot = by_name[name]
        row = {"edition": name, "status": "HELD"}
        try:
            if name in KINDS:
                plan = build_evening(slot, snapshot, now, evidence)
                render = lambda target: render_evening(plan, target, evidence.session)
            else:
                method = (build_sunday_chances if slot.weekday == 6
                          else build_monday_defence)
                plan = method(slot, snapshot, now, evidence.session)
                render = lambda target: render_sunday_chances(plan, target, evidence.session)
            image_path = root / (name + ".png")
            render(image_path)
            with Image.open(image_path) as verify_image:
                verify_image.verify()
            with Image.open(image_path) as image:
                expected_size = (1080, 1920) if slot.edition == "saturday-fdr-grid" else (1920, 1080)
                if image.size != expected_size:
                    raise RuntimeError("Premium preview dimensions are incorrect")
                # A flat background or entirely empty panel is not an accepted PNG.
                variance = ImageStat.Stat(image.convert("RGB")).var
                if sum(variance) < 900:
                    raise RuntimeError("Preview failed nonblank visual QA")
            row.update(status="RENDERED", image=str(image_path),
                       sources=plan.extra.get("sources", []),
                       methodology=plan.extra.get("method"))
        except (RequiredInput, RuntimeError, ValueError, OSError, KeyError) as exc:
            row["reason"] = type(exc).__name__ + ": " + str(exc)
        report["editions"].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    report_path = root / "preview-audit.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    # Incomplete live data is plainly reported but cannot trigger a fake post.
    return int(any(row["status"] != "RENDERED" for row in report["editions"]))


if __name__ == "__main__":
    raise SystemExit(main())
