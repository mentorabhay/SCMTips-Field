"""Unit tests for secrets loading and scrubber (Task T1.071 / TC1.160)."""

from pathlib import Path

import pytest
from field_api.secrets import load_secret, scrub_secrets, scrub_string


@pytest.mark.unit
def test_secrets_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Test environment variable
    monkeypatch.setenv("TEST_FIELD_KEY", "env-secret-value")
    assert load_secret("TEST_FIELD_KEY") == "env-secret-value"

    # Test file-based KMS/vault mount
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "MOUNTED_KEY").write_text("mounted-secret-123", encoding="utf-8")

    monkeypatch.setenv("FIELD_SECRETS_FILE", str(secrets_dir))
    assert load_secret("MOUNTED_KEY") == "mounted-secret-123"

    # Test default fallback
    assert load_secret("NON_EXISTENT", default="fallback") == "fallback"

    # Test missing key raises KeyError
    with pytest.raises(KeyError):
        load_secret("ABSENT_KEY")


@pytest.mark.unit
def test_scrubber_masks_sensitive_dict_keys():
    payload = {
        "user_id": "usr-123",
        "password": "super-secret-password",
        "api_key": "secret-api-key-xyz",
        "token": "tok_9999",
        "nested": {
            "client_secret": "nested-secret",
            "safe_field": "visible-value",
        },
    }

    scrubbed = scrub_secrets(payload)
    assert scrubbed["user_id"] == "usr-123"
    assert scrubbed["password"] == "[REDACTED]"
    assert scrubbed["api_key"] == "[REDACTED]"
    assert scrubbed["token"] == "[REDACTED]"
    assert scrubbed["nested"]["client_secret"] == "[REDACTED]"
    assert scrubbed["nested"]["safe_field"] == "visible-value"


@pytest.mark.unit
def test_scrubber_masks_connection_strings_and_tokens():
    uri = "postgresql://postgres:my-secret-pass@127.0.0.1:5432/field_db"
    assert scrub_string(uri) == "postgresql://postgres:***@127.0.0.1:5432/field_db"

    bearer = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"
    assert scrub_string(bearer) == "Authorization: Bearer [REDACTED]"

    pem = "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----"
    assert scrub_string(pem) == "[REDACTED PRIVATE KEY]"
