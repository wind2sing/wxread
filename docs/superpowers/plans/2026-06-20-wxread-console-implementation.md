# wxread Console v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add an attractive single-admin web console that saves WeRead configuration, launches the unchanged upstream main.py through environment variables, and records redacted run history in SQLite.

**Architecture:** Add an isolated wxread_console package beside the upstream scripts. Flask renders Jinja pages and owns authentication, config storage, SQLite history, redaction, and a background subprocess runner; the runner invokes the existing main.py without importing or restructuring it. Runtime secrets live under data/ and never enter SQLite or normal logs.

**Tech Stack:** Python 3.10, Flask, Jinja, sqlite3, gunicorn, pytest, vanilla JavaScript, custom responsive CSS.

---

## Scope and upstream boundary

Files from upstream that must remain unchanged:

- main.py
- config.py
- push.py
- log_utils.py
- Dockerfile
- .github/workflows/deploy.yml

The only existing tracked file this plan modifies is .gitignore, to prevent local secrets, SQLite files, and visual brainstorming artifacts from being committed. All application code goes into new paths.

## Planned file map

- .gitignore — ignore data/, .superpowers/, Python caches, and test caches.
- requirements-console.txt — console-only production and test dependencies.
- wxread_console/__init__.py — package export.
- wxread_console/__main__.py — local development entrypoint.
- wxread_console/settings.py — environment and runtime path configuration.
- wxread_console/redaction.py — redact curl, cookies, and push tokens.
- wxread_console/curl_parser.py — parse and validate copied curl bash.
- wxread_console/secret_store.py — atomic local secret persistence with restrictive permissions.
- wxread_console/database.py — SQLite schema and repository functions.
- wxread_console/runner.py — background subprocess execution of main.py.
- wxread_console/web.py — Flask app factory, auth, CSRF, routes, and view models.
- wxread_console/templates/base.html — shared layout and navigation.
- wxread_console/templates/login.html — admin login.
- wxread_console/templates/dashboard.html — status cards and quick actions.
- wxread_console/templates/config.html — curl and notification settings.
- wxread_console/templates/runs.html — run history.
- wxread_console/templates/run_detail.html — redacted log detail.
- wxread_console/static/styles.css — polished responsive visual system.
- wxread_console/static/app.js — confirmation and running-state refresh.
- tests/test_redaction.py — sensitive-data masking tests.
- tests/test_curl_parser.py — curl parsing and validation tests.
- tests/test_secret_store.py — secret file permissions and round-trip tests.
- tests/test_database.py — schema, run state, and single-active-run tests.
- tests/test_runner.py — child process environment, result, timeout, and redaction tests.
- tests/test_web.py — authentication, CSRF, config, dashboard, and run route tests.
- Dockerfile.console — console-specific image without modifying upstream Dockerfile.
- docs/wxread-console.md — local and Docker usage, security, and upstream sync notes.

### Task 1: Establish console dependencies and repository hygiene

**Files:**

- Modify: .gitignore
- Create: requirements-console.txt
- Create: wxread_console/__init__.py
- Create: wxread_console/settings.py
- Create: wxread_console/__main__.py
- Test: tests/test_settings.py

- [ ] **Step 1: Write the failing settings test**

Create tests/test_settings.py:

~~~python
from pathlib import Path

import pytest

from wxread_console.settings import Settings


def test_settings_requires_admin_password_in_production(tmp_path: Path):
    with pytest.raises(RuntimeError, match="WXREAD_ADMIN_PASSWORD"):
        Settings.from_env(
            {
                "WXREAD_CONSOLE_ENV": "production",
                "WXREAD_DATA_DIR": str(tmp_path),
                "WXREAD_SESSION_SECRET": "test-session-secret",
            }
        )


def test_settings_builds_runtime_paths(tmp_path: Path):
    settings = Settings.from_env(
        {
            "WXREAD_CONSOLE_ENV": "test",
            "WXREAD_ADMIN_PASSWORD": "admin-password",
            "WXREAD_SESSION_SECRET": "session-secret",
            "WXREAD_DATA_DIR": str(tmp_path),
        }
    )

    assert settings.data_dir == tmp_path
    assert settings.database_path == tmp_path / "wxread.sqlite3"
    assert settings.secrets_path == tmp_path / "secrets.json"
    assert (settings.repo_root / "main.py").exists()
~~~

- [ ] **Step 2: Run the test and verify the missing module failure**

Run:

    python -m pytest tests/test_settings.py -v

Expected: FAIL because wxread_console.settings does not exist.

- [ ] **Step 3: Add dependencies and settings implementation**

Create requirements-console.txt:

    Flask>=3.1,<4
    gunicorn>=23,<24
    requests>=2.32,<3
    pytest>=8,<9

Create wxread_console/__init__.py:

~~~python
"""Web console extension for the upstream wxread scripts."""
~~~

Create wxread_console/settings.py:

~~~python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    environment: str
    admin_password: str
    session_secret: str
    data_dir: Path
    repo_root: Path
    run_timeout_seconds: int

    @property
    def database_path(self) -> Path:
        return self.data_dir / "wxread.sqlite3"

    @property
    def secrets_path(self) -> Path:
        return self.data_dir / "secrets.json"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        values = os.environ if env is None else env
        environment = values.get("WXREAD_CONSOLE_ENV", "development")
        admin_password = values.get("WXREAD_ADMIN_PASSWORD", "")
        session_secret = values.get("WXREAD_SESSION_SECRET", "")
        if environment == "production" and not admin_password:
            raise RuntimeError("WXREAD_ADMIN_PASSWORD is required in production")
        if environment == "production" and not session_secret:
            raise RuntimeError("WXREAD_SESSION_SECRET is required in production")

        repo_root = Path(__file__).resolve().parents[1]
        data_dir = Path(values.get("WXREAD_DATA_DIR", repo_root / "data"))
        return cls(
            environment=environment,
            admin_password=admin_password,
            session_secret=session_secret or "development-only-secret",
            data_dir=data_dir,
            repo_root=repo_root,
            run_timeout_seconds=int(values.get("WXREAD_RUN_TIMEOUT_SECONDS", "14400")),
        )
~~~

Create wxread_console/__main__.py:

~~~python
from .web import create_app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=app.config["ENVIRONMENT"] == "development")
~~~

