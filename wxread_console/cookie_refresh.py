from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

import requests

from .curl_parser import CurlParseError, ParsedCurl, parse_weread_curl


RENEW_URL = "https://weread.qq.com/web/login/renewal"
COOKIE_DATA_VARIANTS = (
    {"rq": "%2Fweb%2Fbook%2Fread", "ql": False},
    {"rq": "%2Fweb%2Fbook%2Fread", "ql": True},
    {"rq": "%2Fweb%2Fbook%2Fread"},
)


@dataclass(frozen=True)
class CookieRefreshResult:
    curl_bash: str
    wr_skey: str
    cookie_summary: str


class CookieRefreshError(RuntimeError):
    pass


def refresh_wrskey_in_curl(curl_bash: str, timeout: int = 10) -> CookieRefreshResult:
    parsed = parse_weread_curl(curl_bash)
    last_error = ""
    for payload in COOKIE_DATA_VARIANTS:
        try:
            response = requests.post(
                RENEW_URL,
                headers=parsed.headers,
                cookies=parsed.cookies,
                data=json.dumps(payload, separators=(",", ":")),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_error = str(exc)
            continue

        wr_skey = response.cookies.get("wr_skey")
        if not wr_skey:
            last_error = f"renewal response missing wr_skey, status={response.status_code}"
            continue

        new_cookies = dict(parsed.cookies)
        new_cookies["wr_skey"] = wr_skey[:8]
        updated = ParsedCurl(
            url=parsed.url,
            headers=parsed.headers,
            cookies=new_cookies,
        )
        return CookieRefreshResult(
            curl_bash=build_curl(updated),
            wr_skey=new_cookies["wr_skey"],
            cookie_summary=updated.cookie_summary,
        )

    raise CookieRefreshError(last_error or "无法获取新的 wr_skey")


def update_cookie_value(curl_bash: str, key: str, value: str) -> str:
    parsed = parse_weread_curl(curl_bash)
    cookies = dict(parsed.cookies)
    cookies[key] = value
    return build_curl(ParsedCurl(parsed.url, parsed.headers, cookies))


def build_curl(parsed: ParsedCurl) -> str:
    parts = ["curl", _quote(parsed.url)]
    for key, value in parsed.headers.items():
        parts.extend(["-H", _quote(f"{key}: {value}")])
    cookie_header = "; ".join(
        f"{key}={value}" for key, value in parsed.cookies.items()
    )
    parts.extend(["-H", _quote(f"Cookie: {cookie_header}")])
    return " ".join(parts)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
