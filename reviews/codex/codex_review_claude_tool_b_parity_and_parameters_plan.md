# Codex Review: Claude Tool B Parity And Parameters Plan

Date: 2026-04-24  
Reviewer: Codex

## Summary Verdict

**STILL NOT READY**

The plan is directionally good. It attacks the right drift sources from the Excel cross-check:

- default gold-price mismatch
- jurisdiction-tier mismatch
- almost-empty manual store
- misleading `best_target = max(...)` headline
- need for a faster scenario-tuning surface inside the workspace

But three parts are not safe to implement as written:

1. Step 3 backfills numbers without backfilling verification state.
2. Step 3 rate “auto-correction” is too loose and can silently distort data.
3. Step 4 mixes real parity work with a new, non-canonical ranking philosophy.

Those need to be corrected in the plan before coding starts.

---

## Findings

| Priority | Finding | Why it matters |
|---|---|---|
| `P1` | Step 3 imports company numbers but not `source_verification` | Imported rows will still read as `ESTIMATED`, so the plan does not actually deliver “friend-verified” Tool B inputs |
| `P1` | Step 3 royalty/tax “if value < 1, multiply by 100” rule is unsafe | The current Tool B stack already normalizes rates as fractions; a blanket script-level correction can silently corrupt valid low-percentage inputs |
| `P1` | Step 4 ranking change is not parity work | Switching `tool_b_score` from `best_upside_pct` to `upside_peer_pe_pct` invents a new product ranking rule that the Excel does not define |
| `P2` | Friend ticker mapping is duplicated across Step 2 and Step 3 | `ARMN → ARIS.TO` and `RMS → RMS.AX` should live in one shared import-side mapping helper/table, not as repeated ad hoc dicts |
| `P2` | Step 2 needs one explicit ownership decision on jurisdiction tiers | Writing friend research directly into `config/universe.yaml` is fine only if we deliberately accept that file as the canonical Tool B jurisdiction source |
| `P2` | Step 4 verification should compare named rows/scenarios, not top-10 order only | The workbook `Top performers` sheet is saved values, not an exposed formula-backed ranking model, so order comparison is a weak acceptance test |
| `P3` | The plan still overuses “pause for Emanuel approval” on safe mechanical steps | This repo’s agreed workflow is low-interruption execution; dry-run reporting is good, but the pauses should be about risky data writes only |

---

## Detail

### `P1` Step 3 imports numbers but not verification state

The plan says Step 3 will:

- read Excel `Screening Data`
- import the numeric mining inputs
- call `upsert_company_input(...)`

But it does **not** say it will update `source_verification`.

That matters because Tool B confidence is not based only on “are the numeric fields present?” It also checks whether all required manual fields are marked `VERIFIED` in the verification table:

- [manual_data.py](C:\Users\Emanuel\code\Golden-Vector\golden_vector\screening\manual_data.py)
  - `determine_manual_confidence(...)`
  - `REQUIRED_MANUAL_FIELDS`

Current behavior is:

- missing required fields → `INCOMPLETE`
- fields present but no verification rows → `ESTIMATED`
- only full verified coverage → `VERIFIED`

So if Step 3 only fills `company_inputs`, most rows will still remain `ESTIMATED`.

That is a direct mismatch with the stated goal of bringing Tool B closer to the friend’s verified workbook.

**Correction needed:**

- Step 3 must import `source_verification` alongside `company_inputs`
- at minimum for every imported required manual field:
  - `ticker`
  - `field_name`
  - `verification_status`
  - `source_date` if available
  - a short provenance note like “Imported from Gold_Mining_Screening_v10226_EVEB.xlsx”

If the workbook cannot support per-field `VERIFIED` honestly, the plan should say so and use `ESTIMATED` deliberately. But it cannot silently skip verification and still claim parity.

---

### `P1` Step 3 royalty/tax auto-correction is unsafe as written

The plan says:

- if royalty/tax value `< 1`, multiply by `100`
- log the correction

That rule is not safe enough.

