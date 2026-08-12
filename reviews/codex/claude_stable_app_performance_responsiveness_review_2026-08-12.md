# Codex review — stable app performance, responsiveness, and recovery

**Audience:** Claude Code  
**Review date:** 2026-08-12  
**Stable code boundary:** `226670e` (`test+docs: Phase 1 close-out`)  
**Current branch observed at review start:** `dev-vic` at `c668913`  
**Status:** REVIEW COMPLETE — implementation should start only after Claude's active ticker-page phases have a stable boundary

## 1. Scope and boundary

This review deliberately does **not** judge Claude's work after `226670e`. At 01:00 BST, `HEAD` was already six commits ahead of that boundary and the post-boundary diff touched 74 files with roughly 4,426 insertions. Those files include the new ticker serve layer, screening rules, FX work, model-state contracts, and tests. Reviewing them while the last phases were still moving would create false findings.

For any file changed after the boundary, this review used `git show 226670e:<path>`. Runtime measurements were limited to code paths that are unchanged from `226670e`, or were taken from the existing real-server evidence recorded at that commit. The current root/Option Trading routes returned an expected transitional unavailable state while the newer schema was being built, so those responses were **not** used as evidence against the stable app.

A separate three-hour follow-up is scheduled for 04:00 BST. It should review the completed post-boundary phases only if the branch, artifacts, and tests show a genuinely finished boundary.

## 2. Executive result

The app is not generally slow. The prior cache work was effective: normal warm pages are mostly tens of milliseconds. The worthwhile work is concentrated in a few places:

1. **Correctness/recovery:** one page request can resolve artifacts from more than one model generation while a refresh publishes; a transient required-Parquet read can also be cached as an empty result.
2. **Cold ticker detail:** the first visit still reads the full 397k-row equity snapshot and computes weekly/horizon/overlay data inside the request. On the current real dataset, the unchanged loader took **2.66 seconds cold and 1.59 ms warm**.
3. **Caches checked too late:** Option Trading and Portfolio reread many Parquets before learning that the request is a cache hit.
4. **Storage retention is manual:** the workspace is **6.61 GB**; the existing safe pruner says **3.61 GB** is reclaimable while protecting the latest ten model states.
5. **Developer loop:** the stable full suite is green but takes **24.2 minutes serially**. `pytest-xdist` is already installed, so the remaining task is to validate and standardize a capped parallel gate, not add a new system.

The mobile/responsive CSS foundation is already good. Rebuilding the frontend, adding Redis, introducing a database, or replacing the local WSGI stack would be over-engineering.

## 3. Measured evidence

### 3.1 Request and page measurements

| Measurement | Result | Interpretation |
|---|---:|---|
| NEM detail loader, cold | **2,656.33 ms** | Full snapshot read plus serve-time weekly/horizon/overlay work is visible to the user. |
| NEM detail loader, immediate repeat | **1.59 ms** | The bounded detail cache is highly effective. |
| Rows handed to the detail render | 1,353 weekly + 11 horizon | The delay is not HTML formatting; it is loading and computation before render. |
| Prior real-server `/ticker/NEM`, cold | about **1.1 s** | Confirms cold time varies with dataset/OS cache but remains user-visible. |
| Prior real-server `/ticker/NEM`, warm | **42–47 ms** | Healthy target after caching. |
| Prior ticker option lens, warm | **200–320 ms** | Still does repeated option I/O before its cache check. |
| Prior `/portfolio`, warm | **160–220 ms** | No generation cache; nine artifacts are reopened. |
| Prior `/tool-b`, warm | **39–44 ms** | Already healthy. |
| Tool B HTML payload | **226,180 bytes** | Fine for 61 companies; not a reason for server-side pagination now. |

Evidence: `reviews/codex/claude_deep_review_2026-08-11.md:43-61`, `reviews/codex/milestones/visual_redesign/route_timings_before.json`, and the 2026-08-12 local probe against unchanged `workspace_state.py`.

### 3.2 Real refresh timing

The last complete pre-boundary model state (`20260811T150006Z-refresh-e478d0fd`) recorded:

