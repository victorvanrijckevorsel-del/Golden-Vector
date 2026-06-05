# Review / Design Response — Option Trading Handoff

**Reviewer:** Claude Code (Opus 4.8)
**Subject:** `reviews/codex/codex_option_trading_handoff_for_claude.md`
**Date:** 2026-06-04
**Verdict:** Codex's diagnosis is **correct**, and its suggested direction (precompute a render-ready artifact during the options phase; UI reads it) is the **right architecture** — it's not a workaround, it's the move that makes the option page finally match how the rest of Golden Vector already works.

## The core principle (answers Q1, Q2, Q6)
Golden Vector's whole design is **raw → features → scoring → UI, each step persisted and auditable, and the UI reads the latest persisted artifact.** Tool A and Tool B already do this (`tool_a_latest.parquet`, `tool_b_latest.parquet`; the UI just reads them). **The option page is the one place that broke the pattern** — it does feature-building + liquidity scanning + slot-building *inside the WSGI request*. That's the entire reason the first load is slow. So the fix isn't clever caching; it's putting the option path back on the house pattern.

**Decision: precompute + persist, do NOT just warm the cache.**
- Warming on startup (Q6) is a band-aid: it recomputes everything on every process restart (exactly what hurt during your dev session with many fresh ports) and persists/audits nothing.
- Precomputing a render-ready artifact fixes it properly: the work runs **once at data-build time**, is persisted, is replay-auditable (fits the provenance system), and survives restarts. After this, cold-start is already fast, so warming becomes unnecessary.

### The clean artifact boundary (Q2)
```
raw option chains        → snapshot parquet            (ALREADY EXISTS — unchanged)
option features          → normalized chain + BS delta + liquidity metrics per contract
option_trading_latest    → render-ready UI package: candidate slots (4 per horizon),
                           accepted candidate grids, overview rows, benchmark-ETF
                           liquidity summary, snapshot dates + run ids for the
                           mixed-refresh check
```
- Built by the **options phase** (`update-data --options`), persisted under `data/output/` or `data/runs/<run_id>/` with a `latest` pointer, snapshotted+hashed into the replay manifest like every other artifact.
- The UI (`serve/option_trading_data.py`, `overview_option_trading.py`, `detail_panels.py`) becomes a **thin reader** of `option_trading_latest`.
- Keep the chain-scanning functions (`options_liquidity.scan_option_chain`, slot building) **pure and testable** — the phase calls them, the request path doesn't.

### What legitimately STAYS in the request path
Only the **sizing calculator** — it's parameterized by user input (chosen contract × quantity × gold-move scenario) so it can't be fully precomputed, and it's cheap. Everything else on the page is a deterministic function of the cached snapshot and belongs in the artifact.

## Refresh scope (Q3) — two explicit actions, don't overload one button
This is the same issue I flagged as F2 in the finish-plan review, now confirmed by the mixed-refresh warning you (correctly) added.
- **Default button = "Refresh options data"** → `update-data --options` (cheap; refreshes the thing the page is about).
- **Add a separate, clearly-labeled "Refresh full model"** → the full `refresh`/`update-data` that also reruns Tool A, Tool B, hedge report, Candidate Finder. Clearly mark it as slower.
- **Keep the mixed-refresh warning** — it's the honest stopgap that makes the staleness visible. One real correctness note: the **sizing calculator uses Tool A beta** for its gold→stock scenario, so after an options-only refresh the scenario P&L runs on a *lagging* beta. For a screening tool with a visible warning that's acceptable for v1; the full-model refresh is what truly realigns it. Worth one sentence in the calculator UI so it's not silent.

## Watch rows (Q4) — default to tradable, Watch behind a disclosure
Emanuel's instruction is "show me good candidates, don't nudge me into untradable contracts." Watch rows visible-but-not-selectable is a fair compromise, but the cleaner answer is:
- **Main matrix shows Tradable candidates by default.**
- **Watch (wide-spread) contracts move behind a "Show watch / wider-spread contracts" disclosure**, with the "you'll likely overpay" framing when expanded.
- This keeps the page on-message and clean, and still preserves full transparency for the curious. It's consistent with keeping `is_usable_candidate()` strict.

## ETF proxy freshness (Q5) — make the zero-state explicit and actionable
Right now Benchmark ETFs = 0 because the cached snapshot predates GDX/GDXJ chain fetching, so the proxy silently hides → it looks broken.
- When benchmark ETFs = 0, **show an explicit prompt**: "GDX/GDXJ option chains aren't in the current snapshot yet — run *Refresh options data* to fetch them."
- **The refresh status should report whether GDX/GDXJ were fetched** (per-symbol success/fail), so a refresh that fails to get them doesn't look like a success.

## Too many concepts? (Q7) — declutter the detail page; don't add a new page
The page is *already* split: `/option-trading` (overview) vs `/ticker/<T>?lens=option-trading` (detail). The overload is on the **detail** page. So the fix is to **reduce**, not to add a third surface:
- **Detail page core = candidate matrix + sizing calculator.** Demote the rest: mixed-refresh warning → compact banner; proxy fallback → only renders when actually relevant; ETF liquidity check → lives on the **overview**, not detail.
- **Naming caution:** Codex's phrase "candidate finder" for the option overview **collides with the actual Candidate Finder tool** (the weighted multi-criteria screener). Don't reuse that name for the option overview — call it the **Option Trading overview** to avoid confusing two different things.

## Priority — this is a strong follow-up, not a blocker
Important sequencing point: **Codex is about to build Tool C/D next** (per the approved build brief). This precompute work is a **clean, well-scoped follow-up to Option Trading**, but the page *works today* (it's slow on cold first-load, then fine). So:
- **Recommended order:** Codex builds **Tool C/D first** (as planned), **then** does this option-precompute refactor as a focused, single-purpose task.
- Don't interleave them — both touch the serve layer, and Tool C/D's Batch 3 already edits the Candidate Finder/serve area. Sequential keeps the tree clean.

## Bottom line
Codex's instinct is right and well-aligned with the codebase: **precompute an `option_trading_latest` artifact in the options phase; make the UI a thin reader; keep scan functions pure.** Plus: two refresh actions (not one overloaded button), Watch behind a disclosure (tradable by default), an explicit ETF zero-state prompt, and declutter the detail page (don't add a new surface; mind the "candidate finder" name clash). Do it **after** Tool C/D, as its own task.
