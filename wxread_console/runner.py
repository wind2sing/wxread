from __future__ import annotations

import os
import re
import select
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Mapping

from .cookie_refresh import CookieRefreshError, refresh_wrskey_in_curl
from .database import Database
from .secret_store import SecretStore
from .redaction import redact_text


class RunService:
    def __init__(
        self,
        database: Database,
        repo_root: Path,
        timeout_seconds: float,
        secret_store: SecretStore | None = None,
    ):
        self.database = database
        self.repo_root = repo_root
        self.timeout_seconds = timeout_seconds
        self.secret_store = secret_store
        self._processes: dict[int, subprocess.Popen[str]] = {}
        self._cancelled: set[int] = set()
        self._lock = threading.Lock()

    def start_background(
        self,
        environment: Mapping[str, str],
        trigger: str = "manual",
    ) -> int:
        run_id = self.database.create_run(
            trigger, int(environment.get("READ_NUM", "40"))
        )
        thread = threading.Thread(
            target=self._execute,
            args=(run_id, environment),
            daemon=True,
            name=f"wxread-run-{run_id}",
        )
        thread.start()
        return run_id

    def cancel_run(self, run_id: int) -> bool:
        with self._lock:
            process = self._processes.get(run_id)
            if process is None or process.poll() is not None:
                return False
            self._cancelled.add(run_id)
            process.terminate()
        self.database.append_log(run_id, "stdout", "INFO", "用户手动停止运行")
        self.database.cancel_run(run_id)
        return True

    def _execute(
        self,
        run_id: int,
        environment: Mapping[str, str],
    ) -> None:
        prepared_environment = dict(environment)
        self._refresh_and_persist_cookie(run_id, prepared_environment)
        if self.secret_store is not None:
            prepared_environment["WXREAD_SECRETS_PATH"] = str(self.secret_store.path)
        child_environment = os.environ.copy()
        child_environment.update(prepared_environment)
        child_environment["PYTHONUNBUFFERED"] = "1"
        chunks: list[str] = []
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "wxread_console.upstream_runner"],
                cwd=self.repo_root,
                env=child_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=0,
            )
            if process.stdout is None:
                raise RuntimeError("无法捕获阅读脚本输出")
            with self._lock:
                self._processes[run_id] = process

            started = time.monotonic()
            buffer = ""
            while True:
                with self._lock:
                    is_cancelled = run_id in self._cancelled
                if is_cancelled:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                    return

                if time.monotonic() - started > self.timeout_seconds:
                    process.kill()
                    remaining = process.communicate(timeout=5)[0] or ""
                    if remaining:
                        chunks.append(remaining)
                        buffer = self._consume_output(run_id, buffer + remaining)
                    if buffer.strip():
                        self._record_message(run_id, buffer)
                    self.database.finish_run(
                        run_id, "timeout", None, "运行超时，请检查网络或 READ_NUM"
                    )
                    return

                ready, _, _ = select.select([process.stdout], [], [], 0.5)
                if ready:
                    chunk = process.stdout.read(1)
                    if chunk:
                        chunks.append(chunk)
                        buffer = self._consume_output(run_id, buffer + chunk)

                return_code = process.poll()
                if return_code is not None:
                    remaining = process.stdout.read() or ""
                    if remaining:
                        chunks.append(remaining)
                        buffer = self._consume_output(run_id, buffer + remaining)
                    if buffer.strip():
                        self._record_message(run_id, buffer)
                    break

            combined = "".join(chunks)
            with self._lock:
                is_cancelled = run_id in self._cancelled
            if is_cancelled:
                return
            if return_code != 0:
                status = "failed"
                summary = "脚本异常退出，请查看脱敏日志"
            elif "阅读脚本已完成" in combined and "推送失败" in combined:
                status = "partial_success"
                summary = "阅读任务已完成，但推送失败"
            else:
                status = "success"
                summary = None
            self.database.finish_run(run_id, status, return_code, summary)
        except Exception as exc:
            self.database.append_log(run_id, "stderr", "ERROR", redact_text(str(exc)))
            self.database.finish_run(run_id, "failed", None, "控制台启动脚本失败")
        finally:
            with self._lock:
                self._processes.pop(run_id, None)
                self._cancelled.discard(run_id)

    def _consume_output(self, run_id: int, text: str) -> str:
        parts = re.split(r"[\r\n]", text)
        for message in parts[:-1]:
            self._record_message(run_id, message)
        return parts[-1]

    def _record_message(self, run_id: int, message: str) -> None:
        clean = message.strip()
        if not clean:
            return
        self.database.append_log(run_id, "stdout", "INFO", redact_text(clean))
        progress = re.search(r"阅读进度:\s*第\s*(\d+)/\d+\s*次", clean)
        if progress:
            self.database.update_completed_steps(run_id, int(progress.group(1)))

    def _refresh_and_persist_cookie(
        self,
        run_id: int,
        environment: dict[str, str],
    ) -> None:
        if self.secret_store is None:
            return
        saved = self.secret_store.load()
        curl_bash = saved.get("WXREAD_CURL_BASH") or environment.get("WXREAD_CURL_BASH")
        if not curl_bash:
            return
        try:
            result = refresh_wrskey_in_curl(curl_bash)
        except (CookieRefreshError, ValueError) as exc:
            self.database.append_log(
                run_id,
                "stdout",
                "INFO",
                f"控制台预刷新 wr_skey 未成功，将交给原脚本刷新：{redact_text(str(exc))}",
            )
            return

        saved["WXREAD_CURL_BASH"] = result.curl_bash
        self.secret_store.save(saved)
        environment["WXREAD_CURL_BASH"] = result.curl_bash
        state = self.database.get_config_state()
        if state:
            self.database.save_config_state(
                curl_summary=result.cookie_summary,
                read_num=state["read_num"],
                push_method=state["push_method"],
                push_summary=state["push_summary"],
            )
        self.database.append_log(
            run_id,
            "stdout",
            "INFO",
            f"控制台已刷新并保存 wr_skey：{result.wr_skey[:2]}***",
        )
