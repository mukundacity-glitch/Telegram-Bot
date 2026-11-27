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
- Friday, 27 November 2026 at 09:55:43 UTC — price/FDR minimum-gap code committed (7a45076).
- Friday, 27 November 2026 at 09:56:41 UTC — radar/rotation minimum-gap code committed (e85322b).
- Friday, 27 November 2026 at 09:57:54.868813 UTC — 451 regression tests passed for 7a45076 (run 45977788745).
- Friday, 27 November 2026 at 09:58:03 UTC — transfer-in and team-desk preview builders committed (020592d).
- Friday, 27 November 2026 at 09:59:25 UTC — price reference renderer committed (e394695).
- Friday, 27 November 2026 at 09:59:33.304049 UTC — 452 regression tests passed for e85322b (run 45977913431).
- New minimum three-hour research-to-post rule applies to all slots. Current implementation increment enforces it for price prediction, finalized radar, weekly rotation and FDR. Radar research is 05:58–06:10 ET before existing 11:30 post; Friday rotation research is 15:28–15:40 ET before existing 20:00 post. Both require persisted research and skip when another job is due. Remaining slots and other active workflows require reconciliation. Existing publication times are retained; runtime conflicts must result in a hold, not a late send.
- Position Watch #7: blocked; do not implement or activate until slots 1–6 are fully implemented and verified. No production merge until that gate passes.

- Slot 2 and 4 selection/rendering increment: official event inflows by position and ownership-ranked distinct same-club options, caller-supplied exclusions, purple background. Builders remain unscheduled until durable cross-edition exclusions and exact production windows are reconciled. 05:00 ET is outside the current approved 05:30–23:00 publication window; no unverified new time has been activated.

- Slot 1 renderer now uses the supplied 4:3 two-column composition, FPL purple background and up to ten verified candidates per direction. A 1600×1200 PNG is required specifically for this edition, without changing the other graphic sizes. The official signed likelihood band is displayed instead of invented probability labels.

- Dispatch exclusivity increment: price, finalized radar, rotation and FDR hold when another real due job is present; idle rotation polling does not block research. Radar no longer permits late-day catch-up, and guarded publication windows are checked again at execution. This is a fail-closed runtime safeguard, not proof of conflict-free operation for every legacy workflow.

- Slot 2/4 dispatch wiring: existing serialized GitHub workflow now evaluates Slot 2 at 05:30 ET (research 01:13–01:30 ET; at least four elapsed hours) and Slot 4 at 22:00 ET except Saturday 10:30 ET (research 04:13–04:28 ET). The 05:30 boundary preserves the approved publishing window; Saturday 10:30 avoids both 21:00 and 22:30 editions and retains a nominal 60-minute margin from the surrounding 09:30 and 11:30 editions. Dynamic price/special triggers, pending jobs, cooldown and late windows may suppress an edition. These are nominal candidates, not guaranteed delivery. Durable staged outbox facts reserve players across editions in the current season/GW; historical legacy receipts without IDs cannot be reconstructed from this alone. No unrelated schedule or catalogue ID is changed.
- Friday, 27 November 2026 at 10:01:03 UTC — exclusivity commit 3167ef9.
- Friday, 27 November 2026 at 10:03:09.485999 UTC — 457 regression tests passed on 3167ef9 (run 45978524376).
- Friday, 27 November 2026 at 10:03:13.852944 UTC — read-only live source audit passed on 3167ef9.

- Added final outbox proof and exact-window checks for settled radar and weekly FDR, stable GW/ISO-week identities, no generic replay for guarded records, live rotation window recheck after rendering, elapsed-UTC gap arithmetic, and prospective legacy player-ID reservations. The shared publisher is unchanged. Historical legacy records with no reliable player identifiers remain an evidence limitation. The complete global all-legacy research schedule is not verified; existing Monday position/defence and Tuesday wildcard research caches still specify one-hour lead windows, so the global release gate remains blocked. No #7 work or production merge is authorized.

- Price timing reconciliation: prefer the original T−1h publication only if free; otherwise select an earlier configured half-hour heartbeat before the live API deadline, with a separate 02:43 ET research check and >=3 elapsed hours. If no feasible slot, no post. Observed settlement is a timestamp interval from consecutive same-season official now_cost snapshots, not the API prediction clock. Actual cost changes and a recent observed settlement interval are required for a qualifying live publication; until actual evidence accumulates, hold. Exact observed settlement minute is not asserted.
- Friday, 27 November 2026 at 10:07:44 UTC — daily dispatch implementation committed (e71c62d).
- Friday, 27 November 2026 at 10:09:13 UTC — outbox proof and Saturday timing reconciliation committed (a324c7e).

