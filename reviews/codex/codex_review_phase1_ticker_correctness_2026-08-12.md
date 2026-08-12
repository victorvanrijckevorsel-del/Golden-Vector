# Codex Review: Platform Redesign Phase 1 — Ticker Correctness

## Review scope

- Diff reviewed: `c7e90db2b3fe5e2c15d32d9a215d03ff70faaf12..b542fe06ed36830e5deb197cb950b2b31d65e71d`
- Branch: `dev-vic`
- Pinned reviewed HEAD: `b542fe06ed36830e5deb197cb950b2b31d65e71d`
- Authority: `reviews/codex/claude_platform_redesign_plan_final_2026-08-12.md` §4.3, §4.4, §4.6, and the Phase 1 gate
- Review mode: read-only. No product code or tests were modified by Codex.

`HEAD` did not change during the review. A concurrent uncommitted edit to
`golden_vector/serve/ticker_page/corporate.py` appeared after the pinned inspection began; it is
not part of this review. Every finding below is against the committed snapshot named above.

## Verdict

**Phase 1 is not ready to pass its gate at the reviewed HEAD.** The normal covered paths are green,
but five high-severity correctness/gate issues remain, together with seven medium and two low
findings. In particular, active scenario cards can carry a false spot label, non-finite spot data
can take down the route, and two chart modes can visually misstate their data.

## Findings

### [P1] Reject missing and non-finite spot values before building the dial payload

**Location:** `golden_vector/serve/ticker_page/corporate.py:366-378`, `:412`, `:1243`

`_dial_state()` only range-checks when `spot is not None`; it does not make a missing/non-finite
spot a State-A failure. `None`/`NaN` therefore returns `(True, "")`: the control happens to become
disabled later because there is no value, but its visible reason is blank, the Corporate Finance
section emits no disabled warning, and the JSON payload still says `enabled: true`. `+/-Infinity`
is preserved in `spot_gold_usd`; `embed_json_payload(..., allow_nan=False)` then raises
`ValueError`, taking down the ticker route. Reproduced with an otherwise-OK row whose
`spot_gold_usd=float("inf")`.

Plan §4.3 explicitly puts missing and non-finite spot values in State A. Resolve the spot through
the shared finite-number helper before the state decision, return one concrete disabled reason,
and ensure every embedded numeric value remains JSON-safe. Add `None`, `NaN`, `+Inf`, and `-Inf`
control/section/payload regressions.

### [P1] Active scenario headlines remain labelled as spot values

**Location:** `golden_vector/serve/ticker_page/corporate.py:820`; `golden_vector/serve/static/gold-dial.js:363-410`

When the user moves the dial, JavaScript hides the persisted headline and reveals the scenario
headline, but the text immediately below every card remains the server-rendered
`fwd @ spot $… as of …`. Only the command-bar `#gold-dial-basis` is updated. A value evaluated at
$4,200 can therefore be presented as being at spot $4,477, which is materially false financial
labelling and violates the State-C/one-headline contract.

Either update/restore explicit card-basis state markers with the headline state, or remove the
per-card basis and rely on the single shared basis context. The Node test should assert the card
basis after movement, manual return, and Reset—not only which numeric `<p>` is hidden.

### [P1] Incomplete OI captures are removed and then visually bridged

**Location:** `golden_vector/serve/charts.py:509-510`, `:558-565`; `golden_vector/serve/ticker_page/options.py:530-533`

Options correctly inserts `None` for an incomplete chain capture and promises a visual gap. The
shared builder removes every `None` point and emits all remaining points as one `<polyline>`, so a
complete day before the bad capture is connected directly to the complete day after it. The note
says smoothing would invent a move, but the SVG does exactly that.

Preserve explicit break information and split only the OI series into separate line segments (or
make gap preservation an explicit builder option so normal market-calendar spacing does not change
accidentally). A complete → partial → complete fixture must produce two disconnected segments.

### [P1] Sub-cent share prices are rendered as `USD 0.00`

**Location:** `golden_vector/serve/charts.py:408-417`, `:434-448`, `:629-633`

