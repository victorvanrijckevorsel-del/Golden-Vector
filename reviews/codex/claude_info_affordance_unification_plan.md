# Plan: one info ("i") affordance everywhere

## Problem (Victor, with screenshots)
The app has **three** info affordances that look different:

| # | Affordance | Emitter | Used on | Look |
|---|---|---|---|---|
| 1 | Structured **click panel** (`.help-panel`) | `help_icon(key=...)` → `help-popover.js` | column headers, categorical values | Title · meaning · **boxed FORMULA** · Read-more ✅ (image 2) |
| 2 | **Flat** cell ratio panel | `metric_formula_icon` → `help_icon(label, text=run-on)` | ratio value cells | everything in one line, no structure ❌ (images 1, 3) |
| 3 | **Hover** tooltip (`.help-pop`) | `help_term` → `help-popover.js` | inline labels (Lab, Scorecard, Portfolio, some detail labels) | dotted-underline hover, plain text |

Root cause: #2 dumps the whole "formula + numbers" string into the panel's *meaning* slot and leaves *formula*/*more* empty, so it renders flat. #3 is a separate hover mechanism. The icon itself is already one component (dark = open state).

## Decisions (Victor)
1. **Cell depth** → cell "i" = the FULL structured panel (same as the header) PLUS this stock's live numbers.
2. **Numbers placement** → a SEPARATE "This stock" section (not inside the FORMULA box).
3. **Scope** → CONVERGE everything: the hover tooltips (#3) also become the click panel. One affordance in the whole app.

## Target panel layout (every "i", header or cell)
```
Title
Meaning paragraph
┌ FORMULA ──────────────┐   (when the metric has a formula)
│ Gold price - AISC     │
└───────────────────────┘
THIS STOCK                  (only on value cells — the instantiation)
4,173 - 2,080 -> 2,093 $/oz
Read more ▾                 (details + direction)
```

## Changes
### A. `column_help.help_icon` — add a `values` slot
- New kwarg `values: str | None` → emit `data-help-values="..."`. Carries the "This stock" line (+ provenance `extra`). No other behaviour change; headers/categorical values pass no `values` and are unaffected.

### B. `help-popover.js` (click panel `build()`) — render the values section
- After the FORMULA box, if `data-help-values` present, append a `.help-panel-values` block with a `THIS STOCK` label + the value text. Built with `textContent` (no innerHTML) like the rest of the panel.

### C. `metric_formula.py` — route the cell icon through the structured panel
- Replace `metric_formula_text` (the flat "label = formula. components -> result") with **`metric_values_text(metric_key, row)`** = just the instantiation line `"Gold price 4,173, AISC 2,080 -> 2,093 $/oz"` (components + result WITH full unit; this is the explanatory line, so it keeps `x`/`$/oz`).
- `metric_formula_icon(metric_key, row, *, extra)` → `help_icon(spec.label, key=spec.help_key, values=<values + extra>)`. Now the cell panel = the header's meaning + formula + Read-more (from the SAME `COLUMN_HELP[help_key]`) + the "This stock" line. Identical structure to the header.

### D. `column_help.help_term` — converge to the click panel
- `help_term(label, key/text)` now returns `escape(label) + <span class="help-anchor">{help_icon(label, key/text)}</span>` (the click "i"), or plain `escape(label)` when there is no help. Same inline call sites, now one affordance. `help_th(panel=False)` consequently also yields the click icon.

### E. Remove the dead hover system
- After D nothing emits `class="help-term"` / `data-help=`. Remove the `.help-pop` hover IIFE from `help-popover.js` and the `.help-pop` / `.help-term` CSS. (Verify via grep that `help_term` is the only emitter first.)

### F. CSS
- Add `.help-panel-values` (+ `.help-panel-values-label` "THIS STOCK") mirroring `.help-panel-formula`. Remove `.help-pop`/`.help-term` rules.

## Tests
- `metric_values_text`: components→result line, percent scaling, missing-input degrade, full unit kept.
- `metric_formula_icon`: emits `data-help-title` + `data-help-meaning` (from COLUMN_HELP) + `data-help-formula` (calculation) + `data-help-values` (this stock); "" when no value.
- `help_icon(values=...)`: `data-help-values` escaped + present.
- `help_term`: now emits a `.help-icon` (not `.help-term`); plain label when no help; value escaped.
- Guard test: no `class="help-term"` / `data-help="` remains in any rendered serve output (the convergence is complete). Update existing help_term/metric_formula tests.
- Full gate + live-verify (header "i", a ratio cell "i" shows This stock, a converged Lab/Portfolio label "i").

## Risk / rollback
UI-only; no model/data math changes. Main risk is missing a `help_term` caller or a panel layout regression — covered by the "no help-term remains" guard test + live-verify. Single commit, easy revert.
