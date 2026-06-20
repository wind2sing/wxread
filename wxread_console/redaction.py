from __future__ import annotations

import re


TOKEN_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "PUSHPLUS_TOKEN",
    "WXPUSHER_SPT",
    "SERVERCHAN_SPT",
    "wr_skey",
    "RK",
    "ptcz",
    "pac_uid",
)


def mask_value(value: str) -> str:
    return f"{value[:2]}***" if value else ""


def redact_text(text: str) -> str:
    result = text
    if "curl " in result.lower() and "weread.qq.com/web/book/read" in result:
        return "curl [REDACTED]"
    result = re.sub(
        r"(?im)(cookie\s*:\s*)[^\r\n]+",
        r"\1[REDACTED]",
        result,
    )
    for key in TOKEN_KEYS:
        result = re.sub(
            rf"(?i)({re.escape(key)}\s*[=:]\s*)[^;\s'\"]+",
            rf"\1[REDACTED]",
            result,
        )
    return result
