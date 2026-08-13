# Manual mining inputs for the five new miners — ABANDONED 2026-08-13

Victor's decision: **"Abandon any names that requires to make something
complicated."** Applied to all five names below. None of them get manual Tool B/D
inputs. They stay **gold-behaviour-only**: Tool A ranks them on price behaviour
(which already works), and Tool B / Tool D / the corporate-finance sections
report them as `INCOMPLETE`, which is the designed degradation, not a bug.

**Do not revisit these without Victor asking.** Do not enter partial figures.
Do not raise the INCOMPLETE state as a review finding.

## Verified behaviour (2026-08-13, against the 14:01 build)

Both tools degrade these five correctly — no crash, no silent wrong number:

- `tool_b`: all five `confidence = INCOMPLETE` (and `confidence_official` too),
  each with explicit `layer2_incomplete_reasons`.
- `tool_d`: all five `confidence = INCOMPLETE`.

Note what the reasons show: GMD.AX, ARTG.V and BC8.AX are missing only **five**
fields — `aisc_margin_est_musd; cash_cost_or_aisc; production_oz; royalty_rate;
tax_rate` — while DSV.TO and AMRQ.L are missing eight, additionally `da_musd`,
`interest_expense_musd` and `net_debt_musd`. So the `FINANCIAL_DUAL_SOURCE_FIELDS`
are being auto-sourced from Yahoo where it carries them, and the manual store is
only strictly needed for the operational ones.

**This narrows the currency blocker below**: of the five operational gaps, only
`cash_cost_or_aisc` / `aisc_margin_est_musd` are currency-bearing. `production_oz`
is a physical quantity and `royalty_rate` / `tax_rate` are percentages — none of
those three need FX. The decision is unchanged (AISC is required, so the ticker
stays INCOMPLETE without it, and AISC is exactly the field FX blocks), but the
blocker is "AISC and cash cost are in the wrong currency", not "everything is".

## What the store requires

`REQUIRED_MANUAL_FIELDS` is the union of `OPERATIONAL_SINGLE_SOURCE_FIELDS` and
`FINANCIAL_DUAL_SOURCE_FIELDS` — i.e. **all eleven** numeric fields. Any single
blank leaves the ticker `INCOMPLETE`. There is no partial-credit state, so
"enter what we can find" buys nothing.

## The blocker that killed four of the five: currency

`company_inputs` has **no currency column**. Every field is named `*_usd_*`
(`aisc_usd_per_oz`, `net_debt_musd`, `ebitda_ltm_musd`, …), so the schema
*assumes* USD without recording or enforcing it. That assumption has never been
tested, because all eight companies currently in the store — NEM, GOLD, AEM,
KGC, BTG, FNV, DPM.TO, FRES.L — report in USD.

Four of the five new names do not:

| Ticker | Company | Reports in |
| --- | --- | --- |
| GMD.AX | Genesis Minerals | AUD (FY26 AISC A$2,670/oz) |
| BC8.AX | Black Cat Syndicate | AUD |
| ARTG.V | Artemis Gold | **CAD financials, USD per-oz costs** |
| AMRQ.L | Amaroq | **CAD financials, USD AISC guidance** |

Hand-converting these into the USD fields would be an ad-hoc conversion at the
call site — banned by the senior-engineer rules ("one normalize boundary") and by
Golden Vector hard rule #1 (no analytics on mixed currencies without explicit
normalization). Worse, it degrades **silently**: the company reports nothing new,
FX moves, and the stored "USD AISC" quietly becomes wrong with nothing to flag
it. That is the same silent-staleness failure mode already recorded for corporate
actions.

The correct fix, **if this is ever wanted**, is a `reporting_currency` column plus
a dated FX rate carried as provenance, converted in one place. That is a schema
change plus a test sweep — explicitly out of scope by Victor's decision.

## Per-name detail

### GMD.AX — Genesis Minerals
AUD reporter. Data is otherwise good: FY26 production 285,402 oz (guidance
260–290koz), AISC A$2,670/oz (guidance A$2,500–2,700). **Also merging with Vault**,
targeted November 2026 — anything entered has a ~3-month expiry and the repo has
no M&A detection.

### BC8.AX — Black Cat Syndicate
AUD reporter **and has never disclosed AISC**. Only reached a ~100kozpa run rate
in July 2026; the company has said AISC and production guidance arrive with FY26
annual results. There is no figure to source at any level of effort.

### ARTG.V — Artemis Gold
Mixed reporter: per-ounce costs in USD (FY26 AISC guidance US$925–1,025/oz, YTD
US$1,013), financial statements in CAD (Q2 adj. EBITDA $285.2M, D&D $12.2M,
finance expense $15.4M, cash $178.9M — all CAD). Reserve life and royalty rate
not disclosed in results releases.

### AMRQ.L — Amaroq
Mixed reporter (CAD statements, USD AISC guidance). Beyond currency it is simply
too early: **no declared mineral reserve** — only resource estimate MRE5, ~500koz
at 30.35 g/t — so `reserve_life_years` has no basis; no EBITDA reported; no tax
line; no royalty rate disclosed; H1 D&A only $0.76M. Already correctly
score-withheld as `LOW_LINKAGE_STRUCTURAL_SIGNAL`.

### DSV.TO — Discovery Mining (the near miss)
The **only USD-native** name of the five ("All dollar amounts are in US dollars").
Most fields are sourceable:

| Field | Value | Basis |
| --- | --- | --- |
| production_oz | 260–300koz FY26 guidance | reaffirmed Q2 2026 |
| aisc_usd_per_oz | 2,101 YTD (guid. 1,950–2,250) | Q2 2026 release |
| cash_cost_usd_per_oz | 1,401 YTD (guid. 1,250–1,400) | Q2 2026 release |
| royalty_rate | 4.25 | 2.25% perpetual + 2.00% NSR, Franco-Nevada package |
| sustaining_capex_musd | 120–165 guidance | Q2 2026 release |
| net_debt_musd | −364.3 (net cash, zero debt) | cash $364.3M at 30 Jun 2026 |

Abandoned anyway, because three fields would each need a judgement call rather
than a source:

1. **`reserve_life_years`** — Porcupine had **no reserve statement**; Discovery was
   still drilling to establish an initial one during 2026. The technical report
   says "average over 285,000 oz for the next 10 years" with production extending
   to 2046, which supports either 10 or ~20 depending on reading.
2. **`tax_rate`** — never disclosed as an effective rate; would require assuming a
   statutory Ontario/federal combined rate.
3. **`ebitda_ltm_musd`** — H1 2026 is $347.9M, but LTM needs H2 2025, and Porcupine
   was only acquired 15 April 2025, so the trailing window is not comparable.

Plus a correctness concern for a *gold* sensitivity tool: Discovery has acquired
**Glencore's Kidd operations** (copper/zinc), so forward EBITDA is no longer pure
gold and would distort EV/EBITDA and the gold linkage.

**If Victor ever wants exactly one name done, this is the one** — it needs three
`ESTIMATED` entries and a note about Kidd, which is consistent with existing
practice (36 of the 45 rows already in `source_verification` are `ESTIMATED`).
