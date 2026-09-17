# Invite-only Golden Vector

Status (2026-09-17): **secure login deployed; research publication not launched.**
The Oracle server and HTTPS login are running at
https://golden-vector.141.147.94.215.sslip.io/login.
No research data or provider credentials have been uploaded, and no real visitor
invitations have been issued. Research sharing approval, data acceptance, backups
and availability alerting remain launch gates. See the
[deployment record](../reviews/codex/milestones/invite_access/oracle_deployment_2026-09-17.md).

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
| `/srv/golden-vector/data` | Persistent volume; never replace it during code deployment |
| `app/data` | Symlink to the persistent data directory, created only in a fresh checkout |
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
rights separately before running an initial refresh. No data has been uploaded.

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
- Establish private backups and an external availability alert before relying on
  the site. Neither has been configured yet. Include the access DB, coherent
  research generation, and append-only history. Use an SQLite-aware backup or
  stop writers briefly; never copy an actively changing SQLite file by itself.
  Keep an independent copy off this VM and test restoration. Verify any cloud
  backup allocation is within the free account allowance before enabling it.
- Deploy code without replacing persistent data. Schema compatibility must be
  checked before rollbacks. Never run `git clean` or recursive data deletion.
- These templates do not enable background refresh, authorize provider use,
  upgrade the cloud account, or register a paid domain. The deployment record
  identifies the explicitly approved server and firewall changes already made.
