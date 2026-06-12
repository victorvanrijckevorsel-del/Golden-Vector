# Predictive Layer — Grounded Ideas & Build Order

**Author:** Claude Code (Opus 4.8), synthesizing a Fable-divergence → Opus-grounding → Fable-planning pipeline (18 agents, 6 lenses, ~36 planned ideas) against the verified literature in `claude_predictive_layer_research.md` and the rules in `.claude/skills/predictive-models/SKILL.md`. **This is curated, not a dump** — I deduped (the beta-gap idea surfaced independently 4×), cut what I'm not convinced by, and own the final judgment. Each item is tagged with its grounding and where I overruled the pipeline.

---

## 0. The two strategic truths that frame everything (both literature-verified)

1. **Don't predict gold — predict which miners win or break *when gold moves*.** Short-horizon gold prediction is near-hopeless (`[V]`: macro R² collapses to ~0.01 daily). The tractable, defensible product is *cross-sectional, conditional-on-a-gold-scenario* — which the gold dial + Tool A already set up. Every idea below obeys this; a "predict raw miner return" idea is a banned gold-bet in disguise.

2. **The NULL is the modal outcome, and it must be a shippable product.** With ~60 names the *effective* breadth is **~5–15 independent bets** (Fundamental Law). That caps the achievable Information Ratio so hard that "Tool A's signals carry no tradeable forecast" is the *most likely honest result*. The deepest design decision in this whole layer: **pre-register the acceptance bar, run once, and ship the null as a trust feature** ("we tested it; there's no edge; Tool A stays a conditional-scenario tool, not a forecaster"). Months of model-building correctly avoided.

> Consequence for product expectations (tell Emanuel plainly): the realistic prize is **(a)** better *descriptions* and *better numbers on the existing dial* — which pay off even at zero alpha — and **(b)** a *modest* cross-sectional tilt if one survives. Not a price oracle.

---

## 1. Foundation first — the engine & discipline (the literature's #1 lesson)

The research is unambiguous: **the backtest engine's discipline matters more than the model.** Build this before any predictive model. Most of it is cheap, and one piece must start *this week*.

| # | Build | Why (grounded) | Effort / Milestone |
|---|---|---|---|
| F1 | **Start the PIT clock today** — append-only, hash-stamped weekly *vintage recorder* for every Tool B/D/options/hedge field, `as_of = the date we knew it`. | PIT fundamentals history **cannot be bought later**; every un-snapshotted week is lost forever (restatement + reporting-lag bias). Highest value-per-effort item in the entire project. | **S, M0 — do this regardless of every other decision.** |
| F2 | **Dead-Miner Registry** — reconstruct the survivorship-complete universe (acquired/bankrupt/delisted) from GDX/GDXJ N-PORT filings, with terminal-return rules frozen in config; hard-gate the engine to INADMISSIBLE below 90% coverage. | The dead names *are* the high-down-beta, weak-survival names the tool exists to flag; excluding them fabricates alpha (`[K]` survivorship). | L, M1 (longest pole — start now). |
| F3 | **Residualize-or-Die** — the label store holds **only GDX-hedged residual alpha** (PIT trailing beta); every backtest P&L is auto-regressed on gold and stamped CONTAMINATED if R²>0.20 or \|t\|>3. | Raw miner returns are ~70–90% gold factor (`[S]` ~2× elasticity); in a gold bull any long-biased high-beta model backtests beautifully with zero skill. Residualizing is what makes IC measure *skill*. | M, M1. |
| F4 | **Backtest engine** — walk-forward + **purge + embargo** (overlapping forward-return labels leak), realistic per-tier costs, **Deflated Sharpe + variant count** on every result, Harvey-Liu-Zhu **t>3** bar. | The core validity standards (`[F]` Deflated Sharpe; `[K]` purge/embargo, t>3). | M, M2. |
| F5 | **Leakage Canaries** — 3 rigged inputs (label-as-feature, within-date-shuffled labels, forward-shifted features) the engine must *catch* in CI before any real run is admissible. | Turns "we follow López de Prado" from a claim into a regression-tested property. Genuinely clever. | M, M2. |
| F6 | **Variant Ledger** — every config sha256-registered *before* compute; `deflated_sharpe()` reads `n_trials` from the ledger (the argument is removed from the human API, so neither agent can forget the denominator). | Backtested Sharpes are "meaningless without adjustment for the number of strategies tested" (`[F]`). | M, M2. |
| F7 | **Kill-List as CI** — banned dead-ends (ML imports on 60 names; feature/label join; gold-return targets; hardcoded horizons) encoded as *failing tests*, red-teamed against planted violations. | Makes the literature's bans survive across sessions and both agents — not folklore. | S, M0. |
| F8 | **IR Ceiling Calculator** + **Design-for-the-Null pre-registration** — measure effective breadth (Ledoit-Wolf-shrunk eigenvalue entropy) → required-IC ceiling → commit a hash-locked, Codex-co-signed acceptance bar before the first M2 result is seen. | Pre-registering an unreachable bar is meaningless; a lax one rubber-stamps noise. The ceiling parameterizes the bar; the null becomes shippable. | M, M1→M2. |