Price mode hard-codes two display decimals and also rounds the embedded raw value to two decimals.
For valid prices such as `0.001`, `0.0015`, and `0.002`, the line visibly moves while every axis
label, tooltip, and accessible-table cell says `USD 0.00`; the embedded raw values become `0.0`.
That fails the Phase 1 “currency-true end to end” gate.

Choose currency precision from the observed scale/quote precision, keep sufficient raw precision
in the crosshair payload, and use the same resolved formatter for axis, tooltip, caption table, and
ARIA. Add a sub-cent regression as well as the existing $6–$7 fixture.

### [P1] Required Phase 1 baseline evidence is neither complete nor committed

**Location:** `reviews/codex/claude_platform_redesign_plan_final_2026-08-12.md:438-441`; current untracked `reviews/codex/milestones/platform_redesign/phase1_baseline.md:26-29`, `:45-46`, `:56-61`, `:73-78`

The authority requires committed 1440/1024/390 route screenshots, payload/render measurements, and
pre-change test evidence. The reviewed commit contains no tracked
`reviews/codex/milestones/platform_redesign/` files. The current untracked note explicitly says the
screenshots were skipped, points to an external temporary measurement script, and records that the
supposed baseline full-suite run overlapped the implementation merges. Static source-reading tests
could therefore have observed post-baseline code.

Capture the specified screenshots and reproducible measurements from an immutable `c7e90db`
worktree, store the scripts/evidence under the milestone directory, and commit them before calling
the Phase 1 gate complete.

### [P2] `align_to_step()` uses the wrong exact-half rule

**Location:** `golden_vector/common/numeric.py:41`; `tests/test_common_helpers.py:275-290`

Python `round()` uses ties-to-even, while HTML range-value sanitization resolves an equal-distance
tie toward positive infinity. For example,
`align_to_step(4476.5, minimum=2000, step=1)` returns `4476`, while the browser-valid choice is
`4477`. The helper claims browser equivalence, but its tests omit half-step inputs.

Implement the range-input tie rule explicitly (without reintroducing float-noise drift) and add
half-step cases, including an off-zero minimum.

### [P2] Slider serialization can still emit an off-grid or out-of-range value

**Location:** `golden_vector/serve/ticker_page/corporate.py:461-468`

The formatter uses only the step's decimal precision, so it can discard precision carried by the
grid origin. With `min=2000.5`, `step=1`, and `spot=4477.4`, alignment produces `4477.5` but the
attribute becomes `"4478"`, which is off-grid and will be rewritten by the browser. It also does
not constrain the rounded point to the highest valid step at or below `max`: `min=0`, `max=10`,
`step=6`, `spot=9` emits `12`. The config model currently permits both geometries.

Resolve the nearest legal point on the bounded `min + k*step` grid and serialize with precision
that accounts for both `minimum` and `step` (preferably exact decimal grid arithmetic). Cover
fractional minima and a non-step-divisible maximum.

### [P2] Fractional-step scenarios announce a different price from the control value

**Location:** `golden_vector/serve/static/gold-dial.js:388-404`, `:423-427`

The configuration and Python tests explicitly support steps such as `0.1` and `0.25`, but scenario
output, visible basis, `aria-valuetext`, and live announcements all use the zero-decimal `usd`
formatter. At a real slider value of `4477.5`, calculations use `4477.5` while sighted and screen-
reader users are told `$4,478`.

Carry or derive the dial's configured display precision and use it consistently for all scenario
price text. Add a real-JS fractional-step movement/reset case.

### [P2] Put and total OI lines receive the same visual series key

**Location:** `golden_vector/serve/ticker_page/options.py:562-568`; `golden_vector/serve/charts.py:553-555`

The OI caller supplies no `series_keys`. The fallback alternates `gdx`, `gdxj`, `gdx`, so Put open
interest and Total open interest get the same line class and legend-swatch class. Two of the three
series are therefore visually indistinguishable even though their text labels differ.

Pass three explicit semantic keys and give each line/swatch a distinct non-colour treatment. Test
that the three polyline classes and their legend classes remain one-to-one.

### [P2] Share-price mode leaks benchmark-unavailable notices

