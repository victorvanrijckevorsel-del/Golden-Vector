# Platform redesign Phase 3 gate — shared professional UI primitives

Date: 2026-08-12  
Branch: `dev-vic`  
Authority: `reviews/codex/claude_platform_redesign_plan_final_2026-08-12.md`, Phase 3

## Outcome

Phase 3 is complete as a shared, opt-in UI foundation for the ticker pilot and later workspace
rollout. It adds a compact analytical command bar, URL-backed segmented controls, data cards,
one-per-family basis strips, compact section navigation, terminal-density wrappers, centralized
density tokens, and accessible coarse-pointer behavior. Existing pages retain their prior markup
unless a later phase explicitly opts them into these primitives.

The global content width remains unchanged at 1,240px. `workspace.css` remains the existing
nine-module manifest, so this phase extends the centralized design system instead of creating a
second page-local theme.

## Compatibility contract

- `_page_shell` keeps old caller output byte-identical while exposing independent `page_id`,
  header label, and active-navigation context for migrated pages.
- `_metric_card` now delegates to the shared `data_card` legacy mode and preserves the exact old
  HTML bytes.
- New density rules target explicit component classes; they do not broadly restyle raw buttons,
  fields, panels, or legacy Candidate Finder numeric cells.
- Semantic data-card states require visible text, so meaning is not communicated by color alone.
- Small help icons keep their visual size while receiving a 44px coarse-pointer hit target.

## Independent review closure

A skeptical read-only review found three actionable issues, all fixed before this gate:

1. semantic data-card state was initially expressed only through border color;
2. the help icon retained a 24px coarse-pointer target;
3. a proposed global `.numeric` rule would have changed an unmigrated Candidate Finder surface.

The final implementation requires a visible state label, expands the help hit area without
enlarging the glyph, and uses the new opt-in `.data-number` utility instead of the pre-existing
legacy `.numeric` class.

## Verification

### Focused foundation gate

`tests/test_ui_components.py tests/test_design_tokens.py tests/test_workspace_shell.py`

- **65 passed**
- Ruff passed on all changed Python files.
- `git diff --check` passed.

### Representative compatibility gate

The focused foundation tests plus ticker gold-dial behavior, ticker options, Candidate Finder page,
and Portfolio M1 coverage:

- **200 passed**
- Duration: **38.54 seconds**

This proportional gate was selected because Phase 3 only adds opt-in presentation primitives; the
mandatory full-suite and browser matrix remain at the combined Phase 3+4 visual checkpoint.

## Gate decision

**PASS.** The shared design system is ready for Phase 4 ticker-page composition. Per the approved
plan, Phase 3 is committed as a foundation but is not merged to `main` independently; Phases 3 and
4 share one visual-approval checkpoint.
