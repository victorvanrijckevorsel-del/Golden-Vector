# Platform redesign Phase 4 gate — ticker-page reference implementation

Date: 2026-08-12  
Branch: `dev-vic`  
Phase 4 base: `ea9d44e` (`feat: add Phase 3 shared professional UI primitives`)  
Authority: `reviews/codex/claude_platform_redesign_plan_final_2026-08-12.md`, especially §§4, 5, 8, and 9

## Outcome

Phase 4 implements the ticker page as the professional reference surface for the later platform
rollout. It preserves the existing analytical calculations while replacing the page composition,
making source/scenario/basis state explicit, and fixing the no-JavaScript and responsive states.

Phases 5 and 6 have **not** started. This phase remains on `dev-vic` for Claude Code's independent
review and Victor's visual approval before any merge to `main`.

## Delivered behavior

- A compact company command bar now shows configured ticker/company identity, listing currency,
  jurisdiction, the truthful USD-normalized quote/date, a keyboard-complete ticker jump, the
  selected financial source, and the gold scenario control.
- Ticker jump accepts configured tickers only, preserves the selected financial source, and does
  not leak scenario or unrelated query state into the next company.
- The ticker shell is neutral: Candidate Finder is no longer falsely selected.
- Performance exposes both **Compare (rebased)** and **Share price**, plus 1Y/3Y/5Y horizons.
  Compare keeps the common indexed-to-100 basis; Share price shows the stock alone in USD levels.
- Compare-series controls progressively enhance the SVG and legend only. The accessible table
  always keeps all data.
- Stock/Gold/GDX/GDXJ use both colour and distinct line patterns, including matching legend
  swatches. Price-basis copy is reader-facing and discloses the bases of every drawn series.
- Currency Attribution remains inside Performance. Its numbers, units, period, FX source, and
  price basis are preserved without exposing internal artifact tokens.
- Corporate Finance uses one basis strip, one first-view data-status strip, and six shared data
  cards. Repeated dates under every card are gone; there is one active headline value per card.
- Our View and Yahoo use source-correct labels. Healthy Yahoo resilience is available with the
  explicit hybrid basis `Yahoo financials · Our View mining assumptions`; degraded states retain
  their actual reasons and never borrow the other source's data.
- The gold dial has an explicit server/JavaScript state contract. The server starts at clean spot
  (`data-scenario-active="0"`), ships a disabled no-JavaScript control, and JavaScript enables it
  only after validating the payload and attaching listeners. Lower, higher, Reset, manual return,
  fractional spot, out-of-range, and invalid-ratio behavior are covered.
- Inputs & Notes is one closed parent workspace with four intact child forms. Validation reopens
  the correct child, echoes input, and focuses the error.
- Ticker tables use semantic numeric cells, a data font, end alignment, and scoped headers. The
  ticker density and touch rules are page-scoped, including compact section navigation.

## Independent review closure

An independent skeptical pass found and the implementation closed these concrete issues:

1. Progressive series controls were visible without JavaScript because component CSS overrode
   `[hidden]`.
2. Corporate card collapse depended on pointer type rather than viewport width.
3. Legend markers did not communicate the plot's non-colour line patterns.
4. Corporate and later ticker numeric tables were not consistently aligned or semantic.
5. Invalid-ratio messages were terse rather than explicit `Not meaningful — …` explanations.
6. Several ticker controls and disclosures missed the coarse-pointer 44 px target.
7. The Inputs summary title and hint had no semantic spacing.
8. Performance and Currency Attribution exposed internal price-basis tokens.
9. A healthy no-JavaScript dial looked interactive although it could not update calculations.
10. State-A table copy falsely implied JavaScript could repair missing data.
11. Corporate data-card labels lost the dense label size through a more-specific heading rule.
12. OI/Greeks, peer, and beta-rug accessible tables lacked some numeric/scope semantics.
13. Corporate Finance hid active-source fundamentals/market/FX status on first view.
14. Compact section tabs missed the coarse-pointer target.
15. The clean server-rendered Corporate section lacked the State-B scenario marker.

