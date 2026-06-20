# wxread Automatic Daily Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add a persisted, web-configurable daily automatic run in Asia/Shanghai that reuses the existing RunService and run history.

**Architecture:** Store one daily schedule in SQLite and run a dependency-free daemon loop inside the console process. The loop atomically claims each local date before starting RunService with trigger scheduled, which prevents duplicate runs and keeps upstream main.py unchanged.

**Tech Stack:** Python 3.10, Flask, sqlite3, threading, zoneinfo, Jinja, existing vanilla CSS.

**Verification note:** The owner explicitly requested no automated tests. This plan uses compilation and isolated real-process smoke checks instead.

---

## File map

- Modify wxread_console/database.py — persist and atomically claim the singleton schedule.
- Modify wxread_console/runner.py — accept manual or scheduled trigger.
- Create wxread_console/scheduler.py — schedule calculation, daily claim, and daemon loop.
- Modify wxread_console/web.py — create scheduler, add schedule route, and expose schedule view data.
- Modify wxread_console/templates/config.html — add enable/time form.
- Modify wxread_console/templates/dashboard.html — show automatic-run state and next run.
- Modify wxread_console/templates/runs.html — render scheduled as 自动.
- Modify wxread_console/__main__.py — disable development reloader to avoid duplicate threads.
- Modify wxread_console/static/styles.css — style schedule controls and state.
- Modify docs/wxread-console.md — document automatic operation.
- Modify Dockerfile.console — retain one worker and correct its user-creation RUN instruction.

### Task 1: Persist schedule state and support scheduled run triggers

**Files:**

- Modify: wxread_console/database.py
- Modify: wxread_console/runner.py

- [ ] **Step 1: Add the schedule schema**

Append this table to Database.initialize():

~~~sql
CREATE TABLE IF NOT EXISTS schedule_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 0,
    daily_time TEXT NOT NULL DEFAULT '01:00',
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    last_claimed_date TEXT,
    last_result TEXT NOT NULL DEFAULT 'never',
    last_message TEXT,
    updated_at TEXT NOT NULL
);
~~~

After executescript, insert the singleton with INSERT OR IGNORE and utc_now().

- [ ] **Step 2: Add schedule repository methods**

Add these exact public methods to Database:

