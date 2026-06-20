from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .database import Database, RunAlreadyActive
from .runner import RunService
from .secret_store import SecretStore


TIMEZONE = ZoneInfo("Asia/Shanghai")


def next_run_at(schedule: dict, now: datetime | None = None) -> datetime | None:
    if not schedule["enabled"]:
        return None
    current = (now or datetime.now(TIMEZONE)).astimezone(TIMEZONE)
    daily_time = datetime.strptime(schedule["daily_time"], "%H:%M").time()
    candidate = datetime.combine(current.date(), daily_time, TIMEZONE)
    return candidate if candidate > current else candidate + timedelta(days=1)


class ScheduleService:
    def __init__(self, database: Database, store: SecretStore, runner: RunService):
        self.database = database
        self.store = store
        self.runner = runner
        self.timezone = TIMEZONE

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
            self.database.update_schedule_result("missing_config", "缺少微信读书 curl 配置")
            return "missing_config"
        values["READ_NUM"] = str(state["read_num"])
        try:
            run_id = self.runner.start_background(values, trigger="scheduled")
        except RunAlreadyActive:
            self.database.update_schedule_result(
                "skipped_busy", "已有任务运行，当天自动任务已跳过"
            )
            return "skipped_busy"
        self.database.update_schedule_result("started", f"已启动自动任务 #{run_id}")
        return "started"


class SchedulerLoop:
    def __init__(self, service: ScheduleService, interval_seconds: int = 30):
        self.service = service
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="wxread-scheduler"
            )
            self._thread.start()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.service.tick()
            except Exception:
                logging.exception("自动运行调度检查失败")
            self.stop_event.wait(self.interval_seconds)
