# Workspace UI system — ownership map

The visual system shipped by the 2026-08 redesign (plan: `GOLDEN_VECTOR_VISUAL_REDESIGN_PLAN.md`).
Rule of the layer: **backend computes, serve renders, ui/ only formats markup** —
modules here import nothing beyond the stdlib (enforced by
`tests/test_ui_components.py::test_ui_package_imports_stay_presentation_pure`).

## Python modules

| Module | Owns | Never does |
|---|---|---|
| `ui/shell.py` | Application frame: grouped sidebar nav (`_NAV_GROUPS`), skip link, header, drawer markup, `html.dark` + `js` bootstrap | Routing, state |
| `page_shell.py` | Compatibility facade re-exporting the shell (historical import path) | New code |
| `ui/components.py` | `page_header`, `section_heading`, `section_nav` (anchors only), `toolbar`, `empty_state`, `disclosure` | Data inspection |
| `ui/status.py` | `notice(tone,…)` — the ONE banner shell (tones per plan §10.5; call sites map already-resolved states) and `status_strip` | Inventing state thresholds |
| `ui/tables.py` | `table_region` — the ONLY horizontal-scroll owner (labelled, keyboard-focusable; JS drops the tab stop when nothing overflows) | Column logic |

Data-aware renderers stay outside `ui/`: `overview_helpers.py` (filter bar, refresh
strip, provenance warnings), `model_state_banner.py`, `column_help.py` (+`help_th`
with `scope`), `format_helpers.py` (`_metric_card`, numeric `<td>`s), `windows.py`,
`charts.py`/`option_signal_charts.py`/`detail_panels.py` (SVG builders emit semantic
`series-*` classes, never paint literals).

## Stylesheets (`static/workspace.css` = pure `@import` manifest)

| File | Owns |
|---|---|
| `css/tokens.css` | EVERY raw colour + z-index scale + fonts/radii/motion (sole literals file) |
| `css/base.css` | Reset, typography, long-content wrapping, forced-colors cues |
| `css/shell.css` | Frame, sidebar, header, nav links, drawer controls |
| `css/components.css` | Notices, page header, section nav/heading, status strip, toolbar, empty state, disclosure, buttons, badges, metric cards, help affordance |
| `css/forms.css` | Form grids, inputs, validation |
| `css/tables.css` | Table structure, `.table-region`, DataTables overrides |
| `css/charts.css` | All SVG paints via `series-*`/`chart-*` classes, dash patterns, legends |
| `css/pages.css` | Small page-specific modifiers only |
| `css/responsive.css` | Breakpoints, drawer (scoped `html.js`), reduced motion |

## First-party JavaScript (all presentation-only, no fetch/storage)

`workspace-shell.js` (drawer modal + region focusability), `workspace-tables.js`
(DataTables wiring, preserved contracts), `help-popover.js` (click-to-explain,
body-attached, clamped), `rug-tooltip.js` + `overlay-crosshair.js` (pointer-event
hover detail, clamped; keyboard gap documented in Phase 6 evidence).

## Guardrails that keep this true

`tests/test_design_tokens.py` (raw-colour/z-index/import-manifest/overflow-x
ownership/dead-selector scans), `tests/test_ui_components.py` (component contracts
+ purity), `tests/test_workspace_shell.py` (shell/drawer/contrast/scope),
`tests/test_workspace_app.py` (serve no-arithmetic sweep), and the pinned release
selection in `tests/tools/run_focused_selection.py`.
