from app.core.security import hash_password, verify_password


def test_hash_and_verify_password():
    hashed = hash_password("testpass123")
    assert hashed != "testpass123"
    assert verify_password("testpass123", hashed)
    assert not verify_password("wrongpass", hashed)
