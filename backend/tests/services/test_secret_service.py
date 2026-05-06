"""Tests for app/services/secret_service.py.

Covers:
- Round-trip encrypt → decrypt
- InvalidToken raised on tampered ciphertext
- MissingSecretKey raised when key is absent
- is_available() behaviour
- scrub() redaction (parametrized) + recursive dict/list handling
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def valid_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture()
def with_key(valid_key: str, monkeypatch: pytest.MonkeyPatch):
    """Set AGENTS_SECRET_KEY in the environment and reload settings + module."""
    monkeypatch.setenv("AGENTS_SECRET_KEY", valid_key)
    # Patch settings directly so the already-imported singleton picks up the new key.
    from pydantic import SecretStr

    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "agents_secret_key", SecretStr(valid_key))
    # Re-import so the module under test uses the patched settings.
    import importlib

    import app.services.secret_service as svc

    importlib.reload(svc)
    return svc


@pytest.fixture()
def without_key(monkeypatch: pytest.MonkeyPatch):
    """Ensure AGENTS_SECRET_KEY is absent."""
    monkeypatch.delenv("AGENTS_SECRET_KEY", raising=False)
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "agents_secret_key", None)
    import importlib

    import app.services.secret_service as svc

    importlib.reload(svc)
    return svc


# ---------------------------------------------------------------------------
# Encrypt / decrypt
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_roundtrip(with_key):
    svc = with_key
    plaintext = "super-secret-api-key-value"
    ciphertext = svc.encrypt(plaintext)
    assert isinstance(ciphertext, bytes)
    assert svc.decrypt(ciphertext) == plaintext


def test_encrypt_returns_bytes_different_each_call(with_key):
    """Fernet uses a random IV — two encryptions of the same plaintext differ."""
    svc = with_key
    ct1 = svc.encrypt("hello")
    ct2 = svc.encrypt("hello")
    assert ct1 != ct2


def test_decrypt_tampered_raises_invalid_token(with_key):
    svc = with_key
    ct = svc.encrypt("value")
    # Flip a byte in the middle of the token.
    tampered = bytearray(ct)
    tampered[20] ^= 0xFF
    with pytest.raises(InvalidToken):
        svc.decrypt(bytes(tampered))


# ---------------------------------------------------------------------------
# MissingSecretKey
# ---------------------------------------------------------------------------


def test_encrypt_raises_missing_secret_key(without_key):
    svc = without_key
    with pytest.raises(svc.MissingSecretKey):
        svc.encrypt("anything")


def test_decrypt_raises_missing_secret_key(without_key):
    svc = without_key
    with pytest.raises(svc.MissingSecretKey):
        svc.decrypt(b"some-token")


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


def test_is_available_false_without_key(without_key):
    svc = without_key
    assert svc.is_available() is False


def test_is_available_true_with_valid_key(with_key):
    svc = with_key
    assert svc.is_available() is True


def test_is_available_false_with_invalid_key(monkeypatch: pytest.MonkeyPatch):
    """A key that isn't valid base64 (or wrong length) should return False."""
    from pydantic import SecretStr

    from app.core import config as cfg_module

    bad_key = SecretStr("not-a-valid-fernet-key")
    monkeypatch.setattr(cfg_module.settings, "agents_secret_key", bad_key)
    import importlib

    import app.services.secret_service as svc

    importlib.reload(svc)
    assert svc.is_available() is False


# ---------------------------------------------------------------------------
# scrub() — string redaction (parametrized)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_value",
    [
        "sk-abc123def456",
        "sk-test123abc",
        "ak_live_d3f4ult",
        "pk_test_somevalue",
        "ghp_abcdefghijklmnopqrst",
        "glpat-abcdefghijklmnopqrst",
        "AKIAIOSFODNN7EXAMPLE",
        "Bearer eyJhbGc.eyJzdWI.SflKxw",
        "https://user:secret@example.com/path",
    ],
)
def test_scrub_redacts_secrets(input_value: str):
    from app.services.secret_service import scrub

    result = scrub(input_value)
    assert isinstance(result, str)
    assert "<redacted" in result, f"Expected redaction for {input_value!r}, got {result!r}"


def test_scrub_jwt_shaped_value():
    from app.services.secret_service import scrub

    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    result = scrub(jwt)
    assert "<redacted" in result


@pytest.mark.parametrize(
    "safe_value",
    [
        "normal user message about a database called postgres",
        "The payment service connects to the order service via gRPC",
        "short",
    ],
)
def test_scrub_does_not_redact_safe_prose(safe_value: str):
    from app.services.secret_service import scrub

    result = scrub(safe_value)
    assert "<redacted" not in result


def test_scrub_truncates_long_plain_string():
    from app.services.secret_service import scrub

    long_value = "a" * 200
    result = scrub(long_value, max_length=100)
    assert result.endswith("...")
    assert len(result) == 103  # 100 chars + "..."


def test_scrub_no_truncate_within_max_length():
    from app.services.secret_service import scrub

    value = "short message"
    assert scrub(value, max_length=100) == value


# ---------------------------------------------------------------------------
# scrub() — recursive dict / list
# ---------------------------------------------------------------------------


def test_scrub_dict_recursively():
    from app.services.secret_service import scrub

    payload = {
        "name": "My workspace",
        "api_key": "sk-abc123def456",
        "nested": {"token": "Bearer eyJhbGc.eyJzdWI.SflKxw"},
    }
    result = scrub(payload)
    assert result["name"] == "My workspace"
    assert "<redacted" in result["api_key"]
    assert "<redacted" in result["nested"]["token"]


def test_scrub_list_recursively():
    from app.services.secret_service import scrub

    payload = [
        "normal prose",
        "sk-secret123abc456",
        {"key": "ak_live_xyz123abc456"},
    ]
    result = scrub(payload)
    assert result[0] == "normal prose"
    assert "<redacted" in result[1]
    assert "<redacted" in result[2]["key"]


def test_scrub_passthrough_non_string_scalars():
    from app.services.secret_service import scrub

    assert scrub(42) == 42  # type: ignore[arg-type]
    assert scrub(3.14) == 3.14  # type: ignore[arg-type]
    assert scrub(None) is None  # type: ignore[arg-type]
    assert scrub(True) is True  # type: ignore[arg-type]
