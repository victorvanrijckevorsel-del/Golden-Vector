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
