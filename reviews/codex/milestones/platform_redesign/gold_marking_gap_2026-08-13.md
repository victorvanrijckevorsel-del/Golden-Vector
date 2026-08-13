# The gold marking gap — how an approved visual rule was lost between mock and build

**Date:** 2026-08-13 · **Found by:** Victor, by putting the live page beside the
approved mock · **Fixed on:** `dev-vic`, same day · **Scope decision:** Victor
chose "ticker page now"; Tool B's gold dial is a candidate for the same
convention later.

## What was wrong

Mock v3 (`mock3_reference.html`) carries one defining visual rule for Corporate
finance: **anything that moves with the gold dial is marked in gold.**

- `.m.live { border-left: 3px solid var(--gold) }` — a gold edge on dial-driven cards
- `◆` in the metric cell of every dial-driven table row
- `.m .sc`, `table.fin td.sc { color: var(--gold) }` — scenario values in gold

The shipped page kept the *words* ("moves with gold" in the Basis column) and
lost the *marking*. The proof it was half-built: `corporate.py` emitted
`<tr class="moves-with-gold">` on exactly the right rows, and **no CSS rule
anywhere selected that class**. A marker with no paint.

## Why no review caught it

The requirements document (`claude_ticker_page_requirements.md`) is the
acceptance authority every review checked against — and the visual rule was
never transcribed into it when the mock was turned into requirements. The doc
specifies page order, disclosure states, which numbers appear and what the dial
drives; it says nothing about how a gold-driven figure is marked. So the build
matched the requirements, every review verified against the requirements, and
all of them passed while the page had quietly dropped the one rule that made
the mock legible at a glance.

**The lesson is not "review harder".** It is that a mock is a specification
artifact, and translating it into prose silently drops whatever the prose does
not mention. Where a mock is the approved design, the review must compare
against **the mock**, not only against the document derived from it.

## What was NOT a defect (checked before changing anything)

Three differences from the mock are correct and were left alone:

1. **No permanent "at spot" caption under each card.** Victor's Q43 decision —
   "clean by default", the scenario appears only once the dial moves.
2. **Different card set** (AISC margin yield, not "FCF yield"). Deliberate: the
   number is an AISC-margin yield and is now named for what it is.
3. **The two basis/status strips above the cards.** They post-date the mock and
   carry real dual-source provenance.

## The fix

One fact, emitted twice. `GOLD_BASIS = "moves with gold"` is the single source
of truth; the row class and the diamond are **derived** from the basis text via
`_is_gold_basis()`, so a row can never wear the marker while its Basis column
says the value is fixed. Previously `_ratio_metric_row` set the class
unconditionally regardless of the `basis` it was handed — correct only because
all six call sites happened to pass a gold basis. That trap is now closed.

| Change | File |
| --- | --- |
| `gold_linked` flag on the shared card primitive | `serve/ui/components.py` |
| `.data-card--gold-linked` edge, declared *before* the state modifiers so a degraded card keeps its warning colour | `css/components.css` |
| `GOLD_BASIS` + `_is_gold_basis`/`_gold_marker`/`_gold_row_attrs`; both row builders derive marker and class from basis; six literals replaced by the constant | `serve/ticker_page/corporate.py` |
| Scenario values take the gold accent; `.gold-linked-marker` styling | `css/pages.css` |
| Legend rewritten to name the symbol; section help text matches | `corporate.py`, `serve/column_help.py` |

Accessibility: the row diamond is `aria-hidden` (the Basis column already says
"moves with gold" in words, so the symbol would be a duplicate announcement).
The diamond **in the legend** is not hidden — there it is the subject of the
sentence.

## Tests

`tests/test_ticker_page_corporate.py`:

- `test_gold_driven_cards_and_rows_are_marked_and_fixed_rows_are_not` — 6 cards,
  11 rows, and a **control**: the balance-sheet table (sliced by region id, not
  by a label that also appears in help text) must carry neither class nor marker.
  A page marking nothing, or everything, fails.
- `test_the_marker_is_derived_from_the_basis_so_the_two_cannot_disagree` —
  non-gold bases yield no marker and no class.
