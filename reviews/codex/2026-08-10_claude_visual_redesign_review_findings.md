# Claude visual redesign — Codex review findings

**Review date:** 2026-08-10  
**Scope reviewed:** Claude's committed Phase 1 work and uncommitted Phase 2 workspace-shell work  
**Review type:** Read-only, risk-focused code review  
**Repository state observed:** `dev-vic` was two commits ahead of `origin/dev-vic`, with Phase 2 changes still uncommitted.

## Instructions for Claude

Resolve every confirmed finding below before continuing to later redesign phases. Record the findings and their resolutions in the redesign defect register, including any additional defects discovered while correcting them.

Do not rerun the full project test suite solely for these presentation-layer fixes. The previous full run was already green and took approximately 13 minutes. Use focused design-system, workspace-shell, route, and affected-page tests instead. Do not weaken existing assertions to obtain a green result.

Preserve all existing routes, analytics, persisted-data contracts, table behavior, and application logic.

## Confirmed findings

### GV-RD-CX-001 — High — Mobile navigation is unavailable without JavaScript

**Evidence**

- `golden_vector/serve/static/css/responsive.css:9-24` moves `.app-sidebar` off-screen and sets `visibility: hidden` below the desktop breakpoint.
- `golden_vector/serve/static/workspace-shell.js:16-29` is the only mechanism that exposes the sidebar.
- `golden_vector/serve/page_shell.py:72-108` provides no progressive-enhancement or no-JavaScript fallback.

**Impact**

At widths below 1024px, navigation disappears completely if JavaScript is disabled, blocked, missing, or fails during initialization. This violates the redesign requirement that the application remain navigable through plain routes.

**Required correction**

Implement progressive enhancement so mobile navigation remains reachable without JavaScript. JavaScript may enhance the navigation into an animated drawer, but it must not be the only way to reach the route links.

**Regression coverage**

- Add a test proving the server-rendered mobile navigation has a usable no-JavaScript fallback.
- Test both the unenhanced state and the JavaScript-enhanced drawer state.

### GV-RD-CX-002 — High — Inactive preset and segmented controls have nearly invisible text

**Evidence**

- `golden_vector/serve/static/css/tokens.css:19` defines the primary text as `#F4F6F8` through `--ink`.
- `golden_vector/serve/static/css/tokens.css:53` defines `--white` as `#ffffff`.
- `golden_vector/serve/static/css/components.css:155-163` uses `background: var(--white)` with `color: var(--ink)`.
- `golden_vector/serve/static/css/pages.css:29-37` repeats the same foreground/background pairing for Candidate Finder presets.
- The resulting contrast is approximately **1.08:1**, far below WCAG AA's 4.5:1 requirement for normal text.

**Impact**

Inactive segmented controls and Candidate Finder Bull/Bear preset controls can appear blank or almost blank in the new dark palette.

**Required correction**

Replace the light background alias with an appropriate semantic dark-surface token, or choose another token pairing that meets contrast requirements. Avoid fixing this separately in two selectors if both controls represent the same shared UI pattern.

**Regression coverage**

- Add a guard that checks the actual foreground/background token pairs used by these selectors, not merely isolated token definitions.
- Cover both inactive and active states.

### GV-RD-CX-003 — Medium — White text on the new teal fails contrast requirements

**Evidence**

- `golden_vector/serve/static/css/tokens.css:30` defines the verified/teal color as `#4DB6AC`.
- `golden_vector/serve/static/css/components.css:192` uses white text on that teal for the active benchmark control.
- `golden_vector/serve/static/css/pages.css:227-236` uses the same pairing for the win-rate visualization.
- White on `#4DB6AC` produces approximately **2.44:1** contrast, below 4.5:1 for normal text and below 3:1 for large text.

**Impact**

Active benchmark labels and win-rate labels can be difficult to read. A text shadow is not a reliable substitute for sufficient foreground/background contrast.

**Required correction**

Use a sufficiently dark semantic foreground on this teal, or darken the background token while preserving the intended verified/positive meaning. Check all uses of the teal token so the rule is consistent across the application.

**Regression coverage**

- Add contrast assertions for the actual active benchmark and win-rate foreground/background combinations.

### GV-RD-CX-004 — Medium — DataTables dark styling is not activated

**Evidence**