| Stage | Seconds | Share of recorded stage time |
|---|---:|---:|
| Update/fetch/normalize | 108.862 | 70.3% |
| Tool A | 21.301 | 13.8% |
| Tool B | 1.965 | 1.3% |
| Tool C | 8.072 | 5.2% |
| Tool D | 3.479 | 2.2% |
| Option artifacts | 8.003 | 5.2% |
| Portfolio | 3.186 | 2.1% |
| **Total recorded stages** | **154.868** | **100%** |

Within Tool A, structural build was 8.577 seconds and volatility diagnostics 8.202 seconds: together, **78.8% of Tool A**. Tool A built and persisted all 310,050 structural rows, so this is real useful work rather than a build-then-discard problem. Do not spend time micro-optimizing Tool B or Tool D; the real timing says they are not bottlenecks.

The stable standalone ticker-data stage also recorded **155.627 seconds** for 395,338 rows built and persisted: research series 76.260s, performance 39.475s, gold response 34.078s, persistence 5.225s, and percentiles 0.589s. That work is correctly outside the web request and it does not build a large set only to discard it. If it is added serially to the full refresh, the data build becomes roughly five minutes; research/performance/gold response are the only three places worth profiling.

### 3.3 Storage and retention

| Area | Files | Bytes |
|---|---:|---:|
| Entire `data/` tree | 19,077 | **6,606,825,606** |
| `data/runs/` | 14,772 | **4,098,423,604** |
| `data/intermediate/` | 896 | **1,390,117,757** |
| `data/output/` | 2,948 | **960,390,532** |

The existing `prune_runs(..., keep_model_states=10, apply=False)` dry run completed with no warning:

- 3,588 deletion candidates;
- **3,614,285,249 bytes** reclaimable (54.7% of the current data tree);
- 3,135 old artifact files, 56 old model-state manifests, and 397 old run directories;
- 309 protected artifact paths and 70 protected run IDs.

However, this dry run understates the retention problem. At the stable cutoff, 67 old run directories containing `snapshots/options` occupied **2.003 GiB**. The irreplaceable option files inside them occupied only **43 MiB**; the pruner preserves the entire directory, leaving **1.961 GiB of collateral data permanently exempt**. The workspace also held 66 copied `foundation_usd_equities.parquet` Tool C replay files totalling **1.453 GiB**.

Nothing was deleted during this review.

### 3.4 Test loop

At the stable boundary, the deterministic serial suite was **1,905 passed in 1,451.31 seconds** (24 minutes 11 seconds). `pytest-xdist>=3.6` is already in `requirements-dev.txt`, and the expensive synthetic validation fixture is already module-scoped. The optimization is therefore operational: validate a safe worker count and use it consistently for the full gate.

## 4. Findings to fix

### P1 — one request does not hold one immutable model-state snapshot

**Why it matters to Victor:** a refresh can publish the atomic `latest_model_state.json` pointer between two reads in the same page request. Each individual read is valid, but the page can combine Tool A from generation X with Tool B/options/portfolio from generation Y. It can also show a false integrity warning during the transition.

**Evidence:**

- `golden_vector/serve/workspace_state.py:196-264` resolves several artifacts independently.
- `golden_vector/serve/option_trading_data.py:488-556,632-655` repeatedly reloads/resolves the model state.
- `golden_vector/portfolio/reader.py:49-63` resolves nine artifacts separately.
- `golden_vector/app/model_state.py:177` rereads the current pointer for each resolution.

**Lean fix:** introduce one small immutable `CurrentModelSnapshot` object loaded once at request entry. It contains the parsed manifest, generation identity, and resolved artifact entries. Pass it to page loaders and derive cache keys from it. Do **not** add one new resolver per page; this must be the shared source of truth.

**Acceptance test:** swap the current pointer between artifact-resolution calls and prove the request still uses only the generation captured at entry.

### P1 — transient required reads can become a sticky empty cached page

**Why it matters to Victor:** `read_current_model_parquet` catches every exception and returns an empty frame. `_load_workspace_state` then caches that state even if the emptiness came from a temporary I/O problem. If the immutable file's timestamp and size do not change, subsequent requests can keep showing a blank/degraded page after the file is readable again.

**Evidence:**

- silent-empty read: `golden_vector/app/model_state.py:225-243`;
- unconditional workspace-state cache: `golden_vector/serve/workspace_state.py:179-189`;
- required Tool A/C/D reads: `golden_vector/serve/workspace_state.py:228-257`.

