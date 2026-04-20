import hashlib
import hmac

from app.services.webhook_service import sign_body


def test_sign_body_deterministic():
    secret = "s" * 32
    body = b'{"hello":"world"}'
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert sign_body(secret, body) == expected
    # Change body → signature changes
    assert sign_body(secret, body + b"x") != expected
    # Change secret → signature changes
    assert sign_body("different", body) != expected
