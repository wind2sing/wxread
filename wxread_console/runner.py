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

    def start_background(self, environment: Mapping[str, str]) -> int:
        run_id = self.database.create_run(
            "manual", int(environment.get("READ_NUM", "40"))
        )
        thread = threading.Thread(
            target=self._execute,
            args=(run_id, self.repo_root / "main.py", environment),
            daemon=True,
            name=f"wxread-run-{run_id}",
        )
        thread.start()
        return run_id

    def _execute(
        self,
        run_id: int,
        script: Path,
        environment: Mapping[str, str],
    ) -> None:
        child_environment = os.environ.copy()
        child_environment.update(environment)
        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=self.repo_root,
                env=child_environment,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            outputs = (("stdout", result.stdout), ("stderr", result.stderr))
            combined = "\n".join(text for _, text in outputs if text)
            for stream, output in outputs:
                for line in output.splitlines():
                    self.database.append_log(run_id, stream, "INFO", redact_text(line))

            progress = [
                int(value)
                for value in re.findall(r"阅读进度:\s*第\s*(\d+)/\d+\s*次", combined)
            ]
            if progress:
                self.database.update_completed_steps(run_id, max(progress))

            if result.returncode != 0:
                status = "failed"
                summary = "脚本异常退出，请查看脱敏日志"
            elif "阅读脚本已完成" in combined and "推送失败" in combined:
                status = "partial_success"
                summary = "阅读任务已完成，但推送失败"
            else:
                status = "success"
                summary = None
            self.database.finish_run(run_id, status, result.returncode, summary)
        except subprocess.TimeoutExpired as exc:
            output = "\n".join(
                value.decode() if isinstance(value, bytes) else value or ""
                for value in (exc.stdout, exc.stderr)
            )
            if output:
                self.database.append_log(run_id, "stderr", "ERROR", redact_text(output))
            self.database.finish_run(
                run_id, "timeout", None, "运行超时，请检查网络或 READ_NUM"
            )
        except Exception as exc:
            self.database.append_log(run_id, "stderr", "ERROR", redact_text(str(exc)))
            self.database.finish_run(run_id, "failed", None, "控制台启动脚本失败")
