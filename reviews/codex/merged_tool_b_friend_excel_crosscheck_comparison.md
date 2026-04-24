# Merged Review Comparison: Tool B vs Friend's Excel — Logic + Numbers Cross-check

Date: 2026-04-24
Sources:
- [claude_review_tool_b_friend_excel_crosscheck.md](claude_review_tool_b_friend_excel_crosscheck.md)
- [codex_review_tool_b_friend_excel_crosscheck.md](codex_review_tool_b_friend_excel_crosscheck.md)
- Original request: [claude_review_request_tool_b_friend_excel_crosscheck.md](claude_review_request_tool_b_friend_excel_crosscheck.md)

Both reviews followed the same framework, both ran the suite (235 passed), both ran `tool-b --gold-price 4500` for apples-to-apples number diffing. Codex additionally ran `--gold-price 4000` to empirically verify the verdict flip on KGC.

## Top-level verdict comparison

| Reviewer | Logic alignment | Number alignment | Manual-data drift |
|---|---|---|---|
| Claude | DRIFTED | ALIGNED (within ~1% on KGC/NEM) | 56 blank tickers + 1 stale field (AEM AISC) |
| Codex | DRIFTED | DRIFTED | 56 blank tickers + 1 stale field (AEM AISC) |

**Substantive agreement.** The "DRIFTED" vs "ALIGNED" tag on numbers is wording, not substance — both agree formulas match per-cell; both agree headline outputs differ because of the `best_target = max()` rule, the gold-price default, and stale jurisdiction tiers. Codex tagged it DRIFTED because the headline numbers users see differ; Claude tagged it ALIGNED because the underlying arithmetic per-formula matches.

---

## Findings both caught (high-confidence — act on these)

| # | Finding | Claude severity | Codex severity | Action |
|---|---|---|---|---|
| A1 | **Default gold-price assumption drift ($4500 in Excel, $4000 in our YAML).** Codex empirically showed KGC flips SCREEN_OUT → WATCHLIST when the price changes. | P1 | P1 | **Bump `default_gold_price_assumption` to 4500** in [config/screening_params.yaml](config/screening_params.yaml). Update workspace status text. |
| A2 | **`best_target_price = max(...)` and `tool_b_score` / `tool_b_rank` are Python-only inventions** the Excel doesn't have. The headline 300%+ "best upside" numbers are the most aggressive of 6 scenarios. | P0 | P1 | **Stop emitting a single "best."** Surface the four scenarios (Peer P/E, 2011 P/E, Peer FCF, 2011 FCF) as separate columns in the Tool B view + parquet, mirroring Excel `Top performers`. Re-validate `tool_b_score` formula afterward (currently depends on `best_upside_pct`). |
| A3 | **AEM AISC is stale in our SQLite store.** Store has $1475, Excel `AISC Verification!D5` shows verified $1275 (Q3 2025). | P1 | P1 | `python main.py manual-data set-company --ticker AEM --aisc-usd-per-oz 1275` |
| A4 | **AEM jurisdiction tier mismatch.** Excel `Screening Data!U5 = 1` (Tier 1). Our `universe.yaml` = 2. We over-discount AEM. | P1 | P1 | Update [config/universe.yaml](config/universe.yaml) AEM `jurisdiction_tier: 1`. |
| A5 | **AISC threshold label vs cell mismatch in the Excel.** Label says "$1,600/oz (2nd Quartile)"; cell `E12 = 1850`. Both Excel formulas and our YAML use 1850. | P3 | P2 | **No Python change.** Tell the friend his label is stale and to clean it up. |
| A6 | **Verdict logic is identical** between Excel and Python. The "huge upside but SCREEN_OUT" behavior is intentional in both — verdict is driven by Layer 1 + forward P/E, not by upside. | informational | P2 | **No formula change.** Add explanation text in the workspace explaining the two-axis (verdict vs upside) logic. |
| A7 | **56 of 59 active Tool B tickers are blank** in the SQLite store. Workspace shows them as INCOMPLETE and they don't get ranked. | P1 | P1 | Backfill from Excel `Screening Data` (priority list below). |
| A8 | **Per-ticker arithmetic on AEM/KGC/NEM matches within ~1% on KGC and NEM** when share prices are equalized. AEM diverges ~6-15% on EPS-based targets due to share price gap (Excel manual Jan 2026 entry vs our live Yahoo April 2026 snapshot — real market move, not a bug). | informational | informational | None — confirms math is right. |

