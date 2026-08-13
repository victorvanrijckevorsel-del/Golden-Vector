# Session state — 2026-08-13, before Victor's machine restart

Everything below is committed and pushed. Nothing is held in a running process,
a scratch file, or an agent's memory. Read this first after the restart.

## Where the work is

| Commit | What |
| --- | --- |
| `e42d03a` | Five miners added to the universe (Victor's list) |
| `a5a6a3f` | `visually-hidden` fix + the emitted-class-has-no-CSS ratchet guard |
| `17a0e59` | Redesign Phases 5–6, release review (17 fixes), incident record, gold marking |
| `1df7f11` | Complementary review of Phases 1–4 (27 fixes) |

`dev-vic` is pushed and clean. `naukri.md` is Victor's personal file — untracked
on purpose, never stage it.

## DONE and verified

- **All six redesign phases shipped.** Ticker page, Finder, Tools A–D, Options,
  Portfolio, Lab, Scorecard.
- **Gold marking restored** (Victor's finding): gold edge on the six dial-driven
  cards, `◆` on the eleven dial-driven rows, scenario values in the gold accent,
  nothing on fixed rows. Derived from each row's Basis text so symbol and words
  cannot disagree. Clean at 1440 / 1024 / 390 px.
- **`visually-hidden` was defined nowhere** while being emitted four times, so
  screen-reader-only labels and two `role="status"` live regions printed as page
  text. Fixed and verified in-browser at 1×1px.
- **New guardrail** `test_every_emitted_class_is_painted_or_a_declared_known_gap`
  closes the reverse of the dead-CSS check — the exact blind spot that let the
  gold marking ship unpainted. It is a ratchet; `KNOWN_UNSTYLED_CLASSES` can only
  shrink. It currently records 52 unstyled classes, 32 of them the score builder.
- **Gates:** focused release selection **1759 passed**; the one failure was the
  Lab ledger guardrail, fixed (see below) and re-verified with lab validation 24,
  scorecard 16, foundations 17 green. Ruff clean. Design tokens 25 green.
- **Five miners added and refreshed**: GMD.AX, BC8.AX, ARTG.V, DSV.TO, AMRQ.L.
  Tool A ranks DSV.TO 9th, BC8.AX 13th, ARTG.V 28th, GMD.AX 38th. AMRQ.L is
  correctly score-withheld (`LOW_LINKAGE_STRUCTURAL_SIGNAL`).
- **Ledger reconstruction corrected.** The first reseed used a flat config shape;
  rewritten in place with the nested `gates` schema, sourced from
  `lab/validation.py`. Never append — appending doubles every signal's `n_trials`.

## NOT done — pick up here

1. **Merge `dev-vic` → `main`** per the repo workflow (see below; may already be
   done in the same session this file was written — check `git log main`).
2. **Options have never captured inside US market hours since the data loss.**
   The 10:34 and 13:00 builds were correctly BLOCKED by the benchmark quality
   gate (`GDX=SPARSE; GDXJ=LOW_LIQUIDITY`) because they ran pre-market. Nothing
   is broken. Run **after 14:30 London / 09:30 New York**:
   ```
   venv/Scripts/python.exe main.py market-hours-refresh
   ```
   The background job that would have done this at 14:32 died with the restart.
3. **Scheduled tasks are still not installed.** Agent-spawned UAC elevation
   silently no-ops on this machine (Defender suspected); the script is proved
   correct — an unelevated dry run fails only with "Access is denied". Victor
   must run, in an elevated terminal:
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File "<scratchpad>\install_tasks.ps1"
   ```
   The scratchpad path dies with the session — if it is gone, the installer is
   `main.py install-scheduled-refresh-tasks --apply` plus a `schtasks /Create`
   for `scripts/backup_data.ps1` at 23:30 as SYSTEM. **Until this is installed
   there is no automatic refresh and no nightly backup.**
4. **400 fixture files pollute the data store.**
   `data/intermediate/status/model_states/model_state_r000000…r000399.json`, all
   stamped 2026-01-01, left by an out-of-repo perf measurement. Because the
   current pointer is `incomplete`, the reader falls back to them and every page
   header reads "Updated Dec 31, 7:00 PM ET · data may be stale". The code is
   right; the store is polluted. **Only Victor deletes under `data/`**
   (incident 2026-08-13):
   ```
   Remove-Item "C:\Users\Emanuel\code\Golden-Vector\data\intermediate\status\model_states\model_state_r*.json"
   ```
5. **Open decision from Victor — mock-fidelity pass.** Ticker-page-only,
   platform-wide for the shared primitives (recommended), or score-builder-only.
   Detail in `gold_marking_gap_2026-08-13.md`.
6. **Open decision from Victor — mining inputs for the five new tickers.**
   Tool B/D and their corporate-finance sections stay INCOMPLETE until
   production, AISC, cash cost, royalty rate, sustaining capex and reserve life
   are entered. Yahoo does not carry these. Options: Victor supplies them, or
   they are researched with sources recorded, or the names stay
   gold-behaviour-only. **Do not invent them.**

## To bring the platform back up

```
cd c:\Users\Emanuel\code\Golden-Vector
venv/Scripts/python.exe main.py workspace --port 8899
```
Then open <http://127.0.0.1:8899>. The server reads `config/universe.yaml` at
startup, so it must be restarted after any universe change.

## Standing rules that bit us this week

- **Never `git clean`; never recursively delete under `data/`.** Incident
  2026-08-13 destroyed two months of option-chain history; NVMe TRIM makes it
  unrecoverable. Deletion is Victor's alone, by hand.
- **Compare against the mock, not only the prose derived from it.** The
  requirements doc had silently dropped the mock's defining visual rule, so every
  review passed while the page was wrong.
