"""Tests for dedicated partner payload snapshot encryption."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.partner_payload_security import (
    PartnerPayloadEncryptionError,
    decrypt_partner_payload,
    encrypt_partner_payload,
    partner_payload_sha256,
)


KEYS_ENV = "PARTNER_PAYLOAD_ENCRYPTION_KEYS"
ACTIVE_ENV = "PARTNER_PAYLOAD_ENCRYPTION_ACTIVE_KEY_VERSION"

key_v1 = Fernet.generate_key().decode("ascii")
key_v2 = Fernet.generate_key().decode("ascii")

results = []


def record(name, passed, detail=""):
    results.append((name, passed))
    status = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"{status}: {name}{suffix}")


def expect_error(name, callback):
    try:
        callback()
    except PartnerPayloadEncryptionError:
        record(name, True)
    except Exception as exc:
        record(name, False, type(exc).__name__)
    else:
        record(name, False, "Expected encryption error")


def main():
    payload = {
        "currency": "ZAR",
        "product_category": "working_capital",
    }

    v1_config = {
        KEYS_ENV: json.dumps({"v1": key_v1}),
        ACTIVE_ENV: "v1",
    }

    with patch.dict(os.environ, v1_config, clear=False):
        ciphertext, version, digest = encrypt_partner_payload(payload)

        record("active key encrypts payload", version == "v1")
        record(
            "encryption returns canonical SHA-256",
            digest == partner_payload_sha256(payload),
        )
        record(
            "encrypted snapshot decrypts",
            decrypt_partner_payload(ciphertext, "v1") == payload,
        )

    # Rotate the active key but retain the old key for historical snapshots.
    rotated_config = {
        KEYS_ENV: json.dumps({"v1": key_v1, "v2": key_v2}),
        ACTIVE_ENV: "v2",
    }

    with patch.dict(os.environ, rotated_config, clear=False):
        new_ciphertext, new_version, _ = encrypt_partner_payload(payload)

        record("rotation selects new active key", new_version == "v2")
        record(
            "historical snapshot remains decryptable",
            decrypt_partner_payload(ciphertext, "v1") == payload,
        )
        record(
            "new snapshot uses new key",
            decrypt_partner_payload(new_ciphertext, "v2") == payload,
        )

        expect_error(
            "unknown historical key fails closed",
            lambda: decrypt_partner_payload(ciphertext, "v3"),
        )

        tampered = ciphertext[:-1] + (
            "A" if ciphertext[-1] != "A" else "B"
        )
        expect_error(
            "tampered ciphertext fails closed",
            lambda: decrypt_partner_payload(tampered, "v1"),
        )

    with patch.dict(
        os.environ,
        {KEYS_ENV: json.dumps({"v1": key_v1}), ACTIVE_ENV: "v2"},
        clear=False,
    ):
        expect_error(
            "missing active key fails closed",
            lambda: encrypt_partner_payload(payload),
        )

    with patch.dict(
        os.environ,
        {ACTIVE_ENV: "v1"},
        clear=False,
    ):
        os.environ.pop(KEYS_ENV, None)
        expect_error(
            "missing key ring fails closed",
            lambda: encrypt_partner_payload(payload),
        )

    with patch.dict(os.environ, v1_config, clear=False):
        expect_error(
            "non-object payload is rejected",
            lambda: encrypt_partner_payload(["not", "an", "object"]),
        )

    failures = [name for name, passed in results if not passed]
    print(f"\nResults: {len(results) - len(failures)} passed, {len(failures)} failed")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
