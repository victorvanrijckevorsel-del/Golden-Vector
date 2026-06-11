# Plan — Option Trading Program: Carry-Forward Fallback · Liquidity Clarity · Horizon Redesign · Explanations

> **Status (2026-06-11):** Reviewed + restructured by Claude. Milestone A (carry-forward) is
> APPROVE WITH CHANGES, changes applied in place. Codex's two appended addendums (liquidity
> clarity, horizon redesign + site-wide explanations) have been **folded into milestones B/C/D**
> below instead of loose end-sections, with a dedicated horizon **blast-radius** analysis.
> Full carry-forward findings + file:line evidence: `reviews/codex/claude_review_option_snapshot_fallback_plan.md`.

## Changelog (2026-06-11 v3, Claude — Milestone C amended per Codex program review)

- **A + B + D1 are SHIPPED** (main `a2b5a65`), including the gold-dial merge, three post-merge
  semantic fixes, and a passed live smoke test. Milestone C is now the active front.
- **Milestone C amended to buildable** per `codex_review_option_program_plan.md`: candidate vs
  signal horizon policies split (signal = explicit 90d knob, never per-ticker most-liquid);
  optionability re-keyed to a core-horizon subset; history migration decided (long-form +
  backfill + `LIMITED_HISTORY`, covering the separate history store the artifact gate misses);
  `OptionTradingRow.*_60d` renamed during the schema bump; concrete side-aware most-liquid
  selector contract in `hedge/option_horizon_selection.py`; LEAPS = named ~450–650 DTE band;
  CF presets switch to benchmark-relative `skew_residual_signal`; blast radius extended with the
  five non-web 60d consumer modules; C5 resolved as bounded acceptance with a persist trigger.
  All ten decisions (6 original + 4 added) are resolved in the Decisions table.

## Changelog (2026-06-11, Claude restructure)

- **Reframed** the document from a single fallback plan into a 4-milestone option-area program
  (A carry-forward, B liquidity clarity, C horizon redesign, D explanations). The carry-forward
  content is unchanged below; it is now **Milestone A** and still ships first (it is the real
  production bug from 2026-06-11).
- **Folded** the "Cached Liquidity Check Clarity" addendum into **Milestone B** as concrete
  backend phases, grounded in the actual median code (`option_artifact_builder.py:350-356`):
  the three tier counts already exist per row, so "tradable-only medians, keep counts" is a tight
  backend filter. Resolved two open points: **all four** medians (incl. near-spot depth) are
  tradable-only, and a **dash/None** path renders when a group has watch/no-trade but zero tradable.
- **Folded** the "Option Horizon Redesign" addendum into **Milestone C**, and added a first-hand
  **Horizon Blast Radius** map. Key correction to the addendum's framing: this is **not** a
  default-switch. The requested 180d / ~230d / 18-month LEAPS horizons sit **outside** the current
  hardcoded 45–150 DTE signal band, and the option page is centered on 60d through **four divergent
  horizon sources** plus a stored 60d/90d history schema. C is split into **C1–C5** sub-chunks and
  flagged as its own milestone that should **not** be bundled with A.
- **Folded** the "Site-Wide Explanations" addendum into **Milestone D**. Found the hover CSS already
  exists and Candidate Finder already has per-column metadata to seed a registry, but tables are
  ~7 bespoke hand-written header blocks with no shared renderer. Proposed split: **D1** (mechanism +
  Option Trading first adopter) then **D2** (rollout to Tool D and the rest). D1 is a prerequisite
  for B's config-sourced "Tradable" tooltip and C4's horizon-qualified labels.
- **Coherence:** confirmed no contradiction with the carry-forward amendments. The freshness **banner**
  (Milestone A) and the column-**tooltip** registry (Milestone D) are different surfaces that share the
  same "backend owns the text/thresholds, serve only renders" rule. One manifest with freshness
  domains is unchanged. The horizon schema bump (C2) composes with carry-forward via the existing
  schema-version → `UNAVAILABLE` downgrade (A test 8).
- **Added** consolidated "Decisions needed from Emanuel/Codex" — the redesign has 6 real forks
  (signal horizon, history-schema migration, most-liquid aggregation policy, LEAPS band, the
  `OptionTradingRow` rename, and the serve-side scenario recompute) that should be settled before C.

## Milestone Map

| Milestone | Scope | Size | Depends on | Ship order |
|---|---|---|---|---|
| **A — Carry-Forward Fallback** | Stop a bad option snapshot from blocking the whole publish; carry forward last good option artifacts; freshness banner | Medium (reviewed) | none | **1st (production bug)** |
| **B — Cached Liquidity Check Clarity** | Tradable-only medians (keep Tradable/Watch/No-trade counts); header renames | Small (backend + labels) | D1 only for the *config-sourced* Tradable tooltip | After A; data change anytime |
| **C — Option Horizon Redesign** | Config-driven horizons incl. long-dated + LEAPS; backend "Most liquid" default; show real expiry dates; de-60d the backend, stored schema, and serve | **Large — own milestone, C1–C5** | A shipped; ideally after D1 | After A (own track) |
| **D — Site-Wide Hover/Explanation Layer** | Shared header-tooltip mechanism reading thresholds from config; row-level skew hover; rename vague labels; rollout | Medium, phased D1→D2 | none for D1 | D1 early (cheap, unblocks B+C labels) |

**Recommended sequence:** A (bug) → D1 (cheap mechanism, unblocks tooltips/labels) → B (small, uses D1)
→ C in sub-chunks C1…C5 → D2 rollout (opportunistic). A, B, D1 are each a few-day chunk; C is multi-week.

---

## Milestone A — Option Snapshot Carry-Forward Fallback (ship first)

> All sections from here through "Review Questions — Answered" are Milestone A. They are unchanged
> from the reviewed carry-forward plan; only the heading above was added. Milestones B/C/D follow.

## Problem

The current refresh behavior is too strict for option data.

On 2026-06-11 around 11:42 London time, `python main.py refresh` reached the option-artifact step and stopped with:

```text
Option signal benchmark rows are not publishable (GDX=SPARSE; GDXJ=LOW_LIQUIDITY);
keeping the previous complete model state.
```

This happened before the US options market was open. Yahoo option chains can exist pre-market, but bid/ask, volume, open-interest updates, and ETF benchmark liquidity can be incomplete or stale. The option-signal gate in `golden_vector/hedge/option_signals.py` correctly refused to publish sector-relative signals when GDX/GDXJ were not reliable.

The problem is not the quality gate itself. The problem is that one bad market-hours-dependent option snapshot blocks the whole current-state publish. Tool A/B/C/D may have fresh data, but the model-state manifest remains old because option signals failed. For a user, that feels like "refresh failed" even though most of the system refreshed correctly.

