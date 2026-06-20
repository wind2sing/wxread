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
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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
                CREATE TABLE IF NOT EXISTS schedule_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    read_num INTEGER NOT NULL DEFAULT 40,
                    daily_time TEXT NOT NULL DEFAULT '01:00',
                    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                    last_claimed_date TEXT,
                    last_result TEXT NOT NULL DEFAULT 'never',
                    last_message TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(schedule_state)")
            }
            if "read_num" not in columns:
                connection.execute(
                    "ALTER TABLE schedule_state ADD COLUMN read_num INTEGER NOT NULL DEFAULT 40"
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO schedule_state
                (id, enabled, read_num, daily_time, timezone, last_result, updated_at)
                VALUES (1, 0, 40, '01:00', 'Asia/Shanghai', 'never', ?)
                """,
                (utc_now(),),
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
                "UPDATE runs SET completed_steps = ?, updated_at = ? WHERE id = ?",
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
            if row is None:
                return
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

    def cancel_run(self, run_id: int, message: str = "用户手动停止") -> None:
        ended_at = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT started_at FROM runs WHERE id = ? AND status = 'running'",
                (run_id,),
            ).fetchone()
            if row is None:
                return
            started = datetime.fromisoformat(row["started_at"])
            ended = datetime.fromisoformat(ended_at)
            connection.execute(
                """
                UPDATE runs
                SET status = 'cancelled', ended_at = ?, duration_seconds = ?,
                    exit_code = NULL, error_summary = ?, updated_at = ?
                WHERE id = ?
                """,
                (ended_at, (ended - started).total_seconds(), message, ended_at, run_id),
            )

    def get_run(self, run_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
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
            row = connection.execute("SELECT * FROM config_state WHERE id = 1").fetchone()
            return None if row is None else dict(row)

    def get_schedule_state(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM schedule_state WHERE id = 1").fetchone()
            if row is None:
                raise RuntimeError("schedule_state is not initialized")
            return dict(row)

    def save_schedule(self, enabled: bool, daily_time: str, read_num: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE schedule_state
                SET enabled = ?, daily_time = ?, read_num = ?, timezone = 'Asia/Shanghai',
                    last_result = CASE WHEN ? THEN last_result ELSE 'disabled' END,
                    last_message = CASE WHEN ? THEN last_message ELSE '自动运行已关闭' END,
                    updated_at = ?
                WHERE id = 1
                """,
                (int(enabled), daily_time, read_num, int(enabled), int(enabled), utc_now()),
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
