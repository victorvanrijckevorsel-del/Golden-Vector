# Codex Review: Tool B vs Friend's Excel — Logic + Numbers Cross-check

Date: 2026-04-24  
Reviewer: Codex

## Summary verdict

- Logic alignment: **DRIFTED**
- Number alignment: **DRIFTED**
- Manual-data backfill needed: **56 active Tool B tickers are blank in SQLite, plus 1 stale verified input (`AEM` AISC).** Rough effort is medium if done by bulk import from the current workbook, high if done one row at a time in the workspace.

The important nuance is this:

- the **core Layer 1 / Layer 2 / target-price / verdict formulas mostly match the friend's Excel**
- the biggest drift is **not** arithmetic
- the biggest drift is:
  - different **default gold price** (`4000` vs Excel `4500`)
  - different **jurisdiction tiers** for many tickers
  - a Python-only **best target / score / rank** layer that the Excel does not expose
  - a severely incomplete / partly stale **manual SQLite store**

I ran:

- `python -m pytest -q` → `235 passed`
- `python main.py status`
- `python main.py tool-b --gold-price 4500`
- `python main.py tool-b --gold-price 4000`

I also cross-checked the current workbook formulas with `openpyxl` using `data_only=False`, and compared cached workbook values with the live Python Tool B outputs.

## Layer 1 — Logic findings

### F1.1 — Default gold-price assumption drift changes day-to-day verdicts

- **Severity:** P1
- **Where (Python):** [config/screening_params.yaml](C:/Users/Emanuel/code/Golden-Vector/config/screening_params.yaml:2) sets `default_gold_price_assumption: 4000`
- **Where (Excel):** `Summary & Parameters!B5` = `4500`
- **What differs:** The canonical workbook now defaults to `$4,500/oz`, while Python defaults to `$4,000/oz`. That is enough to move names across the verdict boundary. The clearest example is `KGC`: at `$4,000` our Python output is `SCREEN_OUT`; at `$4,500` it becomes `WATCHLIST`, which matches the workbook.
- **Which is correct (and why):** If the friend's workbook is the canonical Tool B, then **`4500` is the current canonical default**. Keeping `4000` is acceptable only if we treat it as an intentional product deviation and say so explicitly everywhere.
- **Proposed fix shape:** Pick one canonical default and centralize it. If parity with the friend matters more than scenario flexibility, move the YAML default to `4500` and reflect that in docs / workspace status. If we keep `4000`, the workspace should label it as a deliberate house default, not “the” Tool B default.

### F1.2 — Core Layer 1 / Layer 2 / target formulas are mostly aligned, but jurisdiction-tier inputs are not

- **Severity:** P1
- **Where (Python):**
  - [golden_vector/screening/layer1.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/layer1.py:61) to [golden_vector/screening/layer1.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/layer1.py:80)
  - [golden_vector/screening/layer2.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/layer2.py:67) to [golden_vector/screening/layer2.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/layer2.py:89)
  - [golden_vector/screening/targets.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/targets.py:31) to [golden_vector/screening/targets.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/targets.py:78)
  - [config/universe.yaml](C:/Users/Emanuel/code/Golden-Vector/config/universe.yaml:22), [config/universe.yaml](C:/Users/Emanuel/code/Golden-Vector/config/universe.yaml:97), [config/universe.yaml](C:/Users/Emanuel/code/Golden-Vector/config/universe.yaml:281), [config/universe.yaml](C:/Users/Emanuel/code/Golden-Vector/config/universe.yaml:321)
- **Where (Excel):**
  - `Layer 1 - Robust Screen!F4:Q64`
  - `Layer 2 - Earnings Model!H4:AQ64`
  - `Screening Data!U3:U63`
  - `Layer 2 - Earnings Model!C4` = `=ROUNDUP(VLOOKUP(A4,'Screening Data'!$A:$U,21,FALSE()),0)`
- **What differs:** The formulas mostly match. The drift is the **jurisdiction tier values** feeding the tier discount. The workbook stores fractional tiers in `Screening Data!U:U` and rounds them up in Layer 2. Python uses integer `jurisdiction_tier` values hard-coded in `universe.yaml`. I found **33 mismatches** between active Tool B tickers and the rounded workbook tier. Examples:
  - `AEM`: workbook `Screening Data!U5 = 1.0`, Python `universe.yaml` = `2`
  - `BTG`: workbook `Screening Data!U14 = 2.5` → Layer 2 uses `3`, Python = `2`
  - `AAUC.TO`: workbook `U3 = 3.0`, Python = `2`