Two verified code facts sharpen this (see review doc for line numbers):

- The blocker exit in `run_option_artifacts` happens **before** any artifact is persisted, so on a blocked day the disk still holds the previous good run-stamped option artifacts, their latest aliases, and the previous manifest with their paths and sha256 hashes. The carry-forward source already exists on disk.
- A blocked option step also aborts the **portfolio** step (it runs after option-artifacts in the refresh order) and the manifest publish. Fixing this un-blocks portfolio publication too.

## Product Behavior We Want

When the user opens Option Trading outside US option market hours:

- use the latest good stored option artifact, usually yesterday's market-hours snapshot;
- show a small, clear freshness box: "Option prices are from the latest stored snapshot: 2026-06-10. US options are currently closed.";
- do not pretend those prices are live;
- keep Tool A/B/C/D and Candidate Finder usable with fresh core analytics;
- if no valid option snapshot exists, show "option data unavailable" rather than blocking the whole app.

## Current Code Facts

- `golden_vector/cli.py::run_option_artifacts` builds option artifacts as the final refresh step.
- It calls `build_option_signal_artifacts(...)`.
- If `option_signals.publish_blockers` is non-empty, it returns exit code `1` and the full refresh refuses to publish the model-state manifest.
- The blocker is produced by `_publish_blockers(...)` in `golden_vector/hedge/option_signals.py`.
- The Option Trading reader already reads persisted option artifacts through the model-state manifest in `golden_vector/serve/option_trading_data.py`.
- Current persisted option artifacts include:
  - `option_contract_metrics`
  - `option_liquidity_measurements`
  - `option_candidate_slots`
  - `option_selected_candidates`
  - `option_trading_overview`
  - `candidate_finder_inputs`
  - `option_signal_summary`
  - `option_skew_curve_points`
  - `option_oi_strike_points`
  - `option_signal_history_points`

## Architecture Decision

Keep one model-state manifest, but split freshness into two domains:

1. **Core analytics domain**
   - Foundation, Tool A, Tool B, Tool C, Tool D, portfolio artifacts.
   - Must remain coherent within one refresh identity.
   - A failed core stage still blocks publish.

2. **Market-hours option domain**
   - Option candidate artifacts, option signal artifacts, option charts.
   - May be carried forward from the latest good option snapshot when live option data is unavailable or non-publishable.
   - Must be clearly labeled as carried-forward/stored, never live.

This keeps the data-spine rule intact: readers still resolve through the manifest, and serve still reads persisted artifacts only. The difference is that the manifest is allowed to reference an older immutable option artifact while also recording that the option domain is stale/carried-forward.

Do **not** make the UI scan old `latest` files directly. The fallback must be resolved and recorded by the backend/publish layer.

### Alignment integration (the linchpin — added by review)

The existing manifest builder compares the required option artifacts' `snapshot_refresh_run_id`
against **today's** options ingestion manifest run id (`model_state.py::_alignment`). Carried-forward
artifacts carry yesterday's run id, so without a change every carried-forward publish becomes
`alignment: WARN` → `state: incomplete`. Both Candidate Finder (`candidate_finder_data.py::_alignment`)
and the ticker report (`report.py::_context_alignment`) treat the manifest alignment verdict as
**authoritative when present** — they would show scary "X references run A while options is run B"
warnings right next to our calm freshness box.

Required behavior under `CARRIED_FORWARD`:

- `_alignment` validates the carried option artifact set against its **own** source run id
  (self-consistency within the carried set is still checked — a mixed or tampered set still warns);
- it emits **no** option-vs-today mismatch warnings;
- `alignment.status` stays `OK` and `state` stays `complete` when everything else is healthy;
- the carried-forward fact lives in `freshness_domains` plus one informational manifest warning line
  (worded so it does not match `_is_required_health_warning` patterns).

Because both consumers already defer to the manifest verdict, they stay calm with **zero changes**
to their authoritative-path logic. Under `UNAVAILABLE`, `state` stays `incomplete` (truthful: required
option artifacts are missing) and pages prefer the `freshness_domains` message over generic fallbacks.

The pruning system needs no changes: run pruning already protects every artifact path referenced by
every retained model-state manifest, so a manifest that references older option files automatically
protects them (regression test added in Phase 7).

## Proposed Model-State Additions

Add an optional `freshness_domains` section to the model-state manifest:

```json
{
  "freshness_domains": {
    "core": {
      "status": "OK",
      "as_of_date": "2026-06-11"
    },
    "option_artifacts": {
      "status": "CARRIED_FORWARD",
      "source_run_id": "20260610T150000Z-option-artifacts-...",
      "as_of_date": "2026-06-10",
      "reason": "Benchmark quotes were not publishable at refresh time.",
      "market_session": "CLOSED",
      "blockers": ["GDX=SPARSE", "GDXJ=LOW_LIQUIDITY"]
    }
  }
}
```

Naming notes (from review):

- The domain key is `option_artifacts`, not `options` — `artifacts.options` already means the options
  **ingestion manifest**, which IS fresh on a carried day (chains were fetched; quotes were stale).
  Reusing the name would be ambiguous.
- `core.parent_refresh_id` was dropped — the top-level `parent_refresh_id` already records it.
- `source_run_id` and `as_of_date` come from the carried artifact entries themselves (each option
  artifact frame embeds `options_as_of_date` and run ids at build time), so a multi-day chain keeps
  the original values instead of drifting.
- `market_session` is `OPEN | CLOSED | UNKNOWN` from the existing `market_hours_refresh_decision`
  helper, recorded as context only (see Phase 3 / Q5).
- No `MODEL_STATE_MANIFEST_VERSION` bump needed: the field is additive and the version is written but
  never read-gated anywhere.

The existing `artifacts` map should continue to point to immutable run-stamped files. For carried-forward option artifacts, it points to the previous good option artifact files (re-verified at publish time) and each entry gains `carried_forward: true` plus the source run id so the UI and audits can label them.

## Milestone A — Implementation (Phases 1–7)

> Cross-references elsewhere in this doc say "A Phase 4" / "A test 8" → they point at these phases.

### Phase 1 — Define Option Freshness Contract

Create a small backend contract for option artifact freshness.

Manifest-level statuses (what `freshness_domains.option_artifacts.status` can say):

- `OK`: option artifacts were rebuilt from current refresh inputs and passed publish gates.
- `CARRIED_FORWARD`: current refresh could not publish option artifacts, so the manifest reused the latest prior valid option artifacts.
- `UNAVAILABLE`: no valid prior option artifacts exist.

