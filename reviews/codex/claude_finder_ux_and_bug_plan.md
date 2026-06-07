# Plan — Candidate Finder fixes + tool renames + surface C/D + put/call detail (incl. a high-severity finder bug)

**Author:** Claude Code (Opus 4.8)
**Status:** for Codex review (criticise first), then implement.
**Scope:** one high-severity data bug (do first) + four UX/feature changes from Emanuel.

---

## PART 1 — HIGH PRIORITY BUG: 11 of 20 Candidate Finder filters silently return nothing

### Symptom
Emanuel selected **Down-beta** (Options side = Calls) → empty list. Investigation shows it's not down-beta-specific.

### Root cause (measured first-hand)
- `down_beta_core` is non-null for all 60 tickers in `tool_a_latest.parquet`, **but all-null in the finder's joined frame.**
- The joined frame contains `down_beta_core_x`, `down_beta_core_y`, `up_beta_core_x`, `up_beta_core_y`, etc. → **column-name collisions.** The **Options artifact frame** (`candidate_finder_inputs`, built in `option_artifact_frames.py`) carries *copies* of many Tool A/Tool B fields. When `_joined_frame` (`serve/candidate_finder_data.py:285+`) merges it after Tool A/B **without de-duping columns**, pandas appends `_x`/`_y` suffixes, so the plain `down_beta_core` no longer exists.
- Then `_ensure_configured_source_fields` (called after the merges) sees the configured `source_field` `down_beta_core` is "missing" and **creates it as `pd.NA` for every row.**
- `rank_candidates` then drops the criterion: *"Criteria omitted from scoring because every row is missing: down_beta."* Every row becomes `rank_eligible=False` → no usable list.

### Blast radius (measured — non-null count in the joined frame)
**BROKEN (all-null):** `down_beta`, `up_beta`, `downside_volatility`, `confidence`, `aisc`, `debt_to_mktcap`, `ebitda_to_mktcap`, `revenue_to_mktcap`, `fcf_yield`, `best_upside`, `market_cap` — **11 of 20 criteria.**
**OK:** `gold_beta_core`, `leverage`, `ev_ebitda`, `forward_pe`, `iv_percentile`, `iv_skew`, `tool_c_downside_rank`, `tool_c_upside_rank`, `tool_d_quality_rank`.
Both **presets** are affected: `bearish_put` (down_beta, aisc, debt_to_mktcap, confidence broken) and `bullish_call` (up_beta, aisc, fcf_yield, best_upside broken).
Full set of colliding base columns: `aisc_usd_per_oz, asymmetry_ratio_core, best_upside_pct, cash_cost_usd_per_oz, confidence_score, down_beta_core, downside_volatility_52w, fcf_yield, market_cap_musd, net_debt_musd, production_oz, reserve_life_years, score_eligible, screening_verdict, up_beta_core` (+ fx policy fields).

### Fix
In `_joined_frame`, **prevent the collision** so the authoritative (first-merged) source's column survives:
- Before each subsequent `merge`, **drop from the incoming source any non-key column already present in `joined`** (Tool A is merged first, so its betas/quality win; the Options frame's duplicate copies are dropped). Equivalent alternative: merge with explicit `suffixes=("", "_dupe")` and drop the `_dupe` columns. Either way, no `_x`/`_y` should remain and no configured `source_field` should be silently recreated as NA.
- Keep `_ensure_configured_source_fields` only as a backstop for fields **no** source provides (genuinely-unavailable criteria), not as a silent NA-filler over collisions.

### Guard so it can NEVER silently recur (no-silent-failure principle)
- After the join, **assert there are no `_x`/`_y` collision columns** (fail loud in tests; log a loud warning at runtime).
- After the join, **warn loudly if any configured criterion's `source_field` is entirely null** across all rows (today that's silent — it should scream, since "every row missing" almost always means a wiring bug, not real data).
- Add a regression test that builds the joined frame from representative Tool A/B/C/D/Options inputs and asserts each currently-broken `source_field` is populated.

### Sequencing
**Do Part 1 first.** The categorization and preset work below isn't meaningfully testable until the filters actually return data.

---

## PART 2 — Rename the tools (DISPLAY-ONLY; keep internals)
Change only user-facing labels; **do not** rename internal ids/routes/columns/artifacts (that would be a risky data-contract refactor for zero benefit).
| Internal (unchanged) | New display name |
|---|---|
| Tool A | **Gold Sensitivity** |
| Tool B | **Corporate Finance** |
| Tool C | **Gold Downside** |
| Tool D | **Corporate Resilience** |
- Update nav labels (`page_shell.py:_NAV_LINKS`), page titles/headers, and any on-screen "Tool A/B/C/D" text. Keep `tool_a`/`/tool-a`/`tool_a_*` columns/files as-is.

