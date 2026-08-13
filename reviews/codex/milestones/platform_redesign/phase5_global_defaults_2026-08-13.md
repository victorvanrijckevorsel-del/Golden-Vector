# Phase 5 global-default decisions — 2026-08-13

These decisions were deliberately made only after every platform page had migrated to the shared
controls, cards, density, and table primitives.

## Adopted

- The ordinary workspace `main` width now reads `--content-max-width` instead of a raw `1240px`
  value. The ticker retains its wider, explicitly scoped analytical canvas.
- The last ordinary bare action, **Refresh all model data**, now uses the shared primary `control`.
  The legacy global `button` paint was removed. Purpose-specific help and navigation buttons keep
  their own explicit classes.
- The sidebar width now reads the semantic `--sidebar-width` token.

## Intentionally retained

The sidebar stays at `15rem`. Its longest real labels, including **Corporate Resilience** and
**Gold Sensitivity**, remain readable without wrapping at the desktop breakpoint. Narrow-screen
space is already recovered by the existing drawer transition. A narrower permanent rail would
save little usable comparison width while making navigation slower to scan.

## Guardrails

`tests/test_design_tokens.py` locks the tokenized main/sidebar geometry, the absence of the global
raw-button skin, and the zero-consumer removal of the old `.button-like` and `metric-card` systems.