`FAILED` is **not** a manifest status (changed by review): a hard failure (code/schema error, missing
required local inputs) aborts the refresh before any manifest is written, so a published manifest can
never carry it. `FAILED` remains a run/CLI outcome recorded in the run context.

Store in the domain block:

- option artifact source run id;
- option snapshot date from the carried artifacts (they embed `options_as_of_date`);
- market/session status from the existing `market_hours_refresh_decision` helper (context only);
- publish blockers;
- human-readable reason.

### Phase 2 — Resolve Latest Good Option Snapshot (mostly existing machinery)

Nothing needs to be "preserved" — on a blocked day the previous good artifacts are already on disk
and the previous manifest already records their immutable paths, sha256 hashes, schema versions, and
row counts (the manifest builder computes these on every publish). The resolver is therefore a small
set of functions in `app/model_state.py` (Q4 answered: not a new module, not `hedge/`), following the
existing precedent of `cli.py::_previous_option_contract_metrics` which already reads "the previous
good artifact" through `resolve_current_model_artifact_path`.

Rules:

- Source of truth: the option artifact entries of the previous current model-state manifest
  (loaded via the existing `load_current_model_state_manifest` **before** the new manifest overwrites it).
- Re-verify each entry at publish time: path exists, is immutable/run-stamped, sha256 matches the
  recorded hash, `schema_version` equals the current `OPTION_ARTIFACT_SCHEMA_VERSION`.
- **All ten** `OPTION_ARTIFACT_NAMES` must verify and share one source run (Q2 answered): the serve
  reader requires all ten to resolve through the manifest or it fails loud, and one build persists
  all ten atomically, so this is both necessary and free. The four `REQUIRED_OPTION_ARTIFACT_NAMES`
  must additionally be non-empty; chart artifacts may be empty-but-present.
- Anything less than a fully verified set → `UNAVAILABLE`. Never a partial carry.
- Do not fall back to mutable `*_latest.parquet` as authority. With no previous manifest at all
  (bootstrap), the answer is `UNAVAILABLE`, not an alias scavenge.
- A previous manifest whose overall `state` is `incomplete` for non-option reasons can still donate
  its option entries if they verify (per-artifact usability, not global state, decides).

### Phase 3 — Change Refresh Publish Semantics

Update `run_option_artifacts` / refresh orchestration:

