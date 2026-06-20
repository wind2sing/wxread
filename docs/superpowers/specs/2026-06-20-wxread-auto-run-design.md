# wxread Automatic Daily Run Design

Date: 2026-06-20

## Goal

Add a configurable daily automatic run to wxread Console without modifying the upstream wxread source files or requiring operating-system cron management.

The owner can enable automatic runs and choose a daily time in the web UI. Scheduled executions use the existing saved curl and push configuration, execute the existing main.py through RunService, and appear in the same run history as manual executions.

## Confirmed behavior

- Scheduling is configured in the web console.
- Default time is 01:00.
- Timezone is fixed to Asia/Shanghai for v1.
- The scheduler works only while the console service is running.
- If the service starts after the scheduled time and today's automatic run has not been claimed, it runs once as a same-day catch-up.
- If another run is active when the daily schedule is claimed, the automatic run is skipped for that date.
- Automatic and manual runs share the existing one-active-run rule.
- Automatic runs are marked with trigger scheduled in run history.
- No upstream core file is modified.

## Approaches considered

### External cron

External cron is operationally reliable, but allowing the page to update crontab requires host-level permissions and makes Docker deployment more complicated. It also separates scheduling state from the console database.

### APScheduler

APScheduler offers mature cron semantics, but introduces another dependency and persistent job-store decisions that are unnecessary for one daily job.

### Selected: lightweight in-process scheduler

A small daemon thread checks persisted schedule state at a fixed interval. SQLite provides the durable state and atomic daily claim. This matches the existing single-worker Gunicorn deployment and requires no additional package.

## Architecture

Add a new wxread_console.scheduler module with two responsibilities:

1. ScheduleService
   - Reads the configured schedule from Database.
   - Computes the next run in Asia/Shanghai.
   - Atomically claims today's schedule when due.
   - Loads saved runtime secrets.
   - Starts RunService with trigger scheduled.
   - Stores the scheduling outcome.

2. SchedulerLoop
   - Runs as a daemon thread.
   - Checks every 30 seconds.
   - Stops cleanly when the process exits.
   - Does not contain database or runner business logic.

The Flask application creates one scheduler instance after Database, SecretStore, and RunService are initialized.

The Docker deployment remains one Gunicorn worker. The atomic SQLite claim also prevents duplicate daily claims if an additional process is accidentally started.

## Database changes

Add a singleton schedule_state table:

- id, fixed to 1
- enabled, integer boolean
- daily_time, HH:MM
- timezone, fixed to Asia/Shanghai
- last_claimed_date, local YYYY-MM-DD
- last_result
- last_message
- updated_at

Supported last_result values:

- never
- started
- skipped_busy
- missing_config
- disabled

Database gains:

- get_schedule_state()
- save_schedule(enabled, daily_time)
- claim_schedule_date(local_date)
- update_schedule_result(result, message)

claim_schedule_date must be atomic. It succeeds only when last_claimed_date differs from the requested date, so multiple processes cannot start the same daily job.

## Runner change

RunService.start_background accepts a trigger argument with manual as the default.

Manual page actions continue to use manual. The scheduler passes scheduled. The existing runs table already supports arbitrary trigger strings, so no schema migration is needed for runs.

## Web UI

The configuration page gains a separate Automatic Run panel:

- Enable automatic run checkbox.
- Daily time input.
- Fixed timezone label: Beijing time, Asia/Shanghai.
- Save schedule button.
- Explanation that the console service must remain online.

The schedule form posts to a dedicated authenticated and CSRF-protected route.

Enabling is rejected if no saved WXREAD_CURL_BASH exists.

The Dashboard displays:

- Enabled or disabled.
- Configured daily time.
- Next expected run time.
- Last scheduling result.

Run history renders scheduled trigger as 自动 and manual trigger as 手动.

## Scheduling flow

Every 30 seconds:

1. Read schedule_state.
2. Return if disabled.
3. Convert current time to Asia/Shanghai.
4. Return if current local time is earlier than daily_time.
5. Atomically claim the current local date.
6. If the claim fails, today's schedule has already been handled.
7. Load secrets.json.
8. If WXREAD_CURL_BASH is missing, store missing_config and stop.
9. Call RunService.start_background(values, trigger="scheduled").
10. If RunAlreadyActive is raised, store skipped_busy and stop.
11. Otherwise store started with the created run ID.

This logic provides same-day catch-up after restart without creating multiple runs.

## Error handling

- Invalid daily time returns a Chinese validation message and is not saved.
- Enabling without saved curl returns a Chinese validation message.
- Scheduler exceptions are caught inside the loop and logged through Python logging; the loop continues.
- A busy runner marks that date skipped_busy and does not retry later that day.
- Missing config marks missing_config and does not retry later that day.
- A process restart leaves the schedule configuration intact in SQLite.

## Local and Docker behavior

Local development:

- python -m wxread_console starts the scheduler.
- Disable the Werkzeug reloader to avoid duplicate scheduler threads.

Docker:

- Dockerfile.console continues to run one Gunicorn worker.
- The mounted data directory persists schedule_state.
- If the container is stopped at 01:00 and restarted later that day, the automatic run catches up once.

## Verification

Per the owner's preference, this change will not add automated tests.

Implementation verification will include:

- Python compilation.
- Saving enable/time from the real web page.
- Confirming schedule_state persists in SQLite.
- Using a near-future schedule time with fake curl and a short timeout.
- Confirming exactly one scheduled run record is created.
- Confirming a second scheduler tick on the same date creates no duplicate.
- Confirming manual and scheduled trigger labels display correctly.
- Confirming upstream core files remain unchanged.

## Non-goals

- Multiple schedules per day.
- Weekly schedules.
- User-selectable timezones.
- Editing host crontab.
- Distributed scheduling across many replicas.
- Retrying a skipped busy run later the same day.
