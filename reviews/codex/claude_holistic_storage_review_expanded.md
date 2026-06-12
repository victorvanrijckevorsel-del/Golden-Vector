# Holistic Data Storage & Compute Review — EXPANDED (Claude, 2026-06-12)

Expands `codex_holistic_data_storage_compute_review.md`. Method: 6-agent
verification fleet (atomicity, reader failure modes, serve boundary, storage
footprint/privacy, data utilization/catalog, operational state — ~790k tokens,
321 tool calls), every HIGH re-verified first-hand by Claude before inclusion.
Context: Codex wrote its review BEFORE today's Lab milestones (M0/M1, chunk 2,
/lab page) and before today's live refresh, so several claims are re-dated.

**Expanded verdict: Codex's architecture assessment stands — file-backed
artifact lake + manifest is right, no database rewrite. But Codex understated
the risk in three places (perishable option chains are prunable, the IV
history can be silently wiped, a live serve-side fork renders wrong copy
today) and missed the entire new `lab/` package, which has its own PIT
integrity bug (mine, from this morning, confirmed contaminated on disk).**

---

## 1. Verdict on every Codex claim

| Codex claim | Verdict | Evidence (current tree) |
|---|---|---|
| H1a status reports INCOMPLETE | VERIFIED | manifest 2026-06-12T05:14Z `state=incomplete`, `alignment=WARN` |
| H1b Tool B stale vs newer schema | **STALE** | today's refresh rebuilt Tools A–D at gold $4212; Tool B current |
| H1c portfolio references older refresh | VERIFIED | aligned to foundation 20260608 vs current 20260612 — but see new finding: portfolio is **disabled by config**, so this can never self-heal |
| H1d "fail closed + friendly page everywhere" | PARTLY | options fail closed beautifully (v2 disk vs v3 code → UNAVAILABLE notice); portfolio fails closed (PortfolioStaleSchemaError); but ticker **detail pages render no model-state banner at all**, and Tool A–D snapshots carry **no schema_version column** so their staleness is undetectable by version |
| H2 manual store accepts NaN/inf | VERIFIED + WORSE | `_positive_float` accepts `nan`/`inf`/`1e400` (proven empirically); same class bug in **screening store** (HIGH, below) and `hedge/holdings.py` |
| H3 replay snapshots duplicate private data | PARTLY | real (117 sqlite copies under data/runs) but they are also currently the ONLY backup of user-entered screening data — pruning them without adding a real backup would make things worse |
| M1 foundation manifest non-atomic | VERIFIED | latest_data.py:77-80 bare `write_text`; the atomic helper is used at 44 other call sites — this is the odd one out |
| M2 optional readers dangerous | VERIFIED | and two concrete instances found where it already bites (HIGH: IV-history wipe; HIGH: $0 portfolio headline) |
| M3 compute in serve | VERIFIED | all four cited sites confirmed; `lenses.py` is PARTLY — it's **dead code** (no route since 82707d4), should be deleted not migrated |
| M4 tool_a ~715MB | VERIFIED | 717MB measured — but **644.5MB of it is redundant run-stamped CSV twins** (96MB per run vs 15MB parquet for identical data), and Codex missed that **data/runs is bigger: 957MB** |
| M5 CSV writes non-atomic | VERIFIED | persist.py:326; classification: convenience copies, no in-package reader |
| M6 combined/ leftovers | VERIFIED | 15MB, April-dated; **prune-runs cannot ever clean it** (not in its glob list) |
| Options data underused | VERIFIED | with re-prioritization below — the vintage recorder changes the picture |
| QA/fetch-status underused | VERIFIED | qa_results (265 rows) and normalization_qa (63) have **zero readers**; fetch_status read only by `status` |
| Fundamentals "no reliable artifact" | **STALE** | fetched_fundamentals (310 rows) + raw statements (50,498 rows) exist and version-gate correctly |
| Artifact catalog proposal | VERIFIED | and now drafted for real — §4 |
| DuckDB only if needed | VERIFIED | at 2.1GB total / 62 tickers, pandas-on-parquet is fine |
| Perf: cached Tool A ~14s | PARTLY | the cached harness now self-reports **diverged** (real Tool A stage 13.8s vs harness 8.3s, ratio 0.60) — quote real `stage_timings`, not the harness |
| Perf: fetch dominates, don't micro-optimize | VERIFIED | update_data 91s of the refresh; local compute ~20s |