- The build step returns a **structured outcome** — `OK`, `BLOCKED(blockers, options_as_of)`, or
  `FAILED` — instead of the orchestrator inferring meaning from a bare exit code. Exit codes are
  mapped only at the CLI boundary. Classification is by code path, never by parsing blocker strings:
  `BLOCKED` is precisely "the build succeeded and `option_signals.publish_blockers` is non-empty"
  (Q3 answered: every data-quality verdict — `SPARSE`, `LOW_LIQUIDITY`, `STALE_QUOTES`,
  `NO_BENCHMARK`, missing benchmark rows — is carry-forwardable; they all mean "market data is not
  good enough right now"). Missing options manifest, exceptions during build/persist, and schema
  corruption remain `FAILED`.
- `OK`: persist new option artifacts normally and publish `option_artifacts.status = OK`.
- `BLOCKED`: do **not** fail the refresh. Persist nothing for options (today's behavior — this also
  means option signal **history is not appended** on blocked days, which a Phase 7 test pins down).
  Continue to the portfolio step, then publish the manifest with the carried-forward set from
  Phase 2 and `option_artifacts.status = CARRIED_FORWARD`.
- `BLOCKED` with no resolvable prior set: publish core state with
  `option_artifacts.status = UNAVAILABLE` and option artifact entries absent.
- `FAILED`: keep today's hard-stop behavior — no manifest publish, previous manifest stays current.
- The standalone `option-artifacts` CLI command keeps a non-zero exit code when blocked (it publishes
  no manifest, so there is nothing to carry forward there); its message already says the previous
  state remains current.

Important: this must be backend-driven. The serve layer should not decide which artifact to use.

Market hours (Q5 answered): always attempt, then classify. The option-artifact step is pure local
compute — chains were already fetched by update-data — so attempting costs seconds and the blockers
are ground truth. A calendar gate can false-skip (half-days, holiday drift, a fine 09:50 ET snapshot)
and can never know quote quality. Use `market_hours_refresh_decision` only to enrich the recorded
reason and user-facing message; scheduled runs are already time-gated by the separate
`market-hours-refresh` command.

### Phase 4 — Option Trading UI Freshness Box

Add a small freshness box at the top of Option Trading and ticker option detail pages.

Examples:

Fresh:

```text
Option data refreshed from today's market snapshot: 2026-06-11 15:05 New York time.
```

Carried forward, when `market_session = CLOSED` at refresh time:

```text
Option prices are from the latest stored snapshot: 2026-06-10.
US options were closed at refresh time, so live option quotes were not refreshed.
```

Carried forward, when the market was open or unknown (honesty rule from review — never claim
"market closed" unless the recorded `market_session` says so; the blockers alone cannot prove it):

```text
Option prices are from the latest stored snapshot: 2026-06-10.
Today's option-signal refresh was skipped because GDX/GDXJ benchmark quotes were not publishable.
```

Unavailable:

```text
Option data is not available yet. Run a refresh during US options market hours.
```

The UI must not compute market-hours logic or freshness status. It only renders the backend-provided status/message.

One shared backend formatter builds the status/message from `freshness_domains` — used by the Option
Trading page, the ticker option detail lens, Candidate Finder, and `python main.py status`. Four
hand-rolled copies of this text is exactly the divergent-logic trap we avoid.

### Phase 5 — Candidate Finder Integration

Candidate Finder currently consumes `candidate_finder_inputs` from option artifacts for optionability/options-related criteria.

Rules:

- If options are `OK`, use current option-derived fields.
- If options are `CARRIED_FORWARD`, use carried-forward option-derived fields but show a screen-level note (via the shared formatter), worded as informational, not as an error.
- If options are `UNAVAILABLE`, option-specific filters should show unavailable/disabled behavior, while non-option screens still work.
- The Bull/Bear presets should remain usable; option-dependent criteria should be clearly marked if carried forward.

Integration note (from review): Candidate Finder's `_alignment` and the ticker report's
`_context_alignment` both defer to `summarize_model_state_alignment` when it returns a verdict, and
only run their own run-id comparisons as a fallback. With the Phase 2/3 alignment handling in
`model_state.py`, both stay calm under carry-forward with **no changes to their comparison logic** —
the work here is only (a) reading `freshness_domains` for the note, and (b) the `UNAVAILABLE`
disabled-filter behavior. Files: `serve/candidate_finder_data.py`, `serve/candidate_finder_page.py`,
`serve/option_trading_data.py`, the option page/detail lens, and `hedge/report.py` only if its
displayed context should show the carried-forward note too.

### Phase 6 — Diagnostics for Blocked Option Refreshes

No new diagnostic file (changed by review): `run_context.finalize` already records
`option_signal_publish_blockers` on blocked runs. Enrich that existing run-context summary payload
with:

- per-benchmark data quality label and reason;
- signal contract count;
- quote coverage;
- tradable signal count;
- publish blockers;
- refresh time;
- `market_session` (open/closed/unknown) from the existing helper.

Run-context files are already retained/pruned by existing policy. This is for debugging and
threshold tuning. It should not become a user-facing ranking input.

### Phase 7 — Tests

Add tests that prove:

1. A fresh option-artifact build with OK benchmark rows publishes as `option_artifacts.status = OK`.
2. A benchmark failure with a previous good option artifact carries forward those exact immutable paths (sha256-identical entries).
3. A benchmark failure with no previous good option artifact (no manifest at all, AND manifest without usable option entries) publishes core state with `option_artifacts.status = UNAVAILABLE`; core tools and portfolio still publish; only the option surfaces show the unavailable message.
4. The Option Trading page renders the carried-forward freshness box.
5. The detail option lens renders the same freshness status.
6. Candidate Finder can load with carried-forward option inputs and shows the informational note.
7. Serve code does not read mutable option latest files directly.
8. Schema corruption in carried-forward artifacts fails loud rather than silently falling back; a bumped `OPTION_ARTIFACT_SCHEMA_VERSION` downgrades to `UNAVAILABLE` at publish time instead of publishing a manifest the reader will reject.
9. The refresh status page distinguishes:
   - core current;
   - options current;
   - options carried forward;
   - options unavailable.

Added by review:

10. Multi-day chain: two consecutive blocked refreshes keep the original `source_run_id` and `as_of_date` (no drift), and the second publish re-verifies sha256.
11. Same-day chain: a successful morning refresh followed by a blocked afternoon refresh carries the **morning** artifacts (carry-forward sources from the previous manifest, not "yesterday").
12. Under `CARRIED_FORWARD`, `alignment.status` stays `OK`, `state` stays `complete`, and neither Candidate Finder nor the ticker report emits run-id mismatch warnings.
13. A blocked build appends **nothing** to option signal history.
14. Run pruning never deletes option artifact files referenced by a retained carried-forward manifest.
15. A previous manifest that is `incomplete` for a non-option reason still donates its verified option entries.
16. A blocked refresh still runs and publishes the portfolio step.

## What Not To Do

- Do not loosen GDX/GDXJ quality thresholds just to make refresh pass.
- Do not show stale option prices as live.
- Do not read old option `latest` files directly from serve.
- Do not let option-signal failure block Tool A/B/C/D publication when a prior valid option snapshot exists.
- Do not add a second vendor in this plan.
- Do not rebuild option candidate-selection rules in this plan.
- Do not classify blocked-vs-failed by parsing blocker message strings — classify at the source (build succeeded + `publish_blockers` non-empty).
- Do not carry forward a partial artifact set — all ten names from one source run, or `UNAVAILABLE`.
- Do not use market-hours detection to gate the build — context for messages only.

## Acceptance Criteria

- Opening Option Trading before US options market open shows the latest stored option snapshot with a clear freshness box.
- A full refresh before US options market open still updates core analytics, runs the portfolio step, and publishes a current model-state manifest.
- The manifest records that the option domain is carried forward and why; `state` stays `complete` and no run-id mismatch warnings appear anywhere in the app.
- Option Trading and Candidate Finder continue to read through the manifest.
- If no prior option snapshot exists, the app shows a calm unavailable state rather than a generic failure.

## Review Questions — Answered (Claude, 2026-06-11)

Full reasoning with file:line evidence in `reviews/codex/claude_review_option_snapshot_fallback_plan.md`.

1. **One manifest with freshness domains.** Every reader already resolves through this single
   manifest; pruning protection is derived from retained manifests, so a separate options pointer
   would need its own protection plumbing; and the alignment summarizer both tools treat as
   authoritative reads this manifest. A second pointer reintroduces split-brain.
2. **All ten `OPTION_ARTIFACT_NAMES`, from one source run.** The serve reader requires all ten to
   resolve or it fails loud, and one build persists all ten atomically, so this is necessary and
   free. The four `REQUIRED_OPTION_ARTIFACT_NAMES` must additionally be non-empty; charts may be
   empty-but-present. Anything less → `UNAVAILABLE`.
3. **All data-quality labels are carry-forwardable** — `SPARSE`, `LOW_LIQUIDITY`, `STALE_QUOTES`,
   plus `NO_BENCHMARK` and the missing-benchmark-rows case. They are all "market data is not good
   enough right now" verdicts; none indicates code damage. Hard failures (missing options manifest,
   exceptions, schema corruption) keep aborting the publish. Classify by code path, not by string.
4. **`app/model_state.py`.** Carry-forward is manifest-to-manifest logic, and that module already
   owns previous-manifest loading, immutable/usable resolution rules, sha256 helpers, `_alignment`,
   and the publish path. A new module would split the manifest brain; `hedge/` is build-input
   territory, the wrong layer for publish decisions.
5. **Always attempt, then classify.** The build step is local compute (chains were already fetched
   by update-data); blockers are ground truth; calendar gates can false-skip and cannot know quote
   quality. Use `market_hours_refresh_decision` only to enrich the recorded reason and the freshness
   message. Scheduled runs are already time-gated by the `market-hours-refresh` command.

## Milestone B — Cached Liquidity Check Clarity

**Goal.** The "Cached Liquidity Check" table mixes two ideas: coverage diagnostics across all
measurable contracts, and practical liquidity for contracts a user might actually trade. Split them:
keep the count breakdown (Tradable / Watch / No-trade) over *all* measured contracts, but compute the
median spread / OI / volume / near-spot-depth across **tradable contracts only**.

**Why this is small (first-hand code facts).** `build_option_liquidity_measurements`
(`option_artifact_builder.py:301-358`) already collects every usable-quote contract into `rows`,
already attaches `liquidity_tier` per row (`:323`), and already emits the three counts via
`_tier_count` (`:354-356`). The four medians (`:350-353`) are simply computed over *all* rows today.
So the change is a backend filter, not new analytics. Serve already renders the persisted dataclass
with no recompute (`overview_option_trading.py:135-171`).

### Phase B1 — Backend: tradable-only medians (own the math in the builder)

