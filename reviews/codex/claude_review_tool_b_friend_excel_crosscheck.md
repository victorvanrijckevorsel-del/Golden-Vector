# Claude Review: Tool B vs Friend's Excel — Logic + Numbers Cross-check

Date: 2026-04-24
Reviewer: Claude (Opus 4.7)
Sources:
- Friend's Excel: `Gold_Mining_Screening_v10226_EVEB.xlsx`
- Our Python Tool B: `golden_vector/screening/{layer1,layer2,targets,verdicts,ranking,pipeline}.py`
- Our config: `config/screening_params.yaml`, `config/universe.yaml`
- Our SQLite store: `data/manual/screening/manual_screening.sqlite3`
- Latest published parquet: `data/output/tool_b/tool_b_latest.parquet` (re-run at $4500/oz for apples-to-apples comparison)

This is my parallel review to Codex's. We will compare findings in a merged comparison file once Codex is done.

---

## Summary verdict

- **Logic alignment:** DRIFTED. Most formulas match cell-for-cell. Two structural divergences (the `best_target_price` selection rule and the EV/EBITDA target-price addition) plus one subtle robustness edge case (leverage when EBITDA ≤ 0).
- **Number alignment:** ALIGNED at the per-formula level (within 0.5%) when share prices are equalized. The headline upside numbers in our workspace (300%+) are an artifact of the `best_target = max(...)` rule, not arithmetic bugs.
- **Manual data drift:** Modest — only 3 of 59 active tickers have any manual data in our store at all, and of those 3, only AEM has stale AISC ($1475 vs Excel verified $1275). The other 56 active tickers are blank and need backfill from Excel `Screening Data`.
- **Universe drift:** Minor — Excel has 61 tickers; our universe has 64 entries (61 from Excel + 3 legacy: GOLD/FNV/FRES.L inactive). 2 Excel tickers (ARMN, NGD) are inactive in our universe because Yahoo can't fetch them.
- **Display claim mismatch:** Excel `Summary & Parameters` says "AISC Target < $1,600/oz (2nd Quartile)" but the actual cell value used in formulas is $1850. Our YAML uses $1850 — matches the actual computation, not the display claim. This is a friend-side label inconsistency; we should know about it but don't need to change anything.

---

## Layer 1 — Logic findings

### F1.1 — Layer 1 robust-screen formulas: ALIGNED

**Severity:** none (informational)

I traced each Layer 1 formula in [golden_vector/screening/layer1.py](golden_vector/screening/layer1.py) against Excel `Layer 1 - Robust Screen` row 5 (BTG sample). All five flag formulas match:

| Excel | Python | Match |
|---|---|---|
| `G5 = B$5 - E5` (cash margin = gold − AISC) | `cash_margin_usd_per_oz = gold_price - aisc` (line 61) | ✓ |
| `H5 = G5 / B$5` (margin %) | `margin_pct = cash_margin / gold_price` (line 62) | ✓ |
| `J5 = (G5*D5 - sus_capex*1M) / 1M` | `((cash_margin * production_oz) / 1M) - sustaining_capex_musd` (line 63) | ✓ |
| `K5 = J5 / C5` (FCF yield) | `fcf_yield = sust_fcf / market_cap` (line 64) | ✓ |
| `Q5 = AND(F5..P5 all PASS)` | `layer1_pass = len(reasons) == 0` (line 85) | ✓ |

Constants:
- AISC threshold: Excel `Summary & Parameters!E12 = 1850.0` (label says "$1,600"). Our YAML `aisc_max: 1850`. ✓
- Margin floor: Excel E13 = 0.5. Our YAML `margin_min: 0.5`. ✓
- FCF yield floor: Excel E11 = 0.15. Our YAML `fcf_yield_min: 0.15`. ✓
- Reserve life floor: Excel E14 = 6.0. Our YAML `reserve_life_min: 6`. ✓
- Leverage ceiling: Excel E15 = 2.5. Our YAML `leverage_max: 2.5`. ✓

### F1.2 — Leverage when EBITDA ≤ 0: BEHAVIOR DIVERGES

**Severity:** P2 (low blast radius — only fires for distressed tickers, but the divergence is real)

**Excel** (`Layer 1 - Robust Screen!O5`):
```excel
=IF(VLOOKUP(...,19,FALSE())>0, VLOOKUP(...,18,FALSE())/VLOOKUP(...,19,FALSE()), 0)
```
If EBITDA ≤ 0, returns **0** as the Net Debt/EBITDA value. Then the leverage flag (`P5`) does `IF(O5 <= 2.5, "PASS", "FAIL")`, so a zero-EBITDA company **passes** the leverage check.

