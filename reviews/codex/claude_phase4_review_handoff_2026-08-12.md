# Claude Code handoff — independent Phase 4 review

Start with `git status` on `dev-vic`. Preserve the unrelated untracked personal file `naukri.md`.

Review the committed Phase 4 diff `ea9d44e..HEAD` thoroughly. The governing plan is
`reviews/codex/claude_platform_redesign_plan_final_2026-08-12.md`, especially §§4, 5, 8, 9 and
the Phase 4 gate. Read the implementation/evidence record at
`reviews/codex/milestones/platform_redesign/phase4_ticker_reference_implementation.md` and inspect
the before/after PNG evidence in that directory.

You own the technical and product decisions in this review. The plan is authoritative about the
required outcomes, but the implementation details are not set in stone. If you find a cleaner,
safer, more professional, or more maintainable approach, change it directly. Do not send the plan
back to Codex for another review. Tell Victor what you changed and why your approach is better.

Review and fix, at minimum:

- command-bar identity, ticker jump, selected financial source, and query-state behavior;
- Compare (rebased) versus Share price, horizons, series toggles, units, basis disclosure, legend
  patterns, and accessible table parity;
- Corporate basis/status strips, one-value data cards, spot/scenario state, Reset/manual return,
  fractional/out-of-range/no-JavaScript behavior, invalid ratios, and both-source resilience;
- Currency Attribution composition and non-USD truthfulness;
- Inputs & Notes disclosure/validation behavior;
- table semantics, keyboard/focus/touch behavior, responsive density, no overflow, degraded/empty
  states, and regressions in Market Behaviour, Options, and Compare.

Use focused tests first. Run the full suite only if your findings cross a wider contract or make it
necessary; Phase 6 remains the release-level full-suite gate. Re-run the batched browser matrix for
any visual or interaction changes, update the evidence/handoff record, and commit your fixes on
`dev-vic`.

Do **not** start Phases 5 or 6 and do **not** merge to `main`; Victor wants to review the Phase 4
result first.