**My judgment:** F1, F2, F3, F7, F8 are non-negotiable and mostly cheap. This foundation *is* most of the value — it's what lets us trust (or honestly reject) every signal below.

---

## 2. The honesty output layer (consolidated from the probabilistic-UX lens)

Every number the user sees flows through one grammar. I've collapsed the lens's 7 ideas into **one workstream**:

- **Episode-based "honest N"** — collapse overlapping weekly rows into independent episodes; the *same* logic powers purge/embargo. (At 120d, ~32 max episodes/ticker over 12y — set that expectation.) Verified with a coverage simulation, not assumed.
- **No-naked-probabilities schema** — a `ProbabilisticClaim` contract: no probability may be emitted/persisted/rendered without its siblings (episode-N, interval, calibration status, MinTRL fraction, variant count) + a provenance signature so a *present-but-wrong* N also fails the build.
- **Receipts, not coefficients** — the model *is* an enumerable analog table; every cell rate links to the actual past episodes (incl. dead names). The most beginner-legible possible object.
- **Show the shrinkage** — raw count *and* empirical-Bayes shrunk estimate side by side with an arrow; only the shrunk value is machine-readable downstream (so "best bucket on screen" can't just be the smallest-N bucket).
- **Trust Strip** — MinTRL progress bar + public variant count + Deflated-Sharpe *band*, with mandatory copy distinguishing "needs more history" (waiting fixes it) from "breadth-capped" (waiting won't).
- **Self-grading live ledger + kill-switch** — Candidate Finder is *architecturally unable* to consume a signal until ≥30 matured live predictions pass calibration. Live performance is the only un-gameable evidence.
- **Coverage-audited intervals** — block-conformal ranges that wear their own measured coverage record, with the **time-series exchangeability caveat surfaced** (`[F]` — conformal coverage is only approximate on financial data; "measured, not guaranteed").

**My judgment:** this is the single best thing the pipeline produced and it directly serves "calibrated frequencies for a non-technical founder" (`[K]` Spiegelhalter). Build it alongside the foundation; it's what makes the whole layer trustworthy rather than another vague score.

---

## 3. The flagship signal — Beta-Gap "Sensitivity Drift" nowcast

*(Independently surfaced by 4 lenses → the strongest idea in the set. The literature's deepest under-exploited insight, operationalized.)*

- **What:** per miner per week, `beta_gap = fast_effective_gold_beta (26w EW, James-Stein-shrunk by its own SE) − slow_structural_beta (Tool A 156w)`, regime-split (up/down).
- **The brilliance (why it's near-no-lose):** the **primary deliverable is a calibrated *nowcast of the miner's next-26w effective beta*** that replaces the static beta in the dial/scenario tables — **a product win even if alpha IC = 0**, because a better forward beta improves scenario tables, put sizing, and hedge readiness directly. The alpha-prediction (does a collapsed gap predict under-response to the next gold move?) rides along as an **honestly-reported exploratory secondary** that is *allowed* to null.
- **Grounded in:** `[S]` miner beta is convex, time-varying, hedge-dependent — a static beta is mis-specified; the gap is the measurable signature of that.
- **Model:** one shrinkage parameter (the skill's "heavily-shrunk linear"). No ML.
- **Gate:** nowcast must beat *both* static-beta-persists and raw-fast-beta-persists on next-26w-beta MAE by ≥10%, t>3, in ≥70% of walk-forward folds. Secondary alpha gate is orthogonalized vs beta-level *and* momentum (kill condition: "gap = repackaged Tool A + momentum").
- **Output:** *"Current effective down-beta −2.4 (long-run −1.8). Across N≈420 past nowcasts the blended estimate beat the static beta X/100 times (MAE 0.31 vs 0.44); 10–90% next-26w range −3.1 to −1.7."*
- **My judgment:** **build this first among the signals.** It's the rare idea whose floor is still a shipped product improvement.

---

## 4. The spine — the Conditional Dial (analog table)

*(The substrate every other signal becomes a column on.)*

- **What:** for a *user-chosen* gold 60d scenario bucket, each miner's historical outcome distribution — P(beat GDX), median alpha, 10–90% range — keyed by PIT cohort (down-beta / downside-vol quartile), **pure counting + shrinkage**, with Wilson intervals, raw N *and* effective N.
- **Grounded in:** `[V]` reframe (conditional, not forecast); `[K]` ranks-not-ML at small N; `[K]` calibrated-frequency outputs.
- **Critical guard:** the live dial takes the scenario as an *explicit user parameter*; a test asserts no code path computes a "current bucket" from realized gold (that would smuggle in gold prediction).
- **Output:** *"In N=38 past 60d windows where gold fell 2–7% (effective N≈9), names in this cohort beat GDX 24/100 times [Wilson 12–41]; median −4.2%, range −18% to +6%."* Tail cells render "insufficient history," never a number.
- **My judgment:** **build the spine and the flagship together** — they're M1/M2 and everything else bolts on.

---

## 5. Supporting signals — each gated, each may legitimately null (ranked)

| Rank | Signal | One-line | Verdict |
|---|---|---|---|
| 1 | **Hierarchical EB beta shrinkage (Vasicek)** | Partial-pool each miner's rolling beta toward a PIT liquidity×vol tier prior, shrinking hardest where SEs are largest (juniors). Ships as a "shrunk beta" column beside raw on Tool A. | **Keep — cheapest, highest immediate payoff.** `[S]` says the win is biggest for noisy juniors. A pure accuracy upgrade, no alpha claim. |
| 2 | **Two-factor residual momentum** | 52−4w momentum on residuals from a rolling gold+GDX regression — orthogonal to the bet Tool A already makes; the cleanest *independent* IC for a breadth-starved universe. | **Keep — but gated on beating *raw* momentum (the existential test) and surviving costs.** `[F]` momentum is a top PIT-safe predictor; orthogonality is the whole value. |
| 3 | **Structural-beta law residual** | Fit the convexity law (beta rises as gold-moneyness falls) as a shrunk panel; Leg A = a forward-beta forecast that must beat trailing beta (near-no-lose, upgrades scenario tables); Leg B = rank "coiled spring" residuals. | **Keep Leg A; treat Leg B as exploratory.** `[S]` Tufano/Blose-Shieh convexity. |
| 4 | **Beta-dispersion meta-gate** | Don't predict returns — predict *when the cross-section is predictable*: gate every ranking on whether today's beta dispersion forecasts the forward IC, and abstain honestly ("uninformative this week"). | **Keep — only after a base signal passes.** Brilliant "trade the transfer coefficient" framing; calibrated abstention is the one free lever at fixed breadth. |
| 5 | **Convexity/gamma carry** | Pre-register the Tufano sign-flip (low-gamma pays in calm gold, flips in high vol); parameter-free state-switched rank sort. | **Keep as a falsifiable experiment** — its value is a clean answer either way; high null risk. |
| 6 | **Effective-Breadth Meter (N_eff)** | Weekly participation-ratio of the shrunk residual-correlation matrix; the mandatory denominator for every DSR/sample-size claim + a live confidence gate. | **Keep — it's really foundation** (powers F4/F8 and the Trust Strip). |
| 7 | **Gold-shock event panel** | Use ~30–60 non-overlapping gold shocks as the *unit of inference* (purge dissolves by construction); test which pre-event traits predicted within-event relative performance. | **Keep as the natural backtest frame** for several signals; honest about ~30–60 events = wide intervals. |

**Cut / demoted by my judgment (overruling the pipeline's "keep"):**
- **Pairwise Bradley-Terry contrasts** — clever (LETOR) but marginal value for 60 names at real complexity cost; the novelty was only in the audit line. *Defer indefinitely.*
- **Pooled-horizon ridge** — good estimation hygiene, but it's plumbing for alpha models that themselves may null. *Keep as a technique note inside F4, not a headline idea.*
- **Beta-gap double-demeaned panel** — the pipeline itself flagged it "most likely to null," L effort. *Defer until the simple beta-gap proves it carries anything.*

---

## 6. Diagnostics & benchmarks (explicitly NOT live-alpha — honest history)

- **Gold-Selloff Report Card** — per-miner shrunken base-rate over ~11 historical selloffs ("held up better than its beta predicted in 8 of 11"), barred from the live model, headlined "descriptive history, not a prediction (N=11)." Doubles as the **price-only benchmark Tool D must eventually beat.**
- **Price-only Break Baseline** — a frozen shrunk-logistic on 5 PIT price features predicting ≥30% drawdown, built *before* Tool D has PIT history, so the eventual "does Tool D survival-distance add skill?" contest is pre-registered and un-p-hackable. If price already predicts breaks as well as Tool D, *that's a shippable finding.*
- **"Rubber vs Glass" V-snapback tables** — descriptive-only, fitted model explicitly **cut** (8 events can't clear any honest bar); anecdote-grade tag test-enforced.

**My judgment:** these are high-trust, low-risk, and make the existing tools *accountable*. The Break Baseline + Report Card as "the yardstick Tool D must beat" is a genuinely sharp idea.

---

## 7. Deferred (needs collected history — start the clock, don't fabricate)

- **Hedge-signature inference** — correctly demoted by the pipeline to (a) one PIT price feature now (up-beta suppression vs the convexity norm, gated on incremental IC) + (b) a **go-forward manual hedge-disclosure collection program** (Codex's fields, PIT-stamped from day one), with the causal "behaving hedged" claim locked behind a precision/recall gate against real disclosures — likely 1.5–3 years out, *stated in the UI*. `[S]` hedge books measurably change beta, but inferring them from residuals alone is unvalidated by construction (Tufano used a disclosure database).
- **Fundamentals-/options-aware everything** — unlocks once F1's vintages mature (M4/M5).

---

## 8. Build order (maps to Codex's M0–M5; my recommended sequence)

- **M0 (this week, cheap):** F1 PIT recorder · F7 Kill-List CI. *(Start the irreversible clock; encode the bans.)*
- **M1:** F2 Dead-Miner Registry · F3 Residualize-or-Die labels · F8 IR-ceiling + null pre-registration · honesty layer (§2) skeleton · the shared **feature/label store** + flagship beta-gap *features* + spine *cohort table*.
- **M2:** F4 engine + F5 canaries + F6 ledger · run the **flagship nowcast gate** and the **spine analog backtest** · publish the **pre-registered confirmatory result — pass *or* null.**
- **M3:** ship the survivors live behind the honesty layer + self-grading ledger; the beta-gap nowcast upgrades the dial; supporting signals §5(1–4) added only if their gates pass.
- **M4–M5:** fundamentals-aware backtests (F1 matured) · Tool-D-vs-price-baseline contest · hedge-signature validation.

**The honest bottom line:** the highest-confidence wins are the **beta nowcast** (improves the dial even at null alpha), the **EB-shrunk Tool A betas** (cheap accuracy upgrade), the **conditional-scenario dial** (a calibrated reframe of what you already built), and the **discipline/honesty infrastructure** (which is most of the value). A tradeable cross-sectional alpha *might* emerge — but the design's integrity is that it's allowed to come back empty, and saying so clearly is itself the product.

---
*Provenance: ideas generated by Fable-5 agents (6 divergent lenses), each adversarially graded against the verified literature by Opus-4.8 agents, plans drafted by Fable-5 for survivors; final curation, cuts, and prioritization by Claude Opus 4.8. Full raw pipeline output retained in the run transcript. Evidence + grounding tags: `claude_predictive_layer_research.md`. Operating rules: `.claude/skills/predictive-models/SKILL.md`.*
