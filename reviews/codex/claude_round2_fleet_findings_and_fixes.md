# Round-2 adversarial fleet — findings + fixes (2026-06-12)

Second fleet after the storage/compute review: 6 lenses (model math, option
math, lab statistics, web surface, test quality, concurrency). The three
MATH lenses died twice on session limits/connection resets and are running
a third time — their findings will be appended. Web/test/concurrency
returned in full; every fix below is committed and gated.

## Workspace outage (user-reported) — root cause + fix

The 503s on `/`, `/candidate-finder`, `/option-trading` were NOT a code or
data bug: the two long-running servers (ports 8780/8788) were started
before the schema-v3 milestones shipped — old in-memory code crashed on the
new manifest. A fresh app instance returned 200 with the designed
"unavailable until a market-hours refresh" notices on every page. Fix:
killed both stale servers, started one current server on 8788 (all pages
200), and scheduled a one-shot market-hours refresh (15:53 local) to mint
v3 option artifacts. Codex's handoff interpretation ("partial refresh
state, fail-closed working") was right about the data layer, but missed
that the 503-vs-notice difference was server staleness.

## Web surface lens — substantially CLEAN

14 attack classes verified OK end-to-end through a real WSGI harness:
static-file traversal (10 payloads incl. encoded/backslash/drive-letter),
stored XSS via notes (script/img payloads escaped at render), 404/search/
bucket/query echo escaping, open redirect via return_to (5 payloads),
scenario numeric parsing (9 edge cases), lot-id route edges, download
endpoints, portfolio 403 gating. Two findings, both fixed:
- **MEDIUM:** `?size_mode=budget&budget=inf` 500d the sizing calculator
  (`int(inf)` deep in sizing math) → non-finite now parses as None and
  falls into the existing "Invalid budget" note.
- **LOW:** malformed POST charset → generic 500 → decodes with
  errors=replace.

## Concurrency lens — 13 findings, the serious ones fixed

- **HIGH (fixed):** no PermissionError retry on atomic publishes — on
  Windows, `os.replace` fails the moment ANY reader holds the destination
  open, and the server reads latest aliases on every request. All three
  shared atomic writers (+ replay_manifest's three) now retry briefly on
  PermissionError only, then fail loud.
- **MEDIUM (fixed):** lock acquisition was read-check-write with a real
  race window (two workspace servers demonstrably run in practice) — both
  acquisition paths now serialize through an O_CREAT|O_EXCL sidecar with a
  re-check under it; crash leftovers older than 60s are broken.
- **MEDIUM (fixed):** PID reuse could leave the lock RUNNING forever
  (refresh button dead until a hand-delete) — 2h runtime ceiling recovers
  it with an explicit "stale after ceiling" message.
- **MEDIUM (fixed, proven by the agent):** a torn final ledger line MERGED
  with the next append — the registration was then silently quarantined and
  n_trials undercounted (weakens multiple-testing corrections). Appends now
  newline-guard; quarantine rewrites the ledger clean. Regression test
  proves both registrations survive a torn line.
- **MEDIUM (fixed):** manual vintage recorder racing the refresh-end
  recorder could lose rows (read-modify-rewrite) → manual runs defer to a
  live refresh owned by another process.
- **MEDIUM (fixed):** prune-runs hardened — refuses --apply during a live
  refresh; 24h age floor on run-dir candidates (a blocked publish leaves
  its run dir unreferenced and was deletable same-day).
- **LOW (fixed):** unbounded option-trading cache (one multi-MB generation
  leaked per refresh) → bounded LRU(4); stale-lock recovery write can no
  longer 500 a GET.
- **Deferred (documented):** per-request manifest TOCTOU (~20 independent
  manifest reads per Finder request — needs payload-threading refactor);
  manifest republish without lock in fetch-fundamentals/portfolio; dial
  meta into parquet attrs; sqlite connection closing + verification-import
  UNIQUE constraint.

## Test-quality lens — 8 findings, the actionable ones fixed

- **MEDIUM (fixed):** per-file serve guardrails proven bypassable (pandas
  method-call arithmetic `.add()/.div()`, `df.eval`, `np.where`, inline
  `or`-fallback) and covered only 4 of 20+ modules → new all-modules token
  walker with an explicit sanctioned allowlist (locks today's audited
  state; new violations fail).
- **MEDIUM (fixed):** `rank_in_bucket` — the ONE rank the /lab page sorts
  on — had zero behavioral tests → deliberate-twins tie-break, insufficient-
  last, dense-ranks test added.
- **LOW (fixed):** both `pytest.raises(Exception)` narrowed; mixed
  healthy+degraded loss summation pinned; conftest autouse socket guard
  (a forgotten monkeypatch can never silently hit Yahoo); dead
  serve/lenses.py + its 18 tests deleted (1,063 ≠ live-behavior count);
  config sentinel test with literal floors.
- **Deferred:** fixture-side Tool B formula copy in tests/helpers.py
  (cross-check test); healthy-control gaps in 2 Tool B exclusion tests.

## Net effect

35 findings round-2 (so far), 18 fixed across 4 commits, the rest
documented above as deferred with reasons. Math-lens results pending.
