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
        wr_skey = self.cookies.get("wr_skey")
        if wr_skey:
            return f"wr_skey={mask_value(wr_skey)}"
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

    expected_url = "https://weread.qq.com/web/book/read"
    url = next((part for part in parts[1:] if part.startswith("http")), "")
    if not url.startswith(expected_url):
        raise CurlParseError("请求地址必须是 weread.qq.com/web/book/read")

    headers: dict[str, str] = {}
    cookie_value = ""
    index = 1
    while index < len(parts):
        part = parts[index]
        if part in ("-H", "--header") and index + 1 < len(parts):
            key, separator, value = parts[index + 1].partition(":")
            if separator:
                if key.lower().strip() == "cookie":
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