- **Which is correct (and why):** For Tool B parity, the **workbook is correct**, because the workbook itself is applying those rounded values into peer P/E and EV/EBITDA target discounts. Python is flattening that nuance away.
- **Proposed fix shape:** Stop treating `universe.yaml` as the sole Tool B jurisdiction source. Either:
  - update `universe.yaml` to match the workbook's rounded values exactly, or
  - make Tool B read its jurisdiction discount input from a Tool B-specific store/config that can carry the workbook's `1.0 / 1.5 / 2.5 / 3.0` style inputs and round them the same way as Excel.
  - add regression tests for at least `AEM`, `BTG`, `KGC`, `NEM`, and `AAUC.TO`.

### F1.3 — Python's `best target`, score, and ranking are not present in the workbook

- **Severity:** P1
- **Where (Python):**
  - [golden_vector/screening/targets.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/targets.py:80) to [golden_vector/screening/targets.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/targets.py:102)
  - [golden_vector/screening/verdicts.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/verdicts.py:26) to [golden_vector/screening/verdicts.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/verdicts.py:40)
  - [golden_vector/screening/ranking.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/ranking.py:8) to [golden_vector/screening/ranking.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/ranking.py:30)
- **Where (Excel):**
  - `Layer 2 - Earnings Model!AA:AP` publishes **individual** target-price families only
  - I found **no `MAX(...)` formula** and no exposed “best target” field in `Layer 2 - Earnings Model`, `Top performers`, or `Price comparisons`
  - `Top performers` also does **not** expose an auditable score formula; the sheet is saved as values, not formula-backed ranking logic
- **What differs:** Python adds:
  - `best_target_price_usd = max(peer PE, 2011 PE, peer FCF, 2011 FCF, peer EV/EBITDA, 2011 EV/EBITDA)`
  - `best_upside_pct`
  - `tool_b_score`
  - `tool_b_rank`

  The workbook exposes the target families individually, but the current workbook does **not** expose the same “best-of-six” aggregation or our score/rank layer.
- **Which is correct (and why):** For parity with the friend's workbook, **the workbook is the canonical model**. Python's “best target” and score/rank are extra product logic. They may be useful, but they are not Excel parity.
- **Proposed fix shape:** Treat the current Python score/rank as an explicit product overlay, not canonical Tool B. Either:
  - remove it from parity-sensitive views, or
  - ask the friend to define an explicit “best target” and ranking rule in the workbook, then mirror that exactly.

### F1.4 — The AISC threshold is numerically aligned, but the workbook label is stale and misleading

- **Severity:** P2
- **Where (Python):** [config/screening_params.yaml](C:/Users/Emanuel/code/Golden-Vector/config/screening_params.yaml:9) to [config/screening_params.yaml](C:/Users/Emanuel/code/Golden-Vector/config/screening_params.yaml:14) sets `aisc_max: 1850`
- **Where (Excel):**
  - `Summary & Parameters!A12` label: `AISC Target`
  - `Summary & Parameters!B12` text: `< $1,600/oz (2nd Quartile)`
  - `Summary & Parameters!E12` numeric threshold used in formulas: `1850`
- **What differs:** The workbook text says `$1,600`, but the actual numeric cell used by the formulas is `1850`, which matches Python.
- **Which is correct (and why):** The **numeric cell is correct for parity** because both Excel and Python actually use `1850` in the logic. The text label in the workbook is stale.
- **Proposed fix shape:** Do **not** change Python to `1600` just because the label says so. Fix the workbook label / operating notes so the human text matches the actual model.

### F1.5 — Verdict logic is aligned; the “huge upside but SCREEN_OUT” behavior is mostly intended

- **Severity:** P2
- **Where (Python):** [golden_vector/screening/verdicts.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/verdicts.py:17) to [golden_vector/screening/verdicts.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/verdicts.py:23)
- **Where (Excel):** `Layer 2 - Earnings Model!Y21`, `Y33`, `Y40` use:

  `=IF(AND(L<8,L>0, PASS_ALL="✓ PASS"), "★ STRONG CANDIDATE", IF(AND(L<10,L>0), "◆ WATCHLIST", "○ SCREEN OUT"))`

