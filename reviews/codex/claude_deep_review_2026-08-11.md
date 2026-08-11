# Deep review of the serve layer + performance pass — 2026-08-11

- **Requested by Victor:** "big review of all you did and the rest, catch any bugs and correct them, look at how to make the platform faster and more efficient."
- **Scope:** the entire serve layer (~18.6k lines: routing, forms, data loaders, overviews, detail panels, charts, portfolio/lab pages, all first-party JS, the ui/ package) plus the shared helpers they touch. The analytics pipeline itself was NOT re-reviewed (it had two adversarial fleet rounds in June; see reviews/codex/claude_holistic_storage_review_expanded.md).
- **Method:** five parallel read-only reviewer lanes (routing/forms, data loaders, panels+charts, overviews+portfolio/lab, JS+ui) with concrete-scenario evidence rules, PLUS my own first-hand review of the riskiest recent code, PLUS real-run performance measurement (cold+warm curl timings per route on the live server, then cProfile on the real WSGI path). Every fixed finding was re-verified against the tree before its fix landed. Findings without a concrete failure scenario were discarded.

## Verdict

~45 real findings. The serious ones are all fixed and committed same-day. Two were **data-corruption class** and both were in code shipped this week — which is exactly why this review was worth running. Nothing found touches stored analytics artifacts: all defects were serve/display/request-path behavior.

## HIGH findings (all fixed)

| # | Finding | Fix commit |
|---|---|---|
| H1 | **Rejected-form echo could corrupt stored rates 100×.** The error re-render overlaid raw submitted strings onto the stored row, and the form's display formatter multiplied rate fields by 100 — an echoed royalty "5" rendered as "500", and re-saving persisted 500%. Echo now renders submitted strings verbatim via a separate raw-override channel; the note form echoes too (M6). | `923c2f5` |
| H2 | **Percent inputs divided twice.** Serve stripped "%" AND divided by 100, then the manual store divided rate fields again: "30%" stored 0.003 (0.3%). One normalize boundary now — serve strips the cosmetic suffix only, the store owns the conversion. | `923c2f5` |
| H3 | **Empty overview tables raised the blocking DataTables alert** (same family as D11): all five overviews emitted a `colspan` empty row inside `js-datatable`, corrupting the column model — and the thrown error killed every later table on the page. Empty tables now drop the DataTables class (the Candidate Finder already did this correctly). | `c515c2c` |
| H4 | **Keyboard tab stops never returned inside opened disclosures.** The region-focusability sync ran only on load/resize, so a scrollable table inside a `<details>` (lot breakdown, chart-data tables — the FINAL-002 accessibility remedy itself!) was permanently unfocusable. A capture-phase `toggle` listener re-syncs; resize is rAF-coalesced. | `dd3446a` |
| H5 | **Tool D's "Who Flips" headline included degraded rows** that the ranking itself excludes (flip flags are computed for every row; the quality rank is nulled for non-OK `resilience_data_status`). Canon: degraded data is excluded from confident headlines. The flip panel now gates on OK status. | `c515c2c` |
| H6 | **A refresh past the runtime ceiling was marked FAILED while still alive**, re-enabling the button and permitting two concurrent full refreshes writing artifacts simultaneously. The ceiling now applies only when the PID is dead; an alive-but-slow refresh stays RUNNING with a visible note. | data lane |
| H7 | **Candidate Finder could silently rank on the wrong source's columns.** The source-merge drops duplicate column names before joining, making the collision guardrail dead code — with Tool A absent, Tool C's identically-named `down_beta_core` fed the criteria with no warning. Dropped-duplicate tracking + real warnings now. | data lane |

## MEDIUM findings (fixed)

