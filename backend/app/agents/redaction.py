"""Telemetry boundary scrubber.

Strips secrets and heavy blobs from payloads before they leave the process
(Langfuse traces, structured logs, error reports).

Two layers of protection:

1. **Key-name allowlist** — keys whose *names* are sensitive (``api_key``,
   ``authorization``, ``token``, ...) have their values replaced with a
   redacted marker regardless of value type. This catches the common case of
   a secret stashed under an obvious key.

2. **Regex pattern scrub** — every string value is run through
   ``app.services.secret_service.scrub`` which detects API-key prefixes,
   bearer tokens, JWTs, AWS keys, GitHub PATs, GitLab PATs, and URL creds.
   This catches secrets that slip past layer 1 (e.g. ``Bearer eyJ...`` inside
   prose).

A third heuristic strips known *heavy* fields (``description_html``,
``raw_content``, geometry coordinates, ...) — these are not sensitive but
bloat traces, distract reviewers, and duplicate data already on the model
inputs.

Notes:
- Returns a *new* structure; the input is not mutated.
- Preserves scalar types (``int``, ``float``, ``bool``, ``None``,
  ``Decimal``, ``datetime``) as-is.
- Long strings get truncated to ``max_str_length`` characters with a
  ``...<truncated>`` suffix.
"""

from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal
from typing import Any

from app.services.secret_service import scrub as scrub_str

# ---------------------------------------------------------------------------
# Sensitive / heavy key catalogues
# ---------------------------------------------------------------------------

# Keys whose VALUES are replaced with ``<redacted: {key}>`` regardless of type.
# Compared case-insensitively and against normalized keys (hyphen / underscore
# treated as equivalent).
SENSITIVE_KEY_NAMES: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "x-api-key",
        "x_api_key",
        "authorization",
        "auth_token",
        "password",
        "secret",
        "token",
        "fernet_key",
        "agents_secret_key",
        "langfuse_secret_key",
        "langfuse_public_key",
        "litellm_api_key",
        "anthropic_api_key",
        "openai_api_key",
    }
)

# Keys whose VALUES are stripped to ``<stripped: {key}>``. Not sensitive,
# just bloat for traces.
HEAVY_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "description_html",
        "description_html_raw",
        "html",
        "raw_content",
        "internal_meta",
        # Geometry — individually small, but a batch of object dicts inflates
        # traces dramatically and we don't need them for trace review.
        "x",
        "y",
        "width",
        "height",
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_TRUNC_SUFFIX = "...<truncated>"


def scrub_for_telemetry(payload: Any, *, max_str_length: int = 2000) -> Any:
    """Return a deep-copied, scrubbed version of ``payload``.

    Rules:
    - Dict keys matching ``SENSITIVE_KEY_NAMES`` (case- and separator-
      insensitive) → value replaced with ``"<redacted: {key}>"``.
    - Dict keys matching ``HEAVY_FIELD_NAMES`` → value replaced with
      ``"<stripped: {key}>"``.
    - String values → run through ``secret_service.scrub`` to mask known
      secret patterns; long strings truncated to ``max_str_length`` chars.
    - Lists / tuples / dicts → recursed.
    - Scalars (``int``, ``float``, ``bool``, ``None``, ``Decimal``,
      ``datetime``) → returned unchanged.
    - Anything else → ``str()``-ified and re-scrubbed (defensive default).
    """
    return _scrub(payload, max_str_length=max_str_length)


def is_safe_for_telemetry(payload: Any) -> tuple[bool, list[str]]:
    """Best-effort detector for raw secrets that escaped scrubbing.

    Returns ``(safe, findings)``. ``safe`` is False when a string in the
    payload (recursively) still matches one of the known secret patterns
    *after* scrubbing logic runs. Used by tests to assert nothing leaks.

    The findings list contains short human-readable descriptions of each
    suspect string ("contains api_key pattern at path .foo[0].bar") for
    debugging — not a security boundary.
    """
    findings: list[str] = []
    _walk_for_secrets(payload, path="", findings=findings)
    return (not findings, findings)


