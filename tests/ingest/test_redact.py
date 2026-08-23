from ingest.redact import PLACEHOLDER, redact


def test_bearer_authorization_header():
    result = redact('GET / HTTP/1.1 Authorization: Bearer abc123SECRETtoken456')
    assert "abc123SECRETtoken456" not in result.text
    assert PLACEHOLDER in result.text
    assert result.hits >= 1


def test_jwt_redacted():
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c"
    )
    result = redact(f"token issued: {jwt}")
    assert jwt not in result.text


def test_connection_string_password():
    result = redact("db connect postgres://shop:hunter2pass@db.lab.local:5432/shop")
    assert "hunter2pass" not in result.text
    assert "shop:" in result.text  # username survives


def test_key_value_secret():
    result = redact('login attempt password="correct-horse-battery" user=alice')
    assert "correct-horse-battery" not in result.text
    assert "user=alice" in result.text


def test_aws_access_key():
    result = redact("aws creds AKIAIOSFODNN7EXAMPLE in env")
    assert "AKIAIOSFODNN7EXAMPLE" not in result.text


def test_high_entropy_token():
    token = "9fXk2LmQ8vRt4WzY7bNc1JhG5dPs3aEu0iKo6TqM"
    result = redact(f"session blob {token} attached")
    assert token not in result.text


def test_benign_log_line_untouched():
    line = 'GET /products?page=2 HTTP/1.1 200 512 "Mozilla/5.0" 10.0.0.5'
    result = redact(line)
    assert result.text == line
    assert result.hits == 0


def test_uuid_not_redacted():
    line = "request id 11111111-1111-4111-8111-111111111102 completed"
    result = redact(line)
    assert result.text == line
