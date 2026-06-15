# Codex review request — click-to-explain ⓘ rollout + column-help correctness audit

**Author:** Claude (dev-vic)
**Date:** 2026-06-15
**Branch:** `dev-vic`
**Commits to review (in order):**

| Commit | What it does |
|---|---|
| `7fdba6d` | Click-to-explain ⓘ backbone + Tool D pilot + **6 wrong/inverted explanation fixes** + Resilience Rank→Score rename |
| `63e7237` | Make the ⓘ panel the **default** for all `help_th` headers (app-wide transport flip) |
| `2e5b946` | Migrate the **Portfolio holdings table** onto `help_th` + 9 new verified explanations |

Diff to read: `git diff 2abbc74..2e5b946 -- golden_vector/serve/column_help.py golden_vector/serve/portfolio_page.py golden_vector/serve/overview_tool_d.py golden_vector/model/tool_d.py golden_vector/serve/static/ tests/test_column_help.py tests/test_workspace_app.py`

---

## 1. What this is

A user-facing feature: every metric **column header** now carries a small clickable **ⓘ** that opens a panel — plain-English meaning + the formula, with a "Read more" expansion (details/thresholds/direction). It replaces the old hover tooltip on headers. All explanation text lives in **one registry** (`golden_vector/serve/column_help.py`, `COLUMN_HELP`) and is resolved through one helper (`help_th`). Thresholds resolve from `AppConfig` at render time.

While wiring this up, a user caught a **backwards direction** in the Tool D "Resilience Rank" copy ("lower is more resilient" when higher = more resilient). That triggered a full audit of all 65 registry entries against the **producing model code**. This review is mostly about **whether the corrected/added copy is actually right** — an inverted "higher/lower is better" is the failure mode we care about most, because it actively misleads.

---

## 2. THE THING TO SCRUTINISE MOST — direction/meaning/formula correctness

I re-derived each flagged column from the code and fixed it. **Please independently verify each against the cited source — do not trust my copy.** Default to "wrong until the code proves it right."

### Fixes in `7fdba6d` (all in `column_help.py` unless noted)