# ---------------------------------------------------------------------------
# Internal recursion
# ---------------------------------------------------------------------------


def _normalize_key(key: Any) -> str:
    if not isinstance(key, str):
        return ""
    return key.lower().replace("-", "_")


def _scrub(value: Any, *, max_str_length: int) -> Any:
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            norm = _normalize_key(k)
            if norm in SENSITIVE_KEY_NAMES:
                out[k] = f"<redacted: {k}>"
                continue
            if norm in HEAVY_FIELD_NAMES:
                out[k] = f"<stripped: {k}>"
                continue
            out[k] = _scrub(v, max_str_length=max_str_length)
        return out

    if isinstance(value, list):
        return [_scrub(item, max_str_length=max_str_length) for item in value]

    if isinstance(value, tuple):
        return tuple(_scrub(item, max_str_length=max_str_length) for item in value)

    if isinstance(value, str):
        return _scrub_string(value, max_str_length=max_str_length)

    # Pass-through types — explicit so we don't accidentally stringify them.
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float | Decimal):
        return value
    if isinstance(value, _dt.date | _dt.datetime | _dt.time | _dt.timedelta):
        return value
    if isinstance(value, bytes):
        return f"<bytes: {len(value)} bytes>"

    # Fallback: stringify and scrub. Keeps the function total without
    # silently leaking ``repr(value)`` of unknown objects.
    return _scrub_string(str(value), max_str_length=max_str_length)


def _scrub_string(value: str, *, max_str_length: int) -> str:
    """Run ``secret_service.scrub`` then truncate.

    ``secret_service.scrub`` returns ``"<redacted: ...>"`` for matched
    secrets — we leave those alone (no truncation). For plain prose, it
    truncates with an ellipsis at its own ``max_length``; we override the
    truncation here so callers can pick a more generous limit (the default
    100 is too short for trace inputs).
    """
    # First pass: detect known secret patterns. We pass a generous max_length
    # so plain prose is NOT truncated by secret_service — we'll do that here.
    out = scrub_str(value, max_length=10**9)
    if isinstance(out, str) and out.startswith("<redacted:"):
        return out
    text = out if isinstance(out, str) else str(out)
    if len(text) > max_str_length:
        return text[:max_str_length] + _TRUNC_SUFFIX
    return text


# ---------------------------------------------------------------------------
# is_safe_for_telemetry helpers
# ---------------------------------------------------------------------------

# Conservative re-check: a small subset of secret_service patterns that should
# never appear in a fully-scrubbed payload. Kept here (not imported) so the
# detector remains independent of the scrubber it audits.
_RAW_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("api_key", re.compile(r"\b(?:sk-|ak_|pk_|rk_)[A-Za-z0-9_\-]{8,}", re.IGNORECASE)),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{20,}", re.IGNORECASE)),
    ("gitlab_pat", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}", re.IGNORECASE)),
    ("aws_access_key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("jwt", re.compile(r"\bey[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{16,}", re.IGNORECASE)),
    ("url_credentials", re.compile(r"https?://[^@\s]+:[^@\s]+@[^\s]+")),
]


def _walk_for_secrets(value: Any, *, path: str, findings: list[str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            sub_path = f"{path}.{k}" if path else f".{k}"
            _walk_for_secrets(v, path=sub_path, findings=findings)
        return
    if isinstance(value, list | tuple):
        for i, item in enumerate(value):
            _walk_for_secrets(item, path=f"{path}[{i}]", findings=findings)
        return
    if isinstance(value, str):
        # Already-scrubbed markers are safe.
        if value.startswith("<redacted:") or value.startswith("<stripped:"):
            return
        for label, pattern in _RAW_SECRET_PATTERNS:
            if pattern.search(value):
                findings.append(f"contains {label} pattern at path {path or '<root>'}")
                return
        return
    # Non-string scalars are safe by construction.
    return
