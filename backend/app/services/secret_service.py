"""Fernet symmetric encryption + telemetry redaction helpers.

All secrets at rest (LLM provider API keys, Langfuse keys, etc.) are encrypted
with a single deployment key: AGENTS_SECRET_KEY.

Key management:
- Generate: see .env.example for the one-liner command.
- Rotation: re-encrypt all rows manually (no auto-rotation). See §2.3 of the agent spec.
"""

from __future__ import annotations

import base64
import re

from app.core.config import settings


class MissingSecretKey(Exception):  # noqa: N818 – spec name, not changing
    """Raised when AGENTS_SECRET_KEY is not configured."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_fernet():
    """Return a Fernet instance using AGENTS_SECRET_KEY.

    Raises MissingSecretKey if the key is absent or invalid.
    """
    from cryptography.fernet import Fernet, InvalidToken  # noqa: F401 – ensure available

    raw = settings.agents_secret_key
    if raw is None:
        raise MissingSecretKey(
            "AGENTS_SECRET_KEY is not configured. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    if hasattr(raw, "get_secret_value"):
        key_bytes = raw.get_secret_value().encode()
    else:
        key_bytes = str(raw).encode()
    return Fernet(key_bytes)


# ---------------------------------------------------------------------------
# Public encryption API
# ---------------------------------------------------------------------------

def encrypt(plaintext: str) -> bytes:
    """Encrypt *plaintext* with Fernet using AGENTS_SECRET_KEY.

    Returns the Fernet token (url-safe base64, includes IV + HMAC).
    Raises MissingSecretKey if the key is not configured.
    """
    f = _get_fernet()
    return f.encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    """Decrypt a Fernet *ciphertext* back to a plaintext string.

    Raises:
        MissingSecretKey – AGENTS_SECRET_KEY not configured.
        cryptography.fernet.InvalidToken – ciphertext was tampered with or
            the key does not match.
    """
    f = _get_fernet()
    return f.decrypt(ciphertext).decode()


def is_available() -> bool:
    """Return True iff AGENTS_SECRET_KEY is set and is a valid Fernet key.

    A valid Fernet key is exactly 32 bytes encoded as url-safe base64 (44 chars).
    """
    raw = settings.agents_secret_key
    if raw is None:
        return False
    try:
        key_str = raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)
        decoded = base64.urlsafe_b64decode(key_str.encode())
        return len(decoded) == 32  # noqa: PLR2004
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Redaction / scrubbing helpers
# ---------------------------------------------------------------------------

# Compiled patterns that identify secret-looking values.
_SECRET_REGEXES: list[tuple[str, re.Pattern[str]]] = [
    # Common API key prefixes
    ("api_key", re.compile(r"\b(?:sk-|ak_|pk_|rk_)[A-Za-z0-9_\-]{8,}", re.IGNORECASE)),
    # GitHub personal access tokens
    ("api_key", re.compile(r"\bghp_[A-Za-z0-9]{20,}", re.IGNORECASE)),
    # GitLab personal access tokens
    ("api_key", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}", re.IGNORECASE)),
    # AWS access key IDs
    ("api_key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    # JWT-shaped values (three base64url segments separated by dots)
    ("jwt", re.compile(r"\bey[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")),
    # Bearer tokens in Authorization-style text
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{16,}", re.IGNORECASE)),
    # URL credentials (https://user:password@host)
    ("url_credentials", re.compile(r"https?://[^@\s]+:[^@\s]+@[^\s]+")),
]


def _redact_string(value: str, max_length: int) -> str:
    """Apply all redaction patterns and optionally truncate plain strings."""
    for label, pattern in _SECRET_REGEXES:
        if pattern.search(value):
            return f"<redacted: {label}>"
    # No secret found — truncate long plain strings.
    if len(value) > max_length:
        return value[:max_length] + "..."
    return value


def scrub(
    value: str | dict | list,
    max_length: int = 100,
) -> str | dict | list:
    """Best-effort redaction for telemetry boundaries.

    Replaces patterns that look like API keys, bearer tokens, JWTs, or URL
    credentials with ``<redacted: <label>>``.  Safe to call on plain user prose
    — normal sentences are returned unchanged (subject to *max_length*
    truncation for str inputs).

    Processes recursively for dict and list inputs.

    Args:
        value: The value to scrub.
        max_length: Plain strings longer than this are truncated with '…'.
                    Applied only after all redaction checks pass (so a
                    short secret is still redacted, not just truncated).

    Returns:
        The scrubbed value, same type as the input.
    """
    if isinstance(value, str):
        return _redact_string(value, max_length)
    if isinstance(value, dict):
        return {k: scrub(v, max_length) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(item, max_length) for item in value]
    # For other scalar types (int, float, bool, None) return as-is.
    return value