- In `build_option_liquidity_measurements`, derive `tradable_rows = [r for r in rows if r["liquidity_tier"] == "tradable"]`
  and feed the four `_median(...)` calls from `tradable_rows` (spread, OI, volume, **and** near-spot
  depth — all four, per Emanuel's decision; this resolves the agent's open question).
- Keep `contract_count` = measured (all rows) and keep `tradable_count` / `watch_count` /
  `no_trade_count` over all rows.
- **Empty-tradable path:** when a group has watch/no-trade rows but zero tradable, the four medians
  return `None`; the table renders a dash while the counts still show. Add this explicit None path
  (today `_median` already returns `None` on empty, so this is mostly a render assertion).
- This lives entirely in the backend builder (`hedge/`), honoring "backend computes, serve renders."

### Phase B2 — Render: column headers + hint text

- Columns (the render already has Group / Tickers / Measured Contracts / Tradable / Watch / No-trade /
  4 medians at `overview_option_trading.py:163-167`): rename the four median headers to
  **Median Tradable Spread / OI / Volume / Near-Spot Depth** so the table states what it now measures.
- Update the hint line (`overview_option_trading.py:158-162`) from "cached contracts with usable
  bid/ask/mid" to "medians across **tradable** contracts only; counts cover all measured contracts."
- The **"Tradable" header tooltip** (plain-English rule + the *actual configured thresholds*) is
  delivered by the Milestone D mechanism so the thresholds come from config, never hard-coded template
  text. If D1 has not landed when B ships, B may ship the data change + renames first and the
  config-sourced tooltip follows with D1 — do **not** hand-code threshold numbers into the template as
  a stopgap.

### Phase B3 — Tests

- Medians use `liquidity_tier == "tradable"` only; the three counts still include Tradable + Watch +
  No-trade. (Fixture with mixed tiers proves watch/no-trade rows move the all-rows counts but not the
  medians.)
- Empty-tradable group: medians render as dash, counts still populate.
- Serve does not recompute medians (asserts the dataclass values are passed through unchanged).
- (With D1) the "Tradable" tooltip renders configured thresholds from option policy, not literals;
  changing the threshold in a fixture changes the tooltip text.

**Owns the rule:** the tradable definition stays in `golden_vector/hedge/options_liquidity.py`
(`_liquidity_tier:892-909`) + option policy config. Serve never duplicates it. Note there are
**two** "tradable" definitions in the code — the chain-level `_liquidity_tier` (used by this summary)
and a stricter per-bucket slot rule (`_passes_slot_liquidity:638-657`, used by the candidate badge).
The Cached Liquidity Check and its tooltip document the **chain-level** rule; flag this distinction in
the tooltip so the two never get conflated.

## Milestone C — Option Horizon Redesign (own milestone, C1–C5)

**Product goal.** Stop assuming 60d is the primary option window. Make the horizon explicit,
user-selectable, liquidity-aware, and labeled by **real expiry date** (Emanuel prefers "Jan 15 2027"
over "~230d"). The page opens on a **backend-chosen "Most liquid"** expiry; the user can switch to any
configured horizon. Selectable set:

| Horizon concept | Purpose |
|---|---|
| 90d | Medium-term; often tighter spread than 60d. |
| 180d | Strategic window, broad coverage. |
| ~230d / most-liquid medium-long | Cached data shows this is often the best liquidity window. |
| Long-dated / LEAPS (~18mo) | Long-term thesis window when liquid enough. |

**Why this is a milestone, not a tweak — the blast radius.** The "60d-centered" page is held up by
**four divergent horizon sources** plus a hardcoded signal band and a stored 60d/90d schema. The new
horizons (180/230/LEAPS) sit **outside** today's 45–150 DTE signal band — which is why **candidate
horizons and signal horizons are split** (resolved design): candidate selection extends to
long-dated windows, while Signal/Activity/Cost stay on the explicit short/medium signal horizon.
The signal layer is parameterized, not generalized to LEAPS.

### Horizon Blast Radius (first-hand map, grouped by layer)

**1. Horizon sources that have already drifted apart (consolidate to one policy first).**

| Source | Today | Site |
|---|---|---|
| `target_horizons_days` (refresh) | `[60,90,120]` | `config_models.py:106`, `hedge_readiness.yaml:3` |
| `display_horizons_days` (serve) | `[60,90,120]` | `config_models.py:107`, `hedge_readiness.yaml:7` |
| `option_dte_bands` (band per horizon) | `{60:[40,74],90:[75,104],120:[105,150]}` | `config_models.py:155`, `hedge_readiness.yaml:53` |
| `DISPLAY_SIGNAL_HORIZONS` (module const) | `(60,90,120)` | `option_signals.py:22` |
| `band_for_horizon` in-code fallback dict | `{60,90,120}` | `options_liquidity.py:122-126` |
| Legacy fn defaults | `(30,60,90)` | `candidate_puts.py:94/135/338`, `features/options.py:22`, `option_trading.py:150/226` |

**2. Hardcoded 60d in the signal/overview backend (must be parameterized).**

- Direction signal is **only** the 60d residual: `direction_value = name_skews.get(60) … residuals.get(60)`
  (`option_signals.py:206`). Headline, direction-reason, cost all read `*_60d` (`:232,246-269,281-282`).
- Overview contract pins 60d in **field names**: `OptionTradingRow.iv_skew_60d / iv_rv_ratio_60d /
  pnl_put_at_minus10_60d / pnl_call_at_plus10_60d` (`option_trading.py:77-83`), driven by
  `OPTION_CONTEXT_SIGNAL_HORIZON_DAYS = 60` / `PREFERRED_OPTION_HORIZON_DAYS = 60` (`:29-30`), read
  back in `option_artifact_frames.overview_rows_from_frame:183-189`.
- Context PnL matches a candidate at the **exact** 60 integer slot (`option_trading.py:532,551-558`).
- Cross-sectional IV %ile uses `atm_iv_60d` (`options_phase.py:219`). `term_slope_30_90` reads
  `atm_iv_30d` which the live `[60,90,120]` config never produces — already silently `None`.

**3. Stored-schema 60d/90d (a data migration, not just code).**

- Signal **history** parquet columns are `skew_residual_60d`, `skew_residual_90d`, `atm_iv_60d`
  (`option_signals.py:56-63,306-316,718-728`), and IV-rank reads `atm_iv_60d` from history (`:706`).
  Changing the signal horizon requires either generic columns (`skew_residual_signal`/`atm_iv_signal`)
  with backfill, **or** an `OPTION_ARTIFACT_SCHEMA_VERSION` bump + history reset. **Decision needed.**

**4. Candidate-Finder coupling.**