- **What differs:** Almost nothing. The workbook **does allow** a stock to be `WATCHLIST` even when Layer 1 fails, as long as forward P/E is `<10`. It also allows a name with very high theoretical upside to remain `SCREEN OUT` if forward P/E is too high or Layer 1 fails.
- **Which is correct (and why):** This is **workbook-intended behavior**, not a Python bug. The friend’s workbook does the same thing.
- **Proposed fix shape:** No formula change needed. The product needs clearer explanation text around:
  - “verdict is driven by Layer 1 pass/fail and forward P/E”
  - “target price families are upside scenarios, not verdict overrides”

## Layer 2 — Number findings

### F2.AEM — AEM drifts because Python is using stale AISC and the wrong jurisdiction tier

- **Severity:** P1
- **Python value(s):**
  - `aisc_usd_per_oz` in SQLite = `1475`
  - `forward_revenue_musd` = `15300.0`
  - `forward_ebitda_musd` = `11798.0`
  - `forward_pe` = `13.3784`
  - `target_price_peer_pe` = `202.2550`
  - `best_target_price_usd` = `966.5872`
  - `screening_verdict` = `SCREEN_OUT`
- **Excel value(s):**
  - `AISC Verification!D5 = 1275`
  - `Layer 2 - Earnings Model!H40 = 15300`
  - `I40 = 11798`
  - `L40 = 16.9480`
  - `AA40 = 237.5268`
  - `AK40 = 1032.6260`
  - `Y40 = ○ SCREEN OUT`
- **Likely cause:** Two different drifts stack here:
  1. **stale store input** — our SQLite store still carries the old workbook’s `1475` AISC for `AEM`; the current workbook has `1275`
  2. **tier drift** — workbook uses `Tier 1` for `AEM` (`Screening Data!U5 = 1.0`), while Python uses `jurisdiction_tier: 2`

  The revenue / EBITDA / net income formulas still align, which is why those core values match exactly. The target-price drift comes from the stale manual input and discount input, not from broken arithmetic.
- **Proposed fix shape:** Update the store’s `AEM` AISC to `1275`, align `AEM` jurisdiction tier to the workbook, rerun Tool B at `4500`, then lock a regression test on the Excel row.

### F2.KGC — The current “SCREEN_OUT with huge upside” behavior is caused by the `4000` default, not by broken math

- **Severity:** P1
- **Python value(s):**
  - At the current product default `$4000` (run `20260424T110527Z-tool-b-24d96d66`):
    - `forward_pe = 10.3661`
    - `best_target_price_usd = 188.1845`
    - `screening_verdict = SCREEN_OUT`
  - At `$4500`:
    - `forward_pe = 8.6521`
    - `best_target_price_usd = 230.8128`
    - `screening_verdict = WATCHLIST`
- **Excel value(s):**
  - `Layer 1 - Robust Screen!Q47 = ✗ FAIL`
  - `Layer 2 - Earnings Model!L21 = 9.9527`
  - `Y21 = ◆ WATCHLIST`
  - `AK21 = 231.0721`
- **Likely cause:** The workbook default is `4500`, not `4000`. At `4500`, Python and Excel line up closely on `KGC`. At `4000`, the lower gold-price assumption pushes `KGC` above the `P/E < 10` watchlist line, so the verdict flips to `SCREEN_OUT`.
- **Proposed fix shape:** Decide whether parity or house-view matters more. If parity matters, move the default to `4500`. If house-view matters, keep `4000` but make the workspace explicitly show that the friend’s workbook is being compared at a different scenario.

### F2.NEM — NEM’s huge target price is canonical to the workbook, not a Python overshoot

- **Severity:** P3
- **Python value(s):**
  - At `$4500`: `best_target_price_usd = 736.6475`, `screening_verdict = SCREEN_OUT`, `forward_pe = 10.3520`
- **Excel value(s):**
  - `Layer 1 - Robust Screen!Q51 = ✗ FAIL`
  - `Layer 2 - Earnings Model!L33 = 12.2065`
  - `Y33 = ○ SCREEN OUT`
  - `AK33 = 731.2703`
- **Likely cause:** No formula bug. Both tools are taking the very bullish **2011 FCF yield** target as the highest scenario, while the verdict is still being driven by:
  - Layer 1 `FCF_FAIL`
  - forward P/E above the watchlist cut-off
- **Proposed fix shape:** No arithmetic fix. Add product explanation so users can see which target family is driving the “best target” and why verdict does not follow the highest upside column.

## Layer 3 — Manual-data drift (per-ticker punch list)

Compared all **59 active Tool B tickers** against the current workbook. Action is needed on **57**:

- **56** active Tool B tickers are blank in the SQLite store
- **1** populated ticker (`AEM`) has a stale verified AISC
- `KGC` and `NEM` are materially aligned with the current workbook

