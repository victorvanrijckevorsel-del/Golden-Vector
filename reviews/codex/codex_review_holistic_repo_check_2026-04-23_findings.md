# Codex Review: Holistic Repo Check

Date: 2026-04-23  
Mode: read-only review  
Reviewer: Codex

I reviewed the whole repo against the current product shape:

- `update-data` as the explicit refresh step
- Tool A as the official structural model
- Tool B as the manual-store-backed screening engine
- `workspace` as the current product surface

I also checked the live artifacts under `data/` and reran the full test suite during this review.

`pytest`: **159 passed**

## 1. Findings Ordered P1 To P3

### P1. The workspace can mix different snapshots on the same page and silently degrade when latest files are missing
- Files:
  - `golden_vector/serve/workspace.py:306-314`
  - `golden_vector/serve/workspace.py:327-341`
  - `golden_vector/serve/workspace.py:389-446`
  - `golden_vector/serve/workspace.py:483-515`
  - `golden_vector/serve/workspace.py:1237-1240`
- Why this matters:
  - The overview and headline cards read `latest_tool_a` / `latest_tool_b` from stable alias files.
  - The Tool A detail view is recomputed live from the **current** latest foundation snapshot instead of the `snapshot_refresh_run_id` carried by the published Tool A row.
  - There is no check that the page is showing one coherent refresh across Tool A, Tool B, and the foundation snapshot.
  - If a stable latest file is missing, `_read_optional_parquet()` returns an empty frame and the workspace simply renders blank cells instead of a strong stale/missing-output warning.
- Live evidence:
  - The current repo state has `data/output/tool_b/tool_b_latest.csv` and `data/output/tool_b/tool_b_latest.parquet` **missing**, while run-specific Tool B outputs still exist.
  - That means the workspace can currently blank the Tool B side without telling the user that the stable latest alias is broken or absent.
- Verdict:
  - This is a product-trust issue, not a cosmetic issue. The workspace can show a page that looks valid while mixing stale or missing underlying artifacts.

### P1. Tool A explanations can still contradict the official score because they anchor on one window while scoring uses the structural core
- Files:
  - `golden_vector/model/explanations.py:8-47`
  - `golden_vector/model/pipeline.py:306-355`
  - `golden_vector/model/pipeline.py:417-423`
- Why this matters:
  - Official Tool A eligibility and scoring use `structural_delta_core`.
  - `delta_explanation` is built from `anchor_delta` instead.
  - When the anchor window and the weighted structural core disagree, the explanation can say the stock does **not** earn an official rank even though the row is rankable and scored.
- Live evidence:
  - In `data/output/tool_a/tool_a_latest.csv`, `FNV` is `score_eligible=True`, `tool_a_rank=7`, `score_eligibility_reason=OK`, but its `delta_explanation` says the stock has “not shown enough weekly gold linkage ... to earn an official rank.”
- Verdict:
  - This is exactly the kind of explanation contradiction the redesign was supposed to remove. The numbers may be fine, but the published explanation layer is still capable of misleading the user.

### P1. Tool B output still does not carry enough normalization and refresh provenance to be safely interpreted downstream
- Files:
  - `golden_vector/screening/pipeline.py:29-67`
  - `golden_vector/screening/pipeline.py:175-214`
  - `golden_vector/normalize/market_snapshot.py:10-25`
  - `golden_vector/normalize/market_snapshot.py:81-126`
  - `golden_vector/serve/workspace.py:306-314`
- Why this matters:
  - Normalized Tool B market snapshots explicitly carry `normalization_status`, `fx_source_date`, and `fx_staleness_days`.
  - The published Tool B output drops that context and keeps only `source_run_id`.
  - The output row does **not** include `snapshot_refresh_run_id`, `snapshot_as_of_date`, `normalization_status`, or any FX warning context.
  - The workspace therefore cannot tell the user whether the latest Tool B row is based on the current foundation refresh, nor whether the pricing inputs were cleanly normalized.