- `test_a_degraded_card_keeps_its_warning_edge_over_the_gold_marking` — asserts
  both classes are present **and** that the CSS declaration order gives the
  state the shared edge. Condition beats nature.

Evidence: `gold_marking/corporate_finance_gold_marking_cards.png` (cards) and
`..._expanded.png` (all groups open — diamonds on the eleven dial-driven rows,
none on Market cap, Enterprise value, Share price, the balance sheet, resilience
or data-quality rows).

---

# Follow-up: the same bug class, found systematically (2026-08-13, later)

Victor's reaction to the fix was that the two still do not look alike. Since
"nobody compared against the mock" was the root cause, an independent audit
compared mock v3 against the live page section by section. It found the gold
marking was one instance of a pattern: **the requirements captured what the page
says and lost how the page looks**, and the build implemented the requirements.

## Measured

| | mock | live |
| --- | --- | --- |
| whole page height | 4,152px | 8,137px |
| table row height | 26px | 39px |
| table header | 9px uppercase, dim, transparent | 15px sentence-case on a filled band |
| disclosure summary | 36px bordered card, gold marker, preview hint | 25px bold text, default triangle, no hint |

## Two defects fixed immediately

1. **`visually-hidden` was emitted four times and defined nowhere.** Screen-reader-only
   labels ("Your score: ", "Rank: ") and *two* `role="status"` live regions — in the
   score builder and the options section — rendered as visible body text. That is
   what made the score result read "Your score: 52.8 Rank: #30 of 57 ranked". The
   standard utility now lives in `base.css`; verified in-browser at 1×1px.
2. **The guardrail that would have caught all of it.**
   `test_no_dead_first_party_selectors` checks CSS→markup and its docstring records
   the reverse direction (GV-RD-FINAL-008) as **not** covered. That reverse direction
   is precisely this bug class: `moves-with-gold` shipped with no rule painting it.
   `test_every_emitted_class_is_painted_or_a_declared_known_gap` now closes it, built
   as a **ratchet** — a new unstyled class fails, and painting a known gap without
   deleting its register entry also fails, so the list can only shrink. It found
   **52 emitted classes with no CSS rule**, of which 32 are the score builder.

## Not a defect (verified before touching it)

The audit's second-ranked finding — headline cards hide the spot value once the
dial moves, against requirements §3 "show BOTH values" — is **sanctioned**. The
final plan §2.3 records the override explicitly: "One active headline value per
card… Victor's duplicate-number feedback". Left as built.

## ANSWERED 2026-08-13: NO. This work is dropped.

Victor's decision, verbatim: *"i'm tired of doing this. Dont do it anymore"*.
The mock-fidelity pass described below is **cancelled in full** — not deferred,
not reduced to a smaller scope. The live page's density difference from mock v3
is an accepted permanent difference. Do not re-propose this work; do not open it
as a finding in a future review. The section below is kept only as a record of
what was measured.

## ~~Awaiting Victor's scope decision~~ (superseded — see above)

The remaining mock-fidelity work is one coherent pass, not a list of patches:
the score builder's stylesheet (it has none — browser-default fieldsets, blue
sliders, no contribution bars, unscrolled 61-row list), table density, disclosure
cards with preview hints, section header badges (including "gold explains 62%",
now buried in a fold), group headers, and per-section lede sentences. Ranked
detail and file/line targets are in the audit; the register in
`KNOWN_UNSTYLED_CLASSES` is the machine-checkable half of the same backlog.

## Also found: benchmark fixtures in the production data store

`data/intermediate/status/model_states/` holds 400 synthetic manifests
(`model_state_r000000…r000399.json`, all stamped 2026-01-01) left by an
out-of-repo performance measurement — the "1.8s at 400 retained files" figure in
`latest_successful_refresh.py`. Because today's current pointer is `incomplete`
(the options build was correctly blocked pre-market), the reader falls back to
scanning retained manifests and picks the newest *complete* one — a fixture. The
app header therefore reads **"Updated Dec 31, 7:00 PM ET · data may be stale"**
on every page. The code is right; the store is polluted. Deleting under `data/`
is Victor's alone (incident 2026-08-13), so this is reported, not actioned.
