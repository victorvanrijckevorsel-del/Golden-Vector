# Merged Infrastructure Review — Claude vs Codex

**Author:** Claude Code (Opus 4.8)
**Date:** 2026-06-05
**Inputs:** `claude_infrastructure_holistic_review.md` (Claude) + Codex's infrastructure review (pasted by Emanuel 2026-06-05).

## Headline: strong agreement on the #1 priority
Both reviews, done independently, reached the **same central conclusion**: the foundation/computation layer is solid (run-ids, QA gates, immutable snapshots, currency discipline), and the **weak point is the options layer doing heavy candidate/liquidity computation inside the UI** instead of producing it once in the pipeline. Both prescribe the same fix: **compute option slots/liquidity/scenario inputs at refresh time, persist them as versioned artifacts, make the UI a reader.** Two independent reviews landing on the same top recommendation = high confidence this is the right milestone.

## Point-by-point agreement
| Finding | Claude | Codex | Status |
|---|---|---|---|
| Options analytics computed at request time → slow loads; move to pipeline artifacts, UI reads-only | Theme 2 (main serving gap) | Finding #1 (highest priority) | **AGREE — top fix** |
| Refresh button (`update-data --options`) doesn't rerun Tool A/B/C/D → fresh options vs stale betas | Theme 1 (partial-refresh stale state) | Finding #2 | **AGREE** |
| Need a single "is the whole model built & coherent" signal / current-state manifest | Tier-1 #4 (current-state manifest) | Finding #3 + recommended milestone #1 | **AGREE** |
| Option cache key too coarse (run-ids only, not content/config hashes) | Theme 2 (options cache vs Finder's hash key) | Finding #4 | **AGREE — identical** |
| Yahoo client too thin: no retry/backoff/pacing | Theme 3 | Other risks | **AGREE** |
| Full-chain fetch is slow; want an incremental/expiry-band speed mode | Theme 3 (incremental fetch) | Other risks (expiry-band) | **AGREE** (Codex more specific) |
| Status should distinguish spot Tool D (used by Finder) from scenario Tool D | (in Tool C/D merge, C1) | Other risks | **AGREE** |

## What Claude caught that Codex didn't (deeper root-cause / durability)
1. **No single refresh run-id + non-atomic per-stage publish.** Codex treats the *symptom* (stale estate → add a build manifest); Claude additionally diagnoses the *root cause*: each tool stamps its own id and publishes its `latest` alias immediately, so a mid-chain failure leaves a half-updated state. Fix is **one refresh-id threaded through every stage + an atomic all-or-nothing swap**, which removes the entire mixed-refresh reconciliation layer as a class of problem — stronger than only adding a manifest on top.
2. **Non-atomic `latest` writes → torn-read risk.** A crash or concurrent UI read mid-write can observe a corrupt `*_latest.parquet` (silently degraded to empty). Codex focused on cache invalidation, not write atomicity.
3. **Raw equities + FX not hashed into the replay manifest** — a reproducibility hole in the largest raw input (Codex flagged options-feature auditability but not this).
4. **No retention/cleanup → unbounded growth** (67 run folders in ~3 days).
5. **No schema contracts on tool-output parquets** → schema drift degrades silently instead of failing loudly.
6. **Config-centralization drift in Tool C/D** (hard-coded thresholds/directions) — ties to the Tool C/D audit.
7. **Explicitly verified the two hard rules hold** (QA gate blocks scoring; currency guard raises on mixed-currency) — the reassurance.

## What Codex caught that Claude didn't (empirical / operational)
1. **Ran `status` and found the REAL current state:** foundation/options as of 2026-06-01, **Tool A/B still from 2026-04-24, Tool C/D missing locally.** Claude reasoned about stale-state risk architecturally but didn't run status. **This is concrete and important:** on Emanuel's actual machine the new Tool C/D data isn't built and Tool A/B are ~6 weeks stale — which means the Candidate Finder is *right now* in the degraded/eligibility-dropping state the Tool C/D audit (K1/C1) warned about.
2. **Tied findings to the actual refresh button** (`option_refresh.py:328` runs `update-data --options`) — concrete UI behavior, not just architecture.
3. **Observability framing:** add retry + *timing diagnostics* around Yahoo fetches so "slow loads become measurable instead of mysterious." Claude said retry/backoff but underweighted the measurement angle.
4. **Expiry-band fetch mode** — a concrete, options-specific speed optimization (fetch only expiries near configured bands, keep full-chain audit mode).

## Net comparison
- **Same diagnosis, different lenses.** Claude was more **architectural/durability** (root-cause: single run-id + atomic swap; plus torn-writes, full-input hashing, retention, schema contracts). Codex was more **empirical/operational** (ran status, found the live stale estate, tied to the real button, added observability + expiry-band ideas).
- **Neither contradicts the other.** Merged, they define a complete next milestone.

## Merged "next infrastructure milestone" (the reconciled plan)
**A. The data center (both reviews' core):**
1. **One refresh run-id + atomic all-or-nothing publish** (Claude) folded into a **single full-model build manifest** covering foundation+options+A+B+C+D+Finder readiness with a clear complete/incomplete signal (Codex).
2. **Move option candidate-slot / liquidity / scenario-input compute out of the UI into the options pipeline; persist as versioned artifacts with config + source hashes; UI reads only** (both).
3. **Content-hash cache keys** for options to match the Finder's (both).
4. **Surface build state in the UI** so stale/incomplete is impossible to miss (Codex); separate "data refresh" from "model refresh" on the button (both).

**B. Resilience & durability:**
5. Retry/backoff **+ timing diagnostics** around Yahoo (both); expiry-band speed mode (Codex).
6. Atomic `latest` writes; hash raw equities/FX into the manifest; schema-version + validate outputs; `prune-runs` retention (Claude).

**C. Immediate operational action (Codex's empirical find):**
7. **Rebuild the local data estate now** — run a full `refresh` so Tool A/B are current and Tool C/D exist locally — before relying on the Candidate Finder, which is currently degraded by the missing/stale inputs.
