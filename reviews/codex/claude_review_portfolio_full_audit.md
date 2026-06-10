# Claude review — Portfolio tool FULL holistic audit (M1–M4)

**Reviewer:** Claude Code (Opus 4.8). Method: a 6-dimension deep-read of the actual code (architecture, math, privacy, honesty, data-integrity, tests) with **adversarial verification of every material finding**, then first-hand confirmation of the top findings by me.
**Verdict: the foundation is sound, but it is NOT "done right" yet — a real remediation backlog.** The architecture, privacy-by-default (committed config is `enabled: false`), fail-closed core, honest exposure buckets, backend-computed / serve-reads-only discipline, and manifest integration all hold up. But the audit found **~13 confirmed should-level issues** the per-milestone reviews missed — one of which violates a *locked* plan decision and produces wrong numbers on a reachable edge case. **Recommend a remediation pass before calling the tool finished.**

> Honest note: my per-milestone reviews (M1/M2-M3/M4) were APPROVE and the core is genuinely good — but I **assumed** the §1e "one shared scenario primitive" guardrail was honored without verifying it. It wasn't. That's exactly why the holistic audit was worth running.

## What's solid (verified)
- **Serve is genuinely reads-only** — no scenario/correlation/valuation arithmetic in `serve/`; only `len()`, percent display, and parsing backend-precomputed JSON/chart coords.
- **All 9 artifacts manifest-registered** + read via `resolve_current_model_artifact_path` with `schema_version` validation → friendly 503 on mismatch.
- **Write path** (validate → atomic store write → no-network recompute → manifest republish → redirect) is correct; the republish rebuilds from disk and does **not** clobber tool_a/b/c/d/option artifacts.
- **Privacy-by-default**: committed `config/portfolio.yaml` is `enabled: false`; store + artifacts + CSV are gitignored (`git check-ignore` confirmed); non-loopback bind refused when enabled; user `note`/text is HTML-escaped (no XSS).
- **Fail-closed + honest core**: hedge UNAVAILABLE on bad benchmark/beta/price; benchmark LOW_CONFIDENCE (no fabricated default beta); correlation INSUFFICIENT_HISTORY; four honest exposure buckets; value-over-time "not profit/loss" label; "modeled hedge size" not "recommended".
- **Pence handled once** end-to-end (snapshot + history) via the shared `price_units.py`; portfolio valuation uses `value_major_unit_price` (no double-adjust); `fetch_fast_info` cached so history adds no extra fetch.

## MUST-FIX (correctness / a stated rule / a footgun)
1. **Forked gold-shock math — the LOCKED §1e guardrail was violated, and the copies diverge on negative beta.** `portfolio/analytics.py:130` does `pnl = value_usd * down_beta * -0.10` with **no `max(0, beta)` floor**, and the publishable gate (`analytics.py:106-113`) requires only `down_beta is not None` (not `> 0`). `hedge/expected_downside.py:93` floors (`max(beta,0)`) and `hedge/portfolio_totals.py:237` floors **and** gates out `beta ≤ down_beta_min_for_scenario`. So a **negative measured down-beta** (a real OLS outcome — a name that rises when gold falls) yields a modeled *gain* (loss 0) in the portfolio while the hedge engine floors/excludes it — and the same un-floored beta shrinks `effective_gold_exposure` (`m4_artifacts.py:360-368`), mis-sizing the hedge. **Fix:** extract ONE shared `modeled_gold_shock` primitive (with the `max(0, beta)` floor + scenario fraction) used by both the portfolio pipeline and the hedge engine; delete the forked arithmetic (this is what §1e/§9 locked).
2. **Data-issues panel truncates to 12 rows** (`serve/portfolio_page.py:106` `for issue in issues[:12]`) — **violates your explicit "show ALL results, never truncate / never +X more" rule**, on the one panel whose entire job is to surface every gap. **Fix:** render all issues (scroll, not truncate).
3. **`enabled: true` footgun (my doing).** The committed default is correctly `false`, but I enabled the tool by editing the **tracked** `config/portfolio.yaml` to `true` — one careless `git add` flips privacy-open for everyone who pulls. **Fix:** a safe local-enable mechanism (a gitignored `config/portfolio.local.yaml` override, or a `GV_PORTFOLIO_ENABLED` env var) so enabling never touches a tracked file; restore the tracked file to `false`.
4. **STALE_FX / missing-shares snapshots flow into NAV, modeled loss, and hedge sizing as "Measured beta" with no data-issue flag** (`pipeline.py:402-435`, `analytics.py:85-138`). A name priced on a 30-day-stale FX still counts as fully measured. **Fix:** treat STALE_FX / non-OK snapshot status as a data issue (flag it, and consider excluding from the confident headline).

