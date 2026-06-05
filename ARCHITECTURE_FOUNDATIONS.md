# Architecture Foundations — set these on day one of any data-heavy project

**Why this file exists:** the I1-I3 infrastructure rework (a full day) retrofitted things that are *cheap to do on day one and expensive to retrofit later*. This checklist captures exactly those, so the next project — or the next feature — starts with the spine right and never needs that rework again.

## The honest framing (so we don't over-correct)
You can't design the whole system perfectly upfront, and **over-building infrastructure for a 2-feature prototype is its own waste.** Building Tool A/B fast to validate the idea was the right call. The mistake wasn't "we didn't build everything upfront" — it was:
1. A handful of **cheap, load-bearing conventions** weren't set as defaults from commit 1, so debt accumulated silently.
2. There was **no architecture checkpoint at milestone boundaries** — we added Tool C/D and the option UI on top of a spine that wasn't ready, and only noticed when pages got slow and states got stale.

So the rule is *not* "gold-plate everything early." It's: **set the few cheap foundations below on day one, and review the spine before each major feature.**

## The day-one foundations (cheap early, expensive late)
These are exactly what we retrofitted. Each is a few lines of convention if done from the start.

1. **Compute once, persist, serve reads.** Analytics never run in the request/UI path. Every stage = read inputs → compute → **write a persisted artifact**. The UI/readers only *read* artifacts. (We violated this: the option page scanned thousands of contracts live → ~20s loads.)
2. **One atomic "current state" pointer.** A single manifest names the coherent set of current outputs and is published by **write-temp-then-rename** (`os.replace`). Readers resolve **through** it. Never let readers open N separate mutable "latest" files and hope they match. (This was I1/I2 — and the whole "mixed refresh" headache existed *because* there was no single pointer.)
3. **Immutable, run-stamped outputs + a convenience alias.** Write every output as `{name}_{run_id}.parquet` (immutable) plus a mutable `{name}_latest` alias. The pointer references the **immutable** file. This makes atomic publish and reproducibility almost free, and kills torn-read/overwrite bugs.
4. **One refresh identity.** A full rebuild gets **one id threaded through every stage**. Coherence is then an *invariant*, not something reconstructed afterward by comparing ids (which is what the "mixed refresh" warnings were — a band-aid for a missing id).
5. **All-or-nothing publish.** A build either fully publishes or doesn't. A mid-build failure leaves the **last good build fully intact**.
6. **Fail loud on bad data — never silent-empty.** Required inputs use **checked reads** (raise with context) and **schema validation**; verify a stored checksum where it matters. Don't swallow a corrupt/missing file into an empty frame — that hides outages behind a "looks fine" UI. (This was findings F3/F4.)
7. **One shared utilities module from commit 1.** A `common/` package for numeric coercion, hashing, atomic writes, parquet IO, ticker normalization, status-combining, and freshness. **Grep before adding any helper.** (We grew ~12 copies of "coerce to float", 5-6 of "hash a file", etc.)
8. **One source of truth for freshness/alignment.** A single function, *consumed* everywhere — not recomputed per screen. (Still being cleaned up: 4 copies that can give different answers on different screens for the same build.)
9. **Provenance from the start.** Hash inputs + config, snapshot per run, record everything the current-state manifest needs to replay a build.
10. **(Domain) QA gate before scoring; normalize currency before any cross-entity math.** — *these we did right from the start; keep doing them.*

## The process change (the real fix)
The checklist alone isn't enough — debt creeps back without a gate. So:
- **Architecture checkpoint at every milestone boundary.** Before adding a major feature, spend ~1 hour on: *"Is the data spine ready to carry this — compute-once? through the manifest? no new duplicated helpers? fail-loud?"* That hour is far cheaper than a day of retrofit.
- **"Done" includes infrastructure, not just "the feature works."** A feature is done when it's computed-once-and-persisted, resolved through the manifest, adds no duplicated helper, and fails loud on bad data — not just when the screen renders.

## Smell list — you're accumulating this debt if you see:
- A page or request handler that reads raw data and *computes* (scans, models, aggregates) instead of reading a prepared artifact.
- More than one file written as the "latest X" with readers opening them directly.
- A second copy of a helper you already have (`_optional_float`, `_sha256_file`, `_unique_strings`, a freshness check…).
- `except Exception: return empty` on a *required* input.
- A "warning" that exists to reconcile states that shouldn't be able to diverge in the first place.

**If the next project starts with foundations 1-9 as conventions and runs the milestone checkpoint, the day-long retrofit does not happen.**
