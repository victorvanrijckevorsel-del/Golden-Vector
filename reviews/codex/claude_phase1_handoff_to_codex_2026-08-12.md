# Phase 1 handoff → Codex (2026-08-12, Claude context exhausted)

Victor asked Codex to FINISH Phase 1. Authority: `reviews/codex/claude_platform_redesign_plan_final_2026-08-12.md` (§4.3/§4.4/§4.6, Phase 1). Branch `dev-vic`, committed through `29e07b1`. Victor's standing instructions: NO full test suite (focused lists only); never `git add -A` (explicit paths — `naukri.md` at root is Victor's personal file, never commit it); no Playwright use now (visual gate = Phase 4; Victor approved install, deferred).

## State at handoff

DONE + committed: both correctness lanes merged (dial state machine + one-value-per-card; chart display modes indexed/price/count incl. OI caption + labelOnly crosshair); baseline evidence (`milestones/platform_redesign/phase1_baseline.md`, full pre-change suite 2182 green); adversarial round 1 (24 raw → 10 confirmed, ALL FIXED in `29e07b1` — record in `phase1_review_round1.md`); Codex review findings dispositioned (overlaps: your scenario-label P1 = fixed; count-axis dupes = fixed; out-of-range test = fixed via `scenario_enabled` split — out-of-range spot now keeps the five line values painted, slider inert).

IN FLIGHT at handoff: a background fix agent was applying Codex findings N1–N10 (below) directly in the main tree. **First action: `git status`.** If serve/tests files are modified: the wave-2 work exists — verify with the commands below; finish anything missing from the list; commit (explicit paths). If the tree is clean, implement N1–N10 from scratch.

## N1–N10 (from Codex review `codex_review_phase1_ticker_correctness_2026-08-12.md`; full evidence there)

- N1 Non-finite spot: resolve spot once via `common.numeric.optional_finite_float` at the read boundary in `corporate.py`; NaN/±Inf → None everywhere (payload spot null — ±Inf currently CRASHES the route via `embed_json_payload(allow_nan=False)`; prove with a regression first); concrete reason "no finite spot gold price is published for this ticker and source"; tests None/NaN/±Inf.
- N2 OI gap bridging: in `charts.py`, split each series into contiguous segments at mid-series None runs (one polyline per segment, same class; single-point segment must stay visible). Leading-None (pre-anchor) fixtures keep ONE polyline unchanged. Tests: complete→None→complete OI = two polylines, nothing spans the gap.
- N3 Sub-cent prices: price-mode precision resolved per chart from drawn scale (≥1→2dp; ≥0.1→3dp; else 4dp), ONE formatter for axis/crosshair/table; embed raw rounded at same precision. $6–$7 fixture keeps 2dp; 0.001/0.0015/0.002 distinct.
- N4 `align_to_step` ties must round UP (HTML rule), not banker's: k=floor(delta+0.5); fix docstring; half-step tests (4476.5,min2000,step1→4477).
- N5 Serialization: `align_to_step` gains optional `maximum` clamping k to floor((max-min)/step); `_slider_value_attr` passes it and serializes with decimals = max(dec(step), dec(minimum)) (Decimal technique; no new arithmetic in corporate.py). Tests: min=2000.5/step=1/spot=4477.4→"4477.5"; min=0/max=10/step=6/spot=9→"6".
- N6 Fractional-step announcements: gold-dial.js derives scenario display format from `input.step` decimals (fractional→"usd2", integer→"usd") for output/basis/aria-valuetext/live region/card bases. Node test with step 0.5 → "$4,477.50" everywhere.
- N7 OI series keys: options.py passes explicit `{"Put OI":"gdx","Call OI":"gdxj","Total OI":"stock"}`; test pairwise-distinct classes.
- N8 Price-view leak: sections.py filters marker/notice rows to STOCK in price view (Compare unchanged); test stale-GDX (hidden in price, shown in Compare) + stale-STOCK (shown in both).
- N9 Count anchor into mode contract: indexed→base param(100), count→forced 0, price→None; options.py drops `base=0.0`. Test count-without-base.
- N10 Node suite parameterized over our+yahoo payloads (distinct sentinels) for boot/move/reset.
- If N1 changes payload shape: regenerate `tests/fixtures/gold_dial_parity.json` (`GV_WRITE_PARITY_FIXTURE=1`), diff must be additive-only — report the delta.

## Verification (repo root; venv\Scripts\python.exe; NO full suite)

1. `-m pytest tests/test_common_helpers.py tests/test_ticker_page_corporate.py tests/test_gold_dial_js_behavior.py tests/test_rebased_overlay_panel.py tests/test_ticker_page_sections.py tests/test_ticker_page_options.py -q`
2. `-m pytest tests/test_ticker_page_js_parity.py tests/test_workspace_shell.py -q`
3. `-m pytest tests/test_workspace_app.py tests/test_redesign_routes.py -q`
4. `ruff check` every touched file.

## Then close the gate (in order)

1. Commit wave-2 (message: `fix(phase1): wave 2 — Codex review findings N1-N10`).
2. Write the merged Claude+Codex findings comparison table (CLAUDE.md parallel-review rule) into `milestones/platform_redesign/phase1_review_merged.md`: my 10 confirmed (see `phase1_review_round1.md`) vs your 14, with disposition column (fixed round-1 / fixed wave-2 / process-resolved: baseline evidence committed `8254909`, screenshots deferred-by-Victor to Phase 4).
3. Re-review your own wave-2 diff once (read-only, then fix) — the loop closes when a round finds nothing.
4. Update `phase1_baseline.md` §5 if anything changed; append a short Phase 1 completion note (what shipped, test counts) to `phase1_review_merged.md`.
5. Cleanup worktrees: `git worktree remove` `C:\Users\Emanuel\code\gv-lane1-dial` and `gv-lane2-charts` (branches `phase1-lane1-dial`/`phase1-lane2-charts` are merged; delete branches), and `git worktree unlock` + `remove` the two stale `.claude/worktrees/agent-*` entries at f45560a; `git worktree prune`.
6. Push dev-vic. Then the standing milestone merge workflow (dev-vic → main → delete remote dev-vic → recreate) — Victor said "let me know when phase one is done": TELL VICTOR the gate is green and get his OK before the main merge (he asked to be informed; treat that as the release checkpoint).
7. Tell Victor explicitly: Phase 1 done, and Phase 2 (dual-source Tool D, plan §6) is next — Claude's plan requires the FULL suite for Phase 2 because contracts change (Victor's no-full-suite instruction was for Phase 1 time-saving; re-confirm with him at Phase 2).

Claude memory note `inflight_platform_redesign_final_plan.md` (in Claude's memory dir) should be updated by Claude next session; Codex does not need to touch it.