## SHOULD-FIX (honesty caveats + robustness)
5. **Gold −10% loss shown with no "linear estimate — a real crash is likely worse" caveat and no partial-coverage flag** (`portfolio_page.py:85,350,363`). The plan required the caveat; the headline also doesn't say it covers only the measured slice.
6. **Total USD P&L headline has no caveat that it blends stock + FX moves** (`portfolio_page.py:84`) — the plan deferred USD P&L *precisely* because a single USD number conflates the two. Add the caveat (lead with local, or label the USD as FX-blended).
7. **Concentration is only "Largest position" (NAV-weight, unlabeled)** (`portfolio_page.py:87`). The plan required **equity-weight AND NAV-weight, both labeled**, plus top-3.
8. **`python main.py refresh` values the portfolio against the PREVIOUS refresh's foundation** (`pipeline.py:167` resolves foundation via the prior model-state manifest, republished only at the end of refresh in `cli.py:3081`) → refresh-built portfolio artifacts are **one cycle stale** (self-corrects next cycle; the UI edit path is correct). **Fix:** resolve foundation from the freshly-written `latest_foundation_manifest.json` during refresh, or run the portfolio step after the manifest republish.
9. **Reconciliation CSV download bypasses the manifest** (`workspace.py:154-159` serves the mutable `_latest.csv` alias via `paths.py:332`) — can diverge from the manifest-resolved parquet and has **no stale-schema 503**. Serve the manifest-resolved artifact (or regenerate the CSV from it on download).
10. **Model-state alignment omits ALL portfolio artifacts** (`model_state.py:710-768`) — a stale-foundation portfolio raises no warning. Add portfolio artifacts to the alignment check.
11. **Valuation never re-asserts the snapshot's currency equals the lot's `buy_currency`** (`pipeline.py:392-436`; the stored-lot parse `manual_store.py:161-174` also skips the guard). If a ticker's snapshot currency ever differs from the recorded buy currency, the FX is mismatched silently. Add an assert/data-issue.
12. **Hedge card shows "OK / $0 notional / 0 puts" when the book has zero measured gold exposure** (`m4_artifacts.py:158-160`) — looks like a real answer. Show "no measured gold exposure to hedge" instead of `$0`.
13. **Un-clamped linear loss can report >100% at extreme beta** (`analytics.py:130`) — folded into fix #1 (the floored/clamped shared primitive).

## TEST GAPS (should)
- MISSING_PRICE no-snapshot line path untested (`pipeline.py:386-458`).
- Served stale-schema **503 never asserted end-to-end** (`workspace.py:632-643`).
- No tracked-file **account-number scan test** (plan §B7 / §8.6).
- Empty-book `artifacts_missing` branch + empty-state untested (`reader.py:60-73`, `portfolio_page.py:71-79`).
- (After fix #1) a negative-down-beta test asserting portfolio and hedge agree.

## NITS
- F6 carryover: redundant `position_weight_fraction` column persisted alongside `nav_weight_fraction`.
- Run-stamped portfolio artifacts accumulate every lot edit with **no pruning/retention** (more on-disk holdings copies than needed).
- `GET /portfolio` gates `enabled` inside the render, not at the route level (works, but inconsistent with the `/portfolio/lots*` route-level gate).
- Resilience overlay ("% of covered holdings = N% of book") is computed but **never rendered**.
- "Largest paired exposures" correlation table silently truncates to top 8.
- Catch-all 500 handler renders `str(exc)` as HTML detail — a non-PortfolioError during the gated build could surface internals.
- Per-position "Gold −10% P&L" is signed-negative while the summary card is a positive "loss" — mixed sign conventions.
- No pence (GBp) hint on the manual buy-price entry for LSE tickers.

## Bottom line
The portfolio tool is **architecturally sound and largely built the right way** — but "built the right way" isn't true until the **must-fix** four are resolved (the forked gold-shock math is the important one: it violates a locked decision and is wrong on negative-beta names), and the honesty caveats (#5–#7) + robustness gaps (#8–#12) are addressed. None are catastrophic; all are well-scoped. Recommend one **remediation milestone (M5)** before declaring the portfolio tool done.
