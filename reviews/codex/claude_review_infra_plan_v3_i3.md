# Review — Infrastructure Plan v3 (post-I2, I3 staging)

**Reviewer:** Claude Code (Opus 4.8)
**Subject:** `reviews/codex/codex_merged_infrastructure_remediation_plan.md` v3 — focus on the post-I2 sections (Current Implementation State, anti-duplication rule, revised Phase 3/I3, Phase 4-6 gates, the I3 build brief).
**Main question:** is I3 staged to avoid the I1/I2 mistakes — duplicated helpers, parallel option-selection logic, request-time raw-chain scans, mutable-alias reads?
**Grade: READY WITH MINOR CHANGES.** The staging directly and explicitly targets all four mistakes; the structure is sound. Five clarifications below should land before Codex codes I3 — one of them (the immutable-publish mechanism for the new artifacts) is the real dependency.

## Direct answer: yes, all four mistakes are addressed
- **Duplicated helpers** → the global planning rule ("grep first, reconcile-then-centralize, no new local copies of [explicit list]"), the named shared-primitive inventory, the per-phase duplication gates, the "Do not create" list in Phase 3, the I3 brief's **duplication preflight**, and the I3 gate's **duplication self-review**. This is thorough and consistent.
- **Parallel option-selection logic** → "Do not add a second option-selection engine. Extract or call the existing one," the contract-first reframe, and the named functions to reuse (`_candidate_slots`, `_liquidity_measurements`, `_accepted_candidate_grids`, `_has_usable_slots`, etc.). ✓
- **Request-time raw-chain scans** → acceptance "cold loads do not scan all raw chains" + "**grep proof** that normal serve paths do not scan raw chains" + cold-load before/after timing. ✓
- **Mutable-alias reads** → "New artifacts must be manifest-addressable through `resolve_current_model_artifact_path`" + What-Not-To-Do #7 ("no second current-state concept; mutable aliases are convenience only"). ✓

The reframe — **artifact contract first → builder reusing existing code → parity test → flip readers → delete old path** — is exactly the right safe-refactor order, and the strict before/after parity acceptance (same tickers, slots, `liquidity_tier`, usable=tradable set, overview rows) preserves the behavior contract. This is a well-staged plan.

## Minor changes to make before coding I3

### 1 (the real dependency) — Specify the immutable-publish mechanism for the NEW I3 artifacts, and confirm it's the robust one
The plan says new artifacts get registered in the manifest and resolved via `resolve_current_model_artifact_path` — but that resolver currently **requires `immutable: True`**, and (per the I2 gate review, finding M1) immutability today is *reconstructed by sha256-matching the mutable alias to a run-stamped twin*, which is fragile. The plan's "Current Implementation State" lists the resolver but does **not** confirm whether M1 (writer records the run-id path directly, manifest joins on run-id not bytes) was actually implemented.
- **Action:** state, in the I3 artifact contract, exactly how each new option/candidate artifact achieves `immutable: True` at publish — and make it reuse **whatever M1 settled on**, not a fresh ad-hoc copy of the sha256-matching. If M1 was *not* done, I3 must not inherit/clone the fragile reconstruction for its new artifacts; resolve M1 first. This is the one item that, if left vague, reproduces an I2 mistake in I3.

### 2 — Make explicit that option artifacts are built inside `run_refresh`, BEFORE the atomic manifest publish
Phase 2 step 8 lists "building option/candidate artifacts" then "publishing current state," which is right — but the I3 work/brief should say it outright: **insert the artifact-build step into the refresh sequence between Tool D and the manifest swap; if it fails, nothing publishes.** Otherwise the new artifacts could be published outside the all-or-nothing set, or built lazily on first request (re-introducing request-time compute).

### 3 — Name the non-serve home for the extracted shared builder (avoid a layering inversion)
The current option-selection orchestration lives in the **serve** layer (`serve/option_trading_data.py`), while the pure scan/bucket math is already in `hedge/options_liquidity.py`. If the refresh-time builder "reuses the existing code" by importing from `serve/`, that's a serve→pipeline inversion. **Action:** specify that the shared builder is extracted into a non-serve module (e.g. alongside `hedge/options_liquidity.py` or a new `model/`/`features/` builder) that **both** the interim serve path and the refresh builder call — so there's one engine, imported the right direction.

### 4 — Carve out the per-request sizing calculator as staying request-time
The Option Trading detail page has a **sizing/scenario calculator** parameterized by user input (contract × quantity × gold-move) — it can't be precomputed. **Action:** state that the sizing calculator stays request-time but operates on the **persisted selected candidate** (P&L math on the chosen contract), **not** a fresh raw-chain scan. This prevents both "trying to precompute the parameterized calculator" and "leaving a raw-chain scan in the calculator path" (which the grep-proof acceptance would otherwise flag late).

### 5 (smallest) — Parity-test inputs + full coverage of current request-time option work
- The parity test must feed the **same cached chains AND the same risk-free rate** to old and new paths so Black-Scholes delta/IV match exactly — the "except intentional provenance fields" carve-out must not hide a delta/IV computation difference.
- Confirm the artifact set covers **all** current request-time option computations, including the **benchmark ETF (GDX/GDXJ) liquidity measurement and the proxy-fallback**, so none are left scanning chains at request time (the grep-proof acceptance is the backstop, but list them in the contract).

## On the other sections
- **Current Implementation State + planning rule:** good — this is the "name the reuse" discipline I asked for, and it now lists the shared primitives explicitly (including the new `atomic_write_*`, `common/strings.unique_strings`, `common/eligibility.*` — which retire several duplication-review items). Just resolve the M1 ambiguity (#1).
- **Phase 4-6 gates:** strong and consistent. Phase 5's "define shared schema-validation primitive **once**, then use it for all tools/artifacts" is exactly right (prevents per-tool validators). Phase 6 correctly says "reconcile intended behavior before consolidating" for the divergent freshness/`_unique_strings` copies.
- **I3 build brief:** the duplication preflight up front and the I3 gate deliverables (artifact contract, parity proof, manifest sample, cold-load timing, grep proof, duplication self-review) are exactly the right stop-criteria. Add #1-#4 above into the brief's scope.

## Bottom line
**READY WITH MINOR CHANGES.** I3 is staged to avoid all four I1/I2 mistakes — deliberately and explicitly. Fold in the five clarifications, with #1 (the immutable-publish mechanism for the new artifacts — reuse M1's robust mechanism, don't clone the sha256-reconstruction) being the one that actually matters; the rest are guardrails. After that, Codex is clear to start I3 at the artifact-contract commit.