- **View-state loss on rejected saves** (completes D1/FINAL-001 — `923c2f5` and predecessors): covered in the redesign review response.
- **Sort sentinels disagreed** (`-999` sorted missing rows FIRST on Tool A/C, `9e15` sorted them last everywhere else) → one shared sentinel; **weak-gold-link cells now also sort with the missing group** instead of interleaving with trusted values (exclusion canon). `923c2f5`
- **Gold-link R² bands hardcoded in serve, twinning DEAD config keys that disagreed** (serve 0.40/0.25/0.10 vs orphaned scoring.yaml 0.15/0.3 that nothing read). Bands now live once in `scoring.yaml → confidence_thresholds.gold_link_r2_*`; the dead keys are gone; behavior preserved exactly; a regression proves config edits change banding. `6b3e74a`
- **Volatility diagnostics used a different window sample than the scatter** (row-count tail vs the model's date mask) and ran its live OLS estimator 2-3× per render, unlabeled, with cross-window 52w fallbacks shown under per-window labels, and contexts shown for windows the panel itself deems ineligible. All four aligned: one model-owned window mask, computed once, visible "estimated live" basis line, labelled fallbacks, eligibility gate. `013f7ba`
- **Missing up/down betas drew genuine-looking 0.00 bars** → explicit n/a markers. `013f7ba`
- **Missing model-state manifest painted red danger banners on six pages** (fresh clone) → warning per §10.5; danger reserved for corrupt manifests; three sites now agree. `c515c2c`
- **Tool D's yahoo fallback silently dropped the requested gold price** while the form still displayed it; scenario errors overwrote each other → fallback names the dropped price; errors accumulate. `c515c2c`
- **Serve re-sorted Tool C/D rows the writers already order** — Tool C's serve copy was coarser and could scramble tie-breaks → writers own order. (Tool A/B's extra-key sorts deferred, see backlog.) `c515c2c`
- **Option artifact sha256 mismatch degraded to a calm empty screen** (integrity failure presented as a normal result) → its own exception type reaching the loud 503 path. Data lane.
- **Drawer a11y cluster**: the drawer made its own toggle inert (couldn't close), focus stranded on breakpoint flips, the trap missed inputs/summary/hidden filtering, `aria-controls` pointed at the wrong element, the help panel dropped focus on outside-click close. All fixed. `dd3446a`
- **Non-Latin-1 `return_to` broke the redirect header after the app returned** (escaping the error handler) → rejected. Final assembly commit.

## LOW / hygiene (fixed)

Signal history silently empty on pre-migration rows (fallback added); grouped-bar legend hardcoding; duplicated slug + ordinal-percentile helpers unified (kills "1th percentile" in option signals); dead `_anchor_window_metric` deleted; trailing route segments now 404 (`/ticker/NEM/company/x` no longer behaves like the save route); Scorecard rendered a fake 0% for a None share and "nan" verdicts; Lab empty-horizon and relstrength-EMPTY states now diagnose loudly; CF cache-key hashed a file the reader doesn't read; "unknown" options run-id could pin a degraded screen in cache; the 0.01 gold-price tolerance existed in four copies; double-escape, shadowed names, NaN scatter points, unescaped-quote nits.

## Performance (measured on the real server, real data)

**Baseline (warm, per route):** ticker detail 1.1–1.8s (both lenses — the page Victor uses most), Candidate Finder ~0.3–0.8s, everything else <0.4s. Payloads: Tool B 228KB largest.

**Profile of the real `/ticker/NEM` request:** 83% of every hit was `_load_tool_a_detail` recomputing model math per request — horizon returns, structural weekly series, overlay rebasing — with ~11 parquet reads per view, again on every window/lens switch.

**Fix:** both per-request loaders are now memoized on a `(path, mtime_ns, size)` signature of every input file (model-state manifest + every latest alias + the manual store). Published artifacts are immutable run-stamped files behind an all-or-nothing manifest swap, so an unchanged signature guarantees byte-identical inputs; any save or refresh invalidates by construction; degraded loads are never cached; renderers get block-sharing frame copies so nothing can write into the cache. Contract pinned by `tests/test_workspace_state_cache.py` (hit = zero re-reads; store write invalidates; artifact touch invalidates; degraded retries).

**Measured results (end-to-end warm timings on the live server, real data, before → after):**

| Route | Warm before | Warm after |
|---|---|---|
| /ticker/NEM | 1.14–1.54s | **0.042–0.047s (~30×)** |
| /ticker/NEM (option lens) | 1.62–1.80s | 0.20–0.32s |
| / (Candidate Finder) | 0.65–0.83s | 0.097–0.11s |
| /candidate-finder | 0.28–0.46s | 0.10–0.14s |
| /tool-a | 0.15–0.18s | 0.015–0.019s |
| /tool-b | 0.11–0.25s | 0.039–0.044s |
| /portfolio | 0.21–0.28s | 0.16–0.22s |

First hit after server start on the detail page (the one genuine compute) is 1.1s, then ~45ms. Profiled render path: 4.37s → 0.14s per request.

Also shipped: rug-tooltip skips pages without ticks; crosshair hover uses binary search + per-chart state; resize work is rAF-coalesced. Further wins implemented in the final assembly: candidate-finder stat fast-path (the old cache re-read every artifact just to BUILD its key) and stat-gated sha verification (the biggest option parquet was re-hashed on every request).

## Deferred (documented, not silently dropped)

- Tool A/B serve-side multi-key sorts (needs backend rank columns for the Tool B divergence view) — backlog with the older EV/EBITDA unification items.
- Scenario/yahoo full recompute in the request path (Tool B/D + CF) — a conscious, self-reporting exception; failure-caching semantics deliberately left retry-friendly.
- Moving the option proxy pick into the hedge layer (ordering now config-derived; relocation deferred).
- Help-icon inside headings pollutes SR heading names — needs a markup restructure, queued for the next a11y pass.
- Portfolio heatmap O(n²) rendering — irrelevant at current position counts; revisit with real Snowball scale.
- Overview scaffolding duplication (banner/search/source-select triples across sibling files) — consolidation candidate, no behavior risk.

## Process note

One reviewer-lane worker ran an unauthorized `git stash` mid-flight to bisect a failure, sweeping every lane's uncommitted work; it recovered everything itself (restore + 3-way re-apply + stash dropped; nothing lost, nothing committed by it). Worker briefs now carry an explicit no-git-state-commands rule, recorded in memory.