| Ticker | Field | Python store value | Excel verified value | Status (verified/estimated) | Action |
|---|---|---:|---:|---|---|
| AAUC.TO | ALL_CORE_FIELDS | blank | AISC=1790.0; Prod=575000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| AAZ.L | ALL_CORE_FIELDS | blank | AISC=1500.0; Prod=30000.0 | AISC estimated / Prod ESTIMATED | Import full current Excel row into SQLite store |
| AEM | aisc_usd_per_oz | 1475.0 | 1275.0 | verified | Update stale verified AISC from current workbook |
| AGI | ALL_CORE_FIELDS | blank | AISC=1375.0; Prod=655000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| ALK.AX | ALL_CORE_FIELDS | blank | AISC=1885.0; Prod=167500.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| ALTN.L | ALL_CORE_FIELDS | blank | AISC=1357.0; Prod=53500.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| ASE.V | ALL_CORE_FIELDS | blank | AISC=4574.0; Prod=455000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| AU | ALL_CORE_FIELDS | blank | AISC=1766.0; Prod=3060000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| B | ALL_CORE_FIELDS | blank | AISC=1538.0; Prod=3300000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| BGL.AX | ALL_CORE_FIELDS | blank | AISC=1943.0; Prod=140000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| BTG | ALL_CORE_FIELDS | blank | AISC=1479.0; Prod=992500.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| CDE | ALL_CORE_FIELDS | blank | AISC=1215.0; Prod=415250.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| CG | ALL_CORE_FIELDS | blank | AISC=1750.0; Prod=290000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| CMCL | ALL_CORE_FIELDS | blank | AISC=1937.0; Prod=74250.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| CMM.AX | ALL_CORE_FIELDS | blank | AISC=1060.0; Prod=120000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| CYL.AX | ALL_CORE_FIELDS | blank | AISC=1723.0; Prod=105000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| DPM.TO | ALL_CORE_FIELDS | blank | AISC=1168.0; Prod=180000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| DRD | ALL_CORE_FIELDS | blank | AISC=1881.0; Prod=145000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| EDV.L | ALL_CORE_FIELDS | blank | AISC=1569.0; Prod=1185000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| ELD.TO | ALL_CORE_FIELDS | blank | AISC=1679.0; Prod=500000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| EMR.AX | ALL_CORE_FIELDS | blank | AISC=1186.0; Prod=112500.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| EQX | ALL_CORE_FIELDS | blank | AISC=1833.0; Prod=750000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| EVN.AX | ALL_CORE_FIELDS | blank | AISC=1121.0; Prod=745000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| FSM | ALL_CORE_FIELDS | blank | AISC=1987.0; Prod=293000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| GAU | ALL_CORE_FIELDS | blank | AISC=2300.0; Prod=200000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| GFI | ALL_CORE_FIELDS | blank | AISC=1557.0; Prod=2350000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| GGP.L | ALL_CORE_FIELDS | blank | AISC=1401.0; Prod=285000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| GMIN.TO | ALL_CORE_FIELDS | blank | AISC=1046.0; Prod=175000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| HMY | ALL_CORE_FIELDS | blank | AISC=1806.0; Prod=1450000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| HOC.L | ALL_CORE_FIELDS | blank | AISC=2080.0; Prod=314000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| IAG | ALL_CORE_FIELDS | blank | AISC=1956.0; Prod=770000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| JAG.TO | ALL_CORE_FIELDS | blank | AISC=1844.0; Prod=80000.0 | AISC verified / Prod ESTIMATED | Import full current Excel row into SQLite store |
| KCN.AX | ALL_CORE_FIELDS | blank | AISC=2024.0; Prod=90000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| KNT.TO | ALL_CORE_FIELDS | blank | AISC=1254.0; Prod=175000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| LUG.TO | ALL_CORE_FIELDS | blank | AISC=1036.0; Prod=500000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| MTL.L | ALL_CORE_FIELDS | blank | AISC=1923.0; Prod=80000.0 | AISC verified / Prod ESTIMATED | Import full current Excel row into SQLite store |
| MUX | ALL_CORE_FIELDS | blank | See current Screening Data row | Screening Data only | Import full current Excel row into SQLite store |
| NST.AX | ALL_CORE_FIELDS | blank | AISC=1909.0; Prod=1650000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| OBM.AX | ALL_CORE_FIELDS | blank | AISC=1885.0; Prod=147500.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| OGC.TO | ALL_CORE_FIELDS | blank | AISC=2052.0; Prod=585000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| ORE.TO | ALL_CORE_FIELDS | blank | AISC=1958.0; Prod=177500.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| ORLA | ALL_CORE_FIELDS | blank | AISC=1550.0; Prod=350000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| PAF.L | ALL_CORE_FIELDS | blank | AISC=1575.0; Prod=283500.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| PNR.AX | ALL_CORE_FIELDS | blank | AISC=1463.0; Prod=105000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| PRU | ALL_CORE_FIELDS | blank | AISC=1463.0; Prod=420000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| RMS.AX | ALL_CORE_FIELDS | blank | See current Screening Data row | Screening Data only | Import full current Excel row into SQLite store |
| RRL.AX | ALL_CORE_FIELDS | blank | AISC=1944.0; Prod=365000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| RSG.AX | ALL_CORE_FIELDS | blank | AISC=2200.0; Prod=262500.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| SBM.AX | ALL_CORE_FIELDS | blank | AISC=2860.0; Prod=62000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| SRB.L | ALL_CORE_FIELDS | blank | AISC=1816.0; Prod=55000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| SSRM | ALL_CORE_FIELDS | blank | AISC=2359.0; Prod=550000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| THX.L | ALL_CORE_FIELDS | blank | AISC=1129.0; Prod=80000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| TXG | ALL_CORE_FIELDS | blank | AISC=1600.0; Prod=320000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| VAU.AX | ALL_CORE_FIELDS | blank | AISC=1853.0; Prod=346000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| WAF.AX | ALL_CORE_FIELDS | blank | AISC=1532.0; Prod=325000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| WDO.TO | ALL_CORE_FIELDS | blank | AISC=1419.0; Prod=192500.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |
| WGX.AX | ALL_CORE_FIELDS | blank | AISC=2275.0; Prod=365000.0 | AISC verified / Prod VERIFIED | Import full current Excel row into SQLite store |

