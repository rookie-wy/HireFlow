"""PII 脱敏：输入侧身份证脱敏；输出侧全量脱敏（手机/邮箱/身份证）。"""
from __future__ import annotations

import re
from functools import lru_cache

from app.core.config import get_settings

_PATTERNS = {
    "phone": re.compile(r"1[3-9]\d{9}"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "id_card": re.compile(r"\d{17}[\dXx]"),
}


def _mask_enabled() -> bool:
    return get_settings().enable_pii_masking


@lru_cache(maxsize=1)
def _compiled():
    return _PATTERNS


def mask_id_card(text: str) -> str:
    """输入侧：仅身份证脱敏（手机/邮箱业务上需要保留）。"""
    if not text or not _mask_enabled():
        return text
    return _compiled()["id_card"].sub(lambda m: m.group(0)[:6] + "********" + m.group(0)[-4:], text)


def mask_pii(text: str) -> str:
    """输出侧：全量脱敏。"""
    if not text or not _mask_enabled():
        return text
    out = text
    out = _compiled()["id_card"].sub(lambda m: m.group(0)[:6] + "********" + m.group(0)[-4:], out)
    out = _compiled()["phone"].sub(lambda m: m.group(0)[:3] + "****" + m.group(0)[-4:], out)
    out = _compiled()["email"].sub(lambda m: m.group(0)[:2] + "***" + m.group(0).split("@")[-1], out)
    return out
