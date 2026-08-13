# Automatic Data Refresh

Golden Vector can refresh the complete model automatically without keeping the
workspace or a terminal window open. The scheduler invokes the same atomic
`refresh` pipeline as the manual button, so its single-writer lock, validation,
and all-or-nothing model-state publication still apply.

## Windows setup

Preview the three hidden scheduled tasks without changing Windows:

```powershell
python main.py install-scheduled-refresh-tasks
```

Install them once from an elevated terminal:

```powershell
python main.py install-scheduled-refresh-tasks --apply
```

Both forms print the resolved interpreter, script, and working directory the
tasks will use. Run the command with the PROJECT's interpreter (its `venv`), not
a system Python: `--apply` verifies that the resolved interpreter can import the
project and refuses to install anything if it cannot, because tasks built on the
wrong interpreter fail silently every day. If any task fails to register (the
usual cause is a non-elevated terminal), the ones already created in that run are
removed again and the superseded tasks are left untouched.

The tasks run with `pythonw.exe` as the Windows SYSTEM account, so no terminal
window appears and the refresh does not depend on a signed-in browser session.
During installation, the two fixed-name tasks created by the former
visible-console installer are removed if present, preventing duplicate checks
and stray terminal windows.
They are configured to start when available, ignore overlapping starts, and:

- check five minutes after startup, sign-in, resume, or each new local day, at most
  once per local day;
- check after 5:00 PM New York time on US trading days;
- wake the computer for the post-close check when Windows and the hardware allow it;
- keep a separate all-day 15-minute heartbeat available so even a long-running
  refresh can still retry after 15, 30, and 60 minutes if it eventually fails.

A shutdown computer cannot be woken. Sleep or hibernation wake also depends on
Windows wake-timer and firmware settings.

### Supported machine timezones

The post-close task starts at 21:00 UTC and repeats through the Eastern
daylight-saving window, but Task Scheduler evaluates its weekday set in the
machine's LOCAL days. That is correct anywhere in the Americas or Europe, where
21:00 UTC still falls on the same local weekday. On a machine at roughly UTC+7
or further east, 21:00 UTC on a Friday is already Saturday locally, so the
Friday post-close check never fires. The coordinator's own trading-calendar
guard is unaffected — only the wake-up is missed, and the next first-open or
heartbeat check picks the refresh up.

Reinstall the tasks (`python main.py install-scheduled-refresh-tasks --apply`)
after moving a machine across that band, since the stored trigger boundaries are
computed at install time.

### Environment overrides

The tasks run as the Windows SYSTEM account, so environment variables set in
your USER scope (for example `GV_PORTFOLIO_ENABLED`) are invisible to them. Set
any override the refresh needs at MACHINE scope instead, otherwise the scheduled
run and the manual run will not see the same configuration.

## Portable coordinator

The timing policy is not embedded in Windows. A future cloud scheduler can call:

```powershell
python main.py scheduled-refresh --trigger first-open
python main.py scheduled-refresh --trigger post-close
python main.py scheduled-refresh --trigger retry
```

The coordinator stores its small decision state atomically, handles US holidays
and daylight-saving time, and refuses duplicate work. It launches the existing
background refresh rather than fetching or calculating data itself.

## What users see

The workspace header shows the latest successful model publication discreetly,
plus a running or failed-attempt state when relevant. A failed attempt never
replaces the previous coherent model state.

Options use the latest complete valid snapshot per ticker. A current failure for
one ticker can retain that ticker's prior verified chain while successful tickers
advance. A successful `NONE_LISTED` result is authoritative and does not revive
old contracts. The UI labels carried data as latest available, shows its Eastern
collection context once, and gives a stronger warning at three US trading days old.

## Legacy command

`market-hours-refresh` and `install-market-hours-refresh-task` remain available
for compatibility with older local setups, but the unattended coordinator above
is the recommended installation.