Current Tool B already treats `royalty_rate` and `tax_rate` as **fractions** internally:

- [layer2.py](C:\Users\Emanuel\code\Golden-Vector\golden_vector\screening\layer2.py) uses `_rate(...)`
- [manual_store.py](C:\Users\Emanuel\code\Golden-Vector\golden_vector\screening\manual_store.py) normalizes values `> 1` by dividing by `100`

So the current stack already accepts both:

- `0.30` meaning `30%`
- `30` meaning `30%`

The plan’s proposed blanket correction is therefore:

- redundant for many rows
- dangerous for real sub-1% inputs

Example risk:

- a valid `0.5%` royalty stored as `0.5`
- script multiplies to `50`
- store normalizes to `0.5`
- Tool B now interprets that as **50%**, not **0.5%**

That is silent corruption.

**Correction needed:**

- remove the blanket `if value < 1 then * 100` rule from the plan
- preserve raw Excel values on import
- produce an anomaly report showing rows that look suspicious
- only apply targeted corrections if they are:
  - explicitly listed
  - shown in the dry-run report
  - and clearly justified

If Claude still wants normalization beyond the existing store logic, it must be **cell-specific**, not a blanket threshold rule.

---

### `P1` Step 4 ranking change is not parity work

The scenario split is the right idea:

- remove misleading “best target”
- expose the four main scenarios separately
- make the workspace honest about where upside is coming from

That part is good.

But this proposed score change is not parity:

- current score input: `best_upside_pct`
- proposed score input: `upside_peer_pe_pct`

The workbook does **not** expose a canonical score formula that says Peer P/E upside should drive rank.

So this is not “bringing Python closer to the friend’s Excel.” It is inventing a new product rule.

That may still be a good rule. But it should not be smuggled in as if it were parity work.

**Correction needed:**

Choose one of these explicitly:

1. **Parity-first option**
   - Step 4 only changes display/output:
     - remove `best_target`
     - publish four scenario columns
   - leave `tool_b_score` alone for this milestone
   - re-evaluate ranking philosophy later

2. **Product-overlay option**
   - Step 4 keeps the scenario split
   - score change is allowed
   - but the plan must say clearly:
     - this is a Golden Vector product ranking overlay
     - not Excel parity

My recommendation is option 1 for this milestone.

---

### `P2` Friend ticker mapping should be centralized on the import side

The plan currently duplicates:

- `ARMN → ARIS.TO`
- `RMS → RMS.AX`

in both:

- Step 2 tier-sync script
- Step 3 backfill script

That is the wrong shape.

I do **not** think this mapping belongs in production runtime logic.

But I also do **not** think it should live as two copied dicts inside two scripts.

**Correction needed:**

- create one shared import-side mapping helper or YAML file
- both workbook-ingest scripts read from that same source

That keeps runtime clean while preventing script drift.

---

### `P2` Step 2 needs one explicit ownership decision on jurisdiction tiers

Step 2 proposes to rewrite `config/universe.yaml` from the friend’s workbook.

That is acceptable only if we make one architectural decision explicit:

> `config/universe.yaml` is now the canonical Tool B jurisdiction-tier source.

Right now the plan treats this like a pure mechanical sync, but it is actually a schema/ownership choice.

Why this matters:

- `universe.yaml` is repo-wide config, not a temporary import artifact
- today it still carries the old “defaults to 2, edit as you build conviction” meaning
- after Step 2 it would become “friend workbook jurisdiction research, rounded for Tool B”

That may be the right choice. But the plan should say it explicitly.

**Correction needed:**

- add one sentence locking the ownership decision
- if that decision is not acceptable, use a Tool B-specific config source instead of `universe.yaml`

My practical recommendation:

- for now, using `universe.yaml` is fine
- but only if the plan says that clearly and treats it as deliberate, not incidental

---

### `P2` Step 4 verification should not rely on top-10 order alone

The plan says the main Step 4 check is:

- compare Python top-10 with Excel `Top performers` top-10

That is too weak and slightly misleading.

From the earlier cross-check:

- the workbook `Top performers` sheet is saved values
- there is no exposed canonical score/rank formula we can mirror exactly

So a top-10 ordering comparison is useful as a smell test, but not a strong acceptance test.

**Correction needed:**

Step 4 should verify parity mainly through:

- named ticker checks
- per-scenario target price comparisons
- verdict comparisons
- explanation of any ranking difference caused by live Yahoo prices or product-only score logic

Top-10 order can stay as a secondary sense check, not the primary acceptance gate.

---

### `P3` The plan is a bit too approval-heavy for this repo’s working mode

This repo’s instructions are low interruption:

- do the work
- show results
- ask only for genuinely risky actions

Dry-run previews for Step 2 and Step 3 are good. Those are real data writes and deserve visibility.

But the plan does not need to pause for eyeballs on every safe or mechanical sub-step.

That is a small issue, not a blocker.

---

## Direct Answers To Claude’s Review Questions

### 1. Is the Step 4 ranking change defensible?

**Not as parity work.**

It is defensible only as a **new Golden Vector product choice**.

If the milestone is called “Tool B parity with friend’s Excel,” I would **not** change `tool_b_score` yet.

Recommendation:

- ship the four-scenario split
- keep rank logic unchanged for this milestone, or mark it explicitly as product-only

### 2. Is the in-memory recompute in Step 5 clean enough?

**Yes, if the seam is in the shared math layer, not a parallel implementation.**

The right shape is:

- extract a pure Tool B row-building helper from the persistent pipeline
- reuse that helper in:
  - normal persistent `tool-b`
  - workspace in-memory overrides

Do **not** build a second parallel Tool B implementation for the workspace.

Also make sure the in-memory path preserves:

- snapshot provenance
- normalization status
- FX context

so the page stays auditable even when using URL overrides.

### 3. Should the Combined view also get the Screening Parameters panel?

**No.**

Keep it out.

The agreed product direction is:

- `/tool-b` is the main parameter-tuning surface
- compare/combined comes later

Do not spread scenario-tuning UI into deferred surfaces now.

### 4. Does the friend-ticker mapping belong in the import script only?

**Not in production runtime, but also not duplicated per script.**

Best answer:

- keep mapping on the import side only
- centralize it in one shared import helper/table used by all workbook-ingest scripts

### 5. Should Step 3 auto-correction be silent?

**No.**

Not with the current blanket rule.

At minimum:

- show the exact rows/cells in dry-run output
- explain why they look suspicious
- and only then apply a targeted fix

But my stronger recommendation is:

- remove the blanket correction rule entirely
- rely on existing store normalization for normal percent/fraction handling
- only fix explicit known-bad cells

### 6. Anything missed in scoping?

Yes:

- Step 3 needs `source_verification` import, not just `company_inputs`
- Step 4 should not treat top-10 order as the main parity proof
- Step 2 needs one explicit ownership decision on jurisdiction tiers

---

## Recommended Plan Corrections Before Coding

1. **Expand Step 3** so it imports `source_verification` records for required Tool B fields, not just company numeric values.
2. **Remove the blanket royalty/tax `<1 → *100` rule** and replace it with raw-preserving import plus explicit anomaly reporting.
3. **Separate scenario-display parity from ranking philosophy**:
   - Step 4 should split scenarios and remove `best_target`
   - but not silently redefine the official score unless that is explicitly labeled product-only
4. **Centralize friend ticker mapping** in one shared import-side helper/table used by both Step 2 and Step 3.
5. **Lock the ownership rule for jurisdiction tiers** before Step 2 writes `config/universe.yaml`.
6. **Use named row/scenario checks as the main Step 4 verification**, with top-10 order only as a secondary smell test.

---

## Final Recommendation

The milestone is worth doing.

But I would **revise the plan first**.  
If Claude fixes the points above, the plan becomes strong and implementation-ready.

Without those corrections, the plan risks:

- claiming parity while still leaving imported rows `ESTIMATED`
- introducing silent rate distortions
- and changing the Tool B ranking philosophy under the cover of parity work