---

## Findings only Codex caught — these are what I most need to add to my model

| # | Finding | Codex severity | Why I missed it | Action |
|---|---|---|---|---|
| C1 | **33 jurisdiction-tier mismatches across active tickers** (not just AEM/KGC/NEM). Excel `Screening Data!U:U` stores fractional tiers (e.g., 1.0, 1.5, 2.5, 3.0) and Layer 2 `C5` uses `=ROUNDUP(VLOOKUP(...,21))` to map to integer tiers. | P1 | I only spot-checked AEM, KGC, NEM and assumed Excel returned 0 for non-integer tiers via IFERROR fallback. Codex enumerated all 33 and decoded the actual ROUNDUP rule. | When backfilling manual data, also pull the per-ticker tier from Excel `Screening Data!U:U`, apply ROUNDUP, and write it into `universe.yaml`. Add regression tests for AEM/BTG/KGC/NEM/AAUC.TO. |
| C2 | **`Top performers` sheet is saved as VALUES, not formulas.** There is no canonical Excel ranking formula to mirror. | informational | I assumed the `Top performers` ordering came from a sort formula and tried to reverse-engineer it. Codex confirmed by inspection that no formula exists — the sort is whatever the friend last clicked. | Stop trying to mirror "the canonical Excel rank." Either keep our `tool_b_score` as our explicit product overlay (and label it as such), or define a new explicit rule with the friend. |
| C3 | **`RMS` in Excel vs `RMS.AX` in our universe.** Possibly a real ticker-coverage mismatch (Excel may track NYSE-listed RMS while our universe has the ASX-listed RMS.AX). | P2 (implied) | I only checked direction "Excel ticker → our universe" by exact match and didn't catch the `RMS` / `RMS.AX` near-miss. | Verify with the friend whether he means RMS (NYSE) or RMS.AX (ASX). They are different companies. |
| C4 | **Codex empirically verified the KGC verdict flip** at $4000 (SCREEN_OUT) vs $4500 (WATCHLIST). | P1 (already covered by A1) | I noted the verdict logic was the same but didn't run the side-by-side at both prices. | Reinforces A1 — the gold-price default isn't a cosmetic preference, it materially moves stocks across verdict bands. |
| C5 | **Comprehensive 56-row punch list** of every blank ticker with its Excel-verified AISC, production, and verification status (`verified` / `estimated`). | P1 (data, already in A7) | I sampled the first ~14 rows and provided a top-15 priority. Codex enumerated all 57 actions. | Use Codex's table directly for the bulk import. |

---

## Findings only Claude caught — Codex didn't see or didn't flag

| # | Finding | My severity | Codex's position | Re-judgment |
|---|---|---|---|---|
| L1 | **Royalty/tax-rate convention bug in Excel data for 4 tickers** (AGI, BGL.AX, DRD, EMR.AX). They store 0.03 / 0.025 / 0.05 / 0.03 where the Excel formula `/100` expects 3 / 2.5 / 5 / 3. Effective royalty/tax becomes ~0.03% / ~0.3% — massively inflates net income, EPS, target prices in the Excel. | P1 | Not flagged | **Holding.** This is a real Excel data bug. Worth telling the friend so his `Top performers` for those 4 tickers isn't artificially generous. When we backfill, our `_rate` helper will normalize correctly (it auto-detects). |
| L2 | **Leverage when EBITDA ≤ 0** — Excel `Layer 1!O5` returns 0 (auto-passes the leverage flag), Python returns `LEVERAGE_NON_POSITIVE_EBITDA` (auto-fails). For distressed tickers this means our Layer 1 is stricter. | P2 | Not flagged | **Holding.** Python is correct here — a zero-EBITDA company shouldn't get a free pass on leverage. Worth raising with the friend so he can decide whether to harden the Excel or accept the looser behavior. |
| L3 | **`FCF Yield 2011` benchmark cells (`Summary & Parameters!H27..H30`) may not exist in Excel.** The visible peer-benchmark table only has columns through `FCF Yield 2026` (column G). Layer 2 references H27..H30 for the 2011 FCF target prices — but I couldn't see those cells via openpyxl. | P2 | Not flagged | **Hand to Codex or Emanuel to verify** by opening the Excel and checking H27..H30 cell values. If blank, our YAML's invented `fcf_yield_2011: 0.02 / 0.035 / 0.045 / 0.05` may not match the friend's intent at all. |
| L4 | **Custom Target P/E for Rerating** (`Summary & Parameters!B23 = 10.0`) — friend-only feature not in our Python. Doesn't appear referenced by Layer 2 formulas, so likely vestigial. | P3 | Not flagged | **Defer.** Worth a single line of clarification with the friend: is `B23` used anywhere or is it a leftover? |
| L5 | **EV/EBITDA target prices** are called out as a separate concern from the `max()` rule. Python computes `target_price_peer_evebitda` and `target_price_peak_evebitda`; Excel doesn't compute target prices from EV/EBITDA at all. They go into the `max()` pool but rarely win. | P2 | Bundled into F1.3 (best target / score) | **Agree with Codex's framing** — this is part of the broader "Python adds extra product layer" concern. When we fix A2 (split into separate target columns), decide whether to include the EV/EBITDA targets as 5th and 6th columns or drop them from the published output. |

