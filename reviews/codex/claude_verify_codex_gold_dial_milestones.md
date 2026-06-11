# Claude verification — Codex's gold-dial Tier 2/3 milestones

**Reviewer:** Claude Code (Opus 4.8), first-hand — read the mapper / resolution / difference-algorithm / pipeline / candidate-finder scenario code myself, ran the full suite + ruff, and fanned out a 6-agent **Opus-only** verification (re-checking Codex's 7 self-review findings + hunting for misses). Trust the code, not the summaries.
**Scope:** the ~6,400-line Tier 2/3 implementation on branch `m1-gold-dial` (commits `e7352fb`..`1849a1a`) — Candidate Finder scenario contract, official-fundamentals artifact + Yahoo mapper, Market-vs-Ours comparison. Companion to Codex's self-review `codex_holistic_review_gold_dial_milestones.md`.

**Verdict: NEEDS CHANGES — but the architecture is excellent and faithful to the v2.1 plan.** Codex did careful, plan-aligned work; the new package is a strong foundation. What blocks merge is a cluster of **mapper-correctness gaps the self-review missed** (one financial-correctness HIGH), plus a re-grade of Codex's own headline finding, plus a red lint gate.

**Verification run myself:** full suite **949 passed** (was 907 after my M1); **ruff RED — 2 F-violations** (see L-RUFF). Codex reported a focused 97-passed subset and did not mention ruff.

---

## The most important correction: Codex MIS-GRADED its own HIGH 1

Codex's only stated blocker (HIGH 1: net-debt cash defaults to 0) is **real but mis-graded, and Codex's proposed fix contradicts the locked plan.**

- The bug (`mapper.py:175` `cash = _find_value(balance, CASH_ALIASES) or 0.0`) overstates leverage — the **conservative** direction (a company looks *worse*, never falsely a buy). The genuinely dangerous case — missing *debt* faking a cash-rich balance sheet — **is handled correctly** (`mapper.py:172-173` returns MISSING).
- Codex's fix ("return MISSING when cash absent") **directly contradicts the plan** (§5h.2, plan_v2.md:268): *"No cash row → cash=0 is acceptable (debt-only), but note it."* The code currently follows the plan — except it omits the **"but note it"** (the cash=0 assumption is stamped `value_status='OK'` with no flag).
- **My judgment (a real call for you):** the plan's "cash=0 acceptable" was written before we saw the net-cash-flip risk (NEW-MED-1 below). A real miner virtually always reports cash, so an *absent* cash line is more likely an alias miss than a true zero. I'd **honor "but note it" by flagging the assumption and degrading it out of the confident Official rank** — *not* Codex's blanket MISSING (slightly over-blanks), and *not* the current silent OK. Re-graded **MEDIUM**, not HIGH.

---

## NEW findings Codex's self-review MISSED (the value of independent review)

### NEW-HIGH 1 — `CURRENCY_BASIS_MISMATCH` is unreachable dead code (dual-listed miners silently rank on apples-to-oranges EV)
The status is in the enum (`contracts/fundamentals.py:23`) and the precedence tuple (`pipeline.py:40`) but is **never assigned anywhere.** `_convert_money` (`mapper.py:375-401`) can only emit `OK / MISSING / CURRENCY_UNCONVERTIBLE`; it never receives the snapshot `feed_currency` to compare against the statement currency. The plan **required** this (§5h.4, plan_v2.md:291) and made it load-bearing for **dual-listings/ADRs** (§7.5) — which **Emanuel owns** (Serabi, Celsius). A CAD-statement / USD-market-cap miner is silently treated `OK` and its Official EV/leverage is computed by adding USD market cap to currency-converted debt of a *different entity basis* — exactly the plausible-wrong-number this project exists to avoid. **Fix:** thread `feed_currency` into `resolve_fundamental_layers`; set the consumed money fields' official status to `CURRENCY_BASIS_MISMATCH` on mismatch (flag, never auto-convert). The roll-up gate then excludes the row automatically. (Or consciously defer with a LOUD UI flag — but it can't stay silent dead code.)

