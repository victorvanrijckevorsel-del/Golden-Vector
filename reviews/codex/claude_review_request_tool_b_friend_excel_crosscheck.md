# Review Request: Cross-check Tool B logic + numbers vs friend's latest Excel

Date: 2026-04-24
Requester: Emanuel (via Claude Opus 4.7)
Reviewer: Codex
Mode: Read-only logic + data cross-check between our Python Tool B and the friend's Excel
Expected effort: large. Two layers: (1) line up every Tool B formula in code against the Excel formula in the relevant cell, (2) sanity-check the actual numbers each tool produces for the same inputs.

The friend who maintains the Excel has been iterating on it for months. We need to find every place our Python implementation drifted from his model, plus every place his updated source data (AISC, production, etc.) is now different from what's loaded in our manual store.

---

## Source artifacts to cross-reference

| What | Path |
|---|---|
| Friend's latest Excel (canonical Tool B) | `Gold_Mining_Screening_v10226_EVEB.xlsx` (repo root) |
| Friend's prior Excel (for diff context, optional) | `Gold_Mining_Screening_Updated_18Feb2026 (1).xlsx` |
| Our Python Tool B pipeline | `golden_vector/screening/pipeline.py` |
| Our Layer 1 logic | `golden_vector/screening/layer1.py` |
| Our Layer 2 logic | `golden_vector/screening/layer2.py` |
| Our target-price logic | `golden_vector/screening/targets.py` |
| Our verdict assignment | `golden_vector/screening/verdicts.py` |
| Our ranking | `golden_vector/screening/ranking.py` |
| Manual store schema + writers | `golden_vector/screening/manual_store.py` |
| Tool B config (gold price, thresholds, peer benchmarks, tier discounts) | `config/screening_params.yaml` |
| Universe (ticker → currency, jurisdiction tier) | `config/universe.yaml` |
| Last published Tool B output (parquet) | `data/output/tool_b/tool_b_latest.parquet` |
| Manual data the Python tool reads | `data/manual/screening/manual_screening.sqlite3` |

The Excel sheets to focus on:
- **Summary & Parameters** — gold price assumption, all thresholds (forward P/E, FCF yield, AISC, margin, reserve life, leverage)
- **Screening Data** — all per-ticker manual inputs (61 rows). This is the friend's authoritative source for AISC, production, FCF inputs, etc.
- **Layer 1 - Robust Screen** — robustness flags (AISC, margin, FCF, reserve life, leverage) and PASS ALL?
- **Layer 2 - Earnings Model** — forward P/E, EV/EBITDA, peer benchmarks with tier discount, target prices, screening verdict
- **Top performers** — final ranked output
- **AISC Verification** — verified AISC per ticker with sources and verification status (verified/estimated)
- **Production verification** — verified 2026 production per ticker with "Original (oz)" → "Final 2026 (oz)" deltas
- **Instructions** — friend's intended usage and parameter explanations

---

## Mode of review

Three layers, in this order. Don't change code while reviewing — write findings into `reviews/codex/codex_review_tool_b_friend_excel_crosscheck.md` (mirroring this filename) using the same severity convention as past reviews (P0 / P1 / P2 / P3).

### Layer 1 — Logic cross-check

Walk every Tool B calculation in our Python code against the equivalent Excel formula. The Python code is split across `layer1.py`, `layer2.py`, `targets.py`, `verdicts.py`, `ranking.py`, then assembled in `pipeline.py`. The Excel has the same shape: Layer 1 sheet, Layer 2 sheet, Top performers sheet.

For each formula, ask:
1. **Same inputs?** Does our Python pull the same source fields the Excel pulls?
2. **Same operation?** Same arithmetic in the same order?
3. **Same constants?** AISC threshold, P/E target, FCF yield target, margin target, reserve life target, leverage target — do the YAML values match the Excel's `Summary & Parameters` cells?
4. **Same peer benchmarks?** Compare `screening_params.yaml` `peer_benchmarks` (large/mid/small/micro tiers) against the Excel's peer P/E, EV/EBITDA, FCF yield numbers per size bucket.
5. **Same jurisdiction discount?** Compare `jurisdiction_discounts` in YAML against the Excel's tier discount table.
6. **Same size categorization rule?** How does the Excel decide Large vs Mid vs Small vs Micro? Compare to our `screening/layer2.py` size-categorization function.
7. **Same target-price formula?** The Excel produces:
   - Target Price (Peer $) — peer P/E based
   - Target Price (2011 $) — peak P/E based
   - Target Price (FCF Peer $) 2026 — FCF yield based
   - Target Price (Peer EV/EBITDA $) — EV/EBITDA based
   And then takes "best" among these. Our Python has `target_price_peer_pe`, `target_price_peak_pe`, `target_price_peer_fcf`, `target_price_peak_fcf`, `target_price_peer_evebitda`, `target_price_peak_evebitda`, then picks `best_target_price_usd`. **Does the "best" selection rule match the Excel?**