~~~python
def get_schedule_state(self) -> dict[str, Any]:
    with self.connect() as connection:
        row = connection.execute(
            "SELECT * FROM schedule_state WHERE id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("schedule_state is not initialized")
        return dict(row)

def save_schedule(self, enabled: bool, daily_time: str) -> None:
    with self.connect() as connection:
        connection.execute(
            """
            UPDATE schedule_state
            SET enabled = ?, daily_time = ?, timezone = 'Asia/Shanghai',
                last_result = CASE WHEN ? THEN last_result ELSE 'disabled' END,
                last_message = CASE WHEN ? THEN last_message ELSE '自动运行已关闭' END,
                updated_at = ?
            WHERE id = 1
            """,
            (int(enabled), daily_time, int(enabled), int(enabled), utc_now()),
        )

def claim_schedule_date(self, local_date: str) -> bool:
    with self.connect() as connection:
        cursor = connection.execute(
            """
            UPDATE schedule_state
            SET last_claimed_date = ?, updated_at = ?
            WHERE id = 1 AND enabled = 1
              AND (last_claimed_date IS NULL OR last_claimed_date != ?)
            """,
            (local_date, utc_now(), local_date),
        )
        return cursor.rowcount == 1

def update_schedule_result(self, result: str, message: str) -> None:
    with self.connect() as connection:
        connection.execute(
            """
            UPDATE schedule_state
            SET last_result = ?, last_message = ?, updated_at = ?
            WHERE id = 1
            """,
            (result, message, utc_now()),
        )
~~~

- [ ] **Step 3: Let RunService record its trigger**

Change the signature to:

~~~python
def start_background(
    self,
    environment: Mapping[str, str],
    trigger: str = "manual",
) -> int:
~~~

Pass trigger to database.create_run instead of hard-coding manual.

- [ ] **Step 4: Compile**

Run:

    .venv/bin/python -m py_compile wxread_console/database.py wxread_console/runner.py

Expected: exit code 0.

- [ ] **Step 5: Commit**

Run:

    git add wxread_console/database.py wxread_console/runner.py
    git commit -m "feat: persist automatic run schedule"

### Task 2: Add the dependency-free scheduler

**Files:**

- Create: wxread_console/scheduler.py

- [ ] **Step 1: Implement next-run calculation**

Create next_run_at(schedule, now=None):

- Use ZoneInfo("Asia/Shanghai").
- Parse daily_time with datetime.strptime(..., "%H:%M").
- Return today's configured datetime when it is still in the future.
- Otherwise return tomorrow's configured datetime.
- Return None when disabled.

- [ ] **Step 2: Implement ScheduleService.tick**

Use this flow:

~~~python
def tick(self, now: datetime | None = None) -> str:
    state = self.database.get_schedule_state()
    if not state["enabled"]:
        return "disabled"

    current = (now or datetime.now(self.timezone)).astimezone(self.timezone)
    scheduled_time = datetime.strptime(state["daily_time"], "%H:%M").time()
    if current.time() < scheduled_time:
        return "waiting"

    local_date = current.date().isoformat()
    if not self.database.claim_schedule_date(local_date):
        return "already_claimed"

    values = self.store.load()
    if not values.get("WXREAD_CURL_BASH"):
        self.database.update_schedule_result(
            "missing_config", "缺少微信读书 curl 配置"
        )
        return "missing_config"

    try:
        run_id = self.runner.start_background(values, trigger="scheduled")
    except RunAlreadyActive:
        self.database.update_schedule_result(
            "skipped_busy", "已有任务运行，当天自动任务已跳过"
        )
        return "skipped_busy"

    self.database.update_schedule_result(
        "started", f"已启动自动任务 #{run_id}"
    )
    return "started"
~~~

- [ ] **Step 3: Implement SchedulerLoop**

SchedulerLoop.start creates one daemon thread. Its target:

- Calls service.tick() immediately.
- Catches and logs all exceptions.
- Waits 30 seconds through threading.Event.wait().
- Repeats until stop_event is set.

Use a lock and a stored thread reference so repeated start() calls do not create duplicate threads.

- [ ] **Step 4: Compile**

Run:

    .venv/bin/python -m py_compile wxread_console/scheduler.py

Expected: exit code 0.

- [ ] **Step 5: Commit**

Run:

    git add wxread_console/scheduler.py
    git commit -m "feat: add daily scheduler loop"

### Task 3: Add schedule controls and status to the web console

**Files:**

- Modify: wxread_console/web.py
- Modify: wxread_console/templates/config.html
- Modify: wxread_console/templates/dashboard.html
- Modify: wxread_console/templates/runs.html
- Modify: wxread_console/static/styles.css

- [ ] **Step 1: Start scheduler from create_app**

After RunService creation:

~~~python
schedule_service = ScheduleService(database, store, runner)
scheduler_loop = SchedulerLoop(schedule_service)
scheduler_loop.start()
app.extensions["wxread_schedule_service"] = schedule_service
app.extensions["wxread_scheduler_loop"] = scheduler_loop
~~~

- [ ] **Step 2: Add the authenticated schedule route**

Add POST /schedule:

- Require login and CSRF.
- Read enabled from checkbox.
- Validate daily_time by datetime.strptime(value, "%H:%M").
- Reject enabling when SecretStore has no WXREAD_CURL_BASH.
- Call database.save_schedule().
- Flash 自动运行设置已保存.
- Redirect to config_page.

- [ ] **Step 3: Expose schedule state**

Pass database.get_schedule_state() to:

- dashboard.html as schedule.
- config.html as schedule.

Pass next_run_at(schedule) to dashboard.html as next_auto_run.

- [ ] **Step 4: Add configuration UI**

Add a separate panel containing:

~~~html
<form method="post" action="{{ url_for('schedule_page') }}" class="panel stack schedule-panel">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <div class="switch-row">
    <div>
      <h2>每日自动运行</h2>
      <p class="muted">控制台在线时按北京时间触发；当天错过会补跑一次。</p>
    </div>
    <label class="switch">
      <input type="checkbox" name="enabled" value="1" {% if schedule.enabled %}checked{% endif %}>
      <span></span>
    </label>
  </div>
  <div class="field">
    <label for="daily_time">每日运行时间</label>
    <input id="daily_time" name="daily_time" type="time" value="{{ schedule.daily_time }}" required>
    <small>固定时区：北京时间 Asia/Shanghai</small>
  </div>
  <button class="button button-primary" type="submit">保存自动运行设置</button>
</form>
~~~

- [ ] **Step 5: Add Dashboard status**

Show:

- 已启用 or 未启用.
- Daily time.
- next_auto_run formatted in Beijing time.
- last_message or 尚未触发.

- [ ] **Step 6: Render trigger labels**

In runs.html and run detail, render scheduled as 自动 and manual as 手动.

- [ ] **Step 7: Style the switch and schedule status**

Add CSS for schedule-panel, switch-row, switch, and the checked slider. Reuse existing color tokens and responsive form layout.

- [ ] **Step 8: Compile and commit**

Run:

    .venv/bin/python -m py_compile wxread_console/web.py

Expected: exit code 0.

Commit:

    git add wxread_console/web.py wxread_console/templates wxread_console/static/styles.css
    git commit -m "feat: manage automatic runs from console"

### Task 4: Startup safety, documentation, and real smoke verification

**Files:**

- Modify: wxread_console/__main__.py
- Modify: docs/wxread-console.md
- Modify: Dockerfile.console

- [ ] **Step 1: Prevent development reloader duplication**

Change app.run to:

~~~python
app.run(
    host="127.0.0.1",
    port=8080,
    debug=app.config["ENVIRONMENT"] == "development",
    use_reloader=False,
)
~~~

- [ ] **Step 2: Correct Dockerfile.console**

Ensure the RUN instruction is exactly:

~~~dockerfile
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
~~~

Keep Gunicorn at one worker.

- [ ] **Step 3: Document automatic operation**

Update docs/wxread-console.md:

- Explain enable/time configuration.
- Explain Asia/Shanghai.
- Explain same-day catch-up.
- Explain skipped busy behavior.
- Explain the service/container must stay running.

- [ ] **Step 4: Run isolated scheduler smoke**

Use WXREAD_DATA_DIR under /tmp, a fake curl, READ_NUM=1, and a one-second runner timeout.

Set schedule enabled with a time earlier than now. Call ScheduleService.tick() twice.

Expected:

- First tick returns started.
- Second tick returns already_claimed.
- SQLite has exactly one run with trigger scheduled.
- The run ends as timeout.
- No real account Cookie is used.

- [ ] **Step 5: Run local web smoke**

Start Gunicorn on port 18082 with temporary data. Log in, save fake curl, enable schedule, and GET Dashboard.

Expected:

- Schedule form saves.
- Dashboard displays enabled, daily time, and next automatic run.
- Run history displays 自动 for scheduled trigger.

- [ ] **Step 6: Verify boundaries**

Run:

    .venv/bin/python -m py_compile wxread_console/*.py
    git diff --check
    git diff main -- main.py config.py push.py log_utils.py Dockerfile .github/workflows/deploy.yml

Expected:

- Compilation exit 0.
- No whitespace errors.
- No upstream core changes.

- [ ] **Step 7: Commit**

Run:

    git add wxread_console/__main__.py docs/wxread-console.md Dockerfile.console
    git commit -m "docs: document automatic daily runs"

- [ ] **Step 8: Restart local preview**

Restart the existing local preview at http://127.0.0.1:8080 with the same data directory and password wxread-demo.

Expected: the user can immediately configure and view automatic runs.
