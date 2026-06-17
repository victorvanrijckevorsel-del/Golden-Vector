# Handoff: Codex independent review of the Capture & Behaviour engine (Phases 0–3)

Requested by Victor, 2026-06-17. This is the copy-paste prompt for Codex (also kept here for the record).

---

## PROMPT FOR CODEX

You are doing an **independent, adversarial, super-thorough review** of a new backend analytics
layer in the Golden Vector repo (the "Capture & Behaviour engine"), built by Claude on branch
`dev-vic` in four phases. **The UI is NOT built yet — review the backend (Phases 0–3) BEFORE the UI
is written.** Use **parallel subagents** and be exhaustive: fan out across dimensions, then have a
separate agent **adversarially verify every finding against the actual code and live data** before it
counts. Read the code FIRST-HAND; do not trust Claude's own review records (verify them).

### What the engine is
A symmetric (gold-DOWN **and** gold-UP) Lab layer over ~65 gold miners, weekly data, that answers:
which miners hedge (hold up when gold falls), which have torque (rip when gold rises), which are
convex (both), how each ranks vs peers, and whether any of that behaviour is **changing over time** —
all descriptive, nothing ranking live yet.

### Read first (the contract + prior reviews — verify, don't trust)
- `reviews/codex/claude_capture_behavior_engine_plan.md` — the spec (your earlier plan-review is folded
  into §13; the locked decisions: capture vs GOLD only, Convex offense default, 13w capture / 8w trend).
- `reviews/codex/research_time_decay_and_regime_change_trading.md` — the statistical grounding.
- Claude's per-phase review records (to cross-check, then independently verify):
  `claude_phase1_capture_review.md`, `claude_phase2_peer_review.md`, `claude_phase3_trend_review.md`.

### Scope — the four commits to review (`git log --oneline`: `0f8a335..2808506` on `dev-vic`)
- Phase 0 `0f8a335`: `golden_vector/lab/statistics.py` (shared primitives), `golden_vector/common/stats.py`
  (`weighted_median`), `golden_vector/lab/conditional_dial.py` (spine schema v3→v4: persists
  `stock_fwd_log`/`stock_fwd_simple`), `golden_vector/model/structural.py` (delegates weighted_median).
- Phase 1 `c3e816e`: `golden_vector/lab/behavior_engine.py` (capture/convexity/archetype),
  `CaptureBehaviorConfig` in `golden_vector/contracts/config_models.py`, `config/lab_behavior_trend.yaml`.
- Phase 2 `2e73f31`: peer ranking (`compute_peer_points`/`compute_peer_snapshot` in behavior_engine).
- Phase 3 `2808506`: behaviour-trend (`compute_trend_table` etc.), `two_proportion_p`/`mde_proportion_pp`
  in statistics, `write_run_stamped_set` in `golden_vector/common/parquet.py`.
- Tests: `tests/test_lab_statistics.py`, `test_behavior_engine.py`, `test_behavior_peer.py`,
  `test_behavior_trend.py`.
- Live artifacts to verify claims against: `data/lab/dial_episodes_latest.parquet` (spine, ~434k rows),
  `dial_capture_latest.parquet`, `dial_peer_latest.parquet`, `dial_peer_points_latest.parquet`,
  `dial_behavior_trend_latest.parquet`, `behavior_meta.json`.

### Review dimensions (fan out at least these; add your own)
1. **Financial soundness** — capture ratios (Morningstar up/down-capture), convexity, the
   HEDGE/TORQUE/CONVEX/DEAD_WEIGHT archetype + its data-grounded cutoffs (down-cap p33=1.61, up-cap
   p67=2.17 measured at 13w but applied to all horizons — is that defensible?). Industry-standard
   metrics only; no opaque composite.
2. **Statistical correctness** — this is the highest-risk area. Scrutinize especially:
   - **Effective-N semantics**: all-history uses `n_rows/horizon`; recent/older trend windows use the
     **anchor COUNT** (independent, NOT `/h`); decay uses **Kish ESS via `decay_effective_n(...,
     label_horizon_weeks=1)`**. Is this trio consistent and correct?
   - **Event-time windows** (recent = last fraction of independent anchors), **window-matched
     leave-one-out peer shrinkage** (recent→recent peers, not own past), **Mann-Kendall on anchors**,
     **Theil-Sen** alpha slope, **two-proportion test + Benjamini-Hochberg FDR scoped per
     (benchmark, horizon, bucket)** — is that the right FDR family? **Abstention gate** (the live
     result is 3 beat-movers / 121 alpha-movers / rest STABLE-or-INSUFFICIENT — honest or mis-gated?).
   - **Peer ranks**: point-in-time membership, benchmark-INDEPENDENT union cross-section, raw percentile
     never nulled by a display threshold.
   - **Survivorship**: the universe is survivors-only — is every confident output correctly caveated and
     is the peer *trend* correctly deferred?
3. **Architecture / repo rules** (`CLAUDE.md` + `soul.md` + `ARCHITECTURE_FOUNDATIONS.md`):
   compute-once→persist→serve-reads (no serve yet, but the artifacts must be render-ready);
   one-copy/no-duplication (the shared primitives, the shared `write_run_stamped_set`); fail-loud on
   required data vs degrade/abstain on optional; every threshold in config; label numbers with basis;
   **all-or-nothing publish** (`write_run_stamped_set` + meta-written-last crash safety); the
   **`behavior_config_hash` separate from `dial_config_hash`** + spine-schema provenance check.
4. **Cross-phase integration** — the v4 spine feeding all three lenses; the shared writer used by both
   the dial builder and the behaviour builder; any drift between the capture / peer / trend benchmark
   conventions (capture = GDX rows; peer = union; trend = per-benchmark — consistent + correct?).
5. **Tests** — do they prove behavior or pass by accident? Determinism, ties, NA, the FDR *suppression*
   path, the abstention floors. What is missing that would let a real regression ship?

### How to work
- Use parallel subagents per dimension; each finding gets an independent adversarial verification
  (try to REFUTE it) before inclusion. Verify numeric claims against the live `data/lab/*.parquet`.
- Run the test suite (`python -m pytest`) and report the real result; check `ruff`.
- **Write your findings** to `reviews/codex/codex_review_capture_behavior_engine_phases_0_3.md` as a
  severity-tagged table (HIGH/MEDIUM/LOW/NIT), each with file:line, the concrete defect, and a
  proposed fix. Where you agree/disagree with Claude's phase review records, say so explicitly (a
  merge/comparison column).
- **Do NOT modify product code** — Claude is mid-build (the UI is next) and will integrate your fixes,
  so a parallel edit would conflict. The one exception (per the repo rules) is code that *literally
  crashes the build*. Otherwise: report, don't patch.

Be skeptical, be specific, and prioritize correctness bugs and any place a confident label/number
could mislead. Surface anything Claude's reviews missed or got wrong.
