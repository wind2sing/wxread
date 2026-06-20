from __future__ import annotations

import logging
import os
import runpy
from pathlib import Path
from typing import Any

import requests

from .cookie_refresh import RENEW_URL, update_cookie_value
from .redaction import redact_text
from .secret_store import SecretStore


_original_post = requests.post


def _persist_refreshed_wrskey(response: Any) -> None:
    wr_skey = getattr(response, "cookies", {}).get("wr_skey")
    if not wr_skey:
        return

    new_value = str(wr_skey)[:8]
    secrets_path = os.getenv("WXREAD_SECRETS_PATH")
    curl_bash = os.getenv("WXREAD_CURL_BASH")
    if not secrets_path or not curl_bash:
        return

    try:
        store = SecretStore(Path(secrets_path))
        saved = store.load()
        current_curl = saved.get("WXREAD_CURL_BASH") or curl_bash
        updated_curl = update_cookie_value(current_curl, "wr_skey", new_value)
        saved["WXREAD_CURL_BASH"] = updated_curl
        store.save(saved)
        os.environ["WXREAD_CURL_BASH"] = updated_curl
        logging.info(f"控制台已捕获并保存本次 wr_skey 刷新：{new_value[:2]}***")
    except Exception as exc:  # pragma: no cover - best-effort persistence
        logging.warning(
            "控制台保存本次 wr_skey 刷新失败：%s",
            redact_text(str(exc)),
        )


def _patched_post(url: Any, *args: Any, **kwargs: Any) -> requests.Response:
    response = _original_post(url, *args, **kwargs)
    if str(url).startswith(RENEW_URL):
        _persist_refreshed_wrskey(response)
    return response


def main() -> None:
    requests.post = _patched_post
    repo_root = Path(__file__).resolve().parents[1]
    runpy.run_path(str(repo_root / "main.py"), run_name="__main__")


if __name__ == "__main__":
    main()
