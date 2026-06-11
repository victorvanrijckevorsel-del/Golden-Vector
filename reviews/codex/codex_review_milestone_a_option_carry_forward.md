# Codex Review - Milestone A Option Carry-Forward

Verdict: READY WITH ONE MINOR HARDENING FIX

Reviewed commit: `9f185d1` (`Milestone A: carry forward last good option snapshot when publish gates block`)

Focused test run:

```text
python -m pytest tests/test_option_carry_forward.py -q
16 passed
```

## Summary

Milestone A is structurally sound. The refresh now separates fresh option publishes from blocked option publishes, carries forward a verified prior option artifact set when the market snapshot is blocked, avoids trusting mutable `latest` aliases, and gives the UI a shared option-freshness message. The implementation follows the main architecture rule: readers consume the manifest-resolved artifact set, not request-time option scans.

The one issue I would harden before calling this fully locked is snapshot self-consistency inside the carried option artifact set.

## Finding 1 - Mixed carried snapshot ids are only warned, not rejected

Severity: MEDIUM

Files:
- `golden_vector/app/model_state.py:1001`
- `golden_vector/app/model_state.py:1083`
- `golden_vector/app/model_state.py:340`
- `golden_vector/app/model_state.py:937`
- `golden_vector/app/model_state.py:1290`

`_resolve_option_carry_forward` correctly verifies that all ten option artifacts exist, are immutable, pass sha256, match the current schema, and share one `source_run_id`. However, when the carried artifacts expose multiple `snapshot_refresh_run_id` values, the resolver only appends a warning:

```python
elif snapshot_run_ids:
    warnings.append(
        "Carried option artifacts do not share a single options snapshot id: "
        + ", ".join(sorted(snapshot_run_ids))
        + "."
    )
```

That warning does not necessarily make the manifest incomplete. The manifest state is only downgraded when required artifacts are missing, alignment status is not OK, or a warning matches `_is_required_health_warning`. A mixed carried option snapshot can therefore still publish as a complete current state.

Why this matters:

Carry-forward is meant to preserve the last coherent option snapshot when today's option data is blocked. If the previous manifest's option artifacts were somehow mixed across multiple option snapshots, carrying them forward as complete means the app can present a stitched option view: selected candidates, overview rows, charts, and signal summary may not come from the same underlying chain snapshot.

Recommended fix:

Require carried option artifacts to share one `snapshot_refresh_run_id`, at least across `REQUIRED_OPTION_ARTIFACT_NAMES`. I would prefer the stricter version: all ten `OPTION_ARTIFACT_NAMES` must share one snapshot id, because the optional chart frames are rendered together with the required detail frames.

Suggested implementation shape:

```python
if len(snapshot_run_ids) != 1:
    return None, (
        "Previous option artifacts do not share a single options snapshot id: "
        + ", ".join(sorted(snapshot_run_ids))
        + "."
    )
```

If Claude wants a softer behavior, the minimum acceptable alternative is to mark the manifest `state="incomplete"` when this warning exists. I think rejecting carry-forward is cleaner: a carry-forward set is either coherent or unavailable.

Required test:

Add a regression fixture where the previous manifest has all ten option artifacts with:

- the same `source_run_id`
- valid paths
- valid sha256
- current schema version
- non-empty required frames
- but two different `snapshot_refresh_run_id` values across the set

Expected result:

- carry-forward is refused
- `freshness_domains.option_artifacts.status == "UNAVAILABLE"`
- manifest `state == "incomplete"`
- the warning/reason clearly says the prior option artifact set had mixed snapshot ids

## Finding 2 - Add one page-level freshness render assertion

Severity: LOW

Files:
- `golden_vector/serve/overview_option_trading.py:54`
- `golden_vector/serve/candidate_finder_page.py:66`
- `golden_vector/serve/detail_panels.py:211`

The shared freshness box is tested directly, and the detail-panel fallback is tested. I would still add one page-level assertion for either `/option-trading` or `/candidate-finder` proving the carried-forward message appears on the actual user page when the manifest says `CARRIED_FORWARD`.

Why this matters:

The user-facing promise of Milestone A is not only that the data carries forward, but that the user can see that the option prices are from the stored snapshot. A page-level test prevents this from being accidentally removed during later UI work.

Recommended test:

Render one option page using a manifest with:

```text
freshness_domains.option_artifacts.status = CARRIED_FORWARD
```

Assert the HTML contains language equivalent to:

```text
Option prices are from the latest stored snapshot
```

## What I Verified

- `run_option_artifacts_outcome` returns `BLOCKED` without persisting new option artifacts when option signal publish blockers exist.
- Full refresh treats `BLOCKED` as a recoverable option-domain event, records the blocker in stage timings, continues through the remaining pipeline, and passes `OptionPublishBlock` into model-state publishing.
- Carry-forward resolves through the previous model-state manifest and immutable artifact paths, not mutable `latest` aliases.
- Missing, tampered, stale-schema, or absent previous artifacts correctly degrade to `UNAVAILABLE`.
- Two consecutive blocked refreshes keep the original carried source run rather than chaining a new fake option source.
- `summarize_option_freshness` and `render_option_freshness_box` expose clear `OK`, `CARRIED_FORWARD`, and `UNAVAILABLE` states.

## Final Recommendation

Claude can act on the one medium hardening fix first, then optionally add the page-level UI test. I would not redesign the milestone. The architecture is right; it just needs the carried snapshot coherence rule pinned.