### NEW-MED 1 — split debt-leg `(long_debt or 0.0) + (current_debt or 0.0)` understates leverage (the *dangerous* direction)
`mapper.py:174`: when `Total Debt` is absent and **only one** debt leg is present, the other is coerced to 0 (the `or 0.0` fires because `optional_float` returns None for missing). Plan §5h.2 says a missing leg → MISSING, never 0. This **understates** Net Debt/EBITDA — making a risky miner look *healthier* (opposite of the cash bug, and worse for a screen). Codex flagged the cash direction but not this one. **Fix:** if `Total Debt` absent and *either* split leg absent → `_missing_field`.

### NEW-MED 2 — EBITDA can sum operating income and D&A from **different fiscal periods**
`_map_ebitda` (`mapper.py:210-217`) takes operating income from income's latest period and D&A from cashflow's latest period with **no check they're the same `period_end`.** If Yahoo's income_stmt latest is FY2025 but cashflow latest is FY2024 (one statement lagging — real), it silently sums 2025 op-income with 2024 D&A and stamps 2025's period. **Fix:** require `_period_end(income) == _period_end(cashflow)` or degrade.

### NEW-MED 3 — flow fields labelled `period_type='TTM'` but the data is the latest **ANNUAL** statement
`fetch_financial_statements` pulls `.income_stmt/.balance_sheet/.cashflow` (yfinance **annual**), and `_latest_statement_rows` takes the latest single period. Yet EBITDA/D&A/interest are stamped `TTM` (`mapper.py:247/285/324`) while `statement_period` says `FY{year}`. Self-contradicting provenance on a tool whose premise is auditability; also the field name `ebitda_ltm_musd` implies TTM. Plan §5h.6 said annual-first. **Fix:** stamp `ANNUAL` until real quarterly-TTM reconstruction exists.

### NEW-MED 4 — the status vocabulary is a **second enum** hardcoded in `pipeline.py` (the exact MED-D drift the plan said to eliminate)
Plan §5h.4 / §0.6-MED-D required one shared vocabulary **in `contracts/`, imported everywhere — "no second enum."** But `pipeline.py:39-45` re-lists the precedence locally and never imports the contract's status set. Two engineers can now silently disagree. **Fix:** move precedence into `contracts/fundamentals.py`, import it, delete the local copy; add a drift-guard test `set(precedence) == set(statuses) - {OK}` (today nothing catches a 7th status silently rolling up to MISSING).

### NEW-MED 5 — `fetch-fundamentals` has **no full-outage guard** (a total Yahoo outage overwrites good official data + republishes the manifest)
Per-item degrade is correct, but there's no aggregate check before publishing: a full outage writes an all-MISSING official artifact to the latest alias and advances the model-state manifest to it (`fetch.py:107`, `cli.py:780`). This **contradicts the plan's own fail-closed family** (§0.6 HIGH A — Tool B "fails before persistence"); `fetch_dataset_outage_status` already exists and is unused here. Harm is the safe direction (blank, and the layer is optional), so **MEDIUM**, but it's a real data-loss regression on the new surface. **Fix:** on FULL_OUTAGE (or empty official when prior data exists), write run-stamped only, skip the alias + manifest republish.

### Lower
- **NEW-LOW 1 — net-cash miner silently flips to net-debt.** Tied to the cash bug: if a genuinely net-cash miner's cash alias drifts, net_debt flips negative→positive and is stamped `OK` — a real balance-sheet *strength* silently lost. Reinforces "flag, don't silently OK."
- **NEW-LOW 2 — serve guardrail misses Python-level coalesce-onto-official.** The token denylist (`test_workspace_app.py:1998`) forbids pandas `.fillna(`/`.combine_first(` but not a future `if ours is None: ours = ...get('{metric}_official')` — the single most dangerous boundary violation (serve backfilling our-view from official). Benign today only because `*_our_view` columns are exact aliases. **Fix:** forbid serve assigning from a `*_official` column outside the side-by-side display.
- **NEW-LOW 3 — official run-stamped artifacts are never pruned** (`output/fundamentals/` is absent from `run_pruning.py` candidates) — a *second* unbounded-growth surface beyond Codex's raw-only MED 3.
- **L-RUFF — ruff is RED:** `F401 typing.Any` unused (`fundamentals/raw_store.py:7`) + `F841` unused `paths` (`test_fundamentals_fetch.py:61`). 30-second fixes, but the green `F` baseline is broken and the lint gate was skipped. **Must be green before merge.**

