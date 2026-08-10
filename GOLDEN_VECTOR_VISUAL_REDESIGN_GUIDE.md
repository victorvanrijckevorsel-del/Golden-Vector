# Golden Vector Visual Redesign — Starting Guide

## Purpose

This document is a lightweight handoff for a future Golden Vector redesign task.
It is a starting point for discussion and discovery, not a finished design
specification and not authorization to begin changing the interface immediately.

Optimade recently received a complete visual redesign. The result is more
professional, cohesive, readable, and consistent across the website. That work
should serve as inspiration for Golden Vector, while Golden Vector develops its
own identity as a serious gold-equities research and decision-support product.

The next task should begin by inspecting Golden Vector, discussing the desired
direction with Victor, and producing a project-specific plan before editing UI
code.

## Intended direction

Golden Vector should aim for a similarly polished and cohesive experience to
Optimade, but it should not be a direct visual copy.

The likely direction is:

- a professional dark interface built from layered near-black and charcoal
  surfaces rather than one flat black background;
- a restrained gold accent that gives Golden Vector its own identity;
- clear typography and hierarchy suitable for dense financial information;
- calm, consistent tables, charts, forms, explanations, filters, and status
  messages;
- strong readability and accessibility across desktop and smaller screens;
- a serious analytical character that helps the user trust and understand the
  data.

Gold should normally represent the product brand, navigation selection, or a
primary action. It should not automatically mean that a financial result is
positive. Positive, negative, warning, missing, stale, estimated, and verified
states need their own consistent semantic treatment.

The exact palette, typography, component appearance, navigation design, and
screen density should be decided in the new task after reviewing the existing
application with Victor.

## What was done successfully in Optimade

The useful lesson from Optimade is the method, not only its colours.

1. The full website was inventoried so that every route and unusual surface was
   included in the redesign.
2. Global visual decisions were moved into one canonical design-system source
   of truth: colours, typography, spacing, shape, elevation, control sizes,
   layout widths, motion, layers, status colours, and chart colours.
3. Repeated interface patterns were turned into shared components and page
   templates instead of being redesigned independently on every page.
4. The application shell and navigation established one consistent frame for
   the whole product.
5. Pages were migrated in a controlled sequence, using representative pages to
   validate the system before applying it everywhere.
6. Design exceptions were explicit and limited. New local colours, typography
   scales, and duplicated styling were discouraged or automatically checked.
7. The final result was reviewed holistically for route coverage, responsive
   behaviour, accessibility, loading and error states, and preservation of the
   existing functionality.

Golden Vector should follow the same general method.

## Golden Vector context to preserve

Golden Vector is not a conventional marketing website. It is a local,
Python-based analytical workspace for gold-equities research. Its current
product surfaces include Candidate Finder, Gold Sensitivity, Corporate Finance,
Gold Downside, Corporate Resilience, Option Trading, Portfolio, Lab, Scorecard,
ticker detail views, tables, charts, help explanations, and data-entry forms.

The existing presentation is primarily organized through:

- `golden_vector/serve/page_shell.py` for the shared page shell and navigation;
- `golden_vector/serve/static/workspace.css` for the main visual styling;
- the page renderers under `golden_vector/serve/`;
- shared JavaScript helpers under `golden_vector/serve/static/`.

These are useful starting points for the future audit. They do not by themselves
define the final redesign architecture.

The redesign must preserve Golden Vector's analytical strengths: dense but
explainable information, visible source and freshness information, missing-data
states, verified versus estimated values, comparison workflows, and clear
distinction between different models and assumptions.

## Non-negotiable functional boundary

This project is a visual and usability redesign. It must not silently change:

- calculations, formulas, rankings, thresholds, or financial interpretations;
- data pipelines, persisted artifacts, model-state logic, or refresh behaviour;
- routes, query parameters, filters, sorting, forms, or user workflows;
- data provenance, freshness checks, warning logic, or missing-data handling;
- backend contracts or tests that protect analytical correctness.

Layout, navigation presentation, colour, typography, spacing, component styling,
responsive behaviour, and visual hierarchy may change after they are discussed
and planned. If a visual improvement appears to require a behavioural or data
change, that must be treated as a separate product decision.

## Centralization principle

The redesign should centralize as many reusable decisions as practical.

Golden Vector should have one clear source of truth for its design tokens and
shared styling. Pages should consume shared decisions rather than introducing
their own palettes, font sizes, status meanings, buttons, cards, table styles,
or spacing systems. Shared rendering patterns should be reused across related
screens instead of being copied into each Python page renderer.

The future implementation plan should also consider a lightweight consistency
check so that new raw colours, duplicated design tokens, or undocumented visual
exceptions do not gradually fragment the interface again.

## Recommended beginning for the new task

The new Golden Vector task should:

1. Read the repository guidance and this document.
2. Inspect the current interface and identify every user-facing route and
   special surface.
3. Discuss Golden Vector's own visual identity with Victor, using Optimade only
   as a quality reference.
4. Agree on the main design principles and functional boundaries.
5. Propose a centralized design-system structure and shared component strategy.
6. Create a route-coverage matrix and a phased implementation plan.
7. Review that plan with Victor before changing the interface.

The redesign itself should happen in that new task, not as part of this handoff.

## Suggested prompt for the new Golden Vector task

> Read `AGENTS.md`, `CLAUDE.md`, `README.md`,
> `docs/golden_vector_architecture_map.md`, and
> `GOLDEN_VECTOR_VISUAL_REDESIGN_GUIDE.md`. I want to redesign the complete
> Golden Vector interface while preserving all calculations, data behaviour,
> routes, forms, and workflows. Use the Optimade redesign as a quality and
> process reference, but give Golden Vector its own professional dark-and-gold
> analytical identity. First inspect the existing UI and discuss the direction
> with me. Do not start implementation until we have reviewed and agreed on a
> thorough, centralized plan.

## Success at this starting stage

This guide has done its job if the next task begins with the right context,
avoids premature implementation, treats the whole product consistently, and
creates a Golden Vector-specific redesign plan without changing analytical
behaviour.