- `candidate_finder_inputs` hardcodes `iv_skew_60d`, `iv_rv_ratio_60d`
  (`option_artifact_frames.py:30-43,240-263`) and `candidate_finder.yaml:152` scores on
  `source_field: iv_skew_60d`. Note CF uses the **name's own** skew (`put_iv−call_iv`,
  `features/options.py:138`), *not* the benchmark-relative residual the UI's "Skew Read" shows —
  decide whether to unify (see Decisions).

**4b. Live 60d consumers OUTSIDE the Option Trading web page (added per Codex review — the
original map under-counted).** These encode 60d semantics in production modules and would either
break on the C2 rename or keep showing stale 60d language; each is migrated or explicitly frozen:
`hedge/sensitivity_ranking.py` (:20-22, :34-36, :140-143, :173-181), `hedge/portfolio_totals.py`
(:32, :158-159, :259-265, :311-319), `hedge/header_context.py` (:35-40, :178-188, :227-244),
`hedge/report.py` (:507-517, :580-599, :733-737), `hedge/speculation_section.py` (:22, :31-32,
:174-179), plus `features/options.py` (:22, :143, :155).

**5. Serve render sites still pinned to 60d.**

- Overview "Skew Read" cell → `option_signal_skew_display_value(signal)` default `horizon=60`
  (`option_signal_render.py:26`, called `overview_option_trading.py:197`).
- Skew overlay loops a **literal** `(60,90,120)` (`detail_panels.py:343`) — not config-driven.
- Signal-history chart hardcodes `*_60d` columns + "60d" labels (`option_signal_charts.py:143-261`).
- Horizon default in serve: `default_horizon = 60 if 60 in target_horizons else target_horizons[0]`
  (`option_trading_data.py:311`) — this is exactly where the **backend "Most liquid" default** must hook.

**6. What already works in our favor (de-risks C).**

- Feature computation is **already horizon-parameterized** (`compute_options_features` loops
  `target_horizons_days`; `nearest_expiration(frame, horizon)` picks the nearest listed expiry).
- Candidate slots already iterate `display_horizons_days` and key by `(horizon, expiration, strike,
  type)` — adding horizons auto-produces slots **if** `option_dte_bands` has matching entries.
- **Expiry dates are persisted end-to-end** (`OptionContractMetrics.expiration`,
  `OptionCandidateSlot.expiration`) — "show Jan 15 2027" is render-only.
- The **skew-tooltip data already persists** per horizon (`name_skew_{h}d`, `sector_skew_{h}d`,
  `skew_residual_{h}d`, `benchmark_symbol`) — Milestone D's row hover needs no new field.
- Every input a "most-liquid expiry" ranker needs (per-contract `liquidity_score`, OI, volume,
  `rel_spread`, `near_spot_depth_count`, tier, expiration, dte) **already persists** in
  `option_contract_metrics`. The selection logic is new; the data is not.

### Sub-chunks (build in this order)

**C1 — Consolidate horizon config (foundational, low-risk ratchet; no behavior change).**
Introduce **two** linked policies in config (amended per Codex review — candidate and signal horizons
are different products and must not be conflated):

- `candidate_horizon_policy`: the selectable expiry windows for trade candidates
  (targets + DTE bands + a `default = "most_liquid"` flag). This is what grows to 90/180/~230/LEAPS.
- `signal_horizon_policy`: one explicit `option_signal_horizon_days` driving Signal / Activity /
  Cost / IV-rank. Stays **short/medium (90d in v1)** — an 18-month skew is sparse, rolls slowly,
  and has no history; long-dated *signals* are a separate research question, not part of C.

Also decide **optionability semantics now** (Codex HIGH): `directly_hedgeable` currently requires a
25-delta put estimate at **all** configured target horizons (`features/options.py:223-228`) — with
LEAPS in the set, most names would silently degrade to `thin`. Change to a configured
`core_optionability_horizons` subset (v1: 90/180) or a minimum-coverage count, never "all selectable
horizons". Make `DISPLAY_SIGNAL_HORIZONS`, the `band_for_horizon` fallback dict, and every legacy
`(30,60,90)`/`(60,90,120)` default **derive from config**. Keep live values `[60,90,120]` +
`signal_horizon=60` in this chunk so nothing changes yet. (Golden Vector rule #2: horizons only via
centralized config.)

**C2 — De-60d the signal/feature/history layer (the stored-schema chunk).**
Parameterize the direction/headline/cost/IV-rank reads off `option_signal_horizon_days` (not literal
60). **Rename the `OptionTradingRow.*_60d` persisted fields during the schema bump** (decided —
no parallel old/new forever): `signal_horizon_days`, `iv_skew_signal`, `iv_rv_ratio_signal`,
`pnl_put_at_context`, `pnl_call_at_context` + context horizon/expiry metadata; update
`_build_overview_row` + `overview_rows_from_frame` + render together. **History migration (decided —
long-form, not reset):** the append-only `option_signal_history.parquet` (a separate local store,
NOT covered by the artifact schema gate — Codex HIGH) moves to long format
(`ticker, as_of_date, signal_horizon_days, skew_residual, atm_iv, iv_rv_ratio, benchmark_symbol,
quote_snapshot_run_id`) with a one-time backfill from the existing `skew_residual_60d/90d` +
`atm_iv_60d` columns; IV-rank reads the new shape filtered to the signal horizon, and shows
`LIMITED_HISTORY` calmly while the 90d series fills. Fix `iv_percentile_cross_sectional` to the
signal horizon; **remove `term_slope_30_90`** (reads `atm_iv_30d`, which the live config never
produces — already silently None; removing beats keeping a dead column). **Bump
`OPTION_ARTIFACT_SCHEMA_VERSION`.** Composes with Milestone A: old-schema carried artifacts
downgrade to `UNAVAILABLE` (A test 8). Also sweep the **full 60d consumer list** (Codex HIGH —
migrate or explicitly freeze): `hedge/sensitivity_ranking.py`, `hedge/portfolio_totals.py`,
`hedge/header_context.py`, `hedge/report.py`, `hedge/speculation_section.py` — each either reads the
renamed signal fields or is declared frozen/retired in the C2 commit message; no silent stale-60d
text may survive.

