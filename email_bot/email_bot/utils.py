"""Small shared helpers."""

from __future__ import annotations

import hashlib
import re

EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


def validate_email(addr: str) -> bool:
    """Return True when *addr* looks like a valid email address."""
    return bool(EMAIL_RE.match(addr))


def template_hash(subject_tpl: str, body_tpl: str, html_tpl: str | None) -> str:
    """Deterministic hash of the template content (for idempotency checks)."""
    h = hashlib.sha256()
    h.update(subject_tpl.encode())
    h.update(body_tpl.encode())
    if html_tpl:
        h.update(html_tpl.encode())
    return h.hexdigest()[:16]