**Lean fix:** return a structured result that distinguishes `missing`, `valid empty`, and `unreadable/corrupt`. Never cache the unreadable/corrupt state. Fail the page loudly when its required source is bad, or degrade only the optional panel and retry on the next request.

**Acceptance test:** make the first Parquet read raise `OSError`, make the second succeed without touching the file, and prove the second request recovers.

### P1 — Candidate Finder can fall back to a stale alias even when a current manifest exists

**Why it matters to Victor:** `_resolve_finder_source` cannot distinguish “there is no model-state manifest yet” from “the current manifest exists but does not expose this artifact.” In the latter case it can use a mutable `latest` alias from an older generation, allowing rankings to mix old and new inputs.

**Evidence:** `golden_vector/serve/candidate_finder_data.py:1447-1473`.

**Lean fix:** pass the already captured `CurrentModelSnapshot` into the resolver. Alias fallback is allowed only when there is genuinely no current manifest. If a current manifest exists and omits/unusably marks the source, show that dimension unavailable.

**Acceptance test:** current manifest present + Tool C entry absent + old Tool C alias present must not read the alias.

### P2 — cold ticker detail still loads and computes too much in the request

**Why it matters to Victor:** the first ticker visit is the main remaining obvious pause. `requested_tickers=[ticker]` still reads the complete normalized-equities Parquet (about 397k rows in the measured foundation), filters it in pandas, builds weekly series and horizon returns, and assembles rebased overlays.

**Evidence:**

- full snapshot read before ticker filter: `golden_vector/app/latest_data.py:134-157`;
- request-time weekly/horizon/overlay work: `golden_vector/serve/workspace_state.py:321-405`;
- full structural Parquet read before ticker filter: `golden_vector/serve/workspace_state.py:521-547`;
- measured cold/warm loader: 2,656.33 ms / 1.59 ms.

**Lean fix, in order:**

1. Re-check this after Claude's new ticker-page phases; they may supersede part of the old detail path.
2. Short term, use shared Parquet readers with `columns=` projection and ticker `filters=` instead of full-frame reads.
3. Proper fix, if still needed: persist a display-ready per-ticker detail slice during the build and make the request a read/filter/format operation only.

**Budget:** cold ticker data load below 400 ms and warm full route below 75 ms on the same machine/data.

### P2 — Option Trading checks its cache after eleven Parquet reads

**Why it matters to Victor:** a nominal warm hit still reads Tool A, Tool B, and nine rendered option artifacts, and resolves the model-state manifest many times, before `_CACHE.get(...)` runs. This explains why the option lens remains 200–320 ms when the basic ticker lens is about 45 ms.

**Evidence:** `golden_vector/serve/option_trading_data.py:481-537,632-675`.

**Lean fix:** add a front cache keyed by the one captured model generation plus stat signatures. A hit must return before any Parquet read. Keep the existing bounded stat-gated SHA verification for a changed generation.

**Acceptance test:** instrument `pd.read_parquet`; the second identical load performs zero Parquet reads.

### P2 — Portfolio reloads nine artifacts on every GET

**Why it matters to Victor:** the Portfolio page reparses the manifest and reads nine full Parquets every time. The reconciliation CSV route invokes the full portfolio loader merely to validate before serving one export.

**Evidence:**

- `golden_vector/portfolio/reader.py:49-165`;
- `golden_vector/serve/workspace.py:923-934`.

**Lean fix:** reuse the shared generation-keyed bounded artifact cache. For the CSV endpoint, validate only the export entry/path/hash. Do not introduce a Portfolio-only manifest cache if `CurrentModelSnapshot` can solve it once for the app.

**Budget:** warm Portfolio GET below 75 ms and zero Parquet reads on an unchanged generation.

### P2 gate for the new ticker page — avoid four independent full-universe reads

This is a **baseline reader risk**, not a review of Claude's unfinished integration. At `226670e`, the four ticker-page readers each parse the manifest, hash the whole artifact, read the full-universe Parquet, and only then filter. The performance artifact was roughly 330k rows. If the new route simply calls all four readers, one navigation will repeat that work four times.

**Evidence:** `golden_vector/app/ticker_page_state.py:71-188,298-371`.

