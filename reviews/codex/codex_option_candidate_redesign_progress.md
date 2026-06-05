# Option Candidate Redesign Progress

## Contract Audit

- Current UI slots are produced by `golden_vector.hedge.options_liquidity.build_bucket_slots`, not the older `candidate_puts.build_candidate_slots` path.
- Detail sizing uses `OptionCandidate.bucket` from query params, so the new public bucket IDs should stay side-neutral: `near_atm` and `directional`.
- Existing Candidate Finder uses `slot.candidate is not None` as a side-availability proxy. With Watch candidates becoming selectable, this must change to require `candidate.liquidity_tier == "tradable"`.
- Existing detail rendering exposes rejected candidate quote details and a Half-spread Cost column. The redesign should remove both.
- Current config displays 30/60/90/120. The redesigned primary view should display 60/90/120 only, with non-overlapping flexible DTE bands.