The final bounded recheck found no other Phase 4 acceptance issue. The last two items were then
fixed and locked with 71 focused tests.

## Verification

### Focused automated gate

The consolidated Phase 4 selection passed **454 tests**:

```text
tests/test_ticker_page_command_workspace.py
tests/test_workspace_shell.py
tests/test_workspace_app.py
tests/test_ticker_page_corporate.py
tests/test_gold_dial_js_behavior.py
tests/test_ticker_page_sections.py
tests/test_performance_series_js_behavior.py
tests/test_rebased_overlay_panel.py
tests/test_ticker_page_compare.py
tests/test_ticker_page_behaviour.py
tests/test_ticker_page_options.py
tests/test_design_tokens.py
tests/test_ui_components.py
```

After the last two bounded CSS/markup fixes, the directly affected design-token and Corporate
selection passed **71 tests**. This proportional rerun is deliberate: Phase 4 changes only the
serve/UI layer, while the combined selection already exercises all changed Python and JavaScript
surfaces.

Additional checks:

- Ruff: all affected Python and test files passed.
- `node --check`: `gold-dial.js`, `performance-series.js`, `overlay-crosshair.js`, and
  `workspace-shell.js` passed.
- `git diff --check`: passed; only the repository's existing Windows line-ending notices appeared.
- Independent audit selection: 350 tests passed before its last two bounded findings were fixed.
- No full-suite run was used for this presentation-only phase; Phase 6 owns the full release gate.

### Browser gate

A batched local-browser pass exercised the real rendered workspace and real JavaScript.

| State | Result |
|---|---|
| NEM / Our View / clean fractional spot | Spot output is exact; server state is `0`; JavaScript enables the validated dial; six cards show one value each. |
| Lower scenario (`$4,200`) | State becomes `1`; all six scenario values replace rather than duplicate spot headlines. |
| Reset | Exact `$4,468.20` spot and clean state return. |
| Share price | Stock only, USD level axis/caption, no Compare-series controls. |
| NEM / Yahoo | First-view status says Yahoo data; resilience is active with the explicit hybrid basis. |
| AAR.AX / non-USD | Currency Attribution is inside Performance; AUD, FX, USD-investor return, period, source, and readable price basis are visible. |
| Responsive widths | 1440, 1280, 1024, 768, 390, and 320 px had no page-level horizontal overflow in the batched pass. Final recapture rechecked 1440/1024/390 after the last fixes. |
| Console | No warnings or errors in the final 390 px run. |

The final browser measurements recorded a four-column Corporate grid at 1024 px and one column at
390 px. A fine-pointer responsive browser reports the intentionally compact 32 px section tabs;
the page-scoped coarse-pointer media rule raises those tabs to 44 px and is locked by the design
test.

Automated CSS guards cover focus, reduced-motion, forced-colour, and coarse-pointer rules. Phase 6
still owns the final release-level keyboard/zoom/forced-colour matrix and full-suite run.

## Evidence

### Before

- `phase4_before_1440_reproduced.png`
- `phase4_before_1024_reproduced.png`
- `phase4_before_390_reproduced.png`
- `phase4_before_actual_user_reference.png`
- `phase4_mock_target_user_reference.png`

The reproduced before images were captured from a detached worktree at the pre-redesign commit and
used the same current local artifacts. The temporary worktree was removed after capture without
modifying the real artifact directories.

### After

- `phase4_ticker_1440_final.png`
- `phase4_ticker_1024_final.png`
- `phase4_ticker_390_final.png`
- `phase4_ticker_1440_corporate.png`
- `phase4_ticker_1440_lower_scenario_final.png`
- `phase4_ticker_1440_share_price_final.png`
- `phase4_ticker_1440_yahoo_resilience_final.png`
- `phase4_ticker_1440_currency_attribution_final.png`

## Boundary for the next reviewer

- Review Phase 4 from `ea9d44e..HEAD`; Phase 3's shared primitives are its immediate dependency.
- Do not begin the Phase 5 platform rollout or Phase 6 release work during this review.
- Do not merge to `main` until Victor has reviewed the screenshots.
- The untracked personal file `naukri.md` is unrelated and must remain untouched.