8. **Same Layer 1 PASS criteria?** Does the Excel's `PASS ALL?` cell use the same boolean logic as our `layer1_pass`?
9. **Same verdict assignment?** Excel's `SCREENING VERDICT` column — what verdicts does it emit (STRONG_CANDIDATE / WATCHLIST / SCREEN_OUT / etc.) and on what conditions? Compare against our `screening/verdicts.py`.
10. **Same ranking?** Does the Excel's "Top performers" ranking use the same score we compute (`tool_b_score`)? Or does it sort on something different?

For each disagreement, **report which side looks correct** and propose a fix shape.

### Layer 2 — Number sanity check

The Python tool was last run on 2026-04-23 / 2026-04-24 against 59 active tickers, gold price $4000/oz. The Excel uses gold price $4500/oz. **You'll need to mentally adjust for the price gap** when comparing absolute numbers. If you want apples-to-apples, you can re-run our tool with the Excel's price:

```bash
python main.py tool-b --gold-price 4500
```

Then read `data/output/tool_b/tool_b_latest.parquet` and diff each Python row against the corresponding Excel "Top performers" row. Specifically:
- Forward P/E, EV/EBITDA, FCF yield, margin %, cash margin
- Sustainable FCF, target prices, upside %
- Layer 1 flags (which fail and why)
- Final verdict

For each ticker (start with the 3 with full manual data: AEM, KGC, NEM), report:
- Numbers that match (within rounding)
- Numbers that differ by >5% — and which side looks right
- Numbers that differ by sign or order of magnitude — these are bugs, name them P0

The current Python output has some suspicious-looking numbers I want you to specifically check:
- AEM target price ≈ $797 (current price ~$80) → 300% upside, verdict SCREEN_OUT
- KGC target price ≈ $188 (current price ~$10) → 486% upside, verdict SCREEN_OUT
- NEM target price ≈ $600 (current price ~$50) → 440% upside, verdict SCREEN_OUT

Why are the targets that high? Why are they SCREEN_OUT despite the upside? Either:
- Layer 1 is failing for these tickers (Net Debt/EBITDA? AISC? margin?) — check the Excel for the same ticker
- Target-price formula is over-shooting — compare formula to Excel
- Verdict logic is wrong (SCREEN_OUT despite high upside contradicts intent)

### Layer 3 — Manual data drift

The Excel's `Screening Data`, `AISC Verification`, and `Production verification` sheets have updated, source-verified numbers per ticker (production_oz, AISC, FCF inputs, reserve life, leverage, jurisdiction tier). Our SQLite store (`data/manual/screening/manual_screening.sqlite3`) only has manual data for AEM, KGC, NEM (and stale copies of those — they were entered earlier in the cycle).

For each of the 59 active tickers, compare:
- AISC: Python store (when present) vs Excel `AISC Verification` `Verified AISC (USD)` column
- Production: Python store (when present) vs Excel `Production verification` `Final 2026 (oz)` column
- All other manual fields (cash cost, royalty rate, sustaining capex, D&A, interest, tax rate, reserve life, net debt, EBITDA): Python store vs Excel `Screening Data` row

Report:
- Which Python-store values are stale (Excel has a newer verified number)
- Which Python-store values were never set (Excel has a number, store is blank)
- Tickers where Excel marks status `verified` (high confidence) vs `estimated` (use with caution) — Emanuel needs to know which inputs are firm
- Any tickers in the Excel that are NOT in our `config/universe.yaml` (or vice versa)

The intended outcome here is a punch list: which numbers should be backfilled into the SQLite store, in what order of confidence.

---

## Setup

```bash
python -m pytest -q                          # baseline: 235 should pass
python main.py status                         # see current pipeline state
python main.py tool-b --gold-price 4500      # re-run Tool B at Excel's gold-price assumption
python main.py workspace                      # http://127.0.0.1:8765/tool-b for the live ranked view
```