---

## Codex's other findings — re-graded after first-hand check
| Codex | My re-grade | Note |
|---|---|---|
| HIGH 1 net-debt cash=0 | **MEDIUM** | mis-graded (conservative direction); its fix contradicts the plan — see above |
| MED 1 finder drops official | **LOW** | confirmed, but Finder reads **zero** official columns today → nil impact; fix is right, not urgent |
| MED 2 refresh + no freshness surface | **MEDIUM** ✓ | confirmed; real honesty/UX gap |
| MED 3 raw retention unbounded | **MEDIUM** ✓ | confirmed (and there's a second surface — NEW-LOW 3) |
| MED 4 tax_rate coupling | **LOW** | the coupling is *mathematically necessary* (layer2 needs tax_rate); pure label nit |
| LOW 1 differences-only sort | **LOW** ✓ | confirmed; serve sorts on backend columns only |
| LOW 2 optional torn-write | **LOW** | confirmed but slightly over-framed — manifest-resolved readers stay coherent on the prior immutable artifact; the advanced alias does not leak |

## Verified STRONG (independently confirmed — don't touch)
FX-then-`/1e6` order with **no GBp pence double-scale** on statements (the London trap) · reconciliation/CONTAMINATED gate is apples-to-apples and reported-EBITDA is gate-only · per-ticker degrade isolates one bad ticker · staleness gates on `period_end` not fetch time · raw statements persisted **first** then mapped from storage · Official-rank exclusion is the genuine `.where(status OK)` H1 discipline, end-to-end (NA-last) · serve does **zero** arithmetic/coalesce-resolution · manual store **never mutated** (purely additive frozensets) · official layer is a manifest-tracked immutable parquet, empty-state graceful · **no** Yahoo data leaks into operational single-source fields · Candidate Finder scenario path is **side-effect-free**, validates the *dialed* price, fails to persisted-spot honestly, 32-entry bounded LRU correctly keyed · the new Market-vs-Ours + degraded-exclusion tests are **genuine right-reason tests** (distinct values, healthy controls, selective exclusion).

---

## Recommended merge-blockers (fix before merging onward)
1. **NEW-HIGH 1** — implement `CURRENCY_BASIS_MISMATCH` (or defer with a loud UI flag; not silent dead code). Load-bearing for the dual-listed names Emanuel holds.
2. **NEW-MED 1** — split debt-leg understatement → MISSING (dangerous direction).
3. **NEW-MED 2** — EBITDA cross-period guard.
4. **NEW-MED 3** — `period_type='ANNUAL'` on flow fields.
5. **L-RUFF** — green the lint gate.
6. **Cash bug (re-graded MED)** — flag-and-degrade, **NOT** Codex's blanket MISSING (it contradicts the plan). Your call on flag-vs-MISSING; I lean flag-and-exclude.

Defer-with-a-decision (not blockers): MED-2 freshness surface, MED-3 + NEW-LOW-3 retention policy, NEW-MED-4 precedence-in-contracts + drift test, NEW-MED-5 full-outage guard, MED-1 finder official seam, NEW-LOW-2 serve guardrail tightening. Plus the missing tests Codex listed + the period_type/precedence-ordering assertions.

**Bottom line:** this is strong, plan-faithful infrastructure I'd be glad to build on — *after* the mapper-correctness cluster (especially the dual-listing currency gap) and the lint gate are fixed. The headline is that independent review found the real blocker (a financial-correctness gap on Emanuel's own dual-listed holdings) that the self-review missed, while down-grading the self-review's stated blocker.
