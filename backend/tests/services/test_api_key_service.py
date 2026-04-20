from app.core.security import verify_password
from app.services.api_key_service import (
    KEY_PREFIX,
    PREFIX_LEN,
    _generate_plaintext,
)


def test_generate_plaintext_prefixed():
    full, prefix = _generate_plaintext()
    assert full.startswith(KEY_PREFIX)
    assert prefix == full[:PREFIX_LEN]
    assert len(prefix) == PREFIX_LEN


def test_generate_plaintext_unique():
    a, _ = _generate_plaintext()
    b, _ = _generate_plaintext()
    assert a != b


def test_generated_secret_hash_roundtrip():
    from app.core.security import hash_password

    full, _ = _generate_plaintext()
    hashed = hash_password(full)
    assert verify_password(full, hashed)
    assert not verify_password(full + "x", hashed)
