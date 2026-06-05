# Holistic Infrastructure Review — collect → update → compute → persist → serve

**Author:** Claude Code (Opus 4.8)
**Date:** 2026-06-05
**Method:** read the path layout (`app/paths.py`) and command spine (`cli.py` runners) first-hand, then four parallel deep-dives across the pipeline stages (ingestion, orchestration/freshness, computation/data-flow, persistence/provenance/serving). All read-only.
**Question asked:** is this the best infrastructure for how data is collected, updated, and computed?

## Scorecard
| Stage | Maturity | One-line |
|---|---|---|
| **Ingestion / collection** | 3 / 5 | Strong failure-isolation + QA gates + currency discipline; fragile single-vendor with no retry/incremental; raw equities/FX not hashed for replay |
| **Update / orchestration** | **2 / 5** ← weakest | Linear exit-code script; no single refresh-id; non-atomic per-stage publish; implicit DAG; mixed-refresh warning is a band-aid |
| **Computation / data-flow** | **4 / 5** ← strongest | Clean layering, pure model fns, shared primitives, enforced QA→score gate, guaranteed USD normalization; options compute leaks into serve |
| **Persistence / provenance / serving** | 3 / 5 | Good retained-history + strong replay capture; non-atomic "latest" writes, ~19.8s request-time compute, no retention, no schema contracts |

**Headline:** the *expensive-to-retrofit* things are done well — the **math/computation architecture is genuinely mature and the two Golden Vector hard rules are honored in code** (QA gates physically block scoring on bad data; currency is normalized to USD before any cross-ticker analytic, with a hard guard that raises on mixed currency). The weaknesses are all in **operational robustness** — orchestration, serving, durability — which are *additive*, not a rearchitecture. So: good bones, soft joints.

---

## What's strong (verified — the reassurance)
- **QA gates actually gate.** Foundation refuses to normalize on raw-QA FAIL (`foundation.py:94`); the latest-snapshot manifest is only written when status≠FAIL; tools refuse to load a non-PASS/WARN foundation (`latest_data.py:93-97`). Scoring cannot run on failed data.
- **Currency rule honored end-to-end.** USD normalization happens at ingest; `build_structural_weekly_series` drops non-OK-normalized rows before computing returns; `_currency_from_equity_frame` **raises** on a mixed-currency frame (`prices_usd.py:141`). No cross-ticker percentile ever sees local currency.
- **Failure isolation at collection is excellent.** Every fetcher is per-entity best-effort with a typed status record; one bad ticker/chain/benchmark never aborts the run; empty/non-optionable chains are persisted as explicit markers, never silently dropped.
- **Clean layering & shared primitives.** Model modules are pure (DataFrames in/out, zero IO); `oriented_percentile`, `build_structural_weekly_series`, `compute_tool_b_in_memory` are each single implementations reused everywhere. No duplicate percentile/weekly logic.
- **Strong provenance capture.** Per-run envelope with git commit+dirty flag, sha256 of every config, an online-`.backup()` copy of the manual SQLite store, immutable hashed options snapshots, and a working `verify-replay`.
- **Centralized path module + retained-history-plus-pointer convention** across all tools (full output + per-run latest + mutable `latest` alias).

---

## The gaps that matter, as themes (prioritized)

### Theme 1 — There is no single "refresh" identity or atomic swap (the root operational weakness)
- Each tool mints its **own** timestamp+uuid run-id (`run_context.py:66`); the only shared id is the foundation's, **copied forward** by each downstream tool reading the latest manifest. So a `refresh` is five independently-stamped stages, and coherence is **reconstructed after the fact** by comparing `snapshot_refresh_run_id` across four parquets — in **two duplicated places** (`cli.py` status and `candidate_finder_data._alignment`).
- `refresh` publishes each stage's `*_latest` alias **immediately** and **non-atomically** (`persist.py:349-358` write straight to the final path; `latest_data.py:69` plain `write_text`). A mid-chain failure leaves fresh foundation+A+B with **stale C+D latests** — the exact "mixed refresh" state the warning later flags. A live UI read during a write can observe a **torn file** (defended only by a broad `except` that silently degrades to empty).
- The A→B→C→D DAG is implicit (hardcoded order); a tool will happily consume a **stale** upstream latest with no staleness guard at compute time.
- **The mixed-refresh warning is a band-aid for a missing design**: one refresh-id threaded through every stage + an atomic all-or-nothing swap would make alignment an *invariant* instead of a *check*.

### Theme 2 — Heavy analytics run at request time instead of being persisted (the "data center" gap)
- The serve layer recomputes option analytics on every cold request: `option_trading_data.load_option_trading_data` re-reads raw chains and rebuilds per-contract Black-Scholes greeks, liquidity tiers, candidate slots, and liquidity medians (two full passes over the chains) — the measured **~19.8s cold load**. The Candidate Finder calls it too, then does its five-way join live (~7.3s).
- Root cause is a **layering leak**: candidate-selection/tiering math (`scan_option_chain`, `build_bucket_slots`) lives in `serve/`, so it naturally runs per-request. Tool A/B/C/D keep their math in `model/` and persist results — options didn't get that treatment.
- One of the two in-process caches (options) keys on **run-ids only**, so a same-id in-place overwrite or torn file can serve stale data; the Candidate Finder cache already uses the correct **content-hash** key. The right pattern exists in the repo — it's just not applied uniformly.

