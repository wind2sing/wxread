# wxread Console v1 Design

Date: 2026-06-20

## Goal

Build a lightweight self-hosted web console for this fork of wxread.

The console should let the owner log in, submit the WeRead curl bash captured from the browser, save runtime settings, trigger one manual run, and inspect recent run history and redacted logs.

The design must preserve upstream compatibility. This repository is a fork, so v1 should avoid changing upstream-owned source files unless there is no practical alternative.

## Non-goals

- No multi-user account system.
- No multiple WeRead account profiles.
- No React or Vue frontend build chain.
- No cron schedule editor in v1.
- No rewrite of the original reading algorithm.
- No migration requirement for existing GitHub Actions users.

## Guiding constraint: upstream-friendly extension

Treat the original project files as the upstream core:

- main.py
- config.py
- push.py
- log_utils.py
- Dockerfile
- .github/workflows/deploy.yml

V1 should add new console-related files in a separate area instead of restructuring the upstream scripts. If a later implementation truly needs to touch an upstream file, the change must be small, documented, and easy to re-apply after pulling upstream updates.

Recommended new top-level additions:

- wxread_console/ for the web app, services, templates, static assets, and database helpers.
- data/ at runtime for SQLite, secret config, and persisted logs. This directory must not be committed.
- Optional console-specific Docker entrypoint or Dockerfile, preferably separate from the upstream Dockerfile unless implementation proves a small Dockerfile edit is cleaner.

## Product scope

V1 is a single-admin server/Docker control panel exposed for the owner’s personal use.

Confirmed decisions:

- Deployment target: server/Docker panel.
- Access model: public internet, owner-only.
- Authentication: one administrator password configured by environment variable.
- Config submission: paste full WeRead curl bash.
- Control scope: configure, inspect status, view logs, and manually run once.
- Technical style: lightweight Python server-rendered app.
- Run history storage: SQLite.

## Architecture

Use a lightweight Python server-rendered web app, preferably Flask with Jinja templates and minimal vanilla JavaScript.

High-level components:

1. Browser
   - Displays login, dashboard, config, run history, and logs.
   - Submits forms to the console app.

2. Console web app
   - Owns routes, templates, sessions, form validation, and CSRF protection.
   - Requires authentication for every page and mutation except login.

3. Console services
   - Parse pasted curl bash.
   - Save and load sensitive config.
   - Create and update run records in SQLite.
   - Start a child process for manual runs.
   - Redact sensitive values before storing or rendering logs.

4. Original wxread scripts
   - Continue to run as before.
   - Manual runs should execute python main.py in a child process.
   - The console passes config through environment variables such as WXREAD_CURL_BASH, READ_NUM, PUSH_METHOD, and push tokens.

5. Runtime storage
   - SQLite stores non-secret run state and redacted logs.
   - A local secret config file stores raw curl bash and tokens.

This avoids importing and refactoring main.py, which currently executes work at module import time.

## Pages

### Login

- Shows a single password field.
- Compares submitted password with WXREAD_ADMIN_PASSWORD.
- Creates a server-side or signed session on success.
- Production mode should refuse to start or refuse login if no admin password is configured.

### Dashboard

Shows:

- Whether WeRead config is present.
- Redacted cookie/curl summary, for example wr_skey=ab***.
- READ_NUM and estimated reading time, calculated as READ_NUM × 0.5 minutes.
- Most recent run status.
- Current task state: idle or running.
- Recent success rate, such as last 7 runs or last 7 days.
- Quick actions:
  - Validate saved config with parser and local preflight checks.
  - Run once now.

In v1, config validation means local parsing and completeness checks. Live Cookie validity is confirmed by running once, because duplicating the upstream login renewal logic inside the console would increase maintenance surface.

### Configuration

Allows the owner to set:

- Full WeRead curl bash.
- READ_NUM.
- PUSH_METHOD.
- PushPlus token.
- WxPusher SPT.
- Telegram bot token and chat ID.
- ServerChan SPT.

The page should show a parsed, redacted preview before or after save:

- Read URL recognized or missing.
- Header count.
- Cookie count.
- Important cookie summary, redacted.
- Push token status, redacted.

### Run history

Shows a table of recent runs:

- Run ID.
- Trigger type: manual or scheduled-compatible runner.
- Start time.
- End time.
- Duration.
- Status.
- Exit code.
- Estimated completed count if extractable from logs.
- Error summary.

Statuses:

- running
- success
- failed
- partial_success
- timeout
- cancelled if cancellation is later added

For v1, partial_success means the reading script appears to complete but a secondary action such as push notification fails.

### Logs

Shows redacted stdout/stderr or parsed log events for a selected run.

Requirements:

- Never show raw cookies, raw curl bash, raw push tokens, wr_skey, or Telegram bot tokens.
- Include enough detail to diagnose common failures.
- Prefer Chinese user-facing summaries for common errors.

## Data model

SQLite should store operational data only.

Suggested tables:

### runs

- id
- trigger
- status
- started_at
- ended_at
- duration_seconds
- exit_code
- read_num
- estimated_minutes
- completed_steps
- error_summary
- created_at
- updated_at

### run_logs

- id
- run_id
- stream
- level
- message
- created_at

Messages must be redacted before insert.

### config_state

- id
- has_curl
- curl_summary
- read_num
- push_method
- push_summary
- last_validated_at
- last_validation_status
- last_validation_error
- updated_at

This table stores summaries only, not raw secrets.

## Secret storage