**Lean fix:** the scheduled post-phase review must verify that the new page captures one model snapshot, verifies each generation once, and uses a bounded generation cache. Each full artifact should be read at most once per generation; ticker selection happens from the cached frame or via Parquet predicate pushdown.

### P1 operational — retention is manual and option protection is too coarse

The pruner is already safe and tested, but no refresh or scheduled maintenance path invokes it. There are 56 model-state snapshots above the default keep-ten policy. In addition, `_run_dir_candidates` skips an entire old run directory whenever `snapshots/options` exists, even though the unique option files are only 2.1% of the measured footprint of those directories.

**Evidence:** `golden_vector/app/run_pruning.py:340-365`; CLI-only dry-run policy at `golden_vector/cli.py:639-655`.

**Lean fix:**

1. First run the existing dry-run report as a regular maintenance/status check and report candidate bytes.
2. Decide with Victor whether apply remains manual or runs only after a successful all-or-nothing publication. Do not silently enable deletion.
3. Preserve the irreplaceable option subtree and minimal audit metadata, while allowing unreferenced/refetchable collateral in old chain-bearing runs to prune. Write an explicit test for a mixed old run directory before changing deletion behavior.

This is not the cause of the 2.66-second ticker delay, but unbounded growth can eventually break refreshes and makes backups, antivirus scans, indexing, and workspace copies increasingly expensive.

### P2 — failed refreshes lose their parent timing record

Refresh timings are held in memory, and early failure returns occur before a durable parent summary is written. Successful model states promote detailed substeps only for Tool A; Tool B/C/D/options/portfolio mostly expose a top-level duration, and ticker substeps live in a separate summary.

**Evidence:** `golden_vector/cli.py:3682-3717,3732,4031-4049`; `golden_vector/app/ticker_page_stage.py:507-533`.

**Lean fix:** give the parent refresh one run summary written in `finally`, using the existing shared `record_step_timing`. Merge each child stage's available summary, status, rows built, and rows persisted. This is not a new telemetry system; it makes the existing timing spine survive failures.

### P2 — Tool C replay copies an already immutable 23 MB foundation artifact per run

Tool C includes the normalized-equities foundation snapshot as a replay source, and replay capture physically copies it. At the stable cutoff, 66 copies consumed 1.453 GiB.

**Evidence:** `golden_vector/cli.py:3353-3359`; `golden_vector/app/replay_manifest.py:653-664`.

**Lean fix:** use a content-addressed replay asset or same-volume hard link keyed by path + SHA, while keeping pruning aware of references. Preserve replay verification semantics; do not merely stop capturing the input.

### P2 developer-speed — make the already-installed parallel test mode the measured full gate

The suite is healthy but a 24-minute serial loop discourages frequent full verification. The previous speedup work already added `pytest-xdist` and fixture reuse.

**Lean fix:** after Claude's active work finishes, compare `scripts/test_fast.ps1` (`-n 4 --dist loadscope`) with its `-Auto` mode, record wall time and peak memory, and run the chosen command twice. Add `--durations=25 --durations-min=1` and preserve the result per milestone so regressions are visible. Keep serial pytest available for debugging. Do not weaken canary inputs or skip slow tests.

**Provisional budget:** aim for a full suite at or below 8 minutes on this machine, then set the real gate from the first measured 1,905-test parallel run. The pass set must be identical across two runs.

## 5. Findings to defer unless measurement worsens

### Single-threaded local server

`wsgiref.make_server` is single-threaded (`golden_vector/serve/workspace.py:973-994`), so a cold 2.66-second page blocks other browser requests. However, this is a localhost, single-user app and the caches are currently plain shared `OrderedDict`s without locks.

**Decision:** fix request-time computation and late cache checks first. Only then, if concurrent tabs still feel blocked, use a threaded local WSGI server with locks/single-flight loading around shared caches and mutating routes. Threading first would add concurrency risk without removing wasted work.

### Static assets

The shell can request 18 static files totalling 279,136 bytes on first load. The 15 first-party files total 71,403 bytes and use `no-cache` without ETag/Last-Modified; `workspace.css` discovers nine CSS files through `@import`.

This is inefficient but tiny on localhost. Add ETag/304 or bundle CSS only when a real-browser waterfall shows it matters. Do not spend a phase on it now.

### DataTables paging

