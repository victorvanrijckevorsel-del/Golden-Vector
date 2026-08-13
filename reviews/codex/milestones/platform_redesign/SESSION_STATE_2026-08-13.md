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
   is broken. `market-hours-refresh` carries its own guard and **SKIPS outside
   10:00–15:45 New York** — deliberately, so the unsettled first half-hour after
   the open never becomes a signal. A 14:32 London attempt was refused with
   "09:36 ET is outside 10:00-15:45 ET". So run it **between 15:00 and 20:45
   London**:
   ```
   venv/Scripts/python.exe main.py market-hours-refresh
   ```
3. ~~Scheduled tasks are not installed.~~ **DONE 2026-08-13 14:54.** All four
   registered as hidden SYSTEM tasks, and the superseded visible-console
   "Market Refresh 1600/1930" pair was removed:
   - Golden Vector Data Refresh - First Open
   - Golden Vector Data Refresh - US Post Close
   - Golden Vector Data Refresh - Retry Heartbeat
   - Golden Vector Data Backup (nightly 23:30)

   It had failed all session for a real reason that only became visible once
   elevation worked: the task XML carried
   `<LogonType>ServiceAccount</LogonType>`, which is a TASK_LOGON_TYPE constant
   in the COM API but **not** a value in the Task Scheduler XML schema, so
   `schtasks /Create /XML` rejected the whole file — "(52,35):LogonType:
   ServiceAccount". Fixed in `windows_scheduled_refresh.py`; the test that had
   *asserted* the broken form now asserts its absence.

   Note for the future: an unelevated `schtasks` failing with "Access is denied"
   proves nothing about the XML — it checks permissions before it parses. And a
   normal shell cannot see these tasks at all: `schtasks /Query /TN "Golden
   Vector Data Refresh - First Open"` answers "Access is denied" (they exist,
   hidden and SYSTEM-owned) rather than "cannot find".
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
5. ~~Open decision from Victor — mock-fidelity pass.~~ **CLOSED 2026-08-13 by
   Victor: DROPPED. Do not do it, do not re-propose it.** His words: "i'm tired
   of doing this. Dont do it anymore". This covers the whole remaining
   mock-fidelity backlog — score-builder stylesheet, table density, disclosure
   cards, section header badges, group headers, per-section ledes.

   The page is functionally correct and passes its tests; it simply does not
   match mock v3's density. That is now an accepted permanent difference, not a
   defect and not a deferred task. `KNOWN_UNSTYLED_CLASSES` stays as a ratchet
   guard so nothing gets *worse*, but its 52 entries are no longer a backlog to
   burn down. Any future agent reading `gold_marking_gap_2026-08-13.md` should
   treat its "Awaiting Victor's scope decision" section as answered: **no.**
6. ~~Open decision from Victor — mining inputs for the five new tickers.~~
   **CLOSED 2026-08-13: all five ABANDONED**, on Victor's rule "Abandon any
   names that requires to make something comlicated". They stay
   gold-behaviour-only — Tool A ranks them, Tool B/D report INCOMPLETE, and that
   INCOMPLETE state is now **intentional, not a defect**. Do not enter partial
   figures; do not raise it as a review finding.

   Full research record and per-name reasoning:
   `new_miners_manual_inputs_2026-08-13.md`. Headline: the store has **no
   currency column** and four of the five report in AUD or CAD, so entering them
   would mean an ad-hoc FX conversion — banned by hard rule #1. BC8.AX has never
   disclosed AISC at all. DSV.TO is the only USD-native one and the only
   plausible future candidate.

   Note the correction recorded there: the eleven required fields are *all*
   required (`REQUIRED_MANUAL_FIELDS` = operational ∪ financial), not the six
   this file originally listed — so "enter what we can find" buys nothing.

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
