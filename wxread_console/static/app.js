document.querySelectorAll("[data-confirm]").forEach((element) => {
  element.addEventListener("click", (event) => {
    if (!window.confirm(element.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

const runDetail = document.querySelector("[data-run-detail]");

function setText(selector, value) {
  const element = document.querySelector(selector);
  if (element) {
    element.textContent = value;
  }
}

function renderLogs(logs) {
  const logView = document.querySelector("[data-log-view]");
  if (!logView) {
    return;
  }
  const shouldStickToBottom =
    logView.scrollHeight - logView.scrollTop - logView.clientHeight < 80;
  logView.replaceChildren();
  if (!logs.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.dataset.emptyLog = "";
    empty.textContent = "暂时没有日志；任务刚启动时可能需要等待几秒。";
    logView.append(empty);
    return;
  }
  logs.forEach((log) => {
    const line = document.createElement("div");
    line.className = "log-line";
    const time = document.createElement("time");
    time.textContent = log.created_at;
    const message = document.createElement("span");
    message.textContent = log.message;
    line.append(time, message);
    logView.append(line);
  });
  if (shouldStickToBottom) {
    logView.scrollTop = logView.scrollHeight;
  }
}

function renderRunSnapshot(snapshot) {
  const status = document.querySelector("[data-run-status]");
  if (status) {
    status.className = `status-badge large ${snapshot.run.status}`;
    status.textContent = snapshot.run.status_label;
  }
  setText("[data-run-completed]", `${snapshot.run.completed_steps} 次`);
  setText("[data-run-progress]", snapshot.progress.summary);
  setText("[data-run-duration]", snapshot.run.duration);
  setText("[data-run-exit-code]", String(snapshot.run.exit_code));

  const progressBar = document.querySelector("[data-run-progress-bar]");
  if (progressBar) {
    progressBar.style.width = `${snapshot.progress.percent}%`;
  }

  const errorSlot = document.querySelector("[data-run-error]");
  if (errorSlot) {
    errorSlot.replaceChildren();
    if (snapshot.run.error_summary) {
      const alert = document.createElement("div");
      alert.className = "alert alert-error";
      alert.textContent = snapshot.run.error_summary;
      errorSlot.append(alert);
    }
  }

  renderLogs(snapshot.logs);

  const isRunning = snapshot.run.status === "running";
  runDetail.dataset.running = isRunning ? "true" : "false";
  const liveIndicator = document.querySelector("[data-live-indicator]");
  if (liveIndicator) {
    liveIndicator.hidden = !isRunning;
  }
  if (!isRunning) {
    document.querySelector(".page-actions form")?.remove();
  }
  return isRunning;
}

if (runDetail?.dataset.running === "true") {
  const runId = runDetail.dataset.runId;
  const poll = async () => {
    const response = await fetch(`/runs/${runId}/snapshot`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      return true;
    }
    return renderRunSnapshot(await response.json());
  };
  const timer = window.setInterval(async () => {
    try {
      const keepPolling = await poll();
      if (!keepPolling) {
        window.clearInterval(timer);
      }
    } catch {
      // Keep the current page usable if a transient network hiccup interrupts polling.
    }
  }, 3000);
}
