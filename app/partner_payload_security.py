"""Dedicated encryption for immutable partner-request payload snapshots."""

import hashlib
import json
import os
import re

from cryptography.fernet import Fernet, InvalidToken


KEYS_ENV = "PARTNER_PAYLOAD_ENCRYPTION_KEYS"
ACTIVE_KEY_VERSION_ENV = "PARTNER_PAYLOAD_ENCRYPTION_ACTIVE_KEY_VERSION"
_KEY_VERSION_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,40}\Z")


class PartnerPayloadEncryptionError(ValueError):
    """Raised when partner payload encryption or decryption fails."""


def canonical_partner_payload_bytes(payload):
    """Return deterministic UTF-8 JSON for a validated payload mapping."""
    if not isinstance(payload, dict):
        raise PartnerPayloadEncryptionError(
            "Partner payload must be a JSON object."
        )

    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise PartnerPayloadEncryptionError(
            "Partner payload cannot be canonicalised."
        ) from None


def partner_payload_sha256(payload):
    """Calculate the SHA-256 hash of canonical payload JSON."""
    canonical = canonical_partner_payload_bytes(payload)
    return hashlib.sha256(canonical).hexdigest()


def _load_keyring():
    raw_keys = os.environ.get(KEYS_ENV)
    active_version = os.environ.get(ACTIVE_KEY_VERSION_ENV)

    if not raw_keys or not active_version:
        raise PartnerPayloadEncryptionError(
            "Partner payload encryption is not configured."
        )

    if _KEY_VERSION_PATTERN.fullmatch(active_version) is None:
        raise PartnerPayloadEncryptionError(
            "The active partner payload key version is invalid."
        )

    try:
        configured_keys = json.loads(raw_keys)
    except (TypeError, ValueError):
        raise PartnerPayloadEncryptionError(
            "The partner payload key ring is invalid."
        ) from None

    if not isinstance(configured_keys, dict) or not configured_keys:
        raise PartnerPayloadEncryptionError(
            "The partner payload key ring is empty or invalid."
        )

    keyring = {}

    for version, encoded_key in configured_keys.items():
        if (
            not isinstance(version, str)
            or _KEY_VERSION_PATTERN.fullmatch(version) is None
            or not isinstance(encoded_key, str)
            or not encoded_key
        ):
            raise PartnerPayloadEncryptionError(
                "The partner payload key ring contains an invalid entry."
            )

        try:
            keyring[version] = Fernet(encoded_key.encode("ascii"))
        except (UnicodeEncodeError, TypeError, ValueError):
            raise PartnerPayloadEncryptionError(
                "A partner payload encryption key is invalid."
            ) from None

    if active_version not in keyring:
        raise PartnerPayloadEncryptionError(
            "The active partner payload key is missing from the key ring."
        )

    return active_version, keyring


def encrypt_partner_payload(payload):
    """Encrypt canonical payload JSON using the configured active key.

    Returns (ciphertext, key_version, sha256_hex).
    """
    canonical = canonical_partner_payload_bytes(payload)
    active_version, keyring = _load_keyring()

    try:
        ciphertext = keyring[active_version].encrypt(canonical).decode("ascii")
    except Exception:
        raise PartnerPayloadEncryptionError(
            "Partner payload encryption failed."
        ) from None

    digest = hashlib.sha256(canonical).hexdigest()
    return ciphertext, active_version, digest


def decrypt_partner_payload(ciphertext, key_version):
    """Decrypt a snapshot using its retained historical key version."""
    if not isinstance(ciphertext, str) or not ciphertext:
        raise PartnerPayloadEncryptionError(
            "The encrypted partner payload is missing."
        )

    if (
        not isinstance(key_version, str)
        or _KEY_VERSION_PATTERN.fullmatch(key_version) is None
    ):
        raise PartnerPayloadEncryptionError(
            "The partner payload key version is invalid."
        )

    _, keyring = _load_keyring()
    cipher = keyring.get(key_version)

    if cipher is None:
        raise PartnerPayloadEncryptionError(
            "The historical partner payload key is unavailable."
        )

    try:
        plaintext = cipher.decrypt(ciphertext.encode("ascii"))
        payload = json.loads(plaintext.decode("utf-8"))
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError, ValueError):
        raise PartnerPayloadEncryptionError(
            "Partner payload decryption or decoding failed."
        ) from None

    if not isinstance(payload, dict):
        raise PartnerPayloadEncryptionError(
            "The decrypted partner payload is not a JSON object."
        )

    # Reject non-canonical or altered representations.
    if canonical_partner_payload_bytes(payload) != plaintext:
        raise PartnerPayloadEncryptionError(
            "The decrypted partner payload is not canonical."
        )

    return payload
