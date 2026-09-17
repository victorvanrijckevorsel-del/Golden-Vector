# Oracle research publication — 2026-09-17

## Outcome and authority

The user explicitly approved the research-only upload and asked to continue until
the website worked. Two previously approved email-bound invitations remain active
and unchanged; do not record their addresses or codes in Git. This milestone
publishes research, not private holdings/notes, data-provider credentials, automatic
refresh, paid infrastructure or new third-party services. It makes no legal
determination about provider licensing or guarantee of uninterrupted free hosting.

Live site: https://golden-vector.141.147.94.215.sslip.io/

## Exact publication

- Main source refresh: `20260916T230003Z-refresh-b28c66d1`.
- Full refresh completion: `2026-09-16T23:10:03.839509Z`; date preserved honestly.
- Active release: `/srv/golden-vector/releases/research-20260917-v2/data`.
- Archive SHA256: `c6f312dd2efb3c5dc0dd9bd2fc0f506196c87d6124b8747ecf0b5a8df69f5404`.
- Compressed bytes: 61,383,413; 179 inventoried files.
- Main source application remains `5a63d05`; this milestone adds deployment and
  validation tooling only, not changed analytics or application readers.
- Every selected research artifact retains its original immutable path, checksum,
  row count and refresh identity. A scoped manifest records the source hash and
  explicit portfolio exclusions; no missing research is hidden or fabricated.
- Manual SQLite is built from allowlisted tables into fresh pages, not copied and
  then deleted from: 65 company inputs, 671 source facts, 65 calendar rows; no stock
  notes and no source/calendar free-text notes. Original database hash unchanged.
- The two-row GDX/GDXJ benchmark artifact contains no holdings. Its location under
  `output/portfolio/` is a historical naming detail, not permission to copy that
  directory. The ticker comparison-chart reader also needs two compatibility
  files; these are copied from the selected run's immutable benchmark histories.
- Machine-generated option liquidity/availability warnings in `notes` are research
  output, not personal stock notes; their producer was inspected.

## Safety and recovery

The active `app/data` symlink switches atomically to the new release. Its `access`
entry links to the existing `/srv/golden-vector/data/access`. The previous data
directory and v1 release remain intact. Website account reads research but can
write only access storage under the unchanged systemd restrictions. No data was
deleted. No Oracle resources, account tier or paid-service configuration changed.

The v2 archive and its inventory are retained locally outside Git and on Oracle.
Restoring the archive into a fresh Oracle release directory and serving as the
restricted account passed. A consistent private SQLite access backup was copied
off the VM, restricted to the Windows owner/SYSTEM/Administrators, restored into
an independent in-memory database, and passed integrity checking with both real
invitations intact. Recurring backups and external alerting remain future work.

## Acceptance evidence

- Focused publication + invitation + hosted scheduler suite: **49 passed**.
- All 179 file checksums and all published Parquet row counts verified.
- Real-data staged checks on both Windows and Oracle ARM as `gv-web`:
  20 research/API/scenario URLs return 200; 3 private paths return 403.
- Nonempty Tool A/B/C/D data; ticker artifact schemas/checksums all OK; GDX/GDXJ
  rebased chart comparisons present. Render checks prohibit network connections.
- Live HTTPS acceptance: authenticated research, source switches and ticker pages
  work; unauthenticated access, private pages, writes, wrong-origin login,
  incorrect codes, revoked sessions and repeated guesses are rejected.
- A real browser signed in with the owner's existing code and displayed Candidate
  Finder with populated results and the original September 16 update timestamp.
- Old login-form CSRF expiry was resolved by opening a fresh GET login form;
  neither real invite needed replacement.
- Service activation initially exposed a brief import-time 502; activation now
  waits for real HTTPS readiness rather than relying only on systemd active state.
- Full analytics regression run: **2,576 passed in 1,197.56 seconds**. This run
  collected the first 12 publication tests; the final focused run (49 passed)
  also includes the two subsequently added manual-coherence/benchmark-copy tests.
- Final v2 HTTPS run: all 20 research/scenario/API URLs passed, with the full
  access/revocation/rate-limit suite also passing. Read-only files verified mode
  0640, `gv-refresh:gv-data`; `gv-web` cannot write the research pointer or manual
  store. Both services are active and enabled for boot.
- Browser reloaded after the final release switch without signing in again:
  Candidate Finder present, 158 displayed table rows, no research-unavailable text.

## Honest limitations

- This is a saved snapshot, not a live/automatically refreshed data feed.
- Lab source publication is August 13; newer behavior output is absent locally.
- Scorecard source has no saved results and renders its existing unavailable state.
- No new results or freshness dates were invented for those optional surfaces.
- Oracle Always Free idle reclamation/capacity and the free IP-based hostname
  remain availability limitations; no artificial activity is configured.

## Integration audit

Before integration: no unmerged local/remote branches relative to `origin/main`.
Main checkout is `dev-vic`; the extra `.scratch/invite-baseline` worktree is clean,
detached at `572c10a`, three behind `origin/main`, zero ahead. No competing data
contract or serve changes exist. Changes here are deployment scripts, their tests,
and documentation; the original production data store is untouched.
