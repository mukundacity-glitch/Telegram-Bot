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
    for kind in ("buy", "sell"):
        try:
            article = generate(kind, snapshot, datetime.now(timezone.utc), {})
            path = folder / f"FPLVortex_GW{article.gw}_{kind}_PREVIEW.png"
            render(article, path)
            (folder / f"FPLVortex_GW{article.gw}_{kind}_CAPTION.txt").write_text(
                article.caption + "\n", encoding="utf-8")
            print(f"{kind.upper()} verified preview: {path}; data timestamp {article.data_at}")
        except Exception as exc:
            failures += 1
            print(f"{kind.upper()} preview unavailable: {type(exc).__name__}: {str(exc)[:180]}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
