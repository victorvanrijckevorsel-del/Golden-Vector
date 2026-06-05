# Review — Candidate Finder hardening (commit 49a52b0)

**Reviewer:** Claude Code (Opus 4.8), read-only.
**Verdict: APPROVE — proceed to the UI (Batch 3).** All six focus areas are correctly handled, every one is tested, and two of them directly close findings from my Checkpoint B review (manual-store freshness, the contract test). 41 candidate-finder/related tests pass. No issues.

## The six areas — verified
1. **Corrupt parquet warnings ✅** — `_read_optional_parquet` now returns `(frame, warning)`; on a read error it yields an empty frame **plus** a visible "Tool A/B latest parquet could not be read: …" warning that flows into the screen warnings (and the source's missing run ids flip alignment to `UNKNOWN`). Tested. Corrupt input is now loud, not silently empty.
2. **Cache key file hashes ✅** — the cache key gains `tool_a_latest_hash` / `tool_b_latest_hash` (sha256 of the latest parquets). A `latest` file changing without a run-id change now invalidates the cache — closes the "latest files are mutable" hole. Tested (`..._cache_notices_new_corrupt_latest_file`).
3. **Malformed spec warnings ✅** — unknown preset, invalid `options_side`, invalid `top_n`, and non-list `criteria` all degrade to safe defaults **with a named warning**. Tested (`..._surfaces_invalid_spec_warnings` asserts all of them). A bad URL spec now fails gracefully and visibly.
4. **Zero-weight criteria semantics ✅** — correctly split: **all** weights ≤ 0 → reset to equal; **some** ≤ 0 → those criteria are **dropped** (removed from `selected`, so they affect neither the score nor the coverage denominator) with a "Zero-weight criteria disabled: …" warning. This resolves the edge I was mildly worried about. Tested.
5. **Manual-store freshness warning ✅** — `_manual_freshness_warning` parses the manual store's `as_of` vs the latest Tool B run timestamp and warns "Manual store was updated after the latest Tool B run; rerun Tool B…" when the manual data is newer. **This closes my L-1.** Tested. *(Minor: the run-id timestamp parse takes the leading 16 chars, which works for the `YYYYMMDDThhmmssZ-…` format we use; mildly fragile to a run-id format change — fine for now.)*
6. **Producer-consumer contract test ✅** — `..._configured_source_fields_exist_in_joined_frame` asserts **every** criterion `source_field` in the config resolves to a real column in the joined frame. **This closes my L-3** — a future renamed field can no longer silently turn a criterion into all-missing.

## Other checks
- Warning ordering is sensible: alignment messages → spec warnings → ranking warnings, with the alignment headline surfaced first and de-duplicated.
- No regressions: 41 candidate-finder + option-trading-data tests pass.
- Provenance is now stronger than I asked for (file hashes + manual-freshness + corrupt-source flagging) — good instinct.

## Bottom line
Nothing to fix. The data layer is now genuinely robust to malformed/corrupt/stale inputs, and the criteria contract is locked by a test. **Proceed to Batch 3 (the UI)** — the two views, preset bear/bull lenses, the options-side toggle, the mixed-refresh banner, and the score tooltip. That's the last checkpoint; I'll verify it renders honestly (no "recommended/best" language, the eligible-vs-low-coverage split visible, the tooltip present) and hangs together end to end.