- Friday, 27 November 2026 at 10:11:01 UTC — observed settlement and earlier price-window implementation committed (3b7f0b9).
- Friday, 27 November 2026 at 10:13:08.931709 UTC — 463 regression tests passed, zero failures on 3b7f0b9 (run 45979944006).
- Friday, 27 November 2026 at 10:13:13.498089 UTC — read-only live audit passed, 20 teams and 674 players.
- Existing Monday goalkeeper/striker, Tuesday wildcard and Monday defence boards retain their publication times, with research moved to separate overnight windows (Monday/Tuesday 03:13–03:28 ET, Monday defence 04:43–04:58 ET). Research must be recorded and pass the elapsed three-hour gate at nominal and actual publication; missing evidence is held. New Slot 7 remains unimplemented. The existing press priority is unchanged. Isolated radar/rotation/FDR research may run during send cooldown, but not if a real competing publication is due. Daily conflict checks use the actual dynamic price candidate rather than the abandoned preferred time. This is not yet global verification of all other legacy routes.

- Friday, 27 November 2026 at 10:15:43 UTC — legacy weekly research corrections committed (8a71a87).
- Friday, 27 November 2026 at 10:17:46.413799 UTC — CI on 8a71a87: 465 passed, one failed; old Tuesday one-hour research assertion. Updated the assertion to check the new overnight window and explicitly reject the old window. No test removed.
- Added an independent read-only six-slot live rendering step to PR validation; checks real official data, dimensions, and FDR arithmetic; reports dynamic price timing, observed settlement evidence, and uncovered legacy routes. It does not simulate missing live observations or claim to verify actual delivery. Daily research now records price snapshots, and daily conflict checks include other research windows. Slot 7 and merge remain gated.

- Friday, 27 November 2026 at 10:36:49 UTC — 466 regression tests passed on 32dfd47.
- Friday, 27 November 2026 at 10:37:11 UTC — all six live source-to-PNG checks passed. Observed price settlement, global legacy gap coverage and actual platform delivery remain unverified.
- Friday, 27 November 2026 at 10:39:55 UTC — PR #64 merged at user direction (69d4467). This is not a certification of production publication readiness.
- PR #63 reconciliation: retain the current 50 active permanent graphic IDs (42 regular, 8 dynamic) and one reserved historical ID; the new daily cutover routes are not assigned new permanent catalogue numbers. Preserve receipt keys, weekly cohort migration and honest cooldown reporting. No legacy cleanup or new slot activation.

- Friday, 27 November 2026 at 10:40:58 UTC — PR #63 merged (da04431). PR #64 was already merged by earlier user instruction; it cannot be withheld retroactively.
- Friday, 27 November 2026 at 10:43:08.8415575 UTC — merged-main validation: 468 passed, zero failures, run 45984152493; publish job skipped.
- Slot 7 follow-up: recreate the requested branch from merged main. Code-only single 1920×1080 landscape, four position columns (2 GK, 4 DEF, 4 MID, 3 FWD), dark aubergine/champagne-gold palette, light cards, official identities, last three settled matches and numeric next-five FDR. Real first kickoff comes from fixtures tied to the upcoming bootstrap event; deadline is not kickoff. Only existing quarter-hour heartbeat, no additional cron or catalogue renumbering. Candidates with no permitted window are held, notably early kickoffs outside the existing 05:30–23:00 ET publishing window.
- Slot 7 implementation remains release-disabled (`RELEASE_VERIFIED = False`): observed settlement, complete legacy gap coverage and actual timed platform delivery are still unverified. The existing production branch is unchanged by this follow-up. The PR's read-only audit and tests validate the code without sending messages. No task creation or legacy deletion.

- Friday, 27 November 2026 at 10:49:50 UTC — Slot 7 code, schedule gates and landscape renderer committed (f8468423).
- Friday, 27 November 2026 at 10:50:02 UTC — new draft PR #65 opened. Production PR #64 is historical and already merged.
- Rechecked persisted main state: no `_observed_price_settlement`, `_consecutive_cost_snapshot` or `_pre_gameweek_price_research` yet. Do not fabricate a settlement interval. Older radar/FDR receipts exist but do not establish a timed delivery of the new cutover code. Global gap audit and genuine platform delivery remain outstanding. Keep release disabled.
- Slot 7 polish: larger landscape portraits and typography where available, full-width stacked double-GW fixture tiles, explicit FDR and GW transfer labels. Final outbox must match the persisted research group and a fresh official schedule. Publish job is explicitly limited to main; branch validation does not send posts or push receipts to production.