| Key | New copy (claim) | Verify against |
|---|---|---|
| `tool_d_quality_rank` (label renamed **Resilience Rank → Resilience Score**, `overview_tool_d.py:294`) | 0–100 percentile; **higher = more resilient**; sorted highest-first; "not a 1-2-3 ranking" | `model/tool_d.py:430-433` `oriented_percentile(quality_score, high_good=True)`; sort `overview_tool_d.py:81-86` descending; `features/percentile_ranks.py:8-17` |
| `tool_c_upside_rank` | **Higher captures more upside** (was "lower captures more upside" — BACKWARDS) | `model/tool_c.py:169-172` `oriented_percentile(upside_score, high_good=True)`; `tests/test_tool_c.py:58` strongest BBB → `upside_rank==100` |
| `tool_c_downside_rank` | 0–100 percentile; **higher = more fragile, lower = more resilient**; reframed from the mislabeled "1 = most resilient" ordinal. **I did NOT invert the direction** | `model/tool_c.py:165-168`; `_add_component_scores` `:238-253` (all DOWNSIDE_COMPONENTS `high_good=True`); `tests/test_tool_c.py:56` most-fragile AAA → `downside_rank==100`. ⚠️ The audit's derive-agent claimed this was "backwards"; I judged that claim WRONG (lower IS more resilient). **Please confirm I was right not to flip it.** |
| `tool_a_gamma` | meaning = down-gold beta − up-gold beta; **negative is favorable**, lower is better (was "calm vs volatile regime stability") | `model/structural.py:517-521` `gamma_value = down_beta - up_beta`; `model/scoring.py:35-47` (gamma≥positive_min→0, ≤negative_max→1); page intro `overview_tool_a.py:92` "Negative gamma is favorable" |
| `tool_a_asymmetry` | calc = up-beta **÷** down-beta (a ratio); breakeven at **1**, not 0; higher is better (was "up minus down beta", "positive means…") | `model/structural.py:522-526` `asymmetry_ratio = up_beta / down_beta`; `model/scoring.py:50-68` (≤weak_max 0.9→0, ≥strong_min 1.1→1) |
| `tool_d_survival_distance` | "How far the **selected stress gold price (G)**…" (was "today's gold price") | `model/tool_d.py:90-94` `gold_price` param vs `inputs.spot_gold_usd`; `:102` `same_as_spot` shows G≠spot |
| `tool_b_leverage` | new `_tool_b_leverage_thresholds` helper: **LTM EBITDA**, screen fails above **2.5×** (was showing Tool D's 3.0× forward-EBITDA danger band) | `screening/layer1.py:66-70` `leverage = net_debt / ebitda_ltm_musd`; `:118` fail if `> leverage_max`; `config/screening_params.yaml:14` `leverage_max: 2.5`; contrast `config/tool_d.yaml:3` `debt_stress_leverage_danger_threshold: 3.0` (forward, used by `tool_d_*`) |

**Why I'm flagging `tool_c_downside_rank` specially:** my audit fan-out spawned a derive agent + an adversarial skeptic per column. The derive agent asserted the downside direction was "backwards" and that users would "pick the most fragile stocks as safest." When I checked the code myself, that was a **false alarm** — `lower = more resilient` was already correct; the only real defect was the percentile-vs-ordinal mislabel. If I'd trusted the agent I'd have *introduced* an inversion. I want a human-grade second opinion that I read this right.

---

## 3. New copy to verify — Portfolio holdings table (`2e5b946`)

These are **brand-new** explanations I authored from the portfolio code. They did **not** get the adversarial second-opinion (see §5). Please verify each against `golden_vector/portfolio/analytics.py`:

| Key | Data field | Claim | Verify |
|---|---|---|---|
| `portfolio_avg_cost` | `avg_cost_local` | avg buy price/share, local ccy | manual lots aggregation |
| `portfolio_pnl_pct` | `pnl_fraction_local` | (value − cost)/cost, local ccy; higher better | `portfolio/models.py:76` |
| `portfolio_equity_weight` | `equity_weight_fraction` | value ÷ total equity value | `analytics.py:362-363` |
| `portfolio_nav_weight` | `nav_weight_fraction` | value ÷ total NAV (incl. cash/hedges) | `analytics.py:365-366` |
| `portfolio_gold_down_loss` | `gold_down_10_loss_usd` | **linear**: value × max(beta,0) × 10%, beta floored, capped at value; lower safer | `analytics.py:178-205`; `model/gold_shock.py:60-79` (`raw_pnl = value*effective_beta*scenario`) |
| `portfolio_loss_share` | `beta_contribution_fraction` | this position's gold-down loss ÷ portfolio total | `analytics.py:70-74` |
| `portfolio_resilience` | `resilience_bucket` | band from Tool D score: ≥75 Strong, 50–74 Average, <50 Weak | `analytics.py:235-243` + `_resilience_bucket` `:545-552` |
| `portfolio_position_status` | `position_status` | data-quality/degraded flag; degraded ⇒ risk figures withheld | `analytics.py:210-219`, `_degraded_position_status` |
| Down Beta column | `down_beta_core` | **reuses existing `tool_c_down_beta`** entry (same field) | confirm meaning still fits in the portfolio context |

Open question for you: the **10%** in `portfolio_gold_down_loss` and the **75/50** bucket cutoffs are restated in the copy but are code constants (`DEFAULT_GOLD_DOWN_SCENARIO_FRACTION`, `_resilience_bucket`), not config. They don't drift today, but flag if you think they should be config-resolved like the other thresholds.

---

## 4. Architecture change to sanity-check (`63e7237`)

`help_th(..., panel: bool = True)` — I flipped the **default** from hover to the ⓘ panel. Rationale: every `help_th` caller is a table header, and the user wants click-not-hover on all headers, so panel is the correct default. This is a pure **transport** change — the copy is identical to what those headers already showed on hover, so it adds no new unverified text.

- `help_term` (inline prose hover) is a **separate** function, unchanged.
- `help_th(panel=False)` still available for the legacy hover.
- Check: any header that should NOT be a click panel? I believe none. Also confirm the capture-phase click handler in `static/help-popover.js` (it `stopPropagation`s so header-click still sorts) is sound.

---

## 5. KNOWN-INCOMPLETE — the adversarial second-opinion didn't finish

I ran a Workflow (`wf_a95d6254-370`) that, per column, (1) re-derives truth from code and (2) runs an independent skeptic. **A usage cap killed it mid-run:**

- ✅ **Derive-from-code stage ran for all 65 columns** → flagged the 8 issues I fixed.
- ✅ **Skeptic stage completed only for Tool B + Tool D** (29 columns).
- ❌ **Skeptic stage FAILED (cap) for: options/liquidity (13), Tool A (6), Tool C (6), Lab (11)** — and the **9 new Portfolio keys** were authored after the run, so they have **no skeptic pass at all**.

So the columns that have had **only one** (my) code-based check, not an independent one: all options/liquidity, Tool A, Tool C, Lab, and Portfolio entries. **These are where your review is most valuable.** I'll also resume the workflow once the cap resets, but treat your read as the authoritative second opinion.

---

## 6. How I'd like you to review (the discipline that caught the bug)

1. **Verify, don't trust.** For every direction string, open the producing model code and re-derive which way is "good/safe/more" yourself. Percentile/rank columns: check `oriented_percentile(..., high_good=?)`, any config orientation map (`config/tool_d.yaml` `quality_components`), AND the page's sort direction.
2. **Exhaustive + first-hand**, file-by-file — every finding including nits, not a compressed summary (this repo's standard).
3. If the code literally crashes, fix it; otherwise **write findings, don't edit** — I'll reconcile and fix.
4. Tests: full suite was green at `2e5b946` (1193). `tests/test_column_help.py` and `tests/test_tool_c.py` are the most relevant.

## 7. Deliverable

Findings file at `reviews/codex/codex_review_click_to_explain_rollout.md` — severity-tagged, each with file:line evidence and a suggested fix. Call out any direction you believe is still inverted as **HIGH**.

## 8. NOT in scope (don't touch)

- **Candidate-Finder** — deliberately deferred; it's mid-rework by the finder-cleanup stream. Don't add ⓘ there.
- Scorecard/Detail are card/panel layouts (no column headers) — inline `help_term` there is correct, not a divergence.
- Two open **product** questions (my call to put to the user, not correctness): Tool C default sort (most-fragile-first?) and the near-duplicate Tool C Rank/Score columns.