## PART 3 — Surface Tool C (Gold Downside) & Tool D (Corporate Resilience)
They're computed every refresh but have **no nav link and no page** (only Combined, Tool A, Tool B, Option Trading, Candidate Finder exist).
- Add `_NAV_LINKS` entries `("tool_c", "/tool-c", "Gold Downside")` and `("tool_d", "/tool-d", "Corporate Resilience")`.
- Add GET routes `/tool-c` and `/tool-d` in `serve/workspace.py` + overview pages modeled on `overview_tool_a.py` / `overview_tool_b.py`, reading the persisted Tool C/D latest outputs (downside/upside ranks for C; quality rank for D).
- Keep the page shell/nav/DataTables conventions consistent with the existing overview pages.

## PART 4 — Categorize Candidate Finder filters into collapsible groups
Criteria already carry a `group` field in `config/candidate_finder.yaml` — reuse it; this is mainly a re-map + collapsible UI.
- Re-map `group` values to Emanuel's taxonomy:
  - **Gold Sensitivity** ← down_beta, up_beta, gold_beta_core, downside_volatility, confidence
  - **Corporate Finance** ← aisc, leverage, debt_to_mktcap, ebitda_to_mktcap, revenue_to_mktcap, ev_ebitda, forward_pe, fcf_yield, best_upside, market_cap
  - **Options** ← iv_percentile, iv_skew
  - **Gold Downside** ← tool_c_downside_rank, tool_c_upside_rank
  - **Corporate Resilience** ← tool_d_quality_rank
- In the Screen Builder UI, render criteria grouped under collapsible category headers (each expandable to show its criteria), so the user can open a category and pick filters. Preserve the existing per-criterion controls (Use / Direction / Weight / Field).
- Keep group labels driven by config so they stay in sync with the renamed tools.

## PART 5 — Put/Call side-by-side on the COMPANY DETAIL page
When viewing a single company's detail page, show its option candidates as **two clear sections: Puts (60/90/120) then Calls (60/90/120)** — not a puts-vs-calls toggle.
- Source: the per-ticker `candidate_slots` (puts) and `call_candidate_slots` (calls) already exist in `OptionTradingData` and are loadable per ticker.
- Render two labelled blocks on the detail page, each showing the 60/90/120-day horizon candidates with their key fields (strike/moneyness, liquidity tier, bid/ask/mid, IV). Reuse the existing option-candidate rendering helpers where possible (avoid a divergent copy).
- Confirm the detail page can access both put and call slots for the ticker (today the option views lean put-first); wire calls through if needed.

---

## Tests (gates)
- **Bug:** joined frame has no `_x`/`_y` columns; each of the 11 previously-broken `source_field`s is populated; a screen selecting down_beta (and up_beta) returns a ranked, eligible list; both presets return eligible rows; loud warning fires if a configured source_field is entirely null.
- **Renames:** nav/page headers show the 4 new names; internal ids/routes/columns unchanged (no data-contract diff).
- **C/D pages:** `/tool-c` and `/tool-d` render with the persisted outputs; nav links present.
- **Categorization:** criteria render under the 5 category headers; collapse/expand works; selecting within a category applies correctly.
- **Put/call detail:** detail page shows Puts then Calls sections with 60/90/120 horizons for a ticker that has both.

## Non-goals
- No internal renames of `tool_*` ids/columns/routes/files.
- No change to the option full-chain capture decision or the refresh pipeline.

## Self-review
Part 1 is a real, measured, high-severity silent-data bug (11/20 filters dead, presets dead) with a precise root cause (merge collision → NA backfill) and a fix that also adds a no-silent-failure guard so it can't recur — consistent with the "measure the real thing / fail loud" principle. Parts 2–4 lean on existing structure (display labels, the `group` field, the existing overview-page pattern) to stay simple and avoid duplication; Part 5 should reuse the existing option-candidate renderers. Main risk: the merge de-dupe must keep the *authoritative* source's column (Tool A merged first) — Codex should verify the merge order and that no legitimately-distinct same-named field is dropped. Recommend building Part 1 first and re-running a real screen to confirm the lists come back before the UX work.