Append these exact entries to .gitignore:

    /data/
    /.superpowers/
    __pycache__/
    .pytest_cache/
    *.pyc

- [ ] **Step 4: Install dependencies and rerun the test**

Run:

    python -m pip install -r requirements-console.txt
    python -m pytest tests/test_settings.py -v

Expected: 2 passed.

- [ ] **Step 5: Commit the foundation**

Run:

    git add .gitignore requirements-console.txt wxread_console tests/test_settings.py
    git commit -m "chore: add console foundation"

### Task 2: Implement sensitive-data redaction

**Files:**

- Create: wxread_console/redaction.py
- Create: tests/test_redaction.py

- [ ] **Step 1: Write failing redaction tests**

Create tests/test_redaction.py:

~~~python
from wxread_console.redaction import mask_value, redact_text


def test_mask_value_keeps_only_short_prefix():
    assert mask_value("abcdefghijk") == "ab***"
    assert mask_value("") == ""


def test_redact_text_masks_cookie_header_and_known_tokens():
    text = (
        "Cookie: wr_skey=abcdefgh; RK=secret-rk\n"
        "TELEGRAM_BOT_TOKEN=123456:super-secret\n"
        "PUSHPLUS_TOKEN=push-secret"
    )

    result = redact_text(text)

    assert "abcdefgh" not in result
    assert "secret-rk" not in result
    assert "123456:super-secret" not in result
    assert "push-secret" not in result
    assert "[REDACTED]" in result


def test_redact_text_masks_full_curl_command():
    text = "received curl 'https://weread.qq.com/web/book/read' -H 'Cookie: a=b'"
    result = redact_text(text)
    assert "a=b" not in result
    assert "curl [REDACTED]" in result
~~~

- [ ] **Step 2: Run the tests and verify failure**

Run:

    python -m pytest tests/test_redaction.py -v

Expected: FAIL because wxread_console.redaction does not exist.

- [ ] **Step 3: Implement the redaction module**

Create wxread_console/redaction.py:

~~~python
from __future__ import annotations

import re


TOKEN_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "PUSHPLUS_TOKEN",
    "WXPUSHER_SPT",
    "SERVERCHAN_SPT",
    "wr_skey",
    "RK",
    "ptcz",
    "pac_uid",
)


def mask_value(value: str) -> str:
    if not value:
        return ""
    return f"{value[:2]}***"


def redact_text(text: str) -> str:
    result = text
    result = re.sub(
        r"(?is)curl\s+(['\"]).*?weread\.qq\.com/web/book/read.*",
        "curl [REDACTED]",
        result,
    )
    result = re.sub(
        r"(?im)^(cookie\s*:\s*).*$",
        r"\1[REDACTED]",
        result,
    )
    for key in TOKEN_KEYS:
        result = re.sub(
            rf"(?i)({re.escape(key)}\s*[=:]\s*)[^;\s'\"]+",
            rf"\1[REDACTED]",
            result,
        )
    return result
~~~

- [ ] **Step 4: Run tests**

Run:

    python -m pytest tests/test_redaction.py -v

Expected: 3 passed.

- [ ] **Step 5: Commit redaction**

Run:

    git add wxread_console/redaction.py tests/test_redaction.py
    git commit -m "feat: redact console secrets"

### Task 3: Parse curl bash and persist secrets safely

**Files:**

- Create: wxread_console/curl_parser.py
- Create: wxread_console/secret_store.py
- Create: tests/test_curl_parser.py
- Create: tests/test_secret_store.py

- [ ] **Step 1: Write failing curl parser tests**

Create tests/test_curl_parser.py:

~~~python
import pytest

from wxread_console.curl_parser import CurlParseError, parse_weread_curl


def test_parse_cookie_header():
    command = (
        "curl 'https://weread.qq.com/web/book/read' "
        "-H 'accept: application/json' "
        "-H 'Cookie: wr_skey=abcdefgh; RK=secret-rk' "
        "--data-raw '{}'"
    )

    parsed = parse_weread_curl(command)

    assert parsed.url == "https://weread.qq.com/web/book/read"
    assert parsed.headers["accept"] == "application/json"
    assert parsed.cookies["wr_skey"] == "abcdefgh"
    assert parsed.cookie_summary == "wr_skey=ab***"


def test_parse_dash_b_cookie():
    command = (
        "curl 'https://weread.qq.com/web/book/read' "
        "-b 'wr_skey=abcdefgh; RK=secret-rk'"
    )
    assert parse_weread_curl(command).cookies["RK"] == "secret-rk"


def test_reject_non_weread_url():
    with pytest.raises(CurlParseError, match="weread.qq.com/web/book/read"):
        parse_weread_curl("curl 'https://example.com/read' -b 'a=b'")


def test_reject_missing_cookie():
    with pytest.raises(CurlParseError, match="Cookie"):
        parse_weread_curl("curl 'https://weread.qq.com/web/book/read'")
~~~

- [ ] **Step 2: Write failing secret store tests**

Create tests/test_secret_store.py:

~~~python
import os
from pathlib import Path

from wxread_console.secret_store import SecretStore


def test_secret_store_round_trip_and_permissions(tmp_path: Path):
    path = tmp_path / "secrets.json"
    store = SecretStore(path)
    payload = {"WXREAD_CURL_BASH": "curl secret", "READ_NUM": "40"}

    store.save(payload)

    assert store.load() == payload
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_secret_store_returns_empty_mapping_when_missing(tmp_path: Path):
    assert SecretStore(tmp_path / "missing.json").load() == {}
~~~

- [ ] **Step 3: Run both test files and verify failure**

Run:

    python -m pytest tests/test_curl_parser.py tests/test_secret_store.py -v

Expected: FAIL because the parser and store modules do not exist.

- [ ] **Step 4: Implement curl parsing**

Create wxread_console/curl_parser.py:

~~~python
from __future__ import annotations

import shlex
from dataclasses import dataclass

from .redaction import mask_value


class CurlParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedCurl:
    url: str
    headers: dict[str, str]
    cookies: dict[str, str]

    @property
    def cookie_summary(self) -> str:
        value = self.cookies.get("wr_skey")
        if value:
            return f"wr_skey={mask_value(value)}"
        return f"{len(self.cookies)} cookies"