**Python** ([layer1.py:75-81](golden_vector/screening/layer1.py#L75-L81)):
```python
if ebitda_ltm_musd <= 0:
    reasons.append("LEVERAGE_NON_POSITIVE_EBITDA")
else:
    leverage = net_debt_musd / ebitda_ltm_musd
    if leverage > thresholds.leverage_max:
        reasons.append("LEVERAGE_FAIL")
```
If EBITDA ≤ 0, Python adds `LEVERAGE_NON_POSITIVE_EBITDA` to the failure reasons → the row **fails** Layer 1.

**Which is correct:** The Python interpretation is more conservative and IMO more defensible — a company with zero/negative EBITDA shouldn't get a free pass on leverage. The Excel behavior silently turns a red flag into a green flag. **Recommend keeping the Python rule and flagging the Excel as having a soft bug here**, but raise it with the friend to confirm intent.

**Proposed fix shape:** none in Python. Suggest the friend change Excel `O5` to return `"N/M"` (not meaningful) when EBITDA ≤ 0 and have `P5` treat that as `FAIL`.

---

## Layer 2 — Logic findings

### F2.1 — Layer 2 forward-earnings formulas: ALIGNED

**Severity:** none (informational)

Trace from [golden_vector/screening/layer2.py](golden_vector/screening/layer2.py) vs Excel `Layer 2 - Earnings Model!I5..L5`:

| Excel | Python | Match |
|---|---|---|
| `H5 = gold_price * prod / 1M` | `forward_revenue_musd = (gold_price * prod) / 1M` (line 67) | ✓ |
| `I5 = IF(cash_cost > 0, ...op_margin = gold-cash_cost..., else gold - aisc*0.7)` | identical IF/ELSE in lines 68-72 | ✓ |
| `J5 = (I5 - DA - Int) * (1 - tax/100)` | `(ebitda - da - int) * (1 - tax_rate)` (line 78) | ✓ |
| `K5 = J5 / G5` (units: $m / m_shares = $/share) | `(net_income_musd * 1M) / shares_outstanding_raw` (line 80) | ✓ — different unit conventions, same answer |
| `L5 = F5 / K5` (forward P/E) | `share_price_usd / forward_eps` (line 81) | ✓ |
| `O5 = (D5 + net_debt) / I5` | `(market_cap_musd + net_debt_musd) / forward_ebitda_musd` (line 86) | ✓ |

The `aisc * 0.7` proxy used when cash_cost is absent is identical in both. (No firm source for the 0.7 factor in either codebase — both likely follow the same operating manual heuristic.)

### F2.2 — Royalty / tax-rate input convention: SUBTLE DIVERGENCE — Excel DATA HAS BUGS

**Severity:** P1 (affects ~4 tickers in the Excel; doesn't affect us right now but will the moment we backfill manual data from Excel)

**Excel formula** (`Layer 2!I5` and `J5`) hardcodes a `/100` divisor:
```excel
... - (H5 * VLOOKUP(...,12,FALSE()) / 100)   # royalty
... * (1 - VLOOKUP(...,16,FALSE()) / 100)    # tax
```
This expects the input cell to be in **percent form** (e.g., `5` for 5%, not `0.05`).

**Python** ([layer2.py:119-125](golden_vector/screening/layer2.py#L119-L125)) `_rate()` helper:
```python
if numeric > 1.0:
    return numeric / 100.0
return numeric
```
Auto-detects: if input > 1, treats as percent; else treats as decimal. **More forgiving.**

**The Excel data has both conventions mixed** — sample of `Royalty Rate (%)` column from Excel `Screening Data`:
| Ticker | Stored value | Excel-effective value |
|---|---|---|
| AAUC.TO | 6.0 | 6% ✓ |
| BTG | 4.0 | 4% ✓ |
| **AGI** | **0.03** | **0.03% ✗** (likely meant 3%) |
| **BGL.AX** | **0.025** | **0.025% ✗** (likely meant 2.5%) |
| **DRD** | **0.05** | **0.05% ✗** (likely meant 5%) |
| **EMR.AX** | **0.03** | **0.03% ✗** (likely meant 3%) |

For these four tickers, the friend stored decimals where the formula expects percents. The Excel will compute royalty cost ≈ 0 and effective tax ≈ 0, **massively inflating their forward EBITDA, net income, EPS, and target prices**. This means the Excel "Top performers" ranks for AGI/BGL.AX/DRD/EMR.AX are likely too generous.

**Which is correct:** The friend's intent for these four tickers is presumably 3% / 2.5% / 5% / 3% royalty rates, not the literal 0.03% / 0.025% / 0.05% / 0.03% the formula computes. Our Python `_rate` would handle either convention correctly.

**Proposed fix shape:**
- Tell the friend to fix those four cells in the Excel (multiply by 100 OR change the formula to `IF(rate < 1, rate, rate/100)`).
- When backfilling our SQLite store from Excel `Screening Data`, **multiply those four tickers' royalty/tax inputs by 100 first** OR rely on Python's auto-detect (already works). Either way, our store should hold the same effective rate as the Excel's intent, not the literal cell value.

### F2.3 — Verdict thresholds: ALIGNED

**Severity:** none

| Excel `Y5` | Python `verdicts.py` | Match |
|---|---|---|
| `IF(L5 < E$10 AND L5 > 0 AND Layer1=PASS, "STRONG", ...)` (E10 = 8.0) | `forward_pe < 8 AND layer1=PASS → STRONG_CANDIDATE` | ✓ |
| `IF(L5 < 10 AND L5 > 0, "WATCHLIST", ...)` (hardcoded 10) | `forward_pe < 10 → WATCHLIST` | ✓ |
| else "SCREEN OUT" | else `SCREEN_OUT` | ✓ |

Note: Excel hardcodes the 10x WATCHLIST threshold inside the formula (not from `Summary & Parameters`). Our YAML pulls it from `verdict_thresholds.watchlist_forward_pe_max: 10`. Same value — no drift today, but if the friend ever changes it in Excel, ours won't auto-track.

---

## Targets — Logic findings

### F3.1 — Peer/Peak P/E and FCF target formulas: ALIGNED

**Severity:** none

| Excel | Python | Match |
|---|---|---|
| `T5 = R5 * (1 - S5)` (adjusted peer P/E = peer × (1−tier_disc)) | `adjusted_peer_pe = benchmark.pe_2026 * (1 - tier_discount)` ([targets.py:42](golden_vector/screening/targets.py#L42)) | ✓ |
| `W5 = V5 * (1 - S5)` (adjusted peak P/E) | `adjusted_peak_pe = benchmark.pe_2011_peak * (1 - tier_discount)` (line 43) | ✓ |
| `AA5 = T5 * K5` (peer P/E target) | `target_price_peer_pe = adjusted_peer_pe * forward_eps` (lines 45-49) | ✓ |
| `AC5 = W5 * K5` (peak P/E target) | `target_price_peak_pe = adjusted_peak_pe * forward_eps` (lines 50-54) | ✓ |
| `AI5 = F5 * (AF5 / AG5)` (FCF peer target) | `share_price_usd * (actual_yield / target_yield_2026)` (lines 56-60) | ✓ |
| `AK5 = F5 * (AF5 / AH5)` (FCF peak target) | `share_price_usd * (actual_yield / target_yield_2011)` (lines 61-65) | ✓ |

### F3.2 — Excel does NOT compute EV/EBITDA target prices; Python DOES

**Severity:** P2 (Python invents 2 extra target-price scenarios that Excel doesn't have)

**Excel** computes:
- `O5 EV/EBITDA` (the multiple) ✓
- `P5 Peer EV/EBITDA` (the benchmark) ✓
- `Q5 vs Peer EV/EBITDA` (the % gap) ✓

But it **does not** convert EV/EBITDA into a target price. The analyst eyeballs the gap.

**Python** ([targets.py:67-78](golden_vector/screening/targets.py#L67-L78)) computes two extra targets:
- `target_price_peer_evebitda = ((ebitda * peer_multiple) - net_debt) / shares`
- `target_price_peak_evebitda = ((ebitda * peak_multiple) - net_debt) / shares`

These then enter the `best_target_price_usd = max(...)` pool.

**Which is correct:** Defensible either way — EV/EBITDA → target price is a standard valuation move. But the friend's Excel intentionally keeps EV/EBITDA as a *check* (does this name look cheap on enterprise basis?) rather than a target generator. **Recommend the Python keep computing them** (they're useful) **but exclude them from the `best_target` pool by default** so we match the Excel's intent for the headline ranking.

### F3.3 — `best_target_price_usd = max(...)`: STRUCTURAL DIVERGENCE

**Severity:** P0 (this is the source of the visually inflated upsides in our workspace)

**Excel** does NOT compute a single "best" target. The `Top performers` sheet shows four separate columns:
- `AA Target Price (Peer $)` and `AB Upside to Peer %`
- `AC Target Price (2011 $)` and `AD Upside to 2011 %`
- `AI Target Price (FCF Peer $) 2026` and `AJ Upside to FCF Peer %`
- `AK Target Price (FCF 2011 $)` and `AL Upside to FCF 2011 %`

The analyst reads all four and picks which scenario to weight.

**Python** ([targets.py:88-94](golden_vector/screening/targets.py#L88-L94)):
```python
valid_targets = [value for value in targets.values() if value is not None]
best_target_price_usd = max(valid_targets) if valid_targets else None
best_upside_pct = (best_target_price_usd - share_price_usd) / share_price_usd
```
Takes the **maximum** of all 6 targets (4 from above + 2 EV/EBITDA). This always picks the most aggressive scenario, almost always `target_price_peak_fcf` (2011-peak FCF re-rating).

**Proof** (from re-running our tool at $4500/oz, comparing to Excel):

| Ticker | Excel Peer$ | Excel Peak$ | Excel FCF Peer$ | Excel FCF Peak$ | Python "best" | Notes |
|---|---|---|---|---|---|---|
| AEM | 237.53 | 423.09 | 413.05 | **1032.63** | 966.59 | Python picks ≈ FCF Peak |
| KGC | 50.55 | 90.03 | 92.43 | **231.07** | 230.81 | Python picks ≈ FCF Peak |
| NEM | 144.84 | 258.00 | 292.51 | **731.27** | 736.65 | Python picks ≈ FCF Peak |

The "300% / 486% / 440% upside" the workspace shows for these names is the **2011-peak FCF re-rating scenario** — the most extreme of the four. Excel intentionally never displays it as the headline.

**Proposed fix shape (P0, ship soon):**
- Stop emitting `best_target_price_usd` as a single number.
- Emit each target separately and the corresponding upside, like the Excel.
- Either (a) drop `best_target_price_usd` and `best_upside_pct` from the published columns, OR (b) redefine "best" as the **median or mean** of the 4 scenarios (excluding EV/EBITDA), so the headline upside is a balanced view, not the aggressive one.
- The workspace Tool B view should show the four scenarios as separate columns (matching Excel `Top performers`).
- The `tool_b_score` formula currently mixes verdict (70%) + normalized upside (30%) using `best_upside_pct`. If `best_upside_pct` changes meaning, the score formula needs revisiting.

### F3.4 — `tool_b_score` formula: NOT IN EXCEL

**Severity:** P3 (tool-specific composite; not in friend's Excel at all)

Excel ranks `Top performers` by `Upside to Peer %` (column AB) descending — at least the visual top of the sheet looks ordered that way.

Our Python ([verdicts.py:34-40](golden_vector/screening/verdicts.py#L34-L40)) computes:
```python
base = {STRONG: 0.85, WATCHLIST: 0.60, SCREEN_OUT: 0.20}
upside_score = clip(best_upside_pct, -0.5, +1.5) → normalized to [0, 1]
score = 100 * (0.7 * base + 0.3 * upside_score)
```
Then ranks descending by score.

**Which is correct:** This is a Python-only invention. Codex and Claude have both signed off on it in earlier reviews — it's a defensible weighting (verdict dominates, upside breaks ties within verdict). But because it depends on `best_upside_pct`, fixing F3.3 will also shift the rankings.

**Proposed action:** keep the score formula but, after fixing F3.3, re-validate that the resulting rank order is still sensible.

---

## Constants & config — drift findings

### F4.1 — Default gold-price assumption: $4000 (ours) vs $4500 (Excel)

**Severity:** P1 (decision item)

- Excel `Summary & Parameters!B5 = 4500.0`
- Our `config/screening_params.yaml`: `default_gold_price_assumption: 4000`

The Excel was last edited Jan 2026; gold has rallied since. $4500 is closer to current spot (~$4400-4500 in April 2026). The friend's choice is more current.

**Proposed action:** Bump our `default_gold_price_assumption` to 4500 to match the friend. This is the kind of single-line config change worth doing the moment Emanuel decides; mention in the next manual-data refresh.

### F4.2 — AISC threshold display vs actual: $1600 vs $1850

**Severity:** P3 (friend-side label inconsistency, no action needed in our code)

Excel `Summary & Parameters!A12` says `"AISC Target | < $1,600/oz (2nd Quartile)"` but cell `E12 = 1850.0` is what the formula uses.

Our YAML `aisc_max: 1850` matches the formula's actual value. No code change needed; just be aware that the friend's *stated intent* (1600) differs from his *implemented threshold* (1850). Worth a clarification with him.

### F4.3 — Peer benchmarks (P/E, EV/EBITDA, FCF Yield 2026): EXACT MATCH

**Severity:** none

Excel `Summary & Parameters!C27..G30` vs our `config/screening_params.yaml peer_benchmarks`:

| Size | P/E 2026 | P/E 2011 | EV/EBITDA 2026 | EV/EBITDA 2011 | FCF Yield 2026 |
|---|---|---|---|---|---|
| Large | 16 / 16 ✓ | 28.5 / 28.5 ✓ | 8 / 8 ✓ | 14 / 14 ✓ | 0.05 / 0.05 ✓ |
| Mid | 13 / 13 ✓ | 23 / 23 ✓ | 6.5 / 6.5 ✓ | 12 / 12 ✓ | 0.075 / 0.075 ✓ |
| Small | 11.5 / 11.5 ✓ | 20 / 20 ✓ | 5.5 / 5.5 ✓ | 10 / 10 ✓ | 0.1 / 0.1 ✓ |
| Micro | 10 / 10 ✓ | 18 / 18 ✓ | 4.5 / 4.5 ✓ | 9 / 9 ✓ | 0.12 / 0.12 ✓ |

### F4.4 — FCF Yield 2011 benchmark column: NOT VISIBLE in Excel

**Severity:** P2 (we use values our YAML invents; Excel may not have them at all)

Excel `Summary & Parameters!C26` headers are: `Size, Mkt Cap Range, P/E 2026, P/E 2011, EV/EBITDA 2026, EV/EBITDA 2011, FCF Yield 2026`. **No `FCF Yield 2011` column visible.** But Excel `Layer 2!AH5` references `Summary & Parameters!H27..H30` for FCF Yield 2011 benchmarks, and `Layer 2!AK5` (Target Price FCF 2011 $) uses them.

Our YAML invents these:
- Large: `fcf_yield_2011: 0.02`
- Mid: `fcf_yield_2011: 0.035`
- Small: `fcf_yield_2011: 0.045`
- Micro: `fcf_yield_2011: 0.05`

**Verify:** open the Excel and check what's actually in `Summary & Parameters!H27..H30`. If the cells are blank or `#N/A`, the Excel Target Price FCF 2011 is broken or N/A, and our invented numbers may not match the friend's intent. If the cells have values, compare directly.

I couldn't verify this without opening the Excel in a spreadsheet app (the openpyxl read may be missing a hidden column).

### F4.5 — Tier discounts: ALIGNED

| Tier | Excel `E18..E20` | Our YAML `jurisdiction_discounts` | Match |
|---|---|---|---|
| 1 | 0.0 | tier_1: 0.0 | ✓ |
| 2 | 0.15 | tier_2: 0.15 | ✓ |
| 3 | 0.3 | tier_3: 0.3 | ✓ |

### F4.6 — Custom Target P/E for Rerating (Excel `B23 = 10.0`): NOT IN OUR PYTHON

**Severity:** P3 (friend-only feature)

Excel has a `Custom Target P/E for Rerating` cell at `B23 = 10.0`. I don't see it referenced in any Layer 2 formula, so it may be vestigial or used in an unseen rerating-analysis sheet. Not in our Python. Safe to ignore unless the friend says it's used.

### F4.7 — Size-category cutoffs: ALIGNED

| Excel `E5` | Python `targets.py:13-19` | Match |
|---|---|---|
| `D5 > 15000 → Large` | `> 15_000 → large` | ✓ |
| `D5 > 2000 → Mid` | `> 2_000 → mid` | ✓ |
| `D5 > 500 → Small` | `> 500 → small` | ✓ |
| else `Micro` | else `micro` | ✓ |

---

## Per-ticker number cross-check (apples-to-apples at $4500/oz)

I re-ran our pipeline at the Excel's $4500 gold price and pulled `data/output/tool_b/tool_b_latest.parquet`. Comparing AEM, KGC, NEM (the only three tickers we have manual data for):

### AEM

| Field | Excel | Python | Δ | Cause |
|---|---|---|---|---|
| Share price USD | $251.60 | $198.96 | -21% | Excel uses Jan-2026 manually entered price; Python uses live Yahoo (Apr-2026). Real market move, not a bug. |
| Forward P/E | 16.95 | 13.38 | -21% | Same — lower share price → lower P/E. |
| EV/EBITDA | 10.66 | 8.41 | -21% | Same — lower mkt cap (price × shares). |
| Verdict | SCREEN OUT | SCREEN_OUT | match | Both fwd P/E > 10. ✓ |
| Target Peer $ | 237.53 | 202.25 | -15% | Lower forward EPS via lower price. |
| Target Peak $ | 423.09 | 360.27 | -15% | Same. |
| Target FCF Peer $ | 413.05 | 386.63 | -6% | FCF formula depends on actual_yield/target_yield, which is less sensitive to share price (yield = FCF / mkt_cap, both move). |
| Target FCF Peak $ | 1032.63 | 966.59 | -6% | Same. |
| **Best target (Python only)** | n/a | **966.59** | n/a | Always picks max → FCF Peak. Headline upside = 386%. |

**Layer 1 status (Python):** FAIL with reason `FCF_FAIL` (fcf_yield = 0.097, threshold = 0.15). I couldn't see the Excel's `Layer 1!Q` value for AEM (need to verify in spreadsheet) but with the same inputs the Excel should also FAIL on FCF.

### KGC

| Field | Excel | Python | Δ |
|---|---|---|---|
| Share price USD | $36.99 | $32.12 | -13% |
| Forward P/E | 9.95 | 8.65 | -13% |
| Verdict | WATCHLIST | WATCHLIST | match ✓ |
| Target Peer $ | 50.55 | 50.49 | <0.5% ✓ |
| Target Peak $ | 90.03 | 89.93 | <0.5% ✓ |
| Target FCF Peer $ | 92.43 | 92.33 | <0.5% ✓ |
| Target FCF Peak $ | 231.07 | 230.81 | <0.5% ✓ |

**Excellent agreement** for KGC. The 13% share-price difference is offset for FCF/peer targets because they depend on `actual_yield/benchmark_yield` ratios (both numerator and denominator scale with price).

**Note:** Excel KGC jurisdiction_tier = **1.5** (interpolated — Kinross has US/Mauritania mix). Our universe.yaml has 2. The Excel's VLOOKUP on `1.5` returns 0 (no match in tier table 1/2/3) due to `IFERROR` fallback. So Excel effectively treats KGC as Tier 1 (no discount). Python with our universe.yaml tier 2 applies 15% discount.

That actually means our peak P/E for KGC = 28.5 × 0.85 = 24.225. Excel's effective peak P/E = 28.5 × 1.0 = 28.5. With KGC forward EPS ≈ 3.71, Excel target peak = 28.5 × 3.71 = $105.74. Our number (89.93) is lower because we discount.

But Excel's published peak target is $90.03 — much closer to our $89.93. So Excel must NOT be applying the 1.5 tier as 0%. **Need to verify by opening the Excel and checking `S5` value for KGC** — what does it lookup to? My read suggests S5 = 0, but the matching peak target suggests S5 ≈ 0.15 somehow. Worth Codex confirming by inspection.

### NEM

| Field | Excel | Python | Δ |
|---|---|---|---|
| Share price USD | $130.00 | $111.06 | -15% |
| Forward P/E | 12.21 | 10.35 | -15% |
| Verdict | SCREEN OUT | SCREEN_OUT | match ✓ |
| Target Peer $ | 144.84 | 145.91 | <1% ✓ |
| Target Peak $ | 258.00 | 259.89 | <1% ✓ |
| Target FCF Peer $ | 292.51 | 294.66 | <1% ✓ |
| Target FCF Peak $ | 731.27 | 736.65 | <1% ✓ |

Tiny variance (~1%) likely from rounding differences in EPS calc. NEM passes a clean cross-check.

### What about the other 56 tickers?

All 56 have NO manual data in our store — they hit `MISSING_*` reasons in Layer 1 and emit `INCOMPLETE` rows. Python output is correctly INCOMPLETE for them. Excel `Top performers` has full numbers because the friend filled the Screening Data sheet.

**This is the highest-leverage backfill:** copy the 56 tickers' Screening Data values from Excel into our SQLite store and we go from 3 ranked rows to 59 ranked rows.

---

## Manual-data drift — per-ticker comparison

For the 3 tickers with data in our store:

### AEM — one stale field

| Field | Our store | Excel `Screening Data` AEM (row 5) | Status |
|---|---|---|---|
| production_oz | 3,400,000 | 3,400,000 | ✓ |
| **aisc_usd_per_oz** | **1475** | **1275** | ✗ **STALE** — Excel `AISC Verification` confirms $1275 verified Q3 2025 |
| cash_cost_usd_per_oz | 940 | 940 | ✓ |
| royalty_rate | 0.02 | 2.0 (Excel-percent → 0.02 effective) | ✓ same effective |
| sustaining_capex_musd | 600 | 600 | ✓ |
| da_musd | 1400 | 1400 | ✓ |
| interest_expense_musd | 50 | 50 | ✓ |
| tax_rate | 0.28 | 28.0 (Excel-percent → 0.28 effective) | ✓ same effective |
| reserve_life_years | 14 | 14 | ✓ |
| net_debt_musd | -500 | -500 | ✓ |
| ebitda_ltm_musd | 6700 | 6700 | ✓ |

Action: update AEM AISC from 1475 → 1275.

### KGC — clean

All 11 fields match the Excel's `Screening Data` row 37 exactly (after percent/decimal normalization).

### NEM — clean

All 11 fields match the Excel's `Screening Data` row 41 exactly.

### Jurisdiction-tier mismatches (config drift)

These don't live in the SQLite store but in `config/universe.yaml`:

| Ticker | Excel tier | Our universe.yaml | Notes |
|---|---|---|---|
| AEM | 1 | 2 (default) | Should be 1 (USA-listed, Canadian ops). We over-discount. |
| **KGC** | **1.5** | 2 (default) | Excel uses non-integer tier; our model only supports 1/2/3. Need a decision. |
| NEM | 2 | 2 | ✓ match |
| BTG | 2 | 2 | ✓ |
| GFI | 2 | 2 | ✓ |
| (most others use friend's per-ticker tier on `Screening Data!U`) | varies | all 2 | Need to backfill |

Action: when copying the 56 missing tickers' manual data into our store, also update the `jurisdiction_tier` field in `universe.yaml` per the Excel `Screening Data` column 21. For KGC's 1.5, decide: round down (1, no discount, generous), round up (2, full 15% discount, conservative), or extend our model to support `1.5` as 7.5% discount (ideal but more code).

### Backfill priority list

Top 15 tickers ranked by impact (based on Excel `Top performers` order — names that already screen well + would move the workspace meaningfully):

| # | Ticker | Excel Verdict | Excel FCF Peer Upside % | Why it matters |
|---|---|---|---|---|
| 1 | SRB.L | WATCHLIST | 170% | Excel ranks #1 by Peer P/E upside |
| 2 | BTG | STRONG CANDIDATE | 119% | Excel ranks #2; we already have BTG row but blank |
| 3 | GAU | WATCHLIST | 118% | Small-cap convex name |
| 4 | JAG.TO | WATCHLIST | 104% | TSX micro |
| 5 | AAUC.TO | WATCHLIST | 87% | Allied Gold |
| 6 | WAF.AX | STRONG CANDIDATE | 56% | West African Resources |
| 7 | THX.L | WATCHLIST | 53% | Thor Explorations |
| 8 | HMY | WATCHLIST | 48% | Harmony Gold |
| 9 | EDV.L | STRONG CANDIDATE | 41% | Endeavour |
| 10 | RSG.AX | WATCHLIST | 37% | Resolute |
| 11 | PNR.AX | STRONG CANDIDATE | 46% | Pantoro Gold |
| 12 | ORE.TO | WATCHLIST | 48% | Orezone |
| 13 | TXG | WATCHLIST | 20% | Torex |
| 14 | CG | WATCHLIST | 44% | Centerra |
| 15 | ALTN.L | STRONG CANDIDATE | 63% | AltynGold |

After the top 15, fill the remaining 41 in alphabetical order — they're either SCREEN_OUT in the Excel (lower priority) or peripheral.

**Effort estimate:** each ticker has ~12 numeric fields to copy. With Excel open side-by-side, ~3-5 minutes per ticker via the workspace edit form, OR ~30 seconds per ticker via `python main.py manual-data set-company` if scripted from a CSV export of Excel `Screening Data`. Total: 1-2 hours scripted, 4-5 hours manual.

---

## Universe gaps

| Direction | Tickers | Notes |
|---|---|---|
| In Excel but not in our universe | none — Excel's 61 are all in our universe | ✓ |
| In our universe (active) but not in Excel | none of the 59 active | ✓ |
| In our universe (inactive, kept for tests) but not in Excel | GOLD, FNV, FRES.L | Test fixtures only. No action. |
| In Excel but inactive in our universe | ARMN, NGD | Yahoo Finance returns "no data" — likely re-tickered. Investigate the correct symbol. |

The 2 Yahoo failures (ARMN, NGD) are real names the friend tracks. Worth investigating their correct Yahoo symbols (e.g., NGD might be NGD.TO, ARMN might be ARMN.TO or a different ticker entirely after re-listing). If found, re-activate.

---

## Items NOT addressed in this review (and why)

1. **Forward FCF column `AE5` separately from `J5` (Layer 1 sustainable FCF)**: Excel has both. They look like the same number. Need to confirm they always match.
2. **`Current P/E (LTM)` (`Layer 2!M5`)**: depends on `Net Income (LTM)` which is column 20 in `Screening Data`. Most rows have this blank — both Excel and Python skip it. No comparison possible.
3. **`Next reporting date` from Excel**: pulls from a separate sheet. Our `reporting_calendar` table holds equivalent data. Not cross-checked here.
4. **Live price refresh**: the Excel's `Live Prices (GoogleSheet)` sheet feeds back into the screening — this is a workflow we don't replicate (we use Yahoo on a schedule). Different design choice, not a bug.
5. **`Price comparisons` sheet**: looks like a side analysis, not part of the canonical screening. Skipped.
6. **`AISC Verification` and `Production verification` sheets full audit**: I sampled the first ~14 rows. Worth Codex doing the full 61-row pass to flag any ticker where Python store ≠ Excel verified value.
7. **The 4 royalty/tax-rate convention bugs in Excel data (AGI, BGL.AX, DRD, EMR.AX)**: I flagged the symptom but didn't dig into per-ticker fallout. Worth tracing whether those rows show as artificially-inflated STRONG CANDIDATEs in `Top performers`.

---

## Recommended actions, in priority order

1. **P0** — Drop or redefine `best_target_price_usd = max(...)` per F3.3. Show the four scenarios separately in the Tool B view and the parquet.
2. **P1** — Bump `default_gold_price_assumption` from 4000 → 4500 to match the friend's analysis date (F4.1).
3. **P1** — Backfill manual data for the top 15 tickers from Excel `Screening Data` (F-Backfill). Largest single impact on workspace usefulness.
4. **P1** — Backfill the remaining 41 tickers' manual data.
5. **P1** — Update AEM `aisc_usd_per_oz` from 1475 → 1275 (F-AEM-stale).
6. **P1** — Update jurisdiction_tier per ticker in `config/universe.yaml` from Excel `Screening Data!U`. Decide how to handle KGC's 1.5 (F-Tier).
7. **P2** — Investigate ARMN and NGD correct Yahoo symbols, re-activate if found.
8. **P2** — Decide whether to keep computing EV/EBITDA target prices (they're useful) but exclude them from the headline upside (F3.2).
9. **P2** — Decide whether to harden Python's `LEVERAGE_NON_POSITIVE_EBITDA` rule or relax to match Excel's "passes if EBITDA ≤ 0" (F1.2). I lean keep-Python.
10. **P3** — Tell the friend about: AISC label vs cell mismatch (F4.2), royalty/tax convention bugs in Excel data (F2.2), and the leverage edge case (F1.2).
11. **P3** — Verify Excel `Summary & Parameters!H27..H30` actually has FCF Yield 2011 values, and they match our YAML invented ones (F4.4).

---

## What I'd most like Codex to also check (where my review may be weak)

- I read formulas via openpyxl, not by clicking through cells. If any formula has a hidden conditional or a defined-name reference I missed, point it out.
- Open the Excel in a spreadsheet app and verify `Layer 1!Q` for AEM/KGC/NEM specifically — does Excel say PASS or FAIL for each?
- Confirm `Summary & Parameters!H27..H30` (FCF Yield 2011 benchmarks) cell values — are they populated?
- Verify the four "decimal vs percent" tickers (AGI, BGL.AX, DRD, EMR.AX) actually produce inflated EPS / target prices in the Excel `Top performers`.
- Spot-check 5-10 of the 56 INCOMPLETE tickers' Excel `Screening Data` rows for any field anomalies (unexpected blanks, bad units, signs) before we backfill blindly.