### Theme 3 — Collection resilience & reproducibility are incomplete
- **Single unofficial vendor (yfinance) for everything** — prices, gold, FX, options, risk-free rate — with **no retry/backoff/throttling** and **always a full `period="max"` pull** (no incremental fetch). A transient Yahoo hiccup or soft-ban degrades the whole platform; cost risk is zero (free API) but availability risk is real.
- The **largest raw input — equities + FX — is overwritten in place and NOT hashed into the replay manifest** (only gold, normalized equities, and market snapshots are). So a past run's equity/FX inputs can't be proven intact: a reproducibility hole in otherwise-strong provenance.
- Options ingestion is **entangled with feature computation** (`options_phase` fetches *and* computes greeks/IV in one loop) — you can't re-run options analytics from a stored snapshot without re-entering the fetch path.

### Theme 4 — Durability & contracts
- **No retention/cleanup** anywhere — `data/runs/` grows unbounded (the retention audit already notes 67 run folders in ~3 days), each run copying the full manual-store SQLite + snapshots.
- **No schema contracts on the analytical parquets.** Writers serialize whatever DataFrame they're handed; readers patch missing columns to NA and collapse read errors to empty frames. A renamed/dropped column surfaces as **silently-missing data and degraded screens**, never a loud failure. (Provenance manifests *are* versioned — the analytical outputs are not.)
- **`verify-replay` labeling** marks normal post-`latest` drift as `WARN` (the logic correctly keeps integrity-verdict and drift in separate fields, but the rendering invites "this run is broken" misreading). Relabel drift to INFO/expected.

### Theme 5 — Config-centralization drift (smaller, ties to the Tool C/D audit)
- Tool A/B are fully config-driven, but **Tool C/D embed analytic constants in model code** (`MIN_*_COMPONENTS`, the component lists, tag cutoffs like `down_beta>=1.5`, `headroom<0.10`, and Tool D's rank directions). The hard rule is "modify analytic params only through centralized config." (Already on the Tool C/D fix list as C2.)

---

## Recommended infrastructure roadmap (sequenced)
Do NOT solve Theme 2 by adding more request caches — that hides the first-hit cost and makes keys fragile. Build the data-center instead.

**Tier 1 — The data center (highest leverage; do first):**
1. **One `refresh_run_id`** minted once in `run_refresh` and threaded into every stage, so all outputs are stamped identically by construction — *deletes the entire mixed-refresh reconciliation layer as a class of problem.*
2. **Atomic, staged publish:** compute the whole chain into a staging area keyed by that one id, then **swap all `latest` aliases together at the end (or none)** via `os.replace()` of temp files (the pattern already used in `replay_manifest`/`persist_options`). A failed refresh leaves the prior consistent snapshot fully intact.
3. **Compute option + candidate analytics at refresh time, persist as artifacts** (`option_contract_metrics`, `option_candidate_slots`, `option_overview`, `candidate_finder_input`); reduce `serve/` to thin readers. Fixes the 19.8s load *and* the layering leak in one move.
4. **One atomically-published "current state" manifest** naming the coherent run/hashes for foundation+A/B/C/D+options+manual; UI and CLI read freshness from it instead of each re-deriving joins.

**Tier 2 — Resilience & durability:**
5. Retry/backoff + light throttle in `YahooClient`; add an incremental "bars since last snapshot" fetch path.
6. Hash raw equities + FX into the replay manifest (close the reproducibility hole).
7. Stamp a `schema_version` on each tool output and validate columns/dtypes on write — loud failure, not silent degradation.
8. `prune-runs` retention command (keep N latest + anything referenced by the current-state manifest); make the options cache key content-hash-based like the Finder's.

**Tier 3 — Cleanups:**
9. Config-pin Tool C/D thresholds + directions (also Tool C/D fix C2).
10. Decouple options ingestion from feature computation; relabel `verify-replay` drift to INFO; extract the duplicated freshness/`_unique_strings` helpers into one shared module.

**Explicitly NOT now:** a job scheduler (manual CLI is right for this stage and avoids unattended live-data pulls); more request-time caching; a second data vendor (revisit only if Yahoo reliability becomes a real blocker).

## Bottom line
The infrastructure is **correct where it's hardest to fix and soft where it's easiest to fix.** The computation core is mature (clean layers, shared primitives, enforced QA + currency rules) — that's the part you'd hate to get wrong, and it's right. The work to reach "best infrastructure" is a focused **data-center refactor**: one refresh identity, atomic all-or-nothing publish, and compute-at-refresh artifacts so the UI is a fast reader — then resilience (retry/incremental fetch, full-input hashing, schema contracts, retention). That sequence converts a "works if you follow the happy path" pipeline into a reproducible, robust one without touching the math that's already sound.