def _parse_cookie_string(value: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for item in value.split(";"):
        if "=" not in item:
            continue
        key, cookie_value = item.split("=", 1)
        cookies[key.strip()] = cookie_value.strip()
    return cookies


def parse_weread_curl(command: str) -> ParsedCurl:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise CurlParseError(f"curl 语法无法解析：{exc}") from exc

    if not parts or parts[0] != "curl":
        raise CurlParseError("请输入完整的 curl bash")

    url = next((part for part in parts[1:] if part.startswith("http")), "")
    expected = "https://weread.qq.com/web/book/read"
    if not url.startswith(expected):
        raise CurlParseError("请求地址必须是 weread.qq.com/web/book/read")

    headers: dict[str, str] = {}
    cookie_value = ""
    index = 1
    while index < len(parts):
        part = parts[index]
        if part in ("-H", "--header") and index + 1 < len(parts):
            key, separator, value = parts[index + 1].partition(":")
            if separator:
                if key.lower() == "cookie":
                    cookie_value = value.strip()
                else:
                    headers[key.lower().strip()] = value.strip()
            index += 2
            continue
        if part in ("-b", "--cookie") and index + 1 < len(parts):
            cookie_value = parts[index + 1]
            index += 2
            continue
        index += 1

    cookies = _parse_cookie_string(cookie_value)
    if not cookies:
        raise CurlParseError("curl 中缺少 Cookie")
    return ParsedCurl(url=url, headers=headers, cookies=cookies)
~~~

- [ ] **Step 5: Implement atomic secret storage**

Create wxread_console/secret_store.py:

~~~python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


class SecretStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, values: Mapping[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(dict(values), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        if os.name == "posix":
            os.chmod(self.path, 0o600)
~~~

- [ ] **Step 6: Run parser and secret tests**

Run:

    python -m pytest tests/test_curl_parser.py tests/test_secret_store.py -v

Expected: 6 passed.

- [ ] **Step 7: Commit configuration primitives**

Run:

    git add wxread_console/curl_parser.py wxread_console/secret_store.py tests/test_curl_parser.py tests/test_secret_store.py
    git commit -m "feat: parse and store console configuration"

### Task 4: Add SQLite run history and configuration summaries

**Files:**

- Create: wxread_console/database.py
- Create: tests/test_database.py

- [ ] **Step 1: Write failing database tests**

Create tests/test_database.py:

~~~python
from pathlib import Path

import pytest

from wxread_console.database import Database, RunAlreadyActive


def make_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    return database


def test_create_and_finish_run(tmp_path: Path):
    database = make_database(tmp_path)
    run_id = database.create_run(trigger="manual", read_num=40)

    database.append_log(run_id, "stdout", "INFO", "阅读进度 1/40")
    database.finish_run(run_id, status="success", exit_code=0)

    run = database.get_run(run_id)
    assert run["status"] == "success"
    assert run["exit_code"] == 0
    assert database.get_logs(run_id)[0]["message"] == "阅读进度 1/40"


def test_prevents_two_active_runs(tmp_path: Path):
    database = make_database(tmp_path)
    database.create_run(trigger="manual", read_num=40)

    with pytest.raises(RunAlreadyActive):
        database.create_run(trigger="manual", read_num=20)


def test_config_state_contains_summary_only(tmp_path: Path):
    database = make_database(tmp_path)
    database.save_config_state(
        curl_summary="wr_skey=ab***",
        read_num=40,
        push_method="telegram",
        push_summary="configured",
    )

    state = database.get_config_state()
    assert state["curl_summary"] == "wr_skey=ab***"
    assert "secret" not in state


def test_update_completed_steps(tmp_path: Path):
    database = make_database(tmp_path)
    run_id = database.create_run(trigger="manual", read_num=40)
    database.update_completed_steps(run_id, 12)
    assert database.get_run(run_id)["completed_steps"] == 12
~~~

- [ ] **Step 2: Run database tests and verify failure**

Run:

    python -m pytest tests/test_database.py -v

Expected: FAIL because wxread_console.database does not exist.

- [ ] **Step 3: Implement schema and repository**

Create wxread_console/database.py with:

~~~python
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = {"success", "failed", "partial_success", "timeout", "cancelled"}


class RunAlreadyActive(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds REAL,
                    exit_code INTEGER,
                    read_num INTEGER NOT NULL,
                    estimated_minutes REAL NOT NULL,
                    completed_steps INTEGER,
                    error_summary TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_run
                ON runs ((1)) WHERE status = 'running';

                CREATE TABLE IF NOT EXISTS run_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    stream TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS config_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    has_curl INTEGER NOT NULL,
                    curl_summary TEXT NOT NULL,
                    read_num INTEGER NOT NULL,
                    push_method TEXT NOT NULL,
                    push_summary TEXT NOT NULL,
                    last_validated_at TEXT,
                    last_validation_status TEXT,
                    last_validation_error TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def create_run(self, trigger: str, read_num: int) -> int:
        now = utc_now()
        try:
            with self.connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO runs (
                        trigger, status, started_at, read_num,
                        estimated_minutes, created_at, updated_at
                    ) VALUES (?, 'running', ?, ?, ?, ?, ?)
                    """,
                    (trigger, now, read_num, read_num * 0.5, now, now),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise RunAlreadyActive("已有任务正在运行") from exc

    def append_log(self, run_id: int, stream: str, level: str, message: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO run_logs (run_id, stream, level, message, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, stream, level, message, utc_now()),
            )

    def update_completed_steps(self, run_id: int, completed_steps: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET completed_steps = ?, updated_at = ?
                WHERE id = ?
                """,
                (completed_steps, utc_now(), run_id),
            )

    def finish_run(
        self,
        run_id: int,
        status: str,
        exit_code: int | None,
        error_summary: str | None = None,
    ) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"invalid terminal status: {status}")
        ended_at = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT started_at FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            started = datetime.fromisoformat(row["started_at"])
            ended = datetime.fromisoformat(ended_at)
            connection.execute(
                """
                UPDATE runs
                SET status = ?, ended_at = ?, duration_seconds = ?,
                    exit_code = ?, error_summary = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    ended_at,
                    (ended - started).total_seconds(),
                    exit_code,
                    error_summary,
                    ended_at,
                    run_id,
                ),
            )

    def get_run(self, run_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            return dict(row)

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_logs(self, run_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM run_logs WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def save_config_state(
        self,
        curl_summary: str,
        read_num: int,
        push_method: str,
        push_summary: str,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO config_state (
                    id, has_curl, curl_summary, read_num, push_method,
                    push_summary, last_validated_at, last_validation_status,
                    last_validation_error, updated_at
                ) VALUES (1, 1, ?, ?, ?, ?, ?, 'valid', NULL, ?)
                ON CONFLICT(id) DO UPDATE SET
                    has_curl = 1,
                    curl_summary = excluded.curl_summary,
                    read_num = excluded.read_num,
                    push_method = excluded.push_method,
                    push_summary = excluded.push_summary,
                    last_validated_at = excluded.last_validated_at,
                    last_validation_status = 'valid',
                    last_validation_error = NULL,
                    updated_at = excluded.updated_at
                """,
                (curl_summary, read_num, push_method, push_summary, now, now),
            )

    def get_config_state(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM config_state WHERE id = 1"
            ).fetchone()
            return None if row is None else dict(row)

    def mark_interrupted_runs(self) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET status = 'failed', ended_at = ?, updated_at = ?,
                    error_summary = '控制台重启，运行状态已中断'
                WHERE status = 'running'
                """,
                (now, now),
            )
~~~

- [ ] **Step 4: Run database tests**

Run:

    python -m pytest tests/test_database.py -v

Expected: 4 passed.

- [ ] **Step 5: Commit database**

Run:

    git add wxread_console/database.py tests/test_database.py
    git commit -m "feat: add console run history"

### Task 5: Run the upstream script in a guarded background subprocess

**Files:**

- Create: wxread_console/runner.py
- Create: tests/test_runner.py

- [ ] **Step 1: Write failing runner tests**

Create tests/test_runner.py:

~~~python
import sys
from pathlib import Path

from wxread_console.database import Database
from wxread_console.runner import RunService


def test_run_success_passes_environment_and_redacts_output(tmp_path: Path):
    database = Database(tmp_path / "runs.sqlite3")
    database.initialize()
    script = tmp_path / "fake_main.py"
    script.write_text(
        "import os\n"
        "print('READ_NUM=' + os.environ['READ_NUM'])\n"
        "print('wr_skey=super-secret')\n",
        encoding="utf-8",
    )
    service = RunService(database, tmp_path, timeout_seconds=5)

    run_id = service.run_sync(
        script=script,
        environment={"READ_NUM": "40", "WXREAD_CURL_BASH": "curl secret"},
        executable=sys.executable,
    )

    assert database.get_run(run_id)["status"] == "success"
    messages = "\n".join(log["message"] for log in database.get_logs(run_id))
    assert "READ_NUM=40" in messages
    assert "super-secret" not in messages


def test_run_timeout_is_recorded(tmp_path: Path):
    database = Database(tmp_path / "runs.sqlite3")
    database.initialize()
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
    service = RunService(database, tmp_path, timeout_seconds=0.05)

    run_id = service.run_sync(
        script=script,
        environment={"READ_NUM": "1"},
        executable=sys.executable,
    )

    assert database.get_run(run_id)["status"] == "timeout"


def test_push_failure_is_partial_success_and_progress_is_recorded(tmp_path: Path):
    database = Database(tmp_path / "runs.sqlite3")
    database.initialize()
    script = tmp_path / "partial.py"
    script.write_text(
        "print('阅读进度: 第 40/40 次')\n"
        "print('阅读脚本已完成。')\n"
        "print('PushPlus 推送失败')\n",
        encoding="utf-8",
    )
    service = RunService(database, tmp_path, timeout_seconds=5)

    run_id = service.run_sync(
        script=script,
        environment={"READ_NUM": "40"},
        executable=sys.executable,
    )

    run = database.get_run(run_id)
    assert run["status"] == "partial_success"
    assert run["completed_steps"] == 40
~~~

- [ ] **Step 2: Run runner tests and verify failure**

Run:

    python -m pytest tests/test_runner.py -v

Expected: FAIL because wxread_console.runner does not exist.

- [ ] **Step 3: Implement synchronous and background run service**

Create wxread_console/runner.py:

~~~python
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Mapping

from .database import Database
from .redaction import redact_text


class RunService:
    def __init__(self, database: Database, repo_root: Path, timeout_seconds: float):
        self.database = database
        self.repo_root = repo_root
        self.timeout_seconds = timeout_seconds

    def run_sync(
        self,
        script: Path,
        environment: Mapping[str, str],
        executable: str = sys.executable,
    ) -> int:
        read_num = int(environment.get("READ_NUM", "40"))
        run_id = self.database.create_run("manual", read_num)
        self._execute_existing_run(run_id, script, environment, executable)
        return run_id

    def start_background(self, environment: Mapping[str, str]) -> int:
        run_id = self.database.create_run(
            "manual", int(environment.get("READ_NUM", "40"))
        )

        def target() -> None:
            self._execute_existing_run(
                run_id,
                self.repo_root / "main.py",
                environment,
                sys.executable,
            )

        threading.Thread(target=target, daemon=True, name=f"wxread-run-{run_id}").start()
        return run_id

    def _execute_existing_run(
        self,
        run_id: int,
        script: Path,
        environment: Mapping[str, str],
        executable: str,
    ) -> None:
        child_environment = os.environ.copy()
        child_environment.update(environment)
        try:
            result = subprocess.run(
                [executable, str(script)],
                cwd=self.repo_root,
                env=child_environment,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            outputs = (("stdout", result.stdout), ("stderr", result.stderr))
            combined_output = "\n".join(text for _, text in outputs if text)
            for stream, text in outputs:
                for line in text.splitlines():
                    self.database.append_log(
                        run_id, stream, "INFO", redact_text(line)
                    )
            progress = [
                int(value)
                for value in re.findall(r"阅读进度:\s*第\s*(\d+)/\d+\s*次", combined_output)
            ]
            if progress:
                self.database.update_completed_steps(run_id, max(progress))
            if result.returncode != 0:
                status = "failed"
                summary = "脚本异常退出，请查看脱敏日志"
            elif "阅读脚本已完成" in combined_output and "推送失败" in combined_output:
                status = "partial_success"
                summary = "阅读任务已完成，但推送失败"
            else:
                status = "success"
                summary = None
            self.database.finish_run(run_id, status, result.returncode, summary)
        except subprocess.TimeoutExpired:
            self.database.finish_run(
                run_id, "timeout", None, "运行超时，请检查网络或 READ_NUM"
            )
        except Exception as exc:
            self.database.append_log(
                run_id, "stderr", "ERROR", redact_text(str(exc))
            )
            self.database.finish_run(
                run_id, "failed", None, "控制台启动脚本失败"
            )
~~~

- [ ] **Step 4: Run runner tests**

Run:

    python -m pytest tests/test_runner.py -v

Expected: 3 passed.

- [ ] **Step 5: Commit runner**

Run:

    git add wxread_console/runner.py tests/test_runner.py
    git commit -m "feat: run upstream script from console"

### Task 6: Build Flask authentication, session, and CSRF foundation

**Files:**

- Create: wxread_console/web.py
- Create: tests/test_web.py
- Create: wxread_console/templates/base.html
- Create: wxread_console/templates/login.html

- [ ] **Step 1: Write failing authentication tests**

Create the initial tests/test_web.py:

~~~python
from pathlib import Path

import pytest

from wxread_console.web import create_app


@pytest.fixture()
def app(tmp_path: Path):
    return create_app(
        {
            "TESTING": True,
            "WXREAD_CONSOLE_ENV": "test",
            "WXREAD_ADMIN_PASSWORD": "correct-password",
            "WXREAD_SESSION_SECRET": "test-secret",
            "WXREAD_DATA_DIR": str(tmp_path),
        }
    )


@pytest.fixture()
def client(app):
    return app.test_client()


def test_dashboard_redirects_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def login_form_csrf(client) -> str:
    client.get("/login")
    with client.session_transaction() as current:
        return current["csrf_token"]


def test_login_rejects_wrong_password(client):
    response = client.post(
        "/login",
        data={"password": "wrong", "csrf_token": login_form_csrf(client)},
    )
    assert response.status_code == 401
    assert "密码不正确".encode() in response.data


def test_login_allows_admin(client):
    response = client.post(
        "/login",
        data={
            "password": "correct-password",
            "csrf_token": login_form_csrf(client),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "控制台总览".encode() in response.data
~~~

- [ ] **Step 2: Run auth tests and verify failure**

Run:

    python -m pytest tests/test_web.py -v

Expected: FAIL because wxread_console.web does not exist.

- [ ] **Step 3: Implement app factory and authentication**

Create wxread_console/web.py with these exact public seams:

~~~python
from __future__ import annotations

import hmac
import secrets
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

from .database import Database, RunAlreadyActive
from .secret_store import SecretStore
from .settings import Settings


def create_app(overrides: Mapping[str, Any] | None = None) -> Flask:
    overrides = dict(overrides or {})
    env = {
        key: str(value)
        for key, value in overrides.items()
        if key.startswith("WXREAD_")
    }
    settings = Settings.from_env(env or None)
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.session_secret,
        TESTING=bool(overrides.get("TESTING", False)),
        ENVIRONMENT=settings.environment,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.environment == "production",
    )
    database = Database(settings.database_path)
    database.initialize()
    database.mark_interrupted_runs()
    app.extensions["wxread_settings"] = settings
    app.extensions["wxread_database"] = database
    app.extensions["wxread_secret_store"] = SecretStore(settings.secrets_path)

    def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not session.get("authenticated"):
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    def csrf_token() -> str:
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    def require_csrf() -> None:
        expected = session.get("csrf_token", "")
        supplied = request.form.get("csrf_token", "")
        if not expected or not hmac.compare_digest(expected, supplied):
            abort(400, "CSRF validation failed")

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            require_csrf()
            supplied = request.form.get("password", "")
            if not settings.admin_password or not hmac.compare_digest(
                supplied, settings.admin_password
            ):
                return render_template("login.html", error="密码不正确"), 401
            session.clear()
            session["authenticated"] = True
            csrf_token()
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.post("/logout")
    @login_required
    def logout():
        require_csrf()
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def dashboard():
        return render_template(
            "dashboard.html",
            config_state=database.get_config_state(),
            runs=database.list_runs(limit=7),
        )
    return app
~~~

Create wxread_console/templates/base.html:

~~~html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}wxread Console{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='styles.css') }}">
  </head>
  <body>
    {% block body %}{% endblock %}
  </body>
</html>
~~~

Create wxread_console/templates/login.html:

~~~html
{% extends "base.html" %}
{% block title %}登录 · wxread Console{% endblock %}
{% block body %}
<main class="login-shell">
  <section class="login-card">
    <p class="eyebrow">WXREAD CONSOLE</p>
    <h1>欢迎回来</h1>
    <p class="muted">登录后管理 Cookie、运行状态和脱敏日志。</p>
    {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
    <form method="post" class="stack">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <label for="password">管理员密码</label>
      <input id="password" name="password" type="password" required autofocus>
      <button class="button button-primary" type="submit">进入控制台</button>
    </form>
  </section>
</main>
{% endblock %}
~~~

Create a minimal wxread_console/templates/dashboard.html containing:

~~~html
{% extends "base.html" %}
{% block body %}<h1>控制台总览</h1>{% endblock %}
~~~

- [ ] **Step 4: Add minimal CSS required by login smoke test**

Create wxread_console/static/styles.css:

~~~css
:root {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

body {
  margin: 0;
}
~~~

- [ ] **Step 5: Run auth tests**

Run:

    python -m pytest tests/test_web.py -v

Expected: 3 passed.

- [ ] **Step 6: Commit auth foundation**

Run:

    git add wxread_console/web.py wxread_console/templates wxread_console/static/styles.css tests/test_web.py
    git commit -m "feat: add console authentication"

### Task 7: Add configuration, manual-run, history, and log routes

**Files:**

- Modify: wxread_console/web.py
- Modify: tests/test_web.py
- Create: wxread_console/templates/config.html
- Create: wxread_console/templates/runs.html
- Create: wxread_console/templates/run_detail.html

- [ ] **Step 1: Add failing route tests**

Append to tests/test_web.py:

~~~python
def login(client):
    return client.post(
        "/login",
        data={
            "password": "correct-password",
            "csrf_token": login_form_csrf(client),
        },
    )


def csrf_from_session(client) -> str:
    with client.session_transaction() as current:
        return current["csrf_token"]


def test_save_config_persists_secret_and_summary(app, client):
    login(client)
    csrf = csrf_from_session(client)
    curl = (
        "curl 'https://weread.qq.com/web/book/read' "
        "-H 'Cookie: wr_skey=abcdefgh; RK=secret-rk'"
    )

    response = client.post(
        "/config",
        data={
            "csrf_token": csrf,
            "curl_bash": curl,
            "read_num": "40",
            "push_method": "",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "wr_skey=ab***".encode() in response.data
    store = app.extensions["wxread_secret_store"]
    assert store.load()["WXREAD_CURL_BASH"] == curl


def test_save_config_rejects_invalid_curl(client):
    login(client)
    response = client.post(
        "/config",
        data={
            "csrf_token": csrf_from_session(client),
            "curl_bash": "curl https://example.com",
            "read_num": "40",
            "push_method": "",
        },
    )
    assert response.status_code == 400
    assert "weread.qq.com".encode() in response.data


def test_run_requires_csrf(client):
    login(client)
    assert client.post("/runs").status_code == 400


def test_run_history_page_requires_login(client):
    response = client.get("/runs")
    assert response.status_code == 302
~~~

- [ ] **Step 2: Run the route tests and verify failure**

Run:

    python -m pytest tests/test_web.py -v

Expected: FAIL because /config and /runs routes are not implemented.

- [ ] **Step 3: Implement route registration**

Add register_console_routes to wxread_console/web.py with:

~~~python
def register_console_routes(
    app: Flask,
    login_required: Callable[[Callable[..., Any]], Callable[..., Any]],
    require_csrf: Callable[[], None],
) -> None:
    from .curl_parser import CurlParseError, parse_weread_curl
    from .runner import RunService

    settings: Settings = app.extensions["wxread_settings"]
    database: Database = app.extensions["wxread_database"]
    store: SecretStore = app.extensions["wxread_secret_store"]
    runner = RunService(database, settings.repo_root, settings.run_timeout_seconds)
    app.extensions["wxread_runner"] = runner

    @app.route("/config", methods=["GET", "POST"])
    @login_required
    def config_page():
        if request.method == "GET":
            return render_template(
                "config.html",
                state=database.get_config_state(),
            )
        require_csrf()
        existing = store.load()
        curl_bash = (
            request.form.get("curl_bash", "").strip()
            or existing.get("WXREAD_CURL_BASH", "")
        )
        try:
            parsed = parse_weread_curl(curl_bash)
            read_num = int(request.form.get("read_num", "40"))
            if not 1 <= read_num <= 480:
                raise ValueError("READ_NUM 必须在 1 到 480 之间")
        except (CurlParseError, ValueError) as exc:
            return render_template(
                "config.html", state=database.get_config_state(), error=str(exc)
            ), 400

        values = {
            "WXREAD_CURL_BASH": curl_bash,
            "READ_NUM": str(read_num),
            "PUSH_METHOD": request.form.get("push_method", "").strip(),
            "PUSHPLUS_TOKEN": (
                request.form.get("pushplus_token", "").strip()
                or existing.get("PUSHPLUS_TOKEN", "")
            ),
            "WXPUSHER_SPT": (
                request.form.get("wxpusher_spt", "").strip()
                or existing.get("WXPUSHER_SPT", "")
            ),
            "TELEGRAM_BOT_TOKEN": (
                request.form.get("telegram_bot_token", "").strip()
                or existing.get("TELEGRAM_BOT_TOKEN", "")
            ),
            "TELEGRAM_CHAT_ID": (
                request.form.get("telegram_chat_id", "").strip()
                or existing.get("TELEGRAM_CHAT_ID", "")
            ),
            "SERVERCHAN_SPT": (
                request.form.get("serverchan_spt", "").strip()
                or existing.get("SERVERCHAN_SPT", "")
            ),
        }
        store.save(values)
        database.save_config_state(
            curl_summary=parsed.cookie_summary,
            read_num=read_num,
            push_method=values["PUSH_METHOD"],
            push_summary="configured" if values["PUSH_METHOD"] else "disabled",
        )
        flash("配置已验证并保存", "success")
        return redirect(url_for("config_page"))

    @app.route("/runs", methods=["GET", "POST"])
    @login_required
    def runs_page():
        if request.method == "POST":
            require_csrf()
            values = store.load()
            if not values.get("WXREAD_CURL_BASH"):
                flash("请先保存微信读书 curl 配置", "error")
                return redirect(url_for("config_page"))
            try:
                run_id = runner.start_background(values)
            except RunAlreadyActive:
                flash("已有任务正在运行，请等待完成后再试", "warning")
                return redirect(url_for("dashboard"))
            return redirect(url_for("run_detail", run_id=run_id))
        return render_template("runs.html", runs=database.list_runs())

    @app.get("/runs/<int:run_id>")
    @login_required
    def run_detail(run_id: int):
        try:
            run = database.get_run(run_id)
        except KeyError:
            abort(404)
        return render_template(
            "run_detail.html",
            run=run,
            logs=database.get_logs(run_id),
        )
~~~

Then call register_console_routes(app, login_required, require_csrf) immediately before return app inside create_app.

- [ ] **Step 4: Add functional templates**

Create config.html with fields for curl_bash, read_num, push_method, and all push tokens. Every secret input except curl_bash must use type=password. Do not prefill raw curl or token values; a blank field preserves the existing saved value. Include:

~~~html
<form method="post" class="panel stack">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <label for="curl_bash">微信读书 read 接口 curl bash</label>
  <textarea id="curl_bash" name="curl_bash" rows="10" required></textarea>
  <label for="read_num">阅读次数</label>
  <input id="read_num" name="read_num" type="number" min="1" max="480" value="{{ state.read_num if state else 40 }}">
  <label for="push_method">推送方式</label>
  <select id="push_method" name="push_method">
    <option value="">不推送</option>
    <option value="pushplus">PushPlus</option>
    <option value="wxpusher">WxPusher</option>
    <option value="telegram">Telegram</option>
    <option value="serverchan">ServerChan</option>
  </select>
  <details>
    <summary>推送密钥</summary>
    <input name="pushplus_token" type="password" placeholder="PushPlus token">
    <input name="wxpusher_spt" type="password" placeholder="WxPusher SPT">
    <input name="telegram_bot_token" type="password" placeholder="Telegram bot token">
    <input name="telegram_chat_id" type="password" placeholder="Telegram chat ID">
    <input name="serverchan_spt" type="password" placeholder="ServerChan SPT">
  </details>
  <button class="button button-primary" type="submit">验证并保存</button>
</form>
~~~

Create runs.html with a responsive table showing id, trigger, status, started_at, duration_seconds, and a detail link.

Create run_detail.html with a status header, timing metadata, error summary, and a preformatted list of redacted log messages. Add data-running=true when run.status equals running so app.js can refresh.

- [ ] **Step 5: Run all web tests**

Run:

    python -m pytest tests/test_web.py -v

Expected: all tests pass.

- [ ] **Step 6: Commit routes**

Run:

    git add wxread_console/web.py wxread_console/templates tests/test_web.py
    git commit -m "feat: add console configuration and runs"

### Task 8: Deliver the polished product-designed interface

**Files:**

- Modify: wxread_console/templates/base.html
- Modify: wxread_console/templates/login.html
- Modify: wxread_console/templates/dashboard.html
- Modify: wxread_console/templates/config.html
- Modify: wxread_console/templates/runs.html
- Modify: wxread_console/templates/run_detail.html
- Modify: wxread_console/static/styles.css
- Create: wxread_console/static/app.js
- Test: tests/test_web.py

- [ ] **Step 1: Add failing presentation smoke tests**

Append to tests/test_web.py:

~~~python
def test_authenticated_shell_has_navigation(client):
    login(client)
    response = client.get("/")
    assert "控制台总览".encode() in response.data
    assert "配置".encode() in response.data
    assert "运行记录".encode() in response.data
    assert "退出".encode() in response.data


def test_dashboard_has_status_cards(client):
    login(client)
    response = client.get("/")
    assert "Cookie 状态".encode() in response.data
    assert "最近运行".encode() in response.data
    assert "预计阅读".encode() in response.data
    assert "最近成功率".encode() in response.data
~~~

- [ ] **Step 2: Run presentation tests and verify failure**

Run:

    python -m pytest tests/test_web.py -k "shell or status_cards" -v

Expected: FAIL because the temporary dashboard and base templates lack the polished shell.

- [ ] **Step 3: Build the shared application shell**

Update base.html to include:

- A compact wordmark: wxread Console.
- Desktop sidebar and mobile top bar.
- Navigation links for Dashboard, 配置, and 运行记录.
- A POST logout form with CSRF token.
- Flash message stack.
- Main content area with page title and optional page actions.
- static/app.js loaded with defer.

Use semantic landmarks: aside, nav, header, main, and footer. Add aria-current=page for the active navigation item.

- [ ] **Step 4: Build dashboard information hierarchy**

Dashboard must show four compact cards in this order:

1. Cookie 状态 — configured/missing and redacted summary.
2. 最近运行 — running/success/failed/timeout.
3. 预计阅读 — READ_NUM and calculated minutes.
4. 最近成功率 — successful terminal runs divided by last seven terminal runs.

Replace the dashboard route from Task 6 with:

~~~python
    @app.get("/")
    @login_required
    def dashboard():
        config_state = database.get_config_state()
        runs = database.list_runs(limit=7)
        terminal = [
            run for run in runs
            if run["status"] in {"success", "failed", "partial_success", "timeout"}
        ]
        successful = [
            run for run in terminal
            if run["status"] in {"success", "partial_success"}
        ]
        success_rate = (
            round(len(successful) / len(terminal) * 100)
            if terminal
            else None
        )
        return render_template(
            "dashboard.html",
            config_state=config_state,
            runs=runs,
            latest_run=runs[0] if runs else None,
            success_rate=success_rate,
        )
~~~

Below the cards, use a two-column layout:

- Left: quick actions and a clear primary Run Once button.
- Right: last seven runs with status badges and timestamps.

Status colors:

- success: emerald.
- running: indigo with a subtle pulse.
- partial_success or warning: amber.
- failed or timeout: red.
- idle or unknown: slate.

- [ ] **Step 5: Replace styles.css with the visual system**

Implement these exact design tokens at the top of styles.css:

~~~css
:root {
  color-scheme: light;
  --canvas: #f4f6fb;
  --surface: #ffffff;
  --surface-muted: #f8fafc;
  --ink: #172033;
  --muted: #667085;
  --line: #e4e8f0;
  --brand: #5965d8;
  --brand-strong: #404bb5;
  --success: #17875d;
  --warning: #b56a09;
  --danger: #c43d4b;
  --shadow: 0 18px 50px rgba(30, 42, 76, 0.10);
  --radius-lg: 22px;
  --radius-md: 14px;
  --radius-sm: 10px;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
~~~

CSS acceptance:

- Body uses the soft canvas, not plain white.
- Panels use restrained shadows and 1px borders.
- Maximum content width is approximately 1280px.
- Typography uses a clear 12/14/16/24/32px scale.
- Buttons have visible hover, focus-visible, and disabled states.
- Form controls use at least 44px hit height.
- Code and logs use a monospace stack and dark ink-on-light background.
- Tables collapse into card rows below 760px.
- Sidebar becomes a horizontal mobile navigation below 900px.
- No external fonts, icon services, or image assets are required.
- Respect prefers-reduced-motion.

- [ ] **Step 6: Add small interaction helpers**

Create static/app.js:

~~~javascript
document.querySelectorAll("[data-confirm]").forEach((element) => {
  element.addEventListener("click", (event) => {
    if (!window.confirm(element.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

const runningDetail = document.querySelector("[data-running='true']");
if (runningDetail) {
  window.setTimeout(() => window.location.reload(), 3000);
}

document.querySelectorAll("[data-secret-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.secretToggle);
    if (input) {
      input.type = input.type === "password" ? "text" : "password";
    }
  });
});
~~~

- [ ] **Step 7: Run web tests and inspect responsive pages**

Run:

    python -m pytest tests/test_web.py -v
    WXREAD_CONSOLE_ENV=development WXREAD_ADMIN_PASSWORD=dev-password WXREAD_SESSION_SECRET=dev-secret python -m wxread_console

Expected:

- Tests pass.
- Login page is readable at 390px and desktop widths.
- Dashboard cards wrap without horizontal scroll.
- Config form groups advanced push fields under a details section.
- Run history remains legible on mobile.
- Focus outlines are clearly visible.

- [ ] **Step 8: Commit polished interface**

Run:

    git add wxread_console/templates wxread_console/static tests/test_web.py
    git commit -m "feat: polish wxread console interface"

### Task 9: Add console-specific Docker deployment and documentation

**Files:**

- Create: Dockerfile.console
- Create: docs/wxread-console.md
- Test: tests/test_upstream_boundary.py

- [ ] **Step 1: Write upstream-boundary test**

Create tests/test_upstream_boundary.py:

~~~python
from pathlib import Path


def test_console_does_not_require_upstream_imports():
    root = Path(__file__).resolve().parents[1]
    console_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "wxread_console").glob("*.py")
    )
    assert "import main" not in console_source
    assert "from main import" not in console_source
    assert "import config" not in console_source
    assert "from config import" not in console_source


def test_console_dockerfile_is_separate():
    root = Path(__file__).resolve().parents[1]
    assert (root / "Dockerfile.console").exists()
    assert (root / "Dockerfile").exists()
~~~

- [ ] **Step 2: Create console Dockerfile**

Create Dockerfile.console:

~~~dockerfile
FROM python:3.10-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WXREAD_CONSOLE_ENV=production
ENV WXREAD_DATA_DIR=/app/data

COPY requirements-console.txt ./
RUN pip install --no-cache-dir -r requirements-console.txt

COPY main.py config.py push.py log_utils.py ./
COPY wxread_console ./wxread_console

RUN mkdir -p /app/data
VOLUME ["/app/data"]
EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "wxread_console.web:create_app()"]
~~~

Use one gunicorn worker in v1 because background run coordination is process-local in addition to the SQLite unique-active-run guard.

- [ ] **Step 3: Write deployment documentation**

Create docs/wxread-console.md with:

- Security warning that public deployments need HTTPS.
- Required variables:
  - WXREAD_ADMIN_PASSWORD
  - WXREAD_SESSION_SECRET
- Optional variables:
  - WXREAD_DATA_DIR
  - WXREAD_RUN_TIMEOUT_SECONDS
- Local startup:

      python -m pip install -r requirements-console.txt
      WXREAD_ADMIN_PASSWORD=change-me WXREAD_SESSION_SECRET=change-me-too python -m wxread_console

- Docker build and run:

      docker build -f Dockerfile.console -t wxread-console .
      docker run -d --name wxread-console -p 8080:8080 -v wxread-data:/app/data -e WXREAD_ADMIN_PASSWORD=change-me -e WXREAD_SESSION_SECRET=change-me-too wxread-console

- Reverse proxy recommendation.
- Secret-file backup warning.
- How to add upstream remote:

      git remote add upstream https://github.com/findmover/wxread.git
      git fetch upstream
      git merge upstream/main

- Clarify that the original Dockerfile and GitHub Actions workflow remain available.

- [ ] **Step 4: Run the complete automated suite**

Run:

    python -m pytest -v

Expected: all tests pass.

- [ ] **Step 5: Build the console image**

Run:

    docker build -f Dockerfile.console -t wxread-console:test .

Expected: image builds successfully.

- [ ] **Step 6: Smoke-test the image**

Run:

    docker run --rm -d --name wxread-console-smoke -p 18080:8080 -e WXREAD_ADMIN_PASSWORD=test-password -e WXREAD_SESSION_SECRET=test-session wxread-console:test
    curl -I http://127.0.0.1:18080/login
    docker stop wxread-console-smoke

Expected: login endpoint returns HTTP 200, and the container stops cleanly.

- [ ] **Step 7: Verify upstream files were not modified**

Run:

    git diff origin/main -- main.py config.py push.py log_utils.py Dockerfile .github/workflows/deploy.yml

Expected: no output.

- [ ] **Step 8: Commit deployment and docs**

Run:

    git add Dockerfile.console docs/wxread-console.md tests/test_upstream_boundary.py
    git commit -m "docs: add console deployment"

### Task 10: Final verification and handoff

**Files:**

- Verify only; no planned source changes.

- [ ] **Step 1: Run all tests from a clean environment**

Run:

    python -m pytest -v

Expected: all tests pass with no warnings caused by console code.

- [ ] **Step 2: Check secret patterns are absent from tracked runtime artifacts**

Run:

    git status --short
    rg -n "wr_skey=.*[^*]|TELEGRAM_BOT_TOKEN=|PUSHPLUS_TOKEN=" wxread_console tests docs --glob '!docs/superpowers/**'

Expected:

- No data/ files are tracked.
- Search finds only intentional test fixtures or documentation variable names, never real secrets.

- [ ] **Step 3: Verify upstream compatibility boundary**

Run:

    git diff origin/main -- main.py config.py push.py log_utils.py Dockerfile .github/workflows/deploy.yml

Expected: no output.

- [ ] **Step 4: Perform browser acceptance**

Check at desktop width and approximately 390px mobile width:

- Login has clear hierarchy and no overflow.
- Dashboard has four readable status cards.
- Missing Cookie state points to 配置.
- Config textarea accepts a full curl command.
- Secret fields are password inputs.
- Run button shows a confirmation and prevents duplicate active runs.
- Running detail auto-refreshes.
- Status colors remain understandable with text labels.
- Keyboard focus is visible.
- No raw secret appears in page HTML, SQLite, or run logs.

- [ ] **Step 5: Review commit history**

Run:

    git log --oneline --max-count=12

Expected: small commits matching the task boundaries above.

- [ ] **Step 6: Stop the visual brainstorming server and remove local-only artifacts if desired**

The visual companion files under .superpowers/ are ignored by git. Stop the session after implementation review; do not commit those artifacts.

## Spec coverage checklist

- Single-admin authentication: Tasks 6 and 8.
- Public self-hosted security defaults: Tasks 1, 2, 3, 6, 9.
- Paste full curl bash: Tasks 3 and 7.
- Config summary without SQLite secrets: Tasks 3, 4, and 7.
- Manual run via environment and unchanged main.py: Tasks 5 and 7.
- SQLite run history and redacted logs: Tasks 2, 4, 5, and 7.
- Duplicate-run protection and timeout: Tasks 4 and 5.
- Dashboard, config, history, and logs: Tasks 7 and 8.
- Attractive responsive UI: Task 8.
- Separate Docker deployment: Task 9.
- Preserve original GitHub Actions and upstream files: Tasks 9 and 10.
