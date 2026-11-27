"""Read-only live source-to-PNG verification. Never stage, send or write receipts."""
from datetime import datetime, timezone
from pathlib import Path
import json

from PIL import Image
from .autonomous_content import Evidence, retrying_session
from .autonomous_schedule import Slot, SATURDAY_FDR_GRID, SLOTS, SPECIAL_EDITIONS, ET
from .daily_cutover import slots as daily_slots
from .fpl import collect_snapshot, latest_completed_gw
from .price_prediction_board import official_clock, build_board, render_board, price_schedule, SETTLEMENT_KEY, valid_settlement
from .extra_posts import generate_extra
from .publish_checks import render_checked
from .radar_comparison import build_radar
from .rotation_planner import build_rotation_plan, render_rotation_plan
from .evening_intelligence import build_evening
from .autonomous_render import render
from .bot import read_state
from .autonomous_runner import STATE_FILE
from .autonomous_schedule import season_id
from .legacy_research_gap import WINDOWS
from .schedule import SLOT_HOURS


def run(folder=Path("output/six-slot-live-audit")):
    folder.mkdir(parents=True, exist_ok=True)
    session = retrying_session()
    snapshot = collect_snapshot(session)
    now = datetime.now(timezone.utc)
    evidence = Evidence(snapshot, now)
    state = read_state(STATE_FILE)
    report = {"at": now.isoformat(), "gw": snapshot.gameweek(), "slots": {},
              "mode": "live-source-render-only; no publication or synthetic research evidence"}
    def check(n, title, action, expected):
        target = folder / f"{n}.png"
        target.unlink(missing_ok=True)
        try:
            path = action(target)
            with Image.open(path) as im:
                if im.size != expected:
                    raise ValueError(f"Unexpected image dimensions {im.size}")
                im.verify()
            report["slots"][str(n)] = {"title": title, "status": "rendered", "size": list(expected)}
        except Exception as exc:
            report["slots"][str(n)] = {"title": title, "status": "held", "reason": str(exc)[:500]}
    def price(target):
        update, refreshed = official_clock({"game_config": snapshot.game_config}, now)
        research, post, conflicts = price_schedule(snapshot, now, update, state)
        report["price_clock"] = {"expected_at": update.isoformat(), "source_at": refreshed.isoformat(),
            "research_at": research.isoformat() if research else None, "post_at": post.isoformat() if post else None,
            "observed_settlement_verified": valid_settlement(state.get(SETTLEMENT_KEY, {}), season_id(snapshot, now), now),
            "preferred_window_conflicts": conflicts}
        return render_board(snapshot, build_board(snapshot, update), target, session)
    def daily(kind, target):
        article = generate_extra(kind, snapshot, now)
        return render_checked(article, snapshot, target, session=session)
    def radar(target):
        completed = latest_completed_gw(snapshot)
        slot = Slot("task1", "player-radar-comparison", 11, 30, series_gw=completed)
        plan = build_radar(slot, snapshot, now, evidence)
        page, = render(plan, snapshot, now, target, session)
        return page
    def fdr(target):
        plan = build_evening(SATURDAY_FDR_GRID, snapshot, now, evidence)
        for row in plan.extra["rows"]:
            values = [fixture["fdr"] for cell in row["cells"] for fixture in cell]
            expected = sum(values)/len(values) if values else None
            if row["average"] != expected or row["games"] != len(values):
                raise ValueError("FDR average is not fixture-weighted")
        page, = render(plan, snapshot, now, target, session)
        return page
    check(1, "Price change", price, (1600,1200))
    check(2, "Most transferred-in", lambda p: daily("most_transferred_in",p), (1920,1080))
    check(3, "Player comparison", radar, (1920,1080))
    check(4, "Team Decision Desk", lambda p: daily("team_analysis",p), (1920,1080))
    check(5, "Rotation Planner", lambda p: render_rotation_plan(build_rotation_plan(snapshot,now),p,session), (1920,1080))
    check(6, "FDR Matrix", fdr, (1080,1920))
    covered = set(WINDOWS) | {"player-radar-comparison", "saturday-fdr-grid"}
    report["global_gap_unverified"] = sorted((set(SLOT_HOURS) | set(SPECIAL_EDITIONS) |
        {s.edition for s in SLOTS} | {"matchday-press", "manual/legacy-outbox"}) - covered)
    report["release_ready"] = False  # This audit cannot prove an actual timed platform delivery.
    (folder/"report.json").write_text(json.dumps(report,indent=2,default=str), encoding="utf-8")
    print(json.dumps(report,default=str))
    return all(row["status"] == "rendered" for row in report["slots"].values())


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
