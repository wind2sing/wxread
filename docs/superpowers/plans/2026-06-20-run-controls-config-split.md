# Run Controls and Config Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Automated tests are intentionally omitted per the owner's instruction; use smoke checks instead.

**Goal:** Add stop-running support and split global Cookie/push configuration from per-run READ_NUM settings.

**Architecture:** Keep global secrets in SecretStore and config_state. Store manual default read_num in config_state only as UI default. Store automatic read_num in schedule_state. RunService tracks active Popen processes in memory and exposes cancel_run for the currently running process.

**Tech Stack:** Python, Flask, sqlite3, Jinja, current vanilla CSS.

---

## Tasks

- [ ] Add cancelled finish support and schedule read_num persistence.
- [ ] Refactor RunService to track active processes and cancel running jobs.
- [ ] Split UI: global config page only Cookie/push; dashboard manual run form accepts read_num; schedule form accepts read_num.
- [ ] Verify with py_compile, fake script cancellation smoke, local HTTP smoke.
- [ ] Commit, push, and deploy to Dokploy.