**Location:** `golden_vector/serve/ticker_page/sections.py:138-162`

The drawable rows are correctly restricted to `stock` in price mode, but `marker_rows` is not.
Missing/stale Gold, GDX, or GDXJ markers therefore appear below the stock-only Share price chart,
even though those series belong only to Compare. The current fixture already contains a stale GDX
price marker, but the “stock alone” test does not assert that the notice is absent.

Restrict price-view marker rows to stock (and scope `trim_notes` too if those reasons are
series-specific); retain all benchmark notices in Compare mode.

### [P2] Low-count charts emit duplicate labels at different y positions

**Location:** `golden_vector/serve/charts.py:419-429`, `:576-597`

Count mode formats every tick with zero decimals, but the shared nice-step helper can choose a
fractional interval. A `[0, None, 2]` count range yields distinct tick positions labelled
`0, 0, 1, 2, 2`, making the axis ambiguous.

Use a minimum tick step of one for integral count data (or otherwise deduplicate/format tick labels
without claiming fractional contracts). Add a low-count regression alongside the current
thousands-scale case.

### [P2] The Node “out-of-range” test locks behavior opposite to State A

**Location:** `tests/test_gold_dial_js_behavior.py:540-562`

The test names an out-of-range spot but `_payload(spot=7000)` defaults to `enabled=True`; it then
asserts that moving the disabled-state baseline activates a scenario. The real server is required
to resolve that spot to State A with a disabled dial and no interactive scenario. The separate
generic disabled test does not prove the out-of-range server/JS contract.

Build this case from the server-resolved disabled state/reason and assert disabled input/Reset,
no listeners, no scenario reveal, and readable persisted spot headlines.

### [P3] The locked Yahoo-source JavaScript case is absent

**Location:** `tests/test_gold_dial_js_behavior.py:22-23`, `:60-69`

Every Node payload hard-codes `finance_source="our"`, and the module comment explicitly waives
Yahoo coverage even though the Phase 1 plan requires the real-JS suite to cover both sources. The
runtime logic is intentionally source-agnostic, but a Yahoo sentinel row is still needed to prove
that source-specific payload selection reaches the same clean/move/reset state machine without
borrowing Our View data.

Parameterize at least the fractional boot, genuine movement, and Reset path with distinct Our View
and Yahoo spots/values.

### [P3] Count mode silently inherits a 100-count anchor unless every caller overrides it

**Location:** `golden_vector/serve/charts.py:419-429`, `:451-459`, `:528-546`

Count mode sets `anchored=True`, but the shared function's default `base` remains `100`. The current
OI caller correctly passes `base=0`, yet any future `mode="count"` caller that omits it silently
gets a dashed 100-contract baseline and a range forced around 100.

Make the anchor part of the display-mode contract (zero for count, 100 for indexed, none for price)
or validate an explicit base rather than relying on a caller convention.

## Verification

Focused suites, run while the worktree still matched the pinned commit:

```text
python -m pytest tests/test_common_helpers.py tests/test_ticker_page_corporate.py \
  tests/test_gold_dial_js_behavior.py tests/test_rebased_overlay_panel.py \
  tests/test_ticker_page_sections.py tests/test_ticker_page_options.py -q
172 passed in 18.07s
```

Supplementary route suites also returned `157 passed in 499.84s`, but an uncommitted concurrent
`corporate.py` edit appeared before that later run was audited, so this review does not treat that
result as immutable evidence for `b542fe0`.

Positive checks: indexed mode remains backward-compatible in the covered fixtures; normal-scale
price mode removes base-100 language; `overlay-crosshair.js` correctly uses the preformatted
`labelOnly` value without duplicating it; Reset/manual return and boot-announcement suppression pass
for the covered Our View, step-1 cases.

## Scheduled scope notes

- Repeated dates under the Corporate Finance cards are not raised against this Phase 1 diff because
  the approved plan explicitly schedules basis-strip migration/date removal in Phase 4.
- Yahoo Corporate Resilience is not raised against Phase 1 because its persisted dual-source data
  spine is Phase 2 scope.