---

## 2. NEW findings — HIGH (all six re-verified first-hand)

### N-H1. Lab vintage recorder snapshots manifest-REJECTED option data into the append-only PIT store — contamination confirmed on disk
`golden_vector/lab/vintages.py:115` reads mutable `*_latest` aliases directly,
bypassing the manifest and freshness domains. Confirmed damage: the 2026-06-12
vintage holds 2,294 option_signal_summary rows with `schema_version=2.0`,
`as_of_date=2026-06-11` — exactly the v2 snapshot the manifest had refused
minutes earlier. First-write-wins dedupe makes the contamination permanent:
when a clean v3 build publishes later the same day, its values are skipped.
Lab backtests would train on data the product refused to display.
**Fix:** resolve sources through the manifest; skip option sources unless
`freshness_domains.option_artifacts == OK`; stamp `schema_version` +
freshness as first-class vintage columns; one-time cleanup of the 06-12
option rows. (Codex's review predates the lab package entirely.)

### N-H2. Silent wipe of the cumulative option-signal IV history on one failed read
`option_signal_history.parquet` is the only copy of the accumulated IV-rank
series (34 rows, 3 dates; no run-stamped copies anywhere). It is loaded with
`read_optional_parquet` (hedge/option_signals.py:171) — any read exception
(file lock, torn write) returns empty — and cli.py:1892 unconditionally
overwrites the file on the next successful run. One transiently unreadable
file silently destroys the whole history; IV-rank quietly regresses to
LIMITED_HISTORY. **Fix:** fail loud if the file exists but is unreadable;
add a shrink guard (refuse to persist fewer distinct dates than on disk).

### N-H3. Portfolio headline shows $0 gold-down loss when the true value is unknown
`portfolio/analytics.py:274`: `sum_optional_floats(...) or 0.0` coerces an
honest None (no position had a modelable loss — e.g. all betas
low-confidence) into `$0.00`, which the page headlines as "Estimated linear
loss if gold −10%: $0.00". A confidently wrong decision number — the exact
flag-only pattern the house rules ban. Reachable through ordinary
degradation, no reader failure needed. **Fix:** keep None, render "—" with a
no-coverage note.

### N-H4. `_classify_volatility_context` is a broken fork — every non-canonical window renders wrong copy today
detail_panels.py:1620 reads `scoring_config.volatility_diagnostic_bands`; the
real field is `volatility_bands` (the *type* is VolatilityDiagnosticBands).
The `except AttributeError: return "UNKNOWN"` swallows it, so every 6M/3Y
window shows UNKNOWN and the explanation card says "Residual volatility is
moderate" — verified live on ORLA 6M with 89% annualized vol, where the
pipeline classifier says HIGH_NOISE on the same numbers. A hand-fork of
`model/labels.py` logic (check order also swapped) with zero test coverage.
**Fix:** delete the fork, call `determine_volatility_context`, render-level
regression test with noisy + healthy control rows.

### N-H5. `prune-runs --apply` would delete recent full option-chain snapshots — the one perishable dataset
Full chains live only inside `data/runs/<run>/snapshots/options/` (15 dirs,
902 files). The pruner marks every run dir not referenced by retained model
states; a refresh whose publish was blocked (e.g. market closed) never gets
a model state, so its chains are orphaned and prunable — the dry run lists
chain dirs from 06-10 and 06-11 as delete candidates. This violates the
locked keep-full-chain decision. **Fix (interim):** never delete a run dir
containing `snapshots/options/`. **Fix (proper):** move chains to an
append-only store outside data/runs (~0.62MB/refresh ≈ 220MB/yr — keep
forever).

### N-H6. Screening manual store accepts Infinity into Tool B inputs and silently DELETES fields on NaN
`screening/manual_store.py:886` `_normalize_numeric_value` has no isfinite
gate. Proven: `inf` stores as a REAL and flows into EV/EBITDA math as a
"valid" number (wrong answers); `nan` is converted by SQLite to NULL — typing
"nan" into a form field silently clears the stored value while the UI says
"saved" (data loss). The whole input chain is open: serve `_coerce_form_numeric`,
CLI path, Excel backfill script. Bonus hazard: the rate auto-divide
(`numeric > 1.0 → /100`) maps inf→inf. **Fix:** one shared finite validator
in `common/numeric.py`, applied at all entry points (screening, portfolio
`_positive_float`, serve coercer, hedge holdings).

---

## 3. NEW findings — MEDIUM and LOW (grouped)

### Lab package (all new since Codex's review)
- **M:** dial-table parquet + meta JSON written non-atomically and read
  unguarded by `/lab` — torn build = page raises until rebuild
  (conditional_dial.py:249, lab_data.py:40).
- **M:** variant-ledger JSONL append can leave a torn final line that bricks
  `register_variant`/`require_registered`/`n_trials` — the Lab's
  admissibility gate — until hand-edited (ledger.py:60).
- **M:** beta_gap_panel/verdict artifacts (3.1MB) have **no writer in the
  tree** — written by an ad-hoc session script; non-reproducible experiment
  evidence, violates "versioned and auditable".
- **M:** `build_and_save` reads alphabetically-first gold file + raw equity
  dirs, bypassing the foundation manifest; empty dir = bare IndexError.
- **M:** one corrupt vintage source aborts snapshots of all remaining
  sources that week (single loop, blanket catch in cli).
- **M:** vintage stores are irreplaceable but have no backup/versioning.
- **L:** `data/lab/` not gitignored; hand-rolled atomic write with fixed tmp
  name ending `.parquet` (collides + matches future globs); lab artifacts
  live entirely outside manifest/governance.

### Readers / fail-loud discipline
- **M:** Tool A–D serve reads have no post-publish integrity check (option
  artifacts verify sha256; tools render an unexplained empty page if a
  published file goes unreadable) — model_state.py:203.
- **L:** candidate finder warns on read exceptions but is silent when the
  manifest marked an artifact unusable (candidate_finder_data.py:947).
- **L:** hedge report: tool_a fails loud, tool_b silently degrades to "n/a";
  its chain loader is an unverified fork of the shared sha256-checking one.

### Serve boundary
- **M:** serve refits its own OLS (np.polyfit) for non-canonical window
  volatility while published per-window alpha/beta sit in the loaded
  artifact (detail_panels.py:1592) — move diagnostics to the pipeline.
- **M:** static-scan guardrails cover only 4 of 28 serve modules; the one
  confirmed serve-math bug (N-H4) lives in an unguarded file. Add one
  parametrized walker with per-file allowlists.
- **M:** gold-dial recompute cached on Finder (1.06s→0.04s) but uncached on
  Tool B (0.31s/req) and Tool D (0.65s/req) overviews — extract one backend
  scenario service.
- **L:** spot-equality epsilon 0.01 hardcoded in 9 places, two comparators;
  `serve/lenses.py` (221 lines) is dead since 82707d4 — delete; detail page
  recomputes weekly series per request (0.35s, document or persist);
  falsy-zero `or`-coalescing of volatility values (0.0 falls through).

### Footprint / retention / privacy (measured)
- data/ total **2.1GB**; **data/runs 957MB** (176 dirs — the largest area,
  which Codex missed); tool_a 717MB of which **644.5MB is redundant CSV
  twins**; structural intermediates 203MB; horizon_metrics 77MB (never
  pruned); combined/ 15MB (unprunable dead product).
- **M:** pruner treats every dir under data/runs as a run dir — would
  delete `acceptance_logs/`, `ui_refresh_logs/`, and today's blocked
  option-artifacts run (no model state → unprotected).
- **M:** each update-data run copies ~30MB of full equity history; nothing
  runs the pruner automatically.
- **M:** retention model-state snapshots are not write-once — portfolio lot
  edits inherit parent_refresh_id and overwrite the refresh's snapshot.
- **M:** Tool A–D/foundation/QA artifacts carry no schema_version column —
  the two recent incidents (options v2→v3, portfolio v4→v5) failed loud
  precisely because those families *do* version-gate.
- 117 manual-screening sqlite copies under data/runs (Codex H3) — but they
  double as the only backup of user data: add a real weekly backup of
  data/manual (283KB) *before* pruning them.

### Operational state
- **M:** portfolio disabled in config makes `state=complete` permanently
  unreachable — 5 un-actionable alignment warnings forever; manifest
  builder should be portfolio-aware.
- **M:** ticker detail pages render no model-state banner (the 06-09
  misalignment incident showed numbers silently).
- **L:** banner prints raw run-id jargon with no next action;
  fetch-fundamentals republish erases parent_refresh_id + stage_timings;
  perf-profile self-reports diverged (real Tool A 13.8s vs harness 8.3s).

---

## 4. The artifact catalog — first real draft (from code + disk)

15 families. Encoded in code today: required lists, option schema/carry-forward,
portfolio/fundamentals schema gates, pruner globs. Tribal-only: privacy
classes, lab retention, CSV-twin policy, tool-snapshot schema identity.

| # | Family | Owner | Schema (code/disk) | Required | Privacy | Freshness domain | Carry-fwd | UI w/o it |
|---|---|---|---|---|---|---|---|---|
| 1 | foundation manifest | update-data | none | REQ | market | core | no | no |
| 2 | options ingestion manifest | options ingest | none | REQ | market | core | no | no |
| 3 | tool_a/b/c/d snapshots | model pipelines | **none (tribal)** | REQ | market | core | no | no |
| 4 | tool_d_spot | Tool D | none | opt | market | core | no | yes |
| 5 | tool_a_output_* archives | Tool A | none | archive | market | — | — | yes |
| 6 | tool_a_structural (185,895 rows) | Tool A | none | opt | market | — | no | yes (degrades) |
| 7 | profiles/horizon_metrics/usd_equities | features/ingest | none | interm. | market | — | — | yes |
| 8 | 10 option_* artifacts | option builder | v3/v2 | 4 REQ + 6 opt | market | option_artifacts | **YES (sha256+schema)** | yes (notice) |
| 9 | fundamentals (310 + 50,498 rows) | fundamentals fetch | v1/v1 | opt | market | none (warn only) | no | yes |
| 10 | 10 portfolio_* artifacts | portfolio | v5/v4 (failing closed) | opt | **PRIVATE** | none | no | yes (empty state) |
| 11 | manual stores (lots JSON, sqlite) | user input | store v1 | REQ source | **PRIVATE** | — | — | partial |
| 12 | fetch_status/qa/norm-qa | ingestion | none | diagnostics, **write-only** | market | — | — | yes |
| 13 | data/runs replay (957MB) | run_context | none | audit | **MIXED** | — | — | yes |
| 14 | lab vintages + dial + beta_gap | lab | **none** | research | market | — | — | yes |
| 15 | combined/ | REMOVED | — | deprecated | market | — | — | yes |

**Recommendation:** materialize as `golden_vector/contracts/artifact_catalog.py`
and make readers, pruner, and status read from it.

## 5. Retention policy (proposed, with measured numbers)

| Family | Policy |
|---|---|
| Tool run-stamped parquet + intermediates | keep last-10-model-states (pruner already implements — **just run it**) |
| Run-stamped CSV twins (644MB) | **stop writing**; latest-only CSV (saves ~96MB/run) |
| Run dirs / equity snapshots (~30MB/refresh) | keep last 10 model states, prune monthly |
| **Option chain snapshots (0.62MB/refresh)** | **keep forever**, append-only store outside data/runs (~220MB/yr) |
| Replay sqlite (24.4MB) | prune with run dirs **after** adding weekly data/manual backup (283KB) |
| data/lab/vintages (~6MB/yr) | keep forever + weekly backup; monthly partitions at year 2–3 |
| QA/status stamped (~2.6MB) | keep last 10, add to prune patterns |
| combined/ (15MB) | one-time archive + delete |
| horizon_metrics (77MB) | add to prune, keep last 5 |

## 6. Codex's option-data ideas, re-prioritized

(a) Multi-day skew change — **superseded**: the vintage recorder snapshots
option_signal_summary (47 cols) weekly; the trend series accrues
automatically once N-H1 lands. (b) Sector-relative stress — **partly
shipped** (skew_residual_* is the v3 headline; time dimension comes from a).
(c) Liquidity stability / "usually tradable" — feasible from
option_contract_metrics (liquidity_score, rel_spread, depth, quote_flags ×
10 generations) but **decide chain retention first or the history evaporates**
(N-H5). (d) Backtests — the lab package *is* the scaffolding now.
(e) **Cheapest high-value win Codex missed:** one-time backfill of vintage
stores from the 10 on-disk run-stamped snapshots (using each file's own
as_of_date) — recovers ~6 days of history, races against pruning.
(f) Data Health page — fully buildable today from three write-only
artifacts; pure serve-renders-backend-columns.

## 7. Re-prioritized roadmap (supersedes Codex §Recommended Roadmap)

1. **Now (this session) — ✅ ALL FIXED, four commits:**
   N-H1 vintage integrity (manifest-gated sources, option freshness must be
   OK, per-source isolation, contaminated stores deleted; verified live:
   "skipped: option freshness is UNAVAILABLE") · N-H4 volatility fork
   deleted → ONE pipeline classifier + regression tests · N-H3 headline
   keeps None → renders "—" · N-H2 IV-history fail-loud + shrink guard ·
   N-H5 pruner never deletes chain-bearing run dirs + only stamped dirs are
   candidates · N-H6+H2 shared `require_finite` at all four input
   boundaries · M1 atomic foundation manifest · M5 atomic CSVs · lab
   atomic writes + torn-ledger quarantine · data/lab gitignored.
2. **Next:** vintage backfill from run-stamped snapshots (e); beta_gap
   build_and_save entrypoint; serve guardrail walker for all 28 modules;
   portfolio-aware alignment; detail-page banner; delete lenses.py.
3. **Then:** artifact catalog module + pruner reads it; chain snapshots to
   append-only store; stop CSV twins; schema_version columns per tool
   family (one family per commit, ratchet style); Data Health page;
   scenario service consolidation.
4. **Later:** DuckDB only if cross-run research queries hurt; broker import
   before deeper portfolio work (unchanged from Codex).

## 8. What Codex got right that this expansion reinforces

The foundation is genuinely good: 44 call sites already use atomic helpers;
option artifacts have the gold-standard treatment (schema versions, sha256,
carry-forward, fail-closed UI); the pruner protects manifest-referenced
artifacts; the perf instrumentation self-reports its own divergence. The gaps
are discipline-at-the-edges and governance — exactly Codex's thesis. The one
structural correction: the biggest storage problem is data/runs (957MB) and
CSV twins (644MB), not tool_a parquet; and the biggest data-loss risks are
the perishable chains and the two single-copy cumulative stores (IV history,
vintages), none of which Codex flagged.