- Friday, 27 November 2026 at 10:52:06.5849202 UTC — first Slot 7 regression run 45985419822: 477 passed, 1 failed. Root cause: the existing cooldown regression used the wall clock and entered the dedicated radar research window (05:58–06:10 ET). Its test clock is now pinned to an ordinary publishing period; the cooldown assertion is preserved, not disabled.
- Friday, 27 November 2026 at 10:52:08 UTC — landscape polish and final publication guards committed (857f62aa).

- Friday, 27 November 2026 at 10:52:43 UTC — deterministic cooldown test correction pushed (1b04ef6); latest-head CI still requires verification.
- Slot 8 branch implementation: standalone post-gameweek shot origins, once per official finalized season/GW (finished + data_checked + finished fixtures), rolling last five finalized rounds, FPL Core matches/shots reconciled to official scores and club codes. One 1920×1080 deep forest-teal / champagne / rose board, 20 clubs, large team and numeric share columns, proportional bars, genuine crests. Zero-width/tiny segments still have visible percentage labels. Separate research proof and stable per-GW delivery identity; post only on existing conflict-checked heartbeat after at least three elapsed hours. No fixed Thursday cadence. Release disabled; no production merge, and no catalogue renumbering. The Monday combined edition remains unchanged pending explicit cleanup and verification of removal of overlapping content. The current global audit does not prove every legacy reservation, settlement or actual publication; do not activate either new route until verified.

- Friday, 27 November 2026 at 10:55:37 UTC — Slot 8 branch code committed (a9f24fc).
- Friday, 27 November 2026 at 10:57:30.9764836 UTC — 483 tests passed, zero failures on a9f24fc, run 45986200058.
- Friday, 27 November 2026 at 10:57:41.5945980 UTC — six live renders passed; settlement false, 26 legacy routes still unverified.
- Friday, 27 November 2026 at 10:57:43.7484990 UTC — Slot 7 live read-only render passed (no eligible schedule candidate at audit time).
- Friday, 27 November 2026 at 10:57:45.5807197 UTC — Slot 8 live read-only render passed (20 clubs, GW7–11).
- Slot 9 branch scope: once per upcoming GW, target four hours before first official fixture (tolerance ±30 min), existing heartbeat, research ends at least three hours before publication. Five unique players per tier required for publication; missing qualified players hold rather than fabricate. Verified optional fixture-level xPts only; absent forecasts displayed as dashes. Native 1920×1080 slate/ivory board, availability-derived sell-review/avoid/hold signals, no personal squad advice. No new cron, no new catalogue number. Slot 9 release disabled; conflict and delivery checks remain outstanding. Old retired availability rule stays retired.

## Legacy / Moved Slots (Pending Telegram Cleanup)

The retired Friday two-club rotation and daily radar dispatch rules remain in Git history and the retired edition definitions; do not run them as replacements. Preserve existing catalog numbers and delivery journals. The old Friday two-club graphic retains its reserved historical ID (48/51), but cannot be stamped or scheduled for production; the weekly four-club route retains 51/51. The branch has 50 active graphic IDs plus one reserved ID, with no renumbering or duplicate Friday publication route. No public posts or receipt deletions are authorized.

Superseded timing rules: price research T−2h and FDR research Saturday 19:28–19:40 ET. Archived only; do not execute.

Superseded price graphic: portrait top-eight-per-direction layout and previous social-footer formatting. Historical version remains in Git history; use only the new 4:3 format for this slot.

Superseded existing weekly research windows: Monday goalkeeper/striker 09:30–10:30 ET; Tuesday wildcard 14:30–15:30 ET; Monday defence 19:00–20:00 ET. Retained for cleanup only, not executed. This is distinct from the new gated #7 workflow.

Superseded Slot 8 standalone rule: Thursday 20:00 ET attacking-zones edition (retired). Replaced in the branch by official post-final-GW cadence, not reinstated. Monday combined shot-origin section is preserved pending cleanup; duplicate-content reconciliation remains a release prerequisite.

Retired availability-transfer-decisions: former 05:30 board; replaced in branch scope by Slot 9 dynamic pre-kickoff rule. Retain historic records, no replay or deletion.
