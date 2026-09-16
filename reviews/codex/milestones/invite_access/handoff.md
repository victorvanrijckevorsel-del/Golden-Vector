# Email-and-code website access — in progress

Requested 2026-09-16: Victor wants guests to enter an email address and a code,
with the website available independently of his computer. Hosting must be free;
no domain or hosting account exists. He accepted a separate code for each email.

Scope: all research pages behind one login; guests cannot access the owner's
portfolio, notes, manual editing, or refresh actions. Keep existing local admin
workflow. Codes are generated, email-bound, revocable, and stored only as hashes.

Implementation: separate SQLite access store (no changes to model artifact
contracts); opaque persisted sessions; request limits; HTTPS cookies and CSRF;
one visitor policy reused by routing and UI. Reuse existing WSGI app, static
assets, model-state readers, and scheduled-refresh coordinator. Production server
and deployment instructions will preserve the existing atomic publication path.

Architecture checkpoint: analytical pipeline and current-state manifest remain
authoritative; authentication persistence is transactional, independent of market
refreshes; no public writes to research/manual/portfolio data.

Hosting finding: no existing deployment or host connection. Render Free sleeps
after 15 minutes and has no persistent disk. Oracle Always Free offers persistent
compute but requires account creation, available capacity, and is subject to idle
reclamation; it cannot be presented as guaranteed uptime. Need a verified free
host/account before publishing. Do not purchase, enable paid resources, upload
private holdings, or fetch live market data without separate authorization.

Starting state: dev-vic, clean working tree. No changes to production data.
## Validation and integration checkpoint

- 144 focused access/scheduler/workspace tests passed before the final browser fixes.
- 63 access/scheduler/benchmark tests passed after those fixes (35 new access/scheduler cases).
- Browser/Waitress fixture smoke: sign in/out, desktop/mobile, no horizontal overflow,
  no JavaScript errors, no portfolio navigation, direct portfolio route returns 403.
- Browser testing caught/fixed Origin:null from no-referrer and favicon redirects
  rotating the login CSRF cookie. Referrer policy is now same-origin; favicon is public 204.
- Guest manual-store reads use SQLite mode=ro; local editing/migrations remain unchanged.
- Existing research smoke: all ten research/API routes returned 200, private portfolio
  returned 403; no guest portfolio link or refresh form. External network was blocked.
  Evidence: `real_workspace_smoke.json`. Temporary demo invites exist only in ignored
  scratch databases, not production access storage. Real-data smoke invite was revoked.
- Ruff passed on every changed Python module.
- Full offline suite running; initial collection error was a pre-existing test importing
  the removed `_build_beta_strip_svg`; updated it to the existing shared distribution-strip
  builder, preserving the assertions. The 28 benchmark tests now pass.
- Full-suite failures still being investigated; do not assume a clean regression result.
- Interim full-suite failures identified: three Candidate Finder scenario test doubles
  rejected the new `read_only` keyword; updated their signatures to match the reader.
  The CSS ownership guard caught the standalone login stylesheet; moved the scoped
  login rules into existing `css/pages.css` and reused canonical tokens/base controls.
  All four cases plus the full design-token suite now pass (28 tests). No analytics
  production-code fix or new chart implementation was needed.
- Final workspace/manual-data/access/scheduler focused run: 159 passed (169.36s).

Pre-merge inventory (after fetch): `main`, `dev-vic`, `origin/main`, `origin/dev-vic`
all at 572c10ab16fa6092efc7741bf9eb367d5c3c1b22; ahead/behind 0/0. No local or remote
branch unmerged into origin/main; origin/codex-source-mode is already merged.
Initially one worktree only (this checkout, dev-vic), base 572c10a. A detached baseline
checkout was subsequently created at `.scratch/invite-baseline`, also 572c10a (0/0),
for diagnostic comparison; it has no source edits or pending branch work.
Therefore no active-branch
touched-file overlaps to reconcile. No analytical artifacts/schema/publication contracts
changed. Review final diff/status again before commit/integration.

Deployment templates: Caddy HTTPS proxy, loopback-only Waitress, web service read-only
outside access storage, separate optional persistent refresh coordinator using existing
policy. Hosted refresh defaults disabled; no provider calls authorized or performed.
Linux/ARM runtime, systemd permissions, HTTPS, reboot recovery, backups, monitoring,
and DNS still require the actual server. See `deploy/README.md` for exact launch gates.