## Backfill priority list

Top 10-15 tickers by likely impact, using the friend’s `Top performers` ordering plus verification quality:

1. `SRB.L` — top-ranked in the workbook, store blank, both AISC and production already verified.
2. `BTG` — top-ranked in the workbook, store blank, both AISC and production verified.
3. `GAU` — top-ranked in the workbook, store blank, both AISC and production verified.
4. `AAUC.TO` — high-ranked in the workbook, store blank, both AISC and production verified.
5. `WAF.AX` — high-ranked in the workbook, store blank, both AISC and production verified.
6. `THX.L` — high-ranked in the workbook, store blank, both AISC and production verified.
7. `HMY` — high-ranked in the workbook, store blank, both AISC and production verified.
8. `EDV.L` — high-ranked in the workbook, store blank, both AISC and production verified.
9. `PNR.AX` — high-ranked in the workbook, store blank, both AISC and production verified.
10. `TXG` — high-ranked in the workbook, store blank, both AISC and production verified.
11. `AU` — high-ranked in the workbook, store blank, both AISC and production verified.
12. `NST.AX` — high-ranked in the workbook, store blank, both AISC and production verified.
13. `ALTN.L` — high-ranked in the workbook, store blank, both AISC and production verified.
14. `GFI` — high-ranked in the workbook, store blank, both AISC and production verified.
15. `CG` — high-ranked in the workbook, store blank, both AISC and production verified.

Second wave:

- `JAG.TO` and `MTL.L` rank well, but production is still `ESTIMATED`
- `MUX` and `RMS.AX` are missing dedicated verification rows, so they need more interpretation before import

## Universe gaps

- In Excel but not in our universe:
  - `ARMN`
  - `NGD`
  - `RMS`

- In our universe but not in Excel:
  - `RMS.AX`

- Orphan rows currently sitting in the SQLite store but not in the active Tool B universe:
  - `FNV`
  - `FRES.L`
  - `GOLD`

## Items not addressed in this review (and why)

- I did **not** reverse-engineer a canonical ranking formula from `Top performers`, because the current workbook sheet is saved as values, not formula-backed ranking logic. I could confirm that it does **not** mirror Python’s `tool_b_score`, but I could not prove a single explicit Excel score formula because one is not exposed.
- I focused the numeric cross-check on `AEM`, `KGC`, and `NEM` as requested. For the other 56 blank-store tickers, full number parity is blocked by missing SQLite inputs rather than by hidden math drift.
- I did not mark every single non-critical market-price difference as a finding, because the workbook is using older cached live prices / market caps than the current Python snapshot. Those are source-date differences, not necessarily logic bugs.
