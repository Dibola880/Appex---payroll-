"""Secure storage helpers for external integration credentials.

The encryption key must be supplied through the deployment environment.
Never store the key in the database, source code, or application logs.
"""

import json
import os
import re

from cryptography.fernet import Fernet, InvalidToken


KEY_ENV = "INTEGRATION_ENCRYPTION_KEY"
KEY_VERSION_ENV = "INTEGRATION_ENCRYPTION_KEY_VERSION"
DEFAULT_KEY_VERSION = "v1"


class IntegrationCredentialError(Exception):
    """Raised when integration credentials cannot be safely protected."""


def _get_cipher():
    key = os.environ.get(KEY_ENV, "").strip()

    if not key:
        raise IntegrationCredentialError(
            "Integration encryption is not configured."
        )

    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise IntegrationCredentialError(
            "Integration encryption configuration is invalid."
        ) from None


def _get_key_version():
    version = os.environ.get(
        KEY_VERSION_ENV,
        DEFAULT_KEY_VERSION,
    ).strip()

    if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", version):
        raise IntegrationCredentialError(
            "Integration encryption key version is invalid."
        )

    return version


def encrypt_credentials(credentials):
    """Return authenticated ciphertext and its key version.

    Credentials must be a JSON-serialisable dictionary with string keys.
    """
    if not isinstance(credentials, dict):
        raise IntegrationCredentialError(
            "Credentials must be supplied as an object."
        )

    if not all(isinstance(key, str) for key in credentials):
        raise IntegrationCredentialError(
            "Credential field names must be strings."
        )

    try:
        plaintext = json.dumps(
            credentials,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise IntegrationCredentialError(
            "Credentials contain unsupported values."
        ) from None

    cipher = _get_cipher()
    version = _get_key_version()

    encrypted = cipher.encrypt(plaintext).decode("ascii")
    return encrypted, version


def decrypt_credentials(encrypted, key_version):
    """Decrypt credentials only when the configured key version matches."""
    if not isinstance(encrypted, str) or not encrypted:
        raise IntegrationCredentialError(
            "Encrypted credentials are missing or invalid."
        )

    if not isinstance(key_version, str) or not key_version:
        raise IntegrationCredentialError(
            "Credential key version is missing."
        )

    configured_version = _get_key_version()

    if key_version != configured_version:
        raise IntegrationCredentialError(
            "Credential key version does not match the configured key."
        )

    cipher = _get_cipher()

    try:
        plaintext = cipher.decrypt(encrypted.encode("ascii"))
        credentials = json.loads(plaintext.decode("utf-8"))
    except (
        InvalidToken,
        ValueError,
        UnicodeDecodeError,
        UnicodeEncodeError,
    ):
        raise IntegrationCredentialError(
            "Credentials could not be authenticated or decrypted."
        ) from None

    if not isinstance(credentials, dict):
        raise IntegrationCredentialError(
            "Decrypted credentials have an invalid format."
        )

    return credentials
