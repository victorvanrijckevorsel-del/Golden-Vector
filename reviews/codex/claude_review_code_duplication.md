# Code Duplication Review

**Reviewer:** Claude Code (Opus 4.8)
**Scope:** the whole `golden_vector/` package, focused exclusively on duplicated code and duplicated logic (not correctness/style otherwise).
**Method:** grep for repeated helper signatures across all modules + a full semantic sweep for duplicated logic blocks. Read-only — no code changed.
**Verdict:** The **analytical core is clean** — the things that would be dangerous to duplicate (the percentile engine `oriented_percentile`, the weekly-series builder, the Tool B in-memory seam) are each single implementations, reused. The duplication is in the **utility + freshness/plumbing layer**, where ~10 small helpers and one important piece of *logic* (refresh-id/freshness reconciliation) have been copy-pasted across 4–14 sites each. Two of these duplications hide **latent inconsistencies**, so consolidating has correctness value, not just tidiness. The recent I1 model-state work added a fresh copy of several helpers — worth arresting that trend now, before I2/I3 add more.

---

## Tier A — duplicated LOGIC with latent correctness risk (fix these first)

### A1. Freshness / refresh-id reconciliation — 3 full reimplementations + the CLI status block
The single highest-value duplication. Four places independently compare `snapshot_refresh_run_id` / `refresh_run_id` across foundation/options/Tool A–D and emit OK/WARN/UNKNOWN / "mixed refresh":
- `serve/candidate_finder_data.py:536` `_alignment(...)` → returns `CandidateFinderAlignment`; has an UNKNOWN tier.
- `hedge/report.py:1236` `_context_alignment(...)` → returns `ContextAlignment`; mismatch-vs-options → WARN.
- `app/model_state.py:371` `_alignment(artifacts)` → returns a dict; **has NO UNKNOWN tier** (`status = "OK" if not warnings else "WARN"`).
- `cli.py:~2556` status rendering + per-tool `read_parquet`+run-id inspection blocks (`cli.py:~2605/2632/2673/2708`).

**Why it matters beyond tidiness:** the WARN/UNKNOWN rules have already **drifted** between copies (model_state has no UNKNOWN; the others do). That means the same data can show different freshness verdicts depending on which screen you're on. This is exactly the kind of divergence the single-current-state-manifest is meant to end.
**Consolidate to:** one `reconcile_refresh_run_ids(sources) -> AlignmentResult(status, message, per_source_ids)`. Per the infra plan, **`app/model_state.py` should own this**, and `candidate_finder_data`, `hedge/report`, and the CLI status should call into it. Natural fit for **I5** (the plan already lists "centralize duplicated freshness/alignment logic"), but note I1 just added the *third* copy — so the cost of waiting is more drift.

### A2. Score-eligible truthiness — same intent, opposite default (latent bug)
- `model/tool_c.py:373` and `model/candidate_finder.py:457` `_truthy_score_eligible` — **byte-identical**; default **True**, blacklist `{"false","0","no","n"}`.
- `serve/lenses.py:35` `_is_score_eligible` — default **False**, whitelist `{"true","1","yes"}`.
A missing/odd `score_eligible` value is treated as **eligible** in the models but **ineligible** in the serve lens. That's a real semantic inconsistency riding inside the duplication, not just copy-paste.
**Consolidate to:** one `is_score_eligible(value) -> bool` (+ a `score_eligible_mask(series)`) with one agreed default policy, used by tool_c, candidate_finder, scoring, pipeline, and serve/lenses. (Masking is also re-expressed inline three different ways — `.map(...).mask(~x)` vs `.fillna(False).astype(bool)`.)

### A3. Status-combining precedence (FAIL > WARN > PASS) — 3 copies
- `cli.py:2364` `_combine_statuses` (with unknown-status validation)
- `ingestion/foundation.py:167` `_combine_statuses` (identical minus validation)
- `cli.py:808` `_combine_foundation_and_options_status` (a hand-rolled special case of the same precedence)
**Consolidate to:** one `combine_statuses(*statuses)`; express the foundation+options case in terms of it.

---

## Tier B — duplicated mechanical helpers (low-risk lifts, high copy count)

### B1. Numeric coercion `_optional_float` / `_numeric` / `as_float` — ~12 copies (largest raw count)
Same "coerce to float or None" under two names and minor variants:
- `_optional_float`: `model/tool_c.py:383`, `model/tool_d.py:376`, `model/candidate_finder.py:467`, `model/pipeline.py:639`, `model/structural.py:670`, `serve/format_helpers.py:251`
- `_numeric` (equivalent): `combined/ranking.py:95`, `screening/layer1.py:95`, `screening/layer2.py:103`, `screening/targets.py:159`
- `as_float` (pd.to_numeric variant, byte-identical pair): `features/options_chain.py:267`, `hedge/_helpers.py:12`
**Consolidate to:** one `optional_float`/`as_float` in `golden_vector/common/coerce.py`. (`_optional_int` at `tool_c.py:393` and `serve/option_refresh.py:445` folds in here too.)