Paging is disabled and all rows are in the DOM. At 61 companies and a 226 KB largest page, this is acceptable and preserves quick comparison. Enable 25/50/All client paging only if the universe grows materially or browser profiling shows long scripting/layout time. No server-side paging is justified today.

### Per-step timing in every small model stage

The refresh manifest already answers the main question: update/fetch is 70%, Tool A is 14%, and the rest is small. Tool A has useful per-step row/timing detail; the other model stages mostly expose only total duration. Add shared step timings when those stages are next touched, but do not create a telemetry project for 2–8 second stages.

### Smaller unbounded artifact families

The stable pruner allowlist does not cover roughly 92.44 MiB of stamped lab artifacts, 14.79 MiB of combined outputs, or 76.25 MiB of horizon metrics. These are small beside the run-directory issue. Give each family an explicit “retain forever” or bounded policy when retention code is next changed; do not open a separate cleanup phase for them.

## 6. What is already good

- Workspace/detail caches are bounded, signature-invalidated, copy-on-return, and avoid caching a failed foundation detail load.
- Candidate Finder's normal persisted view has a true stat fast path.
- Raw option chains are no longer scanned in web requests; the large contract artifact is integrity-checked but deliberately not loaded for display.
- Option SHA verification is stat-gated and bounded; a mismatch is never cached.
- Refresh status writes are atomic, duplicate refresh starts are locked out, and dead refresh processes recover.
- The responsive shell has sensible breakpoints, an accessible drawer, reduced-motion handling, and keyboard-reachable horizontal table regions. Static inspection found no reason to redesign mobile layout.
- Vendor assets are immutable-cached.
- The pre-ticker refresh is under three minutes; including the measured ticker stage makes it roughly five minutes and still shows no Tool B/Tool D crisis.
- Tool A records `rows_built` and `rows_persisted`; its measured structural build does not discard most of what it computes.

## 7. Implementation order for Claude after the active phases

### Gate A — correctness and recovery

1. Add one shared request-scoped `CurrentModelSnapshot`.
2. Remove Candidate Finder's stale-alias fallback when a current manifest exists.
3. Replace silent-empty required reads with structured outcomes and never cache transient failures.
4. Re-run the existing model-state, Candidate Finder, workspace cache, option, and portfolio tests.

### Gate B — measured request speed

1. Add an early generation/stat cache to Option Trading.
2. Add the shared generation cache to Portfolio and make CSV validation specific.
3. Review the completed ticker route: one snapshot, one verification/read per artifact per generation, no full-universe repeated reads.
4. Remove remaining ticker-detail request computation with predicate pushdown or a persisted detail slice.
5. Re-run the real route timing harness only after artifacts are stable.

### Gate C — operations and developer loop

1. Record the safe-pruner dry-run in status/maintenance output; narrow the option-chain exemption; ask Victor before changing apply policy.
2. Persist the parent refresh timing summary even on failure and deduplicate replay assets without weakening verification.
3. Validate the parallel full-suite worker count twice and document the winning command plus slowest tests.
4. Consider threading only if the post-fix real-server test still shows blocked concurrent requests.

## 8. Acceptance checklist

- [ ] One request reads `latest_model_state.json` once and never mixes generations.
- [ ] A warm Option Trading or Portfolio hit performs zero Parquet reads.
- [ ] A transient required-file failure recovers on the next request without restart or file touch.
- [ ] Candidate Finder never reads a mutable alias when a current manifest exists but omits that artifact.
- [ ] Cold ticker data load is under 400 ms; warm full ticker route is under 75 ms.
- [ ] The completed new ticker route does not hash/read four full artifacts on every navigation.
- [ ] Pruning remains protection-aware and no deletion policy changes without Victor's decision.
- [ ] Parallel full suite passes twice with the same test set; serial mode remains available.
- [ ] A final viewport/browser pass covers desktop, tablet, and phone only after the new phases are stable.

## 9. Previously reported ticker correctness items

The consolidated backend/FX/AISC/downside review remains the authority for calculation and ticker-publication bugs:

`reviews/codex/claude_phase_one_consolidated_review_and_fx_aisc_downside_plan.md`

Do not duplicate or silently close those items from this performance review. In particular, the earlier generation-atomic ticker-publication finding must be retested against Claude's completed post-boundary implementation during the scheduled follow-up.
