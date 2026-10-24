"""Strip contact details from text before it leaves the server."""
import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s().\-]{8,}\d(?!\w)")
_URL = re.compile(r"(?:https?://|www\.)\S+|(?:linkedin|github)\.com/\S+", re.IGNORECASE)


def _redact_phone(match: re.Match) -> str:
    digits = sum(ch.isdigit() for ch in match.group(0))
    # Real phone numbers have 10+ digits; this avoids wiping ranges like "2019 - 2023".
    return "[PHONE]" if digits >= 10 else match.group(0)


def redact_pii(text: str) -> str:
    text = _EMAIL.sub("[EMAIL]", text)
    text = _URL.sub("[LINK]", text)
    return _PHONE.sub(_redact_phone, text)