**C3 — Add the long-dated horizons + "Most liquid" selector (new backend logic).**
Add 180/230/LEAPS to config. **LEAPS is a named band, not open-ended:** start ~450–650 DTE
(per Codex's read of cached coverage; 1y-ish single-stock coverage is weak — only add a 1y band if
data later supports it). **Selector contract (decided, per Codex's concrete recommendation):**

- Lives in backend `hedge/option_horizon_selection.py`, runs during the option-artifact build after
  `option_contract_metrics` exists; serve only reads the stamped result.
- Evaluates **only configured horizon windows** (never whole-chain), per ticker × side × window ×
  expiry, filtered to `liquidity_tier == "tradable"` with valid mid/rel_spread — reusing Milestone
  B's `aggregate_tradable_liquidity` primitive, never a second liquidity summary.
- Scores an expiry with **robust aggregates, not raw sums** (a sum rewards one ticker with many
  contracts): unique tradable contract count, median tradable spread (lower better), median OI,
  median volume, median near-spot depth; standard-monthly flag and DTE-distance-in-window as
  tie-breakers only.
- **Defaults are side-aware and scoped:** overview default = group-level over single-stock miners
  with per-ticker normalized scores (so GDX/GDXJ can't dominate); ticker detail default = that
  ticker's best expiry for the selected side (put-heavy expiry must not become the call default).
- Deterministic tie-break chain: ticker coverage → median spread → median OI → median volume →
  closer target DTE → earlier expiration → lexical.
- The published **Signal stays on the global signal horizon** (comparable across rows); per-ticker
  most-liquid drives candidate/default expiry only. A LEAPS candidate can coexist with a SPARSE
  90d signal — the UI explains these are different lanes (D2 tooltip).

**C4 — Serve: horizon switcher + real expiry dates (de-60d the render).**
Add a page-wide horizon control threaded through the `/option-trading` overview and `/ticker` detail
routes (querystring `?horizon=`, surviving the existing structural 6M/12M/3Y window switcher and the
option lens). Default to the backend "Most liquid". Replace every serve 60d site from blast-radius #5;
make the skew overlay read config horizons. **Overview stays readable**: one row per ticker for the
*selected* horizon. **Detail shows the full breakdown**: all configured expiries by date, candidate
rows + scenarios for the selected expiry, side switch (`put`/`call`) without rescanning raw chains.
Render `slot.expiration` ("Jan 15 2027") in the switcher/group headers, with the nominal target in the
tooltip ("Target ~230d · selected Jan 15 2027 · most-liquid near target").

**C5 — Serve-side scenario recompute (RESOLVED: bounded acceptance, does not block C).**
`build_option_trading_detail` recomputes P&L scenario bundles **at request time** with hardcoded gold
ladders (`option_trading.py:250,265`) — a pre-existing "backend computes, serve renders" violation,
not introduced by C. Per Codex review: it is backend Python over persisted selected candidates (not a
raw chain scan), so C keeps request-time compute **for the single selected candidate/horizon only**,
adds timing/logging, and a guardrail test proving no raw chain scan happens in the serve path. The
moment any page renders scenario bundles for **multiple** horizons at once, they must move to a
persisted per-horizon artifact — that trigger is written into the C4 acceptance criteria.

### Milestone C tests

- Config: adding a horizon in config produces candidate slots, skew columns, and a DTE band for it;
  no module constant overrides config (C1 regression — change config, assert all surfaces follow).
- Signal horizon is config-driven: with `signal_horizon` ≠ 60, direction/headline/cost read the
  configured horizon and never silently go `UNAVAILABLE` because `.get(60)` returned `None`.
- History schema: the chosen migration round-trips (IV-rank still works; old-schema history handled).
- Most-liquid selector picks the expiry with the best tradable-liquidity aggregate on a fixture; ties
  resolved deterministically; long-dated/LEAPS selection works within its window.
- Overview default horizon equals the backend-selected most-liquid expiry (serve does not choose it).
- Manual horizon selection renders that expiry's **persisted** values (no serve recompute of skew/IV).
- UI shows the real expiration date, not only the nominal horizon integer.
- (C5) Whatever is decided: either scenarios load from a persisted per-horizon artifact, or a test
  documents the bounded serve-side recompute.

Added by the Codex-review amendment:

- Optionability: with LEAPS configured, a name with solid 90/180 coverage but no LEAPS quote keeps
  `directly_hedgeable` (core-subset rule); the old "all horizons" rule is pinned as removed.
- Signal-vs-candidate split: with `option_signal_horizon_days=90`, a ticker with only LEAPS
  candidates still shows a 90d-based Signal (or a calm SPARSE), never a LEAPS-derived one.
- Side-aware defaults: a put-heavy expiry does not become the call-side default on the detail page.
- History backfill: legacy wide-format history rows are readable post-migration; IV-rank matches the
  pre-migration value for the 60d series at the boundary; `LIMITED_HISTORY` renders while 90d fills.
- Frozen-consumer sweep: a grep-level test (or checklist in the C2 PR) proves no production module
  still reads `*_60d` fields except declared-frozen ones.

### Decisions — RESOLVED (2026-06-11, per Codex program review + Claude reconciliation)

| # | Decision | Resolution |
|---|---|---|
| 1 | Signal horizon | Explicit `option_signal_horizon_days` knob, **90d in v1**. Never per-ticker most-liquid for the published Signal — rows must stay comparable (AEM at 230d vs NEM at 90d would make the column meaningless). |
| 2 | History migration | **Long-form history** with `signal_horizon_days` + one-time backfill from `skew_residual_60d/90d`/`atm_iv_60d`; covers the separate `option_signal_history.parquet` store the artifact schema gate does NOT protect. `LIMITED_HISTORY` shown calmly while the 90d series fills. Plus `OPTION_ARTIFACT_SCHEMA_VERSION` bump for the ten artifacts. |
| 3 | Most-liquid policy | Backend per-window expiry scoring over tradable contracts only (reuses B's primitive); robust medians not sums; overview default group-level (per-ticker normalized, miners only), detail default per-ticker **and side-aware**; deterministic tie-breaks. |
| 4 | LEAPS band | Named config band, **~450–650 DTE** to start; no open-ended `>365`; a separate 1y band only if coverage data later supports it. |
| 5 | `OptionTradingRow.*_60d` rename | **Rename during the schema bump** (`iv_skew_signal`, `iv_rv_ratio_signal`, `pnl_*_at_context` + horizon/expiry metadata). No parallel old/new columns; compatibility lives in migration helpers/tests only. |
| 6 | CF skew field | Bull/Bear presets switch to benchmark-relative **`skew_residual_signal`** (asks "unusually tilted vs GDX/GDXJ?"); raw `name_iv_skew_signal` stays available as an optional criterion (different question). `candidate_finder_inputs` gains the generic signal fields + `benchmark_symbol` + `signal_horizon_days`. |

Added decisions (Codex review), also resolved:

| Decision | Resolution |
|---|---|
| Optionability after LEAPS | `directly_hedgeable` keyed to a configured `core_optionability_horizons` subset (v1: 90/180) or min-coverage count — never "all selectable horizons" (`features/options.py:223-228` would silently downgrade names). |
| Is most-liquid side-specific? | Yes — put and call liquidity differ; detail defaults are per-side. |
| LEAPS candidate + SPARSE signal coexistence | Allowed and explained: candidate lanes and signal lanes are different products; D2 tooltip documents it. |
| Old Hedge Readiness markdown/CLI outputs | Each 60d consumer (`report.py`, `sensitivity_ranking.py`, `portfolio_totals.py`, `header_context.py`, `speculation_section.py`) is migrated to the renamed signal fields **or explicitly frozen/retired in the C2 commit** — no silent stale-60d text. |

---

## Milestone D — Site-Wide Hover/Explanation Layer

**Goal.** A reusable metadata layer so any non-obvious header or metric can hover-explain: **Meaning**
(plain English), **Calculation** (the rule), **Thresholds** (the *actual configured values*),
**Direction** (higher/lower/context), and **Source** (backend artifact/config). Threshold values come
from backend/config — never copied into templates — so a config change updates the tooltip
automatically. Applies **site-wide**, not just Option Trading.

**First-hand infra facts (what makes this cheap vs expensive).**
- The **hover CSS already exists**: `workspace.css:612-617` styles `th[title]`. Native browser
  `title=` is a zero-JS MVP; the table JS ignores extra `<th>` attributes, so no JS change is needed.
- **Candidate Finder already has per-column metadata** (label/description/`default_direction`/unit/
  group, validated by `CandidateFinderCriterion`, keyed by `source_field`) — the natural **seed** for
  a registry. It needs new `calculation` / `threshold_ref` / `source` fields.
- **But there is no shared header renderer**: tables are ~7 bespoke hand-written `<th>` blocks across
  `overview_tool_a/b/c/d.py`, `overview_option_trading.py`, `candidate_finder_page.py`, etc. Only Tool D
  uses tooltips today, and its text is **hardcoded literals that do not interpolate config thresholds**
  (`overview_tool_d.py:289-307`) — the exact anti-pattern to replace.
- `page_shell._page_shell` is the global injection point shared by all pages.

### Phase D1 — Mechanism + Option Trading as first adopter (prerequisite for B + C labels)

- Add a shared header renderer (`_th(col_name, label, *, tooltip=...)`) and a **backend metadata
  registry** keyed by dataframe column, where threshold fields reference config attributes by name
  (resolved at render from the already-loaded `AppConfig` — no new plumbing; `hedge_readiness` is
  already in scope in `option_trading_data.py`). Tooltip text is generated from config, satisfying
  "thresholds from backend/config."
- Adopt it on **Option Trading** first, covering exactly what B and C need:
  - the **"Tradable"** header tooltip for the Cached Liquidity Check (B), with the configured
    spread/OI/premium thresholds and a note that this is the **chain-level** rule;
  - the **row-level Skew hover** (data already persisted): single-stock rows show stock skew,
    benchmark symbol, benchmark skew, and the difference, for the **selected** expiry; benchmark-ETF
    rows show the absolute baseline skew. Implement by extending `_vol_points_td`
    (`overview_option_trading.py:243-250`) to emit a `title` from the four persisted fields — serve
    renders, does not recompute (`option_signals.py` owns the math).
  - **Rename vague labels** (paired with the tooltips, so the label + hover land together):

    | Current | Better | Sites to change together |
    |---|---|---|
    | Skew Read | Skew vs Benchmark | `overview_option_trading.py:115` |
    | Cost | Option Cost Signal | header `:117` + detail lane `detail_panels.py:308` |
    | Data Quality | Option Signal Quality | header `:118` + filter label `:96` + detail lane `detail_panels.py:313` |
    | Snapshot Date | Option Snapshot Date | header `:122` + detail row `detail_panels.py:460` |

    (Note the multi-site labels — "Data Quality" lives in 3 serve sites, "Snapshot Date" in 2. The
    rename must touch all sites of each label together. "Option Snapshot Date" is also the column the
    Milestone A freshness **banner** refers to — keep banner vs column distinct.)

### Phase D2 — Rollout (opportunistic, after D1)

- Migrate Tool D's hardcoded tooltip literals to the registry so they interpolate config thresholds.
- Extend to the remaining tool overview tables and Candidate Finder (its ranking `<th>` already has
  the metadata; add the `title` — a near one-line change once the renderer exists).
- Decision for D2: native `title=` (zero-JS, MVP) vs a styled multi-line popover (new CSS+JS). Start
  native; upgrade only if the multi-line layout is insufficient.

### Milestone D tests

- The "Tradable" header tooltip renders configured thresholds from option policy, not literals;
  changing a threshold in a fixture changes the tooltip text (shared with B3).
- Single-stock skew hover includes stock skew, benchmark symbol, benchmark skew, and the difference;
  benchmark-ETF hover renders the absolute baseline, not a residual.
- Serve renders metadata only — no recomputation of skew or liquidity thresholds in the serve layer.
- Renames applied at **every** site of each label (regression guard against partial renames).

---

## Cross-cutting coherence notes

- **No contradiction with the carry-forward amendments.** Milestone A's freshness **banner** and
  Milestone D's column **tooltips** are different surfaces that share one rule: backend owns the
  text/thresholds, serve only renders. The single shared *freshness formatter* (A Phase 4) and the
  *tooltip registry* (D1) are distinct mechanisms; neither duplicates the other.
- **One manifest with freshness domains is unchanged.** None of B/C/D needs a second pointer. The
  most-liquid default (C3) is a backend decision stamped into the artifact/manifest — the same
  "backend decides, serve renders" philosophy as the freshness domain.
- **Schema interaction is already handled.** C2's `OPTION_ARTIFACT_SCHEMA_VERSION` bump means
  carried-forward artifacts built on the old schema downgrade to `UNAVAILABLE` (A test 8) — the right
  behavior, and proof A and C compose rather than collide.
- **"Backend computes, serve renders" — the one standing violation.** Serve recomputes scenario
  bundles at request time (C5). Everything else (skew, medians, IV, liquidity) is already a pure read.
  C5 is the one place to fix or consciously accept; do not let the horizon work quietly multiply it.
- **Golden Vector rule #2 (no ad-hoc horizons).** C1 enforces it: after consolidation, horizons exist
  only in centralized config, removing the four divergent in-code sources that currently violate the
  spirit of the rule.

## Build appetite summary

A and B and D1 are each a few-day chunk and independently shippable. **C is multi-week** and should be
its own milestone with its own plan once Decisions 1–6 are settled — do not bundle C into A. If only
one thing ships next, ship A (the production bug). If a cheap quality win is wanted alongside, D1
unblocks the tooltips and label renames that both B and C want.
