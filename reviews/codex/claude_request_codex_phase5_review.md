# Codex — review the Phase 5 backtest SPEC (pre-registration plan, not code)

**You are Codex, reviewing a pre-registered backtest SPEC — not an implementation.** Read
`reviews/codex/claude_phase5_behaviour_backtest_spec.md` in full, plus the engine it backtests
(`golden_vector/lab/behavior_engine.py`), the infra it will reuse
(`golden_vector/lab/{walk_forward,evaluation,forward_returns,ledger,validation,scorecard}.py`), the
template it mirrors (`reviews/codex/claude_program_a_validation_spec.md`), and the rigor rules
(`.claude/skills/predictive-models/SKILL.md`).

**This is a PLAN, frozen before any compute.** Do NOT file "X is not implemented" / "module doesn't
exist" as findings — that is the downstream build. Judge whether the *design* is statistically sound,
leak-proof, honestly pre-registered, buildable on the cited infra, and honest about survivor bias.

**Use agents and be adversarial:** fan out one agent per dimension below, then have independent
skeptics try to refute each finding (keep only what survives). Be exhaustive; cite spec §section and
real `file:line`.

## Already settled — do NOT re-litigate (challenge only with hard evidence, in a separate section)
- The locked product decisions: capture-vs-gold-only, CONVEX offense default, 13w capture / 8w trend.
- The v2-resolved items in §11: family size **m = 4**; E4 8w/13w; E3 dual labels; target IR 0.3 /
  transfer 0.5.
- This spec already passed an internal 5-dimension / 70-agent review (62 findings → ~9 distinct, all
  folded into v2). **Find what that review MISSED — do not repeat it.**

## Review dimensions
1. **Statistical validity** — the gate shape (IC NW-t > 3 + ≥ 70% folds + tercile spread); the
   fold-level NW-t (n = folds) vs the effective-N IC t-stat; lag-1 adequacy for 8–13w label overlap;
   the m = 4 family-wise α; the split-half noise ceiling; DSR reported-not-gated; the N_eff /
   IR-ceiling math.
2. **Leakage / PIT** — is the per-fold refit of every fitted quantity (capture, EB priors, peer
   pools, FDR family, recent/older split) actually sufficient? Is the regime-conditioning
   outcome-side framing truly leak-free? Do the 9 canaries cover every leak path, or is one missing?
3. **Pre-registration integrity** — any remaining degree of freedom that could be tuned post-hoc
   (fold params, quantile, which robustness variant "counts")? Is the co-signed-bar-before-labels
   mechanism real or circular?
4. **Buildability** — does each cited API actually support what the spec asks? Is the §8 "genuinely
   new code" list complete and correct, or does the spec still hide a new primitive / duplicate an
   existing helper?
5. **Survivor / honesty / completeness** — is the SUPPORTED-not-VALIDATED cap consistent? Does E1–E4
   cover every user-facing claim, or is something shipped-but-untested? Is the E4 null framing honest?

## Also answer the four open questions in §11
Target IR (0.3 / transfer 0.5), the NW lag for overlapping labels, DSR gate-vs-report, and the
walk-forward fold parameters — each with a concrete recommendation.

## Deliverable
Write `reviews/codex/codex_review_phase5_backtest_spec.md`: a severity-ranked findings table
(severity | dimension | §section / file:line | issue | why-real | fix), your answers to the §11
questions, and a final verdict — **READY TO FREEZE** or **NEEDS CHANGES** (with the blocking list).
Do not edit the spec yourself — recommend; Claude will apply.
