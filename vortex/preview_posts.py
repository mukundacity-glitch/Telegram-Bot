"""PR-only local file previews for new posts; never connects to Telegram."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import sys
from .fpl import collect_snapshot, upcoming_deadline
from .content import generate
from .render import render


def main() -> int:
    snapshot = collect_snapshot()
    deadline = upcoming_deadline(snapshot)
    if deadline is None or deadline <= datetime.now(timezone.utc):
        raise RuntimeError("Next GW deadline is not safely in the future")
    folder = Path("output/pr-preview")
    folder.mkdir(parents=True, exist_ok=True)
    failures = 0
    for kind in ("buy", "sell", "review"):
        try:
            article = generate(kind, snapshot, datetime.now(timezone.utc), {})
            path = folder / f"FPLVortex_GW{article.gw}_{kind}_PREVIEW.png"
            if kind in ('sell', 'review'):
                # Use the same renderer and resolution as production.
                from .publish_checks import render_checked
                from .graphic_numbers import stamp
                import os
                for key, value in {'FPL_TELEGRAM_HANDLE':'@FPLVortexDailyBot', 'FPL_DISCORD_HANDLE':'@fplvortex', 'FPL_ENRICHED_VISUALS_ENABLED':'true'}.items():
                    os.environ.setdefault(key, value)
                render_checked(article, snapshot, path)
                stamp(path, kind, required=True)
            else:
                render(article, path)
            (folder / f"FPLVortex_GW{article.gw}_{kind}_CAPTION.txt").write_text(
                article.caption + "\n", encoding="utf-8")
            print(f"{kind.upper()} verified preview: {path}; data timestamp {article.data_at}")
        except Exception as exc:
            failures += 1
            print(f"{kind.upper()} preview unavailable: {type(exc).__name__}: {str(exc)[:180]}", file=sys.stderr)
    try:
        from .autonomous_content import build, Evidence
        from .autonomous_schedule import SLOTS
        from .autonomous_render import render as render_plan
        from .graphic_numbers import stamp
        now = datetime.now(timezone.utc)
        slot = next(s for s in SLOTS if s.edition == 'goalkeeper-striker-watch')
        evidence = Evidence(snapshot, now)
        plan = build(slot, snapshot, now, evidence)
        path = folder / f"FPLVortex_GW{plan.gw}_combined_watch_PREVIEW.png"
        pages = render_plan(plan, snapshot, now, path, evidence.session)
        if len(pages) != 1:
            raise RuntimeError("Expected one combined page")
        stamp(pages[0], slot.edition, required=True)
        (folder / "combined_watch_CAPTION.txt").write_text(plan.caption + "\n", encoding="utf-8")
        print(f"COMBINED WATCH verified preview: {pages[0]}")
    except Exception as exc:
        failures += 1
        print(f"COMBINED WATCH preview unavailable: {type(exc).__name__}: {str(exc)[:180]}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