### B2. Atomic write (temp-file → replace) — 5 copies, plus non-atomic writers that *should* use it
Encapsulated once (`replay_manifest.py:745` `_write_json_atomic`); re-implemented inline at `app/model_state.py:63` & `:694`, `replay_manifest.py:~327/736`, `ingestion/persist_options.py:110`, `serve/option_refresh.py:145`. **Meanwhile the tool-output writers publish in place** (`ingestion/persist.py:349-357` `_write_parquet`/`_write_csv` — plain `to_parquet`/`to_csv`, no temp file) — the non-atomic `*_latest` publish the infra plan is trying to fix.
**Consolidate to:** promote to `common/atomic.py` (`atomic_write_text`, `atomic_write_bytes`, `atomic_replace`) and route everyone — including `persist.py` — through it. **Best done in I2**, which is already centralizing atomic publish; the helper should land there and the five copies collapse into it.

### B3. SHA256 file hashing — 5–6 copies
`_sha256_file`: `app/model_state.py:788`, `app/replay_manifest.py:763` (even re-imports hashlib locally), `ingestion/persist_options.py:160`. `_file_sha256` (returns None on missing/error): `serve/candidate_finder_data.py:699`, `serve/option_trading_data.py:497`. Plus inline config-bytes hashing at `app/config.py:53,56`.
**Consolidate to:** one `sha256_file(path) -> str | None` in `common/hashing.py`; pick one missing/error policy.

### B4. `read_optional_parquet` / `read_required_parquet` — ~8 copies
`try: pd.read_parquet except: empty/None` (several already named `_read_optional_parquet`): `serve/candidate_finder_data.py:709`, `hedge/report.py:1223`/`:1217`, `serve/option_trading_data.py:474`, `hedge/header_context.py:113`, `serve/workspace_state.py:227`, `app/model_state.py:147/448/475`, `cli.py:2215` + status blocks.
**Consolidate to:** `common/parquet_io.read_optional_parquet(path, *, label=None)` and `read_required_parquet(path, description)`.

### B5. `_unique_strings(frame, column)` — 4 copies
`serve/candidate_finder_data.py:770` (tuple), `serve/option_trading_data.py:510` (tuple, identical), `app/model_state.py:620` (list), `hedge/report.py:1336` (list). All feed the freshness logic in A1, so consolidate together.

### B6. `_repo_relative(paths, path)` — 4 copies
`app/latest_data.py:174`, `ingestion/persist_options.py:156`, `app/replay_manifest.py:773` (identical), `app/model_state.py:781` (the safer try/except version — make this the shared one).

### B7. Ticker normalization `astype(str).str.upper().str.strip()` inline — ~14 sites, with order inconsistency
`screening/manual_data.py:165/185/216/234`, `screening/manual_store.py:769/788/815`, `model/tool_c.py:207/218`, `model/tool_d.py:304/313/321`, `serve/candidate_finder_data.py:384`, and `model/candidate_finder.py:285` — **note the last one flips the order** (`.strip().upper()` vs `.upper().strip()`). Scalar versions already exist (`manual_store.py:862 _normalize_ticker`, `hedge/_helpers.py:142`).
**Consolidate to:** one `normalize_ticker_series(s)` with a fixed order; removes 14 copies and the ordering inconsistency.

### B8. Timestamp / ISO-now helpers — scattered
`_parse_run_id_timestamp`/`_parse_timestamp` (`serve/candidate_finder_data.py:683/690`), `_utc_now_iso` (`app/model_state.py:803`), `_utc_now` (`serve/option_refresh.py:454`), `_mtime_iso` (`app/model_state.py:796`). → `common/time.py`.

---

## A note on the trend (the reason to act)
The I1 model-state module — good work overall — added **fresh copies** of `_sha256_file`, `_repo_relative`, `_unique_strings`, `_clean_string`, `_mtime_iso`, `_utc_now_iso`, **and a third `_alignment`**. That's normal when building a new module fast, but it's the moment to notice the pattern: each new plumbing module re-grows the same six helpers. A small `golden_vector/common/` package would stop the regrowth and is exactly the kind of foundation that makes I2/I3 cleaner rather than adding to the pile.

## Recommended sequencing (don't big-bang this mid-flight)
- **Now / anytime (low-risk, mechanical):** extract `common/{coerce,hashing,parquet_io,time}.py` (B1, B3, B4, B6, B8) and point call sites at them — pure lifts, fully test-covered, no behavior change. This is the safe 80%.
- **Fold into I2 (already touching this):** the atomic-write helper (B2) — I2 is centralizing atomic publish anyway, so land `common/atomic.py` there and route `persist.py` through it.
- **Fold into I5 (already planned):** the freshness/alignment reconciliation (A1) + `_unique_strings` (B5) + status-combining (A3) — `app/model_state` becomes the single owner; the plan already lists this.
- **Reconcile-then-merge (don't blind-merge):** A2 (score-eligible default) and B7 (ticker order) have **divergent behavior** between copies — decide the correct policy first, then unify (these are the two that are latent bugs, not just duplication).

## Bottom line
The model/math layer is properly DRY. The duplication is concentrated in utility helpers (~12× numeric coercion, 5–6× sha256, 4× each of unique_strings/repo_relative, 8× parquet-read, 14× ticker-normalize) and — most importantly — in **freshness/alignment logic that has already drifted across its 3+ copies** (A1) and a **score-eligible helper whose default flips between layers** (A2). Prioritize A1 and A2 (correctness), do the mechanical `common/` extraction as a safe low-risk pass, and let the atomic-write and freshness consolidations ride along with I2 and I5 where that code is already being touched.