- The vendored DataTables stylesheet activates its dark variables and rules through `html.dark` selectors.
- `golden_vector/serve/page_shell.py:73` renders `<html lang="en">` without the required `dark` class.
- `golden_vector/serve/static/css/base.css:3` sets `color-scheme: dark`, but that browser hint does not match or activate DataTables' `html.dark` selectors.

**Impact**

DataTables retains light-theme border, ordering, input, and interaction rules on dark application surfaces. Some borders and ordering/hover indications can therefore become visually incorrect or nearly invisible.

**Required correction**

Activate DataTables' supported dark theme at the document root, or fully and deliberately override every relevant DataTables rule with application tokens. The root-class solution is preferable while Golden Vector has one fixed dark theme.

**Regression coverage**

- Add a shell contract test that proves DataTables' dark-theme activation is present.
- Visually inspect at least one sortable table, including header borders and sorted-column state.

### GV-RD-CX-005 — Medium — Mobile drawer behavior and accessibility semantics disagree

**Evidence**

- `golden_vector/serve/page_shell.py:90-104` renders the navigation as a normal `<aside>` plus a non-semantic backdrop.
- `golden_vector/serve/static/workspace-shell.js:16-63` gives it modal-like behavior: visual backdrop, automatic focus movement, Escape handling, and a keyboard focus trap.
- The background is not excluded from assistive technologies, no modal relationship is announced, and there is no visible, focusable close control inside the drawer.

**Impact**

Keyboard behavior suggests a modal drawer, while screen readers continue to perceive the rest of the page as available. Touch, voice-control, and assistive-technology users also lack a clear close control within the drawer.

**Required correction**

Choose one coherent accessible pattern:

1. Treat the drawer as modal and add appropriate dialog/modal semantics, background exclusion, a visible close control, and correct focus restoration; or
2. Treat it as a non-modal navigation disclosure and remove modal-only behavior such as the backdrop/focus trap.

The visual design indicates that the first option is likely the intended behavior.

**Regression coverage**

- Test accessible open/closed state, the close control, Escape, focus containment, background exclusion, and focus restoration.

### GV-RD-CX-006 — Medium — The focused verification runner excludes the new redesign suites

**Evidence**

- `tests/tools/run_focused_selection.py:25-72` explicitly lists focused test files.
- It does not include `tests/test_design_tokens.py`.
- It does not include `tests/test_workspace_shell.py`.

**Impact**

The standard focused redesign gate can report success while every design-token or workspace-shell test is skipped. This creates false confidence at future phase gates.

**Required correction**

Add both suites to the focused selection and update any documented expected collection count. Keep the runner's stated contract synchronized with the tests it actually executes.

**Regression coverage**

- Add or retain a runner contract proving all redesign-critical suites are collected.
- Confirm the runner's collection output visibly includes both files.

### GV-RD-CX-007 — Low — Drawer-open state survives breakpoint changes

**Evidence**

- `golden_vector/serve/static/workspace-shell.js:12-29` stores the open state only through `data-nav-open`.
- There is no resize or `matchMedia` breakpoint-change handling that clears this state.

**Impact**

If a user opens the drawer on a narrow viewport, widens the browser to desktop size, and then narrows it again, the drawer unexpectedly reappears because the stale open attribute remains.

**Required correction**

Clear and normalize drawer state when crossing into desktop layout. Ensure `aria-expanded`, backdrop state, and focus state remain synchronized.

**Regression coverage**

- Add a breakpoint-change test covering mobile open → desktop → mobile.

## Focused verification after correction

Run the directly affected suites rather than the complete project suite:

```powershell
python -m pytest tests/test_design_tokens.py tests/test_workspace_shell.py tests/test_candidate_finder_page.py tests/test_lab_curve.py tests/test_workspace_datatables.py tests/test_redesign_routes.py tests/test_workspace_app.py
```

Also run the focused-selection command after adding the missing suites, plus linting for touched Python/test files. Perform one consolidated browser check at representative narrow and desktop widths, including a JavaScript-disabled navigation check and a sortable DataTable. Store the evidence in the existing redesign evidence location rather than returning large browser output to the conversation.

## Review conclusion

No application-logic, analytics, route, chart-data, or persisted-data-contract regression was identified in this review. The confirmed defects are isolated to the new visual shell, accessibility, palette application, third-party dark-theme integration, and verification coverage.

Codex made no source-code changes and did not rerun the already-green full suite during this review.