- Why this is a real FX safety issue:
  - Today’s live snapshots are all `OK`, so the issue is latent.
  - But if a future non-USD snapshot comes through with `STALE_FX` or another non-`OK` normalization status, the Tool B output contract gives the UI no way to surface that clearly.
- Verdict:
  - Tool B still falls short of the repo’s “fully auditable and explicit FX handling” rule at the published-output boundary.

### P2. Starting the workspace still mutates local Tool B data by auto-creating and seeding the manual store
- Files:
  - `golden_vector/cli.py:1044-1055`
  - `README.md:66`
  - `README.md:79`
- Why this matters:
  - `run_workspace()` calls `bootstrap_manual_screening_data()` unconditionally.
  - That means opening the workspace is not read-only: it can create the SQLite store and seed rows.
  - This conflicts with the otherwise explicit `manual-data init` workflow and makes the product contract harder to reason about.
- Why this is weaker than it looks:
  - It does not destroy data.
  - But it does mean that “open the UI” still has side effects on persistent Tool B state.
- Verdict:
  - This is survivable, but it is still an unnecessary hidden mutation in a tool that is trying to become more explicit and auditable.

### P2. The tests are strong overall, but they still miss the exact failure modes now most likely to hurt the live product
- Files:
  - `tests/test_workspace_app.py`
  - `tests/test_tool_b_pipeline.py`
  - `tests/test_persist_tool_b.py`
- Gaps:
  - No workspace test for a missing stable latest Tool B alias.
  - No workspace test for Tool A latest output and foundation snapshot coming from different refresh runs.
  - No Tool B pipeline test for a non-`OK` normalized market snapshot row.
  - No regression test for the anchor-vs-core explanation contradiction that now exists live for `FNV`.
- Verdict:
  - The suite is broad and useful, but it is still weaker around provenance, stale-output handling, and UI trust signals than it needs to be.

### P3. Some docs still describe the product in slightly conflicting or stale terms
- Files:
  - `README.md:66`
  - `README.md:79`
  - `docs/golden_vector_architecture_map.md:79`
- Issues:
  - `README.md` says the workspace bootstraps the Tool B store if needed, but also tells the user to initialize it explicitly with `manual-data init`.
  - `docs/golden_vector_architecture_map.md` still says “151 passing tests” even though the current suite is `159`.
- Verdict:
  - Minor, but these docs still add friction for a new contributor or future agent.

## 2. Architecture Assessment

The high-level architecture is now coherent:

- local-first runtime
- explicit `update-data`
- structural-first Tool A
- SQLite-backed Tool B manual store
- workspace as the product surface

That is a real improvement over the earlier CLI-heavy / Combined-heavy shape.

The remaining weakness is not the backbone. It is the **output-to-workspace trust layer**:

- latest aliases are still just simple files, not strongly validated published artifacts
- workspace provenance is too loose
- Tool B output auditability is still thinner than Tool A

So the architecture is directionally right, but the final “what the user sees” layer is still more brittle than the engine underneath it.

## 3. Tool A Assessment

Tool A is now much closer to the intended framework.

What looks good:
- official windows are fixed and clear
- weekly USD-normalized structural samples are the scoring basis
- gamma is no longer the old cross-horizon proxy
- asymmetry is explicit
- volatility is treated as diagnostic, not a co-equal core score factor
- normalization-blocked rows can now be withheld

What is still weak:
- the explanation layer is not fully aligned with the scoring layer
- “anchor window” and “structural core” are still mixed too casually in explanation generation

My verdict on Tool A:
- conceptually **mostly sound**
- mathematically **far better than before**
- explanation layer **still not fully trustworthy enough**

So Tool A is close, but I would not call it fully settled until the published explanations can no longer contradict the official score logic.

## 4. Tool B / Manual-Store Assessment

Tool B is operationally usable now:

- local manual store is a good direction
- direct edit commands exist
- notes exist
- store timestamps exist
- CSV is no longer the primary workflow