---

## Severity disagreements between us

| Finding | Claude | Codex | Resolution |
|---|---|---|---|
| `best_target = max(...)` (A2) | **P0** | **P1** | **Going with Codex's P1.** It's not a bug — it's an explicit product overlay that produces a confusing headline number. P0 means ship-block; this is high-priority but doesn't block ship. The fix is to surface the 4 scenarios separately, not to remove anything. |
| AISC label vs cell (A5) | P3 | P2 | **Going with Codex's P2.** No Python action either way; severity reflects how much the friend needs to clean it up. |

Both reviewers agree: no P0 issues remain. The combined cycle severity is **P1** ("substantial action needed but no ship-block"). The Python tool produces correct arithmetic per-formula; what's needed is a product-overlay clean-up + a manual data backfill.

---

## Per-ticker number cross-check (combined view)

Both reviewers ran our tool at $4500 and diffed against Excel `Layer 2 - Earnings Model`:

| Ticker | Field | Excel | Python | Match? | Notes |
|---|---|---|---|---|---|
| AEM | Forward P/E | 16.95 | 13.38 | ~21% gap | Share price drift (Jan→Apr 2026) |
| AEM | Target Peer $ | 237.53 | 202.25 | -15% | Same share-price gap |
| AEM | Target Peak $ | 423.09 | 360.27 | -15% | Same |
| AEM | Target FCF Peak $ | 1032.63 | 966.59 | -6% | FCF yield self-normalizes |
| AEM | Verdict | SCREEN OUT | SCREEN_OUT | ✓ | Both above watchlist |
| KGC ($4500) | Forward P/E | 9.95 | 8.65 | -13% | Price drift |
| KGC ($4500) | Target Peer $ | 50.55 | 50.49 | <0.5% ✓ | Tier discount cancels out |
| KGC ($4500) | Verdict | WATCHLIST | WATCHLIST | ✓ | |
| KGC ($4000) | Verdict | n/a | SCREEN_OUT | flips | Codex confirmed gold-price default is the issue |
| NEM | Forward P/E | 12.21 | 10.35 | -15% | Price drift |
| NEM | Target Peer $ | 144.84 | 145.91 | <1% ✓ | Excellent agreement |
| NEM | Verdict | SCREEN OUT | SCREEN_OUT | ✓ | |

**Conclusion (both agree):** the formulas are right. The visual gaps in our workspace are caused by:
1. The `max()` headline rule (not a bug, a product choice — A2)
2. The $4000 default vs $4500 (A1)
3. Stale share prices and stale single AISC value (A3)
4. Wrong jurisdiction tier on AEM (A4) and 32 others (C1)

---

## Combined action list — priority order

