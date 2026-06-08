# Option Signal Market-Hours Refresh

Option signals are only useful when the option chain is fresh. Golden Vector
therefore provides a scheduler-safe command:

```powershell
python main.py market-hours-refresh
```

The command checks the current time in `America/New_York`. It runs the normal
`python main.py refresh` only when all of these are true:

- today is a normal US equity trading day;
- the current Eastern Time is inside the configured market-hours window;
- the normal refresh lock can be acquired.

Outside that window it exits successfully without starting a refresh. This lets
Windows Task Scheduler run the command on weekdays while the Python guard handles
US holidays and daylight-saving differences.

To print the Windows Task Scheduler commands without installing anything:

```powershell
python main.py install-market-hours-refresh-task
```

To install them:

```powershell
python main.py install-market-hours-refresh-task --apply
```

The default local task times are `16:00` and `19:30`. On a Europe/London machine
that lands during the US trading session for the normal daylight-saving cases.
If the machine uses another timezone, pass local Windows times explicitly:

```powershell
python main.py install-market-hours-refresh-task --times 15:30,18:30
```

Important data-timing note:

- stock/foundation data remains daily-close based;
- option signals are market-hours option-chain snapshots;
- the UI should treat the option signal lanes as fresher intraday context, not
  as a replacement for a new daily stock close.

This milestone deliberately does not add row-level carry-forward, volatility
surface modeling, or a server-side background scheduler.