To inspect the Excel's formulas (not just values), open it in Excel/LibreOffice with formulas visible (Ctrl+`), or read the workbook in Python without `data_only=True`:

```python
import openpyxl
wb = openpyxl.load_workbook('Gold_Mining_Screening_v10226_EVEB.xlsx')  # data_only=False is the default
ws = wb['Layer 2 - Earnings Model']
print(ws['L4'].value)  # the actual formula, e.g. =H4/J4
```

This is essential — the Excel's value cells often hide the real formula behind them.

To inspect the SQLite manual store:

```bash
python main.py manual-data show --ticker AEM
python main.py manual-data show --ticker KGC
python main.py manual-data show --ticker NEM
```

Or directly:

```python
from golden_vector.screening.manual_store import load_store_tables
from golden_vector.app.paths import ProjectPaths
ci, sv, rc, _ = load_store_tables(ProjectPaths.discover())
print(ci.to_string())
```

---

## What I'd most like you to nail down

Ranked by what would change Emanuel's day-to-day use of the tool the most:

1. **Why are AEM/KGC/NEM showing SCREEN_OUT with 300%+ upside?** This is the most user-visible weirdness right now. Either Layer 1 is broken or the verdict logic is. Find the root cause.
2. **The peer benchmark numbers in `config/screening_params.yaml` vs the Excel's peer P/E / EV/EBITDA / FCF yield tables.** If these drifted, every target price in the Python output is off.
3. **The default gold-price assumption.** Friend uses $4500, our config uses $4000. Which is the intended default for v1?
4. **The AISC threshold.** Friend uses $1600 (2nd quartile), our YAML uses $1850. Which is correct?
5. **The "best target price" selection rule.** The Excel emits four candidates and a chosen "best." We do the same. Confirm the choice rule matches.
6. **Manual data backfill order.** Of the 59 active tickers, which 10-15 would have the highest impact if we entered the Excel's verified data into the SQLite store? (i.e., the names that would actually move into a ranked / non-INCOMPLETE state with full data, plus the names with the highest expected upside per the Excel.)
7. **Universe drift.** The Excel covers 61 tickers; our universe.yaml has 64 entries (62 active). Is everyone the same set? Any tickers the friend tracks that we're missing, or vice versa?

---

## Output format

Write `reviews/codex/codex_review_tool_b_friend_excel_crosscheck.md` with these sections:

```markdown
# Codex Review: Tool B vs Friend's Excel — Logic + Numbers Cross-check

Date: 2026-04-XX
Reviewer: Codex

## Summary verdict
- Logic alignment: ALIGNED / DRIFTED / SEVERELY DRIFTED
- Number alignment: ALIGNED / DRIFTED / SEVERELY DRIFTED
- Manual-data backfill needed: how many tickers, what's the rough effort

## Layer 1 — Logic findings (one heading per finding)
### F1.1 — <short title>
- **Severity:** P0/P1/P2/P3
- **Where (Python):** `path.py:line` and the snippet
- **Where (Excel):** sheet name, cell reference, the formula
- **What differs:**
- **Which is correct (and why):**
- **Proposed fix shape:**

## Layer 2 — Number findings (one per ticker that disagrees)
### F2.<ticker> — <short title>
- **Severity:**
- **Python value(s):**
- **Excel value(s):**
- **Likely cause:** (links back to a Layer 1 finding when applicable)
- **Proposed fix shape:**

## Layer 3 — Manual-data drift (per-ticker punch list)
A table:
| Ticker | Field | Python store value | Excel verified value | Status (verified/estimated) | Action |

## Backfill priority list
Top 10-15 tickers ranked by impact, with reasoning.

## Universe gaps
- In Excel but not in our universe:
- In our universe but not in Excel:

## Items not addressed in this review (and why)
```

---

## Ground rules

- Don't change code. This is read-only.
- If the Excel has a formula bug (e.g., wrong cell reference, broken absolute reference), call it out so we can flag it to the friend.
- If our Python has a bug, propose the fix shape but DO NOT apply it. Emanuel will decide which to action.
- When citing Excel cells, give the sheet name + cell reference (e.g. `Layer 2 - Earnings Model!L4`) so Emanuel can click directly to it.
- When citing Python, give `path.py:line` so the workspace links work.
- Be honest about what you couldn't verify — for example, if a formula is too tangled to trace cleanly, say so and suggest how Emanuel could verify it manually.

Thanks. This one matters more than the workspace polish reviews because it's about whether the tool is producing the right answer, not just rendering it nicely.
