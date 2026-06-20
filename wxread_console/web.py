from __future__ import annotations

import hmac
import secrets
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .curl_parser import CurlParseError, parse_weread_curl
from .database import Database, RunAlreadyActive
from .runner import RunService
from .secret_store import SecretStore
from .settings import Settings


PUSH_METHODS = {"", "pushplus", "wxpusher", "telegram", "serverchan"}
STATUS_LABELS = {
    "running": "运行中",
    "success": "成功",
    "failed": "失败",
    "partial_success": "部分成功",
    "timeout": "超时",
    "cancelled": "已取消",
}


def create_app(overrides: Mapping[str, Any] | None = None) -> Flask:
    override_values = dict(overrides or {})
    settings = Settings.from_env(
        {key: str(value) for key, value in override_values.items() if key.startswith("WXREAD_")}
    )
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.session_secret,
        ENVIRONMENT=settings.environment,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.environment == "production",
    )
    app.config.update(
        {key: value for key, value in override_values.items() if not key.startswith("WXREAD_")}
    )

    database = Database(settings.database_path)
    database.initialize()
    database.mark_interrupted_runs()
    store = SecretStore(settings.secrets_path)
    runner = RunService(database, settings.repo_root, settings.run_timeout_seconds)
    app.extensions["wxread_settings"] = settings
    app.extensions["wxread_database"] = database
    app.extensions["wxread_secret_store"] = store
    app.extensions["wxread_runner"] = runner

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
    app.jinja_env.globals["status_label"] = lambda value: STATUS_LABELS.get(value, value)

    @app.template_filter("datetime_cn")
    def datetime_cn(value: str | None) -> str:
        if not value:
            return "—"
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return str(value)

    @app.template_filter("duration")
    def duration(value: float | None) -> str:
        if value is None:
            return "—"
        seconds = int(value)
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes}分 {seconds}秒" if minutes else f"{seconds}秒"

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
        if session.get("authenticated"):
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
        config_state = database.get_config_state()
        runs = database.list_runs(limit=7)
        terminal = [
            run
            for run in runs
            if run["status"] in {"success", "failed", "partial_success", "timeout"}
        ]
        successful = [
            run for run in terminal if run["status"] in {"success", "partial_success"}
        ]
        success_rate = (
            round(len(successful) / len(terminal) * 100) if terminal else None
        )
        return render_template(
            "dashboard.html",
            config_state=config_state,
            runs=runs,
            latest_run=runs[0] if runs else None,
            success_rate=success_rate,
        )

    @app.route("/config", methods=["GET", "POST"])
    @login_required
    def config_page():
        state = database.get_config_state()
        if request.method == "GET":
            return render_template("config.html", state=state)

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
            push_method = request.form.get("push_method", "").strip().lower()
            if push_method not in PUSH_METHODS:
                raise ValueError("推送方式无效")
        except (CurlParseError, ValueError) as exc:
            return render_template("config.html", state=state, error=str(exc)), 400

        values = {
            "WXREAD_CURL_BASH": curl_bash,
            "READ_NUM": str(read_num),
            "PUSH_METHOD": push_method,
            "PUSHPLUS_TOKEN": _saved_or_submitted(request, existing, "pushplus_token", "PUSHPLUS_TOKEN"),
            "WXPUSHER_SPT": _saved_or_submitted(request, existing, "wxpusher_spt", "WXPUSHER_SPT"),
            "TELEGRAM_BOT_TOKEN": _saved_or_submitted(
                request, existing, "telegram_bot_token", "TELEGRAM_BOT_TOKEN"
            ),
            "TELEGRAM_CHAT_ID": _saved_or_submitted(
                request, existing, "telegram_chat_id", "TELEGRAM_CHAT_ID"
            ),
            "SERVERCHAN_SPT": _saved_or_submitted(
                request, existing, "serverchan_spt", "SERVERCHAN_SPT"
            ),
        }
        missing = _missing_push_value(push_method, values)
        if missing:
            return render_template("config.html", state=state, error=missing), 400

        store.save(values)
        database.save_config_state(
            curl_summary=parsed.cookie_summary,
            read_num=read_num,
            push_method=push_method,
            push_summary="已配置" if push_method else "未启用",
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

    return app


def _saved_or_submitted(
    request: Any,
    existing: Mapping[str, str],
    form_name: str,
    env_name: str,
) -> str:
    return request.form.get(form_name, "").strip() or existing.get(env_name, "")


def _missing_push_value(push_method: str, values: Mapping[str, str]) -> str | None:
    requirements = {
        "pushplus": ("PUSHPLUS_TOKEN", "请填写 PushPlus token"),
        "wxpusher": ("WXPUSHER_SPT", "请填写 WxPusher SPT"),
        "serverchan": ("SERVERCHAN_SPT", "请填写 ServerChan SendKey"),
    }
    if push_method == "telegram":
        if not values.get("TELEGRAM_BOT_TOKEN") or not values.get("TELEGRAM_CHAT_ID"):
            return "请填写 Telegram bot token 和 chat ID"
        return None
    requirement = requirements.get(push_method)
    if requirement and not values.get(requirement[0]):
        return requirement[1]
    return None
