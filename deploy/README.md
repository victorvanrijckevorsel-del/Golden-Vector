# Invite-only Golden Vector

Status (2026-09-17): **invite-only research is deployed and verified.**
The Oracle server, HTTPS login and research pages are running at
https://golden-vector.141.147.94.215.sslip.io/login.
The owner approved the research-only upload and two separate invitations. The
published main snapshot was completed on 2026-09-16 at 23:10 UTC. No holdings,
private notes or provider credentials were uploaded. Automatic refresh remains
disabled. Lab retains its older August 13 publication; Scorecard has no saved
results in the source and displays that limitation rather than fabricated results.
See the [research deployment record](../reviews/codex/milestones/invite_access/research_publication_2026-09-17.md)
and the earlier [server setup record](../reviews/codex/milestones/invite_access/oracle_deployment_2026-09-17.md).

## Publishing a reviewed saved research snapshot

Run these modules from the repository root with the existing Python environment:

```sh
python -m deploy.build_research_bundle --source . --destination .scratch/oracle-deploy/research-NEW-ID
python -m deploy.check_research_bundle --root .scratch/oracle-deploy/research-NEW-ID --config config
```

The builder refuses an existing destination, unreviewed artifact types, incomplete
generations, checksum mismatches, or manual inputs changed since publication.
It reuses the selected immutable research artifacts, creates a new notes-free
SQLite store, explicitly excludes portfolio artifacts, and records the source
manifest hash and exclusions. It does not modify the original data or claim a new
refresh. The benchmark-only GDX/GDXJ artifact is admitted despite its historical
`output/portfolio/` location; it contains no holdings. Chart compatibility files
come from that same selected run, never a newer mutable alias.

After checking the archive hash on Oracle, extract into a **new** reviewed release
directory. Set research ownership `gv-refresh:gv-data`, directories 0750 and files
0640. Run the checker as `gv-web` using the deployed config before activation.
`deploy/activate_research_bundle.py` atomically switches `app/data` to the verified
release and preserves the previous target. Invitations remain separately stored
at `/srv/golden-vector/data/access`, linked into the release. No original data or
old release is deleted. The systemd writable path remains the access directory.

Keep the research archive and publication inventory off the VM for recovery.
`deploy/backup_access.py` creates an exclusive, mode-0600, SQLite-aware backup;
keep it outside Git with restricted local permissions. A publication-time access
backup has been restored and checked; recurring backups and external availability
alerting are not yet configured.

## What visitors get

Open the HTTPS address, enter an email and its individually issued code, and
browse research. Codes default to 90 days; a browser session lasts at most seven
days. Reissue or revoke immediately invalidates that person's existing sessions.
The owner sends codes privately; this version does not send or verify email.
Someone with both the email and code can sign in, so codes must not be shared.

Portfolio, downloads containing holdings, private stock notes, manual forms,
and refresh actions are not available to visitors. The owner's existing local
workspace remains unchanged. Every new route is private until explicitly added
to the shared visitor policy. Assets contain no secrets. Do not expose the local
`main.py serve` entry point to the Internet.

## Free hosting decision (checked 2026-09-16)

This app needs a continuously running Python process and persistent files.
Render's free service sleeps and loses local files; static-only hosting cannot
run this application as it stands.

Oracle Always Free is a possible no-subscription-cost VM option: the current A1
allowance is 2 OCPUs / 12 GB total and 200 GB of combined boot/block storage.
Use only resources shown as Always Free eligible in the account's home region;
trial credit is not an ongoing free plan. Do not upgrade to a paid account or
create paid resources. Check the final console estimate before provisioning.
Capacity is not guaranteed; Oracle can reclaim idle instances. This is **not a
guarantee of uninterrupted 24/7 service**. Do not generate artificial activity
to evade the idle policy.

The owner must create the account and complete identity/phone/card verification.
Do not send card details or passwords in chat. The owner's Free Tier account is
now configured in its London home region; it has not been upgraded to paid.
A hostname such as `golden-vector.<public-ip>.sslip.io` avoids buying a domain;
the actual hostname depends on the assigned public IP and DNS/certificate checks.
It is not reserved, and a changed IP changes the address. A free DuckDNS name is
another option if the owner creates an account and the preferred name is available.

Official references:

- [Oracle Always Free limits and idle policy](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [Oracle signup requirements](https://docs.oracle.com/iaas/Content/FreeTier/freetier.htm)
- [Render free-service limitations](https://render.com/docs/free)
- [Free IP-based DNS](https://sslip.io/)
- [Caddy HTTPS reverse proxy](https://caddyserver.com/docs/quick-starts/reverse-proxy)

## Host layout and separation

Use a supported Ubuntu Linux image and Python 3.12+ with a virtual environment;
install the repository's `requirements.txt`. Linux/ARM package compatibility and
the actual research workload must be tested on the selected machine before launch.

| Path/account | Purpose |
| --- | --- |
| `/srv/golden-vector/app` | Root-owned checkout; not writable by the website |
| `/srv/golden-vector/venv` | Root-owned Python environment |
| `/srv/golden-vector/data/access` | Persistent private invitation/session store |
| `/srv/golden-vector/releases/<publication>/data` | Verified read-only research snapshot; previous releases retained |
| `app/data` | Atomic symlink to the active release, with access linked separately |
| `gv-web` / group `gv-data` | Non-login website account; research read access only |
| `gv-refresh` / group `gv-data` | Separate non-login data worker; cannot read access credentials |
| `data/access` | Owned by `gv-web`, mode 0700; SQLite file mode 0600 |
| `/etc/golden-vector/website.env` | Public origin; root-owned, mode 0600 |
| `/etc/golden-vector/refresh.env` | Optional worker configuration; root-owned, mode 0600 |

Research directories should be worker-owned, group-readable/traversable; files
normally 0640 and directories 0750. Review generated permissions, not just umask.
Prepare/upgrade the manual SQLite schema offline before starting the web service:
visitor readers open it read-only and never apply migrations. Give the worker ownership of `app/reviews`
if refresh audit outputs need it; keep all application code root-owned.

**Do not copy the local `data/` directory wholesale.** It contains irreplaceable
research history and private portfolio information. Prepare an explicitly reviewed
research-only publication on the server, preserving the current-state manifest,
its immutable referenced artifacts, and required research/manual inputs. Exclude
private portfolio/holdings and stock notes. Do not edit a manifest to hide missing
inputs or upload API keys. Approve any hosted provider calls and confirm data-sharing
rights separately before running an initial refresh. The explicitly approved saved
research publication described above does not enable provider calls.

## Start the website once the account and research data are ready

1. Allocate the eligible VM and persistent storage, create the accounts/layout
   above, and install Caddy using its official package instructions. Never overwrite
   an existing data directory to make a symlink.
2. Initialize access storage as `gv-web` (commands below). Its parent must be writable
   by that account. No production code or secret is included in these templates.
3. Copy `website.env.example` to `/etc/golden-vector/website.env` and set the real
   lowercase HTTPS origin with no trailing slash. Configure the same hostname in
   Caddy. Install the web unit in `/etc/systemd/system/`.
4. Validate the service and proxy before enabling them:

   ```sh
   sudo systemd-analyze verify /etc/systemd/system/golden-vector-web.service
   sudo caddy validate --config /etc/caddy/Caddyfile
   sudo systemctl daemon-reload
   sudo systemctl enable --now golden-vector-web
   sudo systemctl reload caddy
   ```

5. Open only HTTP/HTTPS (80/443) publicly in both the VM firewall and cloud network
   rules. Restrict SSH (22) to the owner's address. Never expose 8080 or 8765.
   Caddy terminates HTTPS and preserves Host; Waitress trusts forwarded scheme/IP
   only from the local proxy. Do not add a public CDN/proxy without rechecking trust.
6. Confirm `/healthz`, HTTPS renewal, and the acceptance tests below. `/healthz`
   checks the access database, **not research freshness**. Monitor the authenticated
   `/api/data-status` using its existing canonical status, and inspect the research
   screens. Do not treat a green login page as proof that research is ready.

## Issue and revoke codes (server terminal)

Run from `/srv/golden-vector/app`. All commands target the server's separate
access database; they do not change the owner's local research or portfolio.

```sh
sudo -u gv-web /srv/golden-vector/venv/bin/python -m golden_vector.access init
sudo -u gv-web /srv/golden-vector/venv/bin/python -m golden_vector.access invite --email guest@example.com
sudo -u gv-web /srv/golden-vector/venv/bin/python -m golden_vector.access list
sudo -u gv-web /srv/golden-vector/venv/bin/python -m golden_vector.access revoke --email guest@example.com
```

The generated code is shown once. Never paste codes into Git, public logs, or URLs.
`invite --email ... --days 365` can choose a longer lifetime. Reissuing replaces
the previous code. Backups contain emails/session material: keep them private.

## Optional background updates

The website itself never launches a refresh. After separate approval for the
data-provider use/configuration, install the refresh unit and `refresh.env`, set
`GV_ENABLE_HOSTED_REFRESH=1`, validate the unit, and enable it with systemd.
The persistent coordinator reuses the existing daily/post-close timing, retry,
single-writer, and atomic model-publication rules. It does not add a second schedule.
Leave it disabled until authorized. A prepared research snapshot can still be served
without enabling the worker; the existing freshness indicator then tells the truth.

## Acceptance, recovery, and remaining launch work

- In an unauthenticated browser, every research page redirects to login and APIs
  reject access. Correct email/code works; mismatched email, revoked/expired code,
  and repeated guesses fail. Sign out and revoke invalidate the session.
- Probe portfolio/download paths and editing/refresh POSTs with a valid visitor
  session: all must be blocked. Verify no owner notes or admin controls appear.
- Check desktop and mobile, proxy-derived IP limits, Secure/HttpOnly cookies,
  HTTPS redirect/certificate, and rejection of a wrong Host. Restart the service
  and reboot the VM: valid sessions should survive, services should return.
- Verify all research routes against the real read-only service filesystem. A
  missing artifact or schema mismatch must fail visibly, not show synthetic data.
- Establish recurring private backups and an external availability alert before
  relying on the site. A publication-time research/archive and access DB recovery
  copy is verified; recurring backups and alerts remain outstanding. Include the
  access DB and coherent hosted research generation. Keep the local append-only
  history separately backed up; it is not copied wholesale to the website. Use an SQLite-aware backup or
  stop writers briefly; never copy an actively changing SQLite file by itself.
  Keep an independent copy off this VM and test restoration. Verify any cloud
  backup allocation is within the free account allowance before enabling it.
- Deploy code without replacing persistent data. Schema compatibility must be
  checked before rollbacks. Never run `git clean` or recursive data deletion.
- These templates do not enable background refresh, authorize provider use,
  upgrade the cloud account, or register a paid domain. The deployment record
  identifies the explicitly approved server and firewall changes already made.