| # | Action | Source | Effort |
|---|---|---|---|
| 1 | **Bump `default_gold_price_assumption: 4000 → 4500`** in `config/screening_params.yaml` | A1 | 1 line |
| 2 | **Update AEM AISC** in SQLite: `1475 → 1275` | A3 | 1 CLI call |
| 3 | **Update jurisdiction tiers in `config/universe.yaml`** for all 33 mismatched tickers using Excel `Screening Data!U:U` with ROUNDUP. AEM: 1, BTG: 3, KGC: 2 (1.5→2), AAUC.TO: 3, etc. | A4 + C1 | 30 min if scripted from Excel |
| 4 | **Backfill manual data for 56 blank tickers** from Excel `Screening Data` (use Codex's full punch list) | A7 + C5 | 1-2 hours scripted, 4-5 hours manual |
| 5 | **Stop emitting `best_target_price_usd` as a single number.** Add 4 scenario columns to Tool B view + parquet (Peer P/E target, 2011 P/E target, Peer FCF target, 2011 FCF target). Decide whether EV/EBITDA targets stay as 5th/6th columns or get dropped. | A2 + L5 | 1-2 hours code + tests |
| 6 | **Re-validate `tool_b_score` formula** after A2 lands. It currently uses `best_upside_pct` which won't exist anymore. | A2 follow-up | 30 min |
| 7 | **Verify `Summary & Parameters!H27..H30`** (FCF Yield 2011 benchmark cells) in Excel. If they have values, sync our YAML to match. If blank, decide whether to keep our YAML invented values or drop the FCF Peak target entirely. | L3 | 5 min in Excel + decision |
| 8 | **Investigate `RMS` vs `RMS.AX`** with the friend — different exchanges, different companies. | C3 | 1 message to friend |
| 9 | **Investigate ARMN and NGD** correct Yahoo symbols. Re-activate if found. | both reviews | 10 min Yahoo lookup |
| 10 | **Add product explanation text** to workspace describing why a ticker can be SCREEN_OUT despite high "best upside." | A6 | ~10 min HTML |
| 11 | **Tell the friend about Excel data/label issues:** | combined |  |
|  | • AISC label `$1600` vs cell `1850` (A5) | A5 |  |
|  | • Royalty/tax convention bug for AGI, BGL.AX, DRD, EMR.AX (L1) | L1 |  |
|  | • Leverage edge case when EBITDA ≤ 0 (L2) | L2 |  |
|  | • `B23 Custom Target P/E` — is it used? (L4) | L4 |  |
|  | • `Top performers` saved as values, no canonical rank formula (C2) | C2 |  |

---

## Backfill priority — combined top 15

Both reviewers produced near-identical priority lists. Combined order:

| # | Ticker | Why it matters |
|---|---|---|
| 1 | SRB.L | Top of Excel `Top performers`, AISC + production both VERIFIED |
| 2 | BTG | #2 in Excel, STRONG_CANDIDATE, both VERIFIED |
| 3 | GAU | High Excel rank, both VERIFIED |
| 4 | AAUC.TO | High Excel rank, both VERIFIED |
| 5 | WAF.AX | STRONG_CANDIDATE, both VERIFIED |
| 6 | THX.L | High Excel rank, both VERIFIED |
| 7 | HMY | High Excel rank, both VERIFIED |
| 8 | EDV.L | STRONG_CANDIDATE, both VERIFIED |
| 9 | PNR.AX | STRONG_CANDIDATE, both VERIFIED |
| 10 | TXG | Both VERIFIED |
| 11 | AU | Both VERIFIED |
| 12 | NST.AX | Both VERIFIED |
| 13 | ALTN.L | STRONG_CANDIDATE, both VERIFIED |
| 14 | GFI | Both VERIFIED |
| 15 | CG | Both VERIFIED |

Second wave (lower-confidence inputs):
- JAG.TO, MTL.L — production status `ESTIMATED`
- MUX, RMS.AX — no dedicated verification rows; need interpretation

---

## What this comparison tells us about review quality

- **Codex stronger on:** Enumerative completeness (33 tier mismatches vs my 3, full 56-row backfill table vs my top-15) and empirical verification (running both `--gold-price 4000` and `4500` to prove the verdict flip).
- **Claude stronger on:** Excel data quality issues that don't show up in formula-by-formula comparison (royalty/tax convention bug, leverage edge case, FCF 2011 benchmark verification need, `B23` cell question).
- **Both equally strong on:** Per-formula cell-by-cell logic comparison, peer benchmark / tier discount / size category constants, the AEM/KGC/NEM number cross-check, and the verdict logic confirmation.
- **Severity calibration:** Claude over-rated the `best_target = max()` issue at P0; Codex correctly P1. No other meaningful divergences.

The two reviews are **substantially complementary, not redundant.** Roughly 60% overlap on findings, 25% Codex-only, 15% Claude-only. Combined coverage is high.
