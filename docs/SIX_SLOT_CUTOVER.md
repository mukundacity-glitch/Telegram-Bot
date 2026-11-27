# Six-slot GitHub cutover

GitHub is the execution owner; do not create ChatGPT schedules. Only replace instructed slots; preserve unrelated editions and delivery receipts.

| Priority | Cadence / contract |
|---|---|
| 1 Price change | One per target GW, live API clock plus timestamped cost deltas, at least 3h check-to-post gap; T-4h15m research/T-1h post, no material change = no post. 12/54 reference. Conference dates separate. |
| 2 Transfers in | Daily, position-segregated official event inflows, four hours of research lead, no repeated IDs. Exact five-hour interpretation must be reconciled with production schedule before cutover. |
| 3 Radar comparison | Once after official GW settlement, last five completed and next five fixtures, teal/gold reference. |
| 4 Team Decision Desk | Daily, one club, nine completed matches GF/GA and three distinct eligible players ranked by live ownership or transfers, no conflicts. |
| 5 Rotation planner | Weekly four-club nine-GW official matrix, white background and premium fills. |
| 6 FDR | Weekly Saturday, existing portrait matrix, six consecutive future GWs, exact fixture-weighted averages, official crests, ivory/purple palette. |

Slot 6 uses existing Saturday 20:00 ET edition. Research check 15:28 ET (:28 UTC hourly heartbeat), research window 15:28–15:40; post window 20:00–20:15 ET (existing 0/13 minute heartbeats). UTC offsets follow America/New_York. If other due jobs, spacing lock, no verified same-day research or pending identity, skip. Never add another publisher. Existing serialized job is retained. These are nominal scheduling opportunities, not a guarantee of timely GitHub runner starts. Actual workflow validation is required before production cutover.

Slot 1 now uses a target-season/GW key, T−4h15m research evidence and at least 3h elapsed and a verified material price/projection-state change gate before staging. Both dispatch and outbox validation require evidence. The existing 45-minute publisher cooldown and existing legacy schedules may prevent a qualifying price window; no conflicting publish is authorized. The remaining requirements for slots 1 (layout and full runtime verification), 2 and 4 and cross-slot coordination must be implemented and regression-tested before merging the cutover. No claim of completed migration from this document alone.

## Cutover verification tracker — UTC
- Friday, 27 November 2026 at 09:51:27 UTC — catalogue correction committed (c81e2a8).
- Friday, 27 November 2026 at 09:53:14.083743 UTC — regression suite passed: 442 passed, zero failures (run 45977206370).
- Friday, 27 November 2026 at 09:53:18.128314 UTC — read-only live source audit generated passing result, 20 teams and 674 players.
- New minimum three-hour research-to-post rule applies to all slots. Current implementation increment enforces it for price prediction, finalized radar, weekly rotation and FDR. Radar research is 05:58–06:10 ET before existing 11:30 post; Friday rotation research is 15:28–15:40 ET before existing 20:00 post. Both require persisted research and skip when another job is due. Remaining slots and other active workflows require reconciliation. Existing publication times are retained; runtime conflicts must result in a hold, not a late send.
- Position Watch #7: blocked; do not implement or activate until slots 1–6 are fully implemented and verified. No production merge until that gate passes.

## Legacy / Moved Slots (Pending Telegram Cleanup)

The retired Friday two-club rotation and daily radar dispatch rules remain in Git history and the retired edition definitions; do not run them as replacements. Preserve existing catalog numbers and delivery journals. The old Friday two-club graphic retains its reserved historical ID (48/51), but cannot be stamped or scheduled for production; the weekly four-club route retains 51/51. The branch has 50 active graphic IDs plus one reserved ID, with no renumbering or duplicate Friday publication route. No public posts or receipt deletions are authorized.

Superseded timing rules: price research T−2h and FDR research Saturday 19:28–19:40 ET. Archived only; do not execute.