Store raw secrets in a local runtime file, for example data/secrets.json.

Contains:

- Raw WXREAD_CURL_BASH.
- Push tokens.
- Optional runtime config that must be passed to main.py.

Requirements:

- File must not be committed.
- Save with restrictive permissions where supported, preferably 0600.
- Do not copy raw secret values into SQLite.
- Do not render raw secret values in templates.

## Key data flows

### Save config

1. Authenticated user submits configuration form.
2. Server parses curl bash.
3. Server validates that the command appears to target https://weread.qq.com/web/book/read and includes cookies.
4. Server produces a redacted preview.
5. Server writes raw values to local secret storage.
6. Server writes only summaries and validation state to SQLite.
7. Dashboard updates config status.

### Manual run

1. Authenticated user clicks “run once”.
2. Server checks that no other run is active.
3. Server checks that required config is present.
4. Server creates a runs row with status running.
5. Server builds an environment for the child process:
   - WXREAD_CURL_BASH
   - READ_NUM
   - PUSH_METHOD
   - selected push tokens
6. Server starts python main.py as a child process from the repository root.
7. Server captures stdout/stderr.
8. Server redacts output and writes log lines to SQLite.
9. Server updates the run status, exit code, duration, and error summary.

### Scheduled-compatible run

V1 does not need a cron editor.

Recommended follow-up direction:

- Add a new console-owned command such as python -m wxread_console.runner.
- Cron calls this command.
- The command loads console config, calls main.py as a child process, and records the result in SQLite.

This preserves upstream compatibility while allowing scheduled runs to appear in the console history.

## Error handling

Common user-facing error summaries:

- Config missing: “请先粘贴微信读书 read 接口的 curl bash。”
- Curl parse failed: “无法解析 curl，请确认复制的是 weread.qq.com/web/book/read 请求。”
- Cookie likely expired: “Cookie 可能已失效，请重新抓包并保存配置。”
- Run already active: “已有任务正在运行，请等待完成后再试。”
- Child process timeout: “运行超时，可能是网络请求卡住或 READ_NUM 设置过大。”
- Push failure: “阅读任务可能已完成，但推送失败，请检查推送配置。”
- Unexpected script exit: “脚本异常退出，请查看脱敏日志详情。”

The console should keep raw technical details in redacted logs and show short summaries on dashboard/history pages.

## Security requirements

- All pages except login require authentication.
- All mutation routes require authentication.
- Use CSRF protection or an equivalent same-origin form protection.
- Admin password must come from an environment variable such as WXREAD_ADMIN_PASSWORD.
- Session signing secret should come from an environment variable such as WXREAD_SESSION_SECRET, or be generated for local development only.
- Production mode should fail safe if admin password is not set.
- Redact sensitive values before writing logs to SQLite.
- Redact sensitive values before rendering templates.
- Avoid logging raw request bodies from the config form.
- Allow only one active run at a time.
- Use a child process timeout.
- Recommend HTTPS reverse proxy for public deployment.

Sensitive terms and patterns to redact include:

- Cookie
- curl command bodies
- wr_skey
- push tokens
- Telegram bot token
- RK, ptcz, pac_uid, and other cookie key/value pairs

## Testing strategy

### Unit tests

- curl bash parser extracts headers and cookies from representative commands.
- Parser handles both -H 'Cookie: ...' and -b '...'.
- Redaction masks cookies, tokens, and raw curl content.
- Config validation rejects missing URL or missing cookies.
- Estimated minutes calculation matches READ_NUM × 0.5.

### Service tests

- Saving config writes secrets to secret storage and summaries to SQLite.
- Secret values are absent from SQLite summaries.
- Creating a run prevents a second active run.
- Run status transitions from running to terminal states.

### Integration tests

- Mock child process success updates run to success.
- Mock child process non-zero exit updates run to failed.
- Mock timeout updates run to timeout.
- Mock output containing cookie/token-like content is redacted before storage.

### Manual acceptance

- Start the console locally or in Docker.
- Log in with the configured admin password.
- Paste a curl bash request.
- Save config and see a redacted summary.
- Trigger a manual run.
- See the run appear in history.
- Open logs and confirm sensitive values are not visible.
- Confirm the original script can still run in its original environment-variable style.

## Compatibility acceptance

- Upstream-owned files remain unchanged unless explicitly documented.
- New console implementation is concentrated in wxread_console/ and supporting docs/tests.
- Original GitHub Actions flow remains usable.
- Original python main.py behavior remains usable.
- Pulling future upstream changes should mostly affect upstream files, not console files.

## Deployment notes

V1 should document two deployment modes:

1. Local development
   - Run the Flask app from the repository root.
   - Use a local SQLite database under data/.

2. Docker/server
   - Expose the console web port.
   - Mount data/ for persistence.
   - Configure WXREAD_ADMIN_PASSWORD.
   - Configure WXREAD_SESSION_SECRET.
   - Put the service behind HTTPS if public.

The existing upstream Docker/GitHub Actions approach should remain documented and usable.

## Implementation decisions

To keep the implementation aligned with the upstream-friendly goal, use these defaults during planning:

- Add a separate Dockerfile.console or console-specific entrypoint instead of editing the upstream Dockerfile.
- Use Flask's signed session cookie with WXREAD_SESSION_SECRET for v1.
- Leave scheduled-compatible runner as a follow-up unless implementation can include it without changing upstream files or expanding scope.

The design preference is to choose the option with fewer upstream merge conflicts.
