# Compute-only rebuild — before/after diff (2026-08-11 overnight run)

Rebuilt from persisted raw data at the Gate A+B+C code pins (no live fetch).
Before = artifacts as of `226670e` era; After = tonight's rebuild.

## Tool A (C3 as_of_date max-not-min)

- rows before/after: 61 / 61
- tickers whose latest as_of_date changed: 0 of 61

## Tool B (C1 AISC margin/yield, sustaining capex charged once)

- tickers with a changed margin yield: 60 of 60

| Ticker | old 'FCF yield' | new AISC margin yield | delta |
|---|---:|---:|---:|
| AAR.AX | 115.70% | 144.08% | +28.39% |
| ASE.V | -23.51% | -8.39% | +15.12% |
| CMCL | 38.17% | 42.75% | +4.58% |
| GAU | 76.30% | 80.02% | +3.72% |
| BGL.AX | 17.84% | 21.51% | +3.67% |
| IAG | 14.65% | 18.26% | +3.61% |
| AAUC.TO | 50.22% | 53.73% | +3.51% |
| JAG.TO | 45.02% | 48.51% | +3.49% |
| HMY | 27.84% | 31.08% | +3.24% |
| OBM.AX | 17.20% | 20.44% | +3.24% |
| ALK.AX | 24.60% | 27.84% | +3.24% |
| AAZ.L | 10.72% | 13.85% | +3.13% |

- 15% yield screen flips: 3 — IAG (14.6%->18.3%), WDO.TO (13.1%->16.1%), AU (14.7%->16.6%)

## Tool C (C2 exact ordinary-return thresholds)

- tickers with changed downside hit rate: 57 of 61

| Ticker | old rate | new rate | new hits/n |
|---|---:|---:|---:|
| THX.L | 12.28% | 5.26% | 3/57 |
| TXG | 23.75% | 18.75% | 15/80 |
| CDE | 28.57% | 24.71% | 64/259 |
| SBM.AX | 33.49% | 29.72% | 63/212 |
| ORE.TO | 28.24% | 24.71% | 21/85 |
| FSM | 27.00% | 23.50% | 47/200 |
| RMS.AX | 26.89% | 23.58% | 50/212 |
| CMM.AX | 25.14% | 21.86% | 40/183 |
| AU | 19.69% | 16.60% | 43/259 |
| WGX.AX | 21.43% | 18.37% | 18/98 |
| IAG | 29.17% | 26.25% | 63/240 |
| EMR.AX | 17.92% | 15.09% | 32/212 |

## Tool D at spot (C5 eligible-only pools + C1 breakeven=AISC)

- tickers with changed resilience rank: 25 of 61

| Ticker | old rank | new rank |
|---|---:|---:|
| ALTN.L | 86.7 | 80.0 |
| BTG | 84.4 | 91.1 |
| RRL.AX | 44.4 | 50.0 |
| ELD.TO | 51.1 | 45.6 |
| AAZ.L | 57.8 | 62.2 |
| ALK.AX | 33.3 | 37.8 |
| PAF.L | 37.8 | 33.3 |
| ASE.V | 35.6 | 31.1 |
| NST.AX | 31.1 | 35.6 |
| OBM.AX | 15.6 | 20.0 |
| SBM.AX | 20.0 | 15.6 |
| AGI | 91.1 | 87.8 |

- fcf_breakeven_gold_usd column present before: True; after: False (C1 removed the double-counted concept)

## Ticker percentiles (C6 Yahoo isolation + eligibility, v2 evidence)

- Yahoo Tool D rows available before: 90; after: 0 (plan: 0 after)
- Yahoo ineligible rows after (all with reasons + null percentiles): 288
- downside_hit_rate rows carrying exact hit_count/n evidence: 61 of 61

## FX attribution (new artifact)

- rows: 183; tickers: 61; horizons: ['1Y', '3Y', '5Y']
- status counts: {'OK': 120, 'NOT_APPLICABLE_USD': 63}
- relationship counts: {'OFFSET': 63, 'NOT_APPLICABLE_USD': 63, 'SAME_DIRECTION': 56, 'REVERSAL': 1}

| Ticker | Horizon | ccy | local ret | FX ret | USD ret | FX contrib (pp) | relationship |
|---|---|---|---:|---:|---:|---:|---|
| GMIN.TO | 5Y | CAD | 1222.89% | -10.10% | 1089.25% | -133.65 | OFFSET |
| OBM.AX | 3Y | AUD | 1378.26% | 8.51% | 1504.04% | +125.78 | SAME_DIRECTION |
| LUG.TO | 5Y | CAD | 919.45% | -10.10% | 816.46% | -102.99 | OFFSET |
| DPM.TO | 5Y | CAD | 788.40% | -10.10% | 698.64% | -89.75 | OFFSET |
| CYL.AX | 3Y | AUD | 950.00% | 8.51% | 1039.34% | +89.34 | SAME_DIRECTION |
| SRB.L | 3Y | GBP | 1230.67% | 6.63% | 1318.85% | +88.18 | SAME_DIRECTION |
| ALTN.L | 3Y | GBP | 885.44% | 6.63% | 950.74% | +65.30 | SAME_DIRECTION |
| OGC.TO | 5Y | CAD | 501.75% | -10.10% | 440.96% | -60.79 | OFFSET |
