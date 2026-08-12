# Phase 1 — adversarial review, round 1

- Date: 2026-08-12, on dev-vic `b542fe0` (diff reviewed: `c7e90db..b542fe0`)
- Method: review-loop workflow — diverse-lens parallel reviewers, then one default-refute
  skeptic per raw finding; only verified findings survive. 29 agents total.
- Result: **24 raw findings → 10 confirmed** (14 refuted by verification).

## Confirmed findings (all being fixed in the round-1 fix commit)

| # | Sev | Where | Finding |
|---|---|---|---|
| F0 | MEDIUM | corporate.py `_dial_state` + gold-dial.js | The new out-of-range State A gate sets `payload.enabled=False`, which trips the pre-existing JS branch that overwrites the five line-metric spot cells with the reason text — erasing five trustworthy published values (linearity is verified at true spot by the producer) and contradicting "Spot values below are the published ones". Fix: split artifact availability (`enabled`) from scenario availability (`scenario_enabled`); out-of-range keeps cells painted and only disables the slider. |
| F1/F2 | MEDIUM | gold-dial.js `render()` + card markup | With one-value-per-card, an active scenario leaves the scenario number sitting above a card basis line that still reads "fwd @ spot $X/oz" — the surviving number is mislabelled. Fix: JS rewrites each card basis to "fwd @ scenario $Y/oz · baseline …" while moved, restores exactly on return/reset. (Two lenses filed the same defect; one fix.) |
| F3 | LOW | charts.py gridlines | Nice-step finer than a mode's decimals duplicates axis labels (count mode span 3 → "1","1","2","2"). Fix: per-mode `min_step` clamp. |
| F4 | LOW | sections tests | `_price_currency` disagreeing-currency branch untested. Fix: mixed USD/CAD case → chart withheld. |
| F5 | LOW | overlay tests | Price mode's widened 76px gutter pinned by no test. Fix: tick-x assertions for price (76) and indexed (48). |
| F6 | NIT | .gitignore | `.scratch/` not ignored. Fix: ignore it. (`naukri.md` at repo root also flagged as unrelated — surfaced to Victor, not touched: user file.) |
| F7 | NIT | sections tests | Bare "Share price" no-drawable fallback label asserted nowhere. Fix: add the case. |
| F8 | NIT | charts.py embed | Overlay embed carries a `base` key no consumer reads, pinned by 5 tests as if live. Fix: remove key, update tests. |
| F9 | NIT | corporate.py | `disabled_attr` and `dial_unavailable` are the same predicate twice. Fix: folds into the F0 refactor (one `scenario_enabled` predicate). |

## Notable refutations (why 14 died)

Recorded in the workflow journal (`wf_f3ad4ecd-359`); the surviving set above is the complete
actionable list. Verification downgraded F0 from HIGH to MEDIUM: with shipped config
(range $2,000–$6,000) and gold near $4,477 the trigger is latent, and no wrong number is ever
shown — correct data is replaced by an explanatory string. It is fixed anyway (blast radius is
every ticker page at once if spot leaves the band).

Round 2 of the loop runs after the fix commit; the gate closes only when a round returns zero.