Main remaining weakness:
- Tool B outputs are still not provenance-rich enough
- the workspace still depends on a stable Tool B alias that can disappear silently
- the workspace auto-creates/seeds the manual store instead of staying explicit

My verdict on Tool B / manual-store:
- good enough for engineering progress
- not yet strong enough to call “fully trustworthy for normal daily use” without caveats

## 5. FX / Normalization / QA Assessment

The repo is much safer than before on FX.

What looks good:
- normalization happens upstream
- Tool A structural logic uses USD-normalized data
- foundation snapshot signatures include FX policy
- non-OK normalization can now withhold Tool A scoring

What is still weak:
- Tool B publishes too little FX/normalization context downstream
- the workspace does not surface output-level provenance strongly enough
- the user can still see a “current-looking” workspace without a strong signal that a latest output is missing or stale

So the normalization layer itself is much improved, but the **published-output layer** still under-communicates normalization trust.

## 6. Workspace / Presentation Assessment

The workspace is useful now, but it is still not a fully trustworthy v1 surface.

Good:
- simple local workflow
- Tool A explanations are visible
- Tool B editing and notes are usable
- exploratory Tool A layer is visually separated

Weak:
- no source-verification editing yet
- no hard warning when latest Tool B output is missing
- Tool A detail can be rebuilt from a different refresh than the headline row
- the refresh summary card describes the latest foundation snapshot, not necessarily the exact snapshot behind the current Tool A / Tool B outputs

My verdict:
- promising product surface
- still too thin and too quiet around provenance to call finished

## 7. Tests / Docs / Residual Risks

### Tests
- Full suite passed: **159 passed**
- The suite is broad and useful.
- The missing coverage is mostly around:
  - stale/missing published latest artifacts
  - snapshot provenance mismatch in the workspace
  - Tool B behavior under non-`OK` normalized market snapshots
  - explanation contradictions at the anchor/core boundary

### Docs
- Docs are much closer to reality than before.
- Remaining issues are mostly stale counts and mixed messaging around workspace/manual-store initialization.

### Residual risks
- workspace still lacks source-verification editing
- stable published output contracts are still file-based, not manifest-backed
- Tool B provenance is thinner than Tool A provenance

## 8. Final Verdict

**Final verdict: `NOT READY`**

The repo is much more coherent than it used to be, and the direction is now good.

But I would still block a “ready” verdict because the remaining issues hit the exact place where product trust matters most:

1. the workspace can mix or silently lose published outputs
2. Tool A explanations can still contradict the score logic
3. Tool B still drops too much FX / refresh provenance at the published-output boundary

## Direct Answers

### 1. Is the current product architecture coherent and trustworthy overall?
Coherent: **yes**.  
Trustworthy enough overall: **not yet**.

### 2. Is Tool A now good enough to be treated as the official structural model?
**Almost, but not fully.** The structural core is much better; the explanation layer still needs one more tightening pass.

### 3. Is Tool B / manual-data handling now strong enough for normal daily use?
**Mostly operational, but not fully strong.** The manual store is fine; the published Tool B output contract still needs better provenance and clearer normalization surfacing.

### 4. Is the workspace now a good enough product surface for v1, or is it still too thin / too risky?
**Still too risky.** The biggest problem is provenance trust, not layout.

### 5. What are the most important remaining conceptual weaknesses?
- anchor-window explanations versus structural-core decisions in Tool A
- Tool B output contract still not carrying enough trust context

### 6. What are the most important remaining engineering weaknesses?
- workspace/latest-artifact provenance mismatch
- missing/stale latest-output handling
- missing tests around those exact failure modes

### 7. If I had to prioritize only the next 3 things to fix or improve, what would they be?
1. Make workspace pages provenance-safe:
   - no mixed refreshes on one page
   - strong warnings for missing/stale latest outputs
2. Fix Tool A explanation generation so the published text cannot contradict official score eligibility
3. Add refresh/normalization provenance directly into Tool B published outputs and surface it in the workspace
