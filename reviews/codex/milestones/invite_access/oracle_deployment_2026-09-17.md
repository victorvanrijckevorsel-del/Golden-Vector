# Oracle login deployment — 2026-09-17

Historical setup record. The research snapshot and two real invitations were
subsequently deployed; see [research publication](research_publication_2026-09-17.md)
for the current state. The initial launch boundary below describes this earlier phase.

## Outcome and launch boundary

The code-only visitor login is deployed at
https://golden-vector.141.147.94.215.sslip.io/login.
This is NOT a completed research-site launch. No research artifacts, holdings,
private notes, provider keys or local databases were uploaded. No real invitations
exist. One synthetic acceptance-test invitation was created and revoked.

Victor approved the dedicated server SSH key, free server/restricted network,
and free server software installation. Research-only upload/sharing rights remain
unconfirmed. Do not infer that approval from the software-installation approval.

## Resources and cost controls

| Component | Verified configuration |
| --- | --- |
| Account | Free Trial / Free Tier; no paid upgrade |
| Region | UK South London, tenancy home region |
| VM | golden-vector-web; VM.Standard.A1.Flex; 2 OCPUs / 12 GB RAM |
| Image | Ubuntu 24.04 Minimal ARM; running Ubuntu 24.04.4 LTS |
| Disk | 47 GB; actual volume detail explicitly marked Always Free |
| Network | Dedicated VCN/subnet/internet gateway; no NAT/load balancer |
| Ingress | TCP 80/443 public; TCP 22 restricted to owner's current IPv4 /32 |
| App | Waitress on 127.0.0.1:8080 only |
| TLS | Caddy 2.11.4; trusted Let's Encrypt certificate; automatic renewal configured |
| Hostname | Free IP-based sslip.io hostname; no domain purchase |

The create wizard displayed a £1.60/month disk estimate and warned that it excluded
tier pricing. The actual created disk is labelled Always Free. The selected VM
fits the current 2 OCPU / 12 GB allowance and storage fits the 200 GB allowance.
Optional Cloud Guard Workload Protection and Custom Logs Monitoring were excluded.
Compute Instance Monitoring remains enabled. No paid account upgrade or paid
provider operation was performed. Oracle's current rules say the card is not
charged unless the account is upgraded. This is not a forever-price or uptime
guarantee: policies can change and idle free instances may be reclaimed.

Official references:

- https://docs.oracle.com/en/learn/cloud_free_tier/
- https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- https://caddyserver.com/docs/install
- https://sslip.io/

## Deployment provenance and isolation

- Application source: `5a63d05233eb1bc19146ef0244ec2beeaf2a6e6e`.
- Code-only archive SHA256:
  `64cf3b40511e192a3c611dd7a45cc038199649d977f7f2c70e48f3328f0431ea`.
- Archive included tracked `golden_vector/`, `config/`, `deploy/`, requirements,
  entry point and selected tests. No `data/`, `.env`, local config overrides,
  private keys, holdings files, reviews or Git credentials were copied.
- The first test run exposed an omitted `tests/test_workspace_app.py` fixture
  helper (34 passed, one import error). Added that file from the same source
  revision, then reran: all 35 passed. Application code was not changed.
- Root-owned `/srv/golden-vector/app` and `/srv/golden-vector/venv`.
- Persistent `/srv/golden-vector/data`; new app/data symlink, no replaced data.
- `gv-web` and `gv-refresh` non-login users; research group `gv-data`.
- Access directory mode 0700, DB 0600, configuration root-owned 0600.
- Web service: strict read-only system filesystem, no new privileges, private
  temporary directory, only access storage writable. Existing repo service reused.
- Dedicated SSH key stays in ignored local `.scratch/oracle-deploy/`; owner is
  Windows account Emanuel, with SYSTEM/Administrators also allowed. Never publish
  its contents. Public key only was supplied to Oracle.
- Password and keyboard-interactive SSH authentication disabled. Cloud and VM
  firewalls restrict SSH to the owner's connection; a changed owner IP requires
  an explicitly reviewed firewall update, not opening SSH to everyone.
- No hosted refresh service installed/enabled. No provider credentials configured.

## Verification

| Check | Result |
| --- | --- |
| Code archive SHA256 on server | Matched |
| ARM Python dependency compatibility | Installed; pip check passed |
| Invite/access + hosted scheduler tests on server | 35 passed |
| HTTPS login | 200; public certificate verification passed |
| Plain HTTP | 308 redirect to HTTPS |
| Correct email/code | Accepted using synthetic test invite |
| Wrong code / mismatched email | Rejected |
| Secure session cookie | Secure, HttpOnly, SameSite Strict, Path=/ |
| Unauthenticated research/API | Redirect to login / 401 |
| Authenticated holdings/private pages and writes | 403 |
| Cross-origin login | 403 |
| Revocation | Prior session and code rejected |
| Repeated incorrect login | 429 rate limit |
| Full VM reboot | HTTPS login returned 200; both services active |
| Firewall persistence after reboot | Public 80/443, restricted SSH retained |
| Browser check | Live email/code login rendered correctly |

`/healthz` checks access storage only. These results do not establish research
freshness or readiness. Caddy renewal is configured; an actual future renewal
has not occurred yet. No backup/restore or external-alert acceptance has passed.

## Remaining work before inviting users

1. Confirm research redistribution permission and owner approval to upload a
   specifically reviewed research-only publication.
2. Prepare a coherent immutable generation via the existing model-state manifest,
   excluding holdings/notes/credentials. Never copy the local data directory
   wholesale or fabricate missing outputs. Verify research pages under gv-web.
3. Configure private backups within free limits; verify off-VM recovery and
   restoration. Establish external availability alerting.
4. Issue the owner's real email-bound code, then invited visitors' codes privately.
5. Separately approve any hosted data-provider configuration/refresh calls. Until
   then, refresh remains disabled and research freshness must be reported honestly.

## Integration inventory

Before this documentation-only milestone: `dev-vic` and `origin/main` were both
at the deployed source revision, with no unmerged local or remote branches.
The only additional worktree is clean/detached `.scratch/invite-baseline` at
`572c10a`, two commits behind main, zero ahead. No competing data-spine or serve
changes require reconciliation. This milestone changes deployment documentation
only; no schema, manifest, analytics or application behavior changes.
