"""Tests for app/agents/redaction.py."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from app.agents.redaction import (
    HEAVY_FIELD_NAMES,
    SENSITIVE_KEY_NAMES,
    is_safe_for_telemetry,
    scrub_for_telemetry,
)

# ---------------------------------------------------------------------------
# Sensitive-key redaction
# ---------------------------------------------------------------------------


def test_dict_with_sensitive_key_is_redacted():
    out = scrub_for_telemetry({"api_key": "sk-abc1234567890abcdef"})
    assert out == {"api_key": "<redacted: api_key>"}


def test_dict_with_authorization_header_redacted():
    out = scrub_for_telemetry(
        {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.foo.bar"}
    )
    assert out == {"Authorization": "<redacted: Authorization>"}


def test_dict_with_hyphenated_key_redacted():
    """``x-api-key`` is normalized to match ``x_api_key`` in the catalogue."""
    out = scrub_for_telemetry({"x-api-key": "sk-secret"})
    assert out == {"x-api-key": "<redacted: x-api-key>"}


def test_sensitive_keys_are_case_insensitive():
    out = scrub_for_telemetry({"API_KEY": "sk-abc", "Token": "xyz"})
    assert out == {
        "API_KEY": "<redacted: API_KEY>",
        "Token": "<redacted: Token>",
    }


def test_all_documented_sensitive_keys_are_redacted():
    payload = {k: "value-that-should-not-appear" for k in SENSITIVE_KEY_NAMES}
    out = scrub_for_telemetry(payload)
    for k in SENSITIVE_KEY_NAMES:
        assert out[k] == f"<redacted: {k}>"


# ---------------------------------------------------------------------------
# Heavy-field stripping
# ---------------------------------------------------------------------------


def test_description_html_is_stripped():
    payload = {"description_html": "<p>X</p>" * 1000}
    out = scrub_for_telemetry(payload)
    assert out == {"description_html": "<stripped: description_html>"}


def test_all_documented_heavy_fields_stripped():
    payload = {k: "irrelevant" for k in HEAVY_FIELD_NAMES}
    out = scrub_for_telemetry(payload)
    for k in HEAVY_FIELD_NAMES:
        assert out[k] == f"<stripped: {k}>"


def test_geometry_fields_stripped_but_other_numerics_preserved():
    payload = {"x": 12, "y": 34, "name": "Service", "step_index": 7}
    out = scrub_for_telemetry(payload)
    assert out == {
        "x": "<stripped: x>",
        "y": "<stripped: y>",
        "name": "Service",
        "step_index": 7,
    }


# ---------------------------------------------------------------------------
# Recursion through nested structures
# ---------------------------------------------------------------------------


def test_nested_dict_scrubbing():
    payload = {
        "outer": {
            "name": "OK",
            "secret": "sk-leak",
            "child": {"api_key": "sk-deep"},
        },
        "ok": "fine",
    }
    out = scrub_for_telemetry(payload)
    assert out == {
        "outer": {
            "name": "OK",
            "secret": "<redacted: secret>",
            "child": {"api_key": "<redacted: api_key>"},
        },
        "ok": "fine",
    }


def test_list_of_dicts_scrubbing():
    payload = [
        {"name": "A", "api_key": "sk-1"},
        {"name": "B", "description_html": "<p>blob</p>"},
    ]
    out = scrub_for_telemetry(payload)
    assert out == [
        {"name": "A", "api_key": "<redacted: api_key>"},
        {"name": "B", "description_html": "<stripped: description_html>"},
    ]


def test_tuple_is_recursed():
    payload = ({"api_key": "sk-1"}, "ok")
    out = scrub_for_telemetry(payload)
    assert out == ({"api_key": "<redacted: api_key>"}, "ok")


# ---------------------------------------------------------------------------
# String pattern scrubbing
# ---------------------------------------------------------------------------


def test_bearer_token_in_string_redacted():
    out = scrub_for_telemetry(
        "Auth header: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
    )
    assert out.startswith("<redacted:")


def test_sk_prefixed_key_in_string_redacted():
    out = scrub_for_telemetry("My key is sk-deadbeefcafebabe1234")
    assert out.startswith("<redacted:")


def test_url_credentials_in_string_redacted():
    out = scrub_for_telemetry("connect to https://user:hunter2@db.example/db")
    assert out.startswith("<redacted:")


def test_normal_prose_passes_through():
    text = "The order service handles checkout."
    assert scrub_for_telemetry(text) == text


# ---------------------------------------------------------------------------
# Long-string truncation
# ---------------------------------------------------------------------------


def test_long_string_is_truncated():
    long = "a" * 5000
    out = scrub_for_telemetry(long)
    assert isinstance(out, str)
    assert out.endswith("...<truncated>")
    # Body length 2000 + suffix.
    assert len(out) == 2000 + len("...<truncated>")


def test_truncation_threshold_overridable():
    long = "x" * 100
    out = scrub_for_telemetry(long, max_str_length=10)
    assert out == "x" * 10 + "...<truncated>"


def test_string_at_threshold_not_truncated():
    s = "y" * 2000
    assert scrub_for_telemetry(s) == s


# ---------------------------------------------------------------------------
# Scalar pass-through
# ---------------------------------------------------------------------------


def test_decimal_passes_through():
    payload = {"cost": Decimal("0.0042")}
    out = scrub_for_telemetry(payload)
    assert out == {"cost": Decimal("0.0042")}


def test_datetime_passes_through():
    now = _dt.datetime(2026, 4, 27, 12, 0, 0)
    today = _dt.date(2026, 4, 27)
    payload = {"ts": now, "day": today}
    out = scrub_for_telemetry(payload)
    assert out == {"ts": now, "day": today}


def test_bool_int_float_none_pass_through():
    payload = {"flag": True, "n": 7, "f": 1.5, "z": None}
    out = scrub_for_telemetry(payload)
    assert out == payload


def test_bytes_become_size_marker():
    out = scrub_for_telemetry({"blob": b"\x00\x01\x02"})
    assert out == {"blob": "<bytes: 3 bytes>"}


# ---------------------------------------------------------------------------
# Immutability: scrub_for_telemetry must not mutate the input
# ---------------------------------------------------------------------------


def test_input_is_not_mutated():
    payload = {"api_key": "sk-orig", "child": {"token": "tok"}}
    snapshot = {"api_key": "sk-orig", "child": {"token": "tok"}}
    scrub_for_telemetry(payload)
    assert payload == snapshot


# ---------------------------------------------------------------------------
# is_safe_for_telemetry detector
# ---------------------------------------------------------------------------


def test_safe_for_normal_prose():
    safe, findings = is_safe_for_telemetry({"normal": "user prose"})
    assert safe is True
    assert findings == []


def test_unsafe_for_raw_secret():
    safe, findings = is_safe_for_telemetry(
        {"sneaky": "sk-leakedabcdef1234567890"}
    )
    assert safe is False
    assert findings  # at least one finding
    assert any("api_key" in f for f in findings)


def test_safe_for_already_redacted_marker():
    safe, findings = is_safe_for_telemetry({"api_key": "<redacted: api_key>"})
    assert safe is True
    assert findings == []


def test_unsafe_finds_nested_jwt():
    payload = {"outer": {"inner": ["ok", "ey" + "abc.def.ghi" + "X" * 5]}}
    safe, findings = is_safe_for_telemetry(payload)
    assert safe is False
    assert any("jwt" in f for f in findings)


def test_unsafe_finds_aws_access_key():
    payload = {"creds": "AKIAIOSFODNN7EXAMPLE"}
    safe, findings = is_safe_for_telemetry(payload)
    assert safe is False
    assert any("aws_access_key" in f for f in findings)


def test_unsafe_finds_url_credentials():
    payload = "https://admin:secret123@db.example/db"
    safe, findings = is_safe_for_telemetry(payload)
    assert safe is False
    assert any("url_credentials" in f for f in findings)


# ---------------------------------------------------------------------------
# End-to-end: scrubbed payload is safe by detector
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "sk-leakedabcdef123456"},
        {"nested": {"token": "Bearer eyJ.payload.sig" + "X" * 30}},
        ["sk-foobarabcdef1234567890", {"x": 1, "y": 2}],
        "Bearer eyJleak.foo.bar" + "X" * 30,
    ],
)
def test_scrub_then_detector_finds_no_secrets(payload):
    scrubbed = scrub_for_telemetry(payload)
    safe, findings = is_safe_for_telemetry(scrubbed)
    assert safe, f"leaked secrets after scrub: {findings}"
