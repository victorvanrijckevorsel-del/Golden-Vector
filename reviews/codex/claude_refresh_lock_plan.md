# Plan — One refresh at a time: close the CLI/website lock gap

**Author:** Claude Code (Opus 4.8)
**Status:** for Codex review, then build.
**Trigger:** Emanuel clicked the website "Refresh" button during a CLI refresh → a second refresh spawned (the "black window") → the two raced and published a mismatched/INCOMPLETE manifest.

## 1. Root cause (verified first-hand)
A refresh lock **already exists** and is well-built — but it only covers website-initiated refreshes:
- `serve/option_refresh.py:start_options_refresh` (line 159–165) reads the refresh status; if `REFRESH_STATUS_RUNNING`, it **refuses** to start a second one (`already_running=True`).
- `read_option_refresh_status` (line 120–136) **auto-recovers stale locks**: if the recorded PID is no longer alive, it flips the status to FAILED so a crashed refresh doesn't block forever.
- `render_option_refresh_control` (line 290) renders the button **disabled** while `RUNNING`.

**The gap:** the CLI command `cli.py:run_refresh` (line 2614) runs the 6 steps **without ever touching that lock** — it never reads it and never writes a RUNNING status. So a CLI refresh is invisible to the website: the button isn't disabled, and clicking it starts a concurrent refresh. (This is exactly how the mess happened — my `python main.py refresh` timing runs are CLI refreshes.)

## 2. Fix — make the CLI refresh participate in the SAME lock (reuse, don't rebuild)
Wrap `run_refresh` with acquire / check / release using the existing `option_refresh` functions (no new lock system):

1. **Check + acquire at the start:**
   - `existing = read_option_refresh_status(paths)` (this also auto-recovers a stale lock).
   - If `existing.status == REFRESH_STATUS_RUNNING` → print a clear message (`"A refresh is already running (started {started_at}, PID {process_id}). Aborting to avoid a conflict."`) and return a non-zero exit code. **Do not run.**
   - Otherwise write a `RUNNING` status with **this process's** identity: `OptionRefreshStatus(status=REFRESH_STATUS_RUNNING, job_id=<new>, process_id=os.getpid(), started_at=now, command=...)` via `write_option_refresh_status`.
2. **Release on every exit path (try/finally):** refactor the current body into an inner function returning the exit code; `run_refresh` does `acquire → try: code = _inner(...) finally: write terminal status`. Terminal status = `SUCCEEDED` if `code == 0` else `FAILED` (reuse `complete_options_refresh(paths, job_id=job_id, return_code=code)` if its log-path assumptions degrade gracefully for the CLI; otherwise write the status directly). The try/finally guarantees the lock is released even on an early `return` or exception.

**Effect:** CLI and website now share one mutual-exclusion lock:
- CLI refresh running → website status = RUNNING → **button auto-disables** (existing line 290) → user can't click → no duplicate.
- Website refresh running → CLI `python main.py refresh` **refuses** with a clear message.
- Two CLI refreshes → the second refuses.

## 3. Robustness (mostly already handled — confirm)
- **Stale lock / crash:** already covered — `read_option_refresh_status` reclaims a dead-PID lock. The try/finally is the primary release; the stale-PID recovery is the backstop if the process is killed (-9) before finally runs.
- **Check-then-acquire race:** the existing pattern isn't strictly atomic (two starters could both read "not running"). For a single-user desktop tool this is negligible, and the CLI fix matches the existing pattern. *Optional hardening:* atomic create (`open(lock, "x")` / `O_CREAT|O_EXCL`) for a true mutex — note it but don't over-engineer.
- **Naming:** the lock file is `option_refresh_status` but it governs the **full** model refresh. Consider documenting/aliasing it as the general refresh lock; don't rename-churn now.

## 4. Frontend (already works once §2 lands)
The button already disables on `RUNNING` (line 290), so once the CLI writes RUNNING, the website greys it out automatically. Optional polish: make the disabled hint explicit — `"A refresh is already running (started HH:MM). Please wait."`.

## 4b. Move the refresh button to the MAIN page (Emanuel request)
Today the refresh control is rendered only on the **option-trading** pages (`detail_panels.py:211, 221, 373`, `return_to="/option-trading"`), and the POST endpoint is `/option-trading/refresh` (`workspace.py:113`). The **main page** is the Combined overview at `/` (`_render_overview_page`; nav `("combined", "/", "Combined")`). Putting the refresh button behind the option-trading page is unintuitive — it should be on the home screen.

Change:
- Render `render_option_refresh_control(status, return_to="/")` **prominently on the main page** (`_render_overview_page` / its page shell), so the user refreshes from the first screen they see.
- **Route:** add a clean general endpoint `POST /refresh` that runs the same logic as `/option-trading/refresh` (both call `start_options_refresh(paths)` then redirect to a safe `return_to`); point the main-page form at `/refresh`. Keep `/option-trading/refresh` working (or 307-redirect it to `/refresh`) so existing forms don't break.
- The shared lock makes the button **auto-disable on the main page** while a refresh is running (it reads the same status) — no extra work, and it ties directly into §2/§4.
- **Decide (Emanuel's call):** keep the button on the option-trading page too, or remove it now that it's on the main page. Recommend: primary placement on the main page; the option-trading copy can stay (harmless) or be removed.

## 5. Tests (the gate)
- The **main page** (`/`) renders the refresh control; `POST /refresh` from the main page starts a refresh when unlocked and redirects to `/`; the button shows **disabled** while RUNNING.
- CLI `run_refresh` **refuses** (non-zero, no steps run) when status is RUNNING with a live PID — for both a website-started and a CLI-started lock.
- CLI `run_refresh` **acquires** then **releases** the lock on success (terminal status SUCCEEDED) and on failure / each early-return path (terminal status FAILED) — assert the lock is free afterward.
- A **stale** RUNNING lock (dead PID) does **not** block a new CLI refresh (reclaimed).
- Website `start_options_refresh` is refused while a **CLI** refresh holds the lock (the cross-path case that caused the bug).
- Use injected `process_exists` / fake PIDs (as the existing tests do) — no real subprocess.

## 6. Non-goals
- Don't change the refresh steps, ordering, or outputs. Pure concurrency-guard addition.
- Don't queue a second refresh — **refuse** it (simpler, and "once a day" needs no queue).

## 7. Self-review
Reuses the existing, already-tested lock infrastructure rather than inventing a second one (anti-duplication). The only real care points are (a) releasing on **every** exit path — handled by extracting an inner function + try/finally — and (b) confirming `complete_options_refresh` degrades gracefully for the CLI (no website log file), else write the status directly. Both are test-pinned. Low risk, high value: it makes the duplicate-refresh mess structurally impossible from either entry point.
