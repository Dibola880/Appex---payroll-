"""Safe platform audit-event recording."""

import json
import re

from . import db
from .models import PlatformAuditLog


class PlatformAuditError(ValueError):
    pass


FORBIDDEN_KEYS = {
    "password",
    "password_hash",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "salary",
    "monthly_salary",
    "bank_account",
    "account_number",
    "tax_number",
    "national_id",
    "id_number",
    "date_of_birth",
}


def validate_snapshot(snapshot, field_name):
    if snapshot is None:
        return None

    if not isinstance(snapshot, dict):
        raise PlatformAuditError(
            f"{field_name} must be a dictionary or None."
        )

    def inspect(value, depth=0):
        if depth > 8:
            raise PlatformAuditError("Snapshot nesting is too deep.")

        if isinstance(value, dict):
            for key, nested in value.items():
                if not isinstance(key, str):
                    raise PlatformAuditError("Snapshot keys must be strings.")

                if key.strip().lower() in FORBIDDEN_KEYS:
                    raise PlatformAuditError(
                        f"Sensitive field prohibited: {key}"
                    )

                inspect(nested, depth + 1)

        elif isinstance(value, list):
            for nested in value:
                inspect(nested, depth + 1)

        elif value is not None and not isinstance(
            value, (str, int, float, bool)
        ):
            raise PlatformAuditError("Snapshot contains unsupported data.")

    inspect(snapshot)

    try:
        encoded = json.dumps(snapshot, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PlatformAuditError("Snapshot is not valid JSON.") from exc

    if len(encoded.encode("utf-8")) > 12000:
        raise PlatformAuditError("Snapshot exceeds 12 KB.")

    return snapshot


def record_platform_audit(
    *,
    actor,
    action,
    target_type,
    target_id=None,
    company_id=None,
    reason,
    before_data=None,
    after_data=None,
):
    """Flush an audit event without committing the transaction."""

    if actor is None or not getattr(actor, "id", None):
        raise PlatformAuditError("A persisted actor is required.")

    if getattr(actor, "role", None) != "platform_super_admin":
        raise PlatformAuditError("Platform super administrator required.")

    if not isinstance(action, str) or not re.fullmatch(
        r"[a-z][a-z0-9_.-]{1,99}", action
    ):
        raise PlatformAuditError("Invalid audit action.")

    if not isinstance(target_type, str) or not re.fullmatch(
        r"[a-z][a-z0-9_.-]{1,79}", target_type
    ):
        raise PlatformAuditError("Invalid target type.")

    if target_id is not None:
        target_id = str(target_id)
        if not target_id or len(target_id) > 128:
            raise PlatformAuditError("Invalid target ID.")

    if company_id is not None:
        if not isinstance(company_id, int) or company_id <= 0:
            raise PlatformAuditError("Invalid company ID.")

    if not isinstance(reason, str) or not reason.strip():
        raise PlatformAuditError("A reason is required.")

    reason = reason.strip()
    if len(reason) > 2000:
        raise PlatformAuditError("Reason exceeds 2000 characters.")

    before_data = validate_snapshot(before_data, "before_data")
    after_data = validate_snapshot(after_data, "after_data")

    event = PlatformAuditLog(
        actor_user_id=actor.id,
        actor_role=actor.role,
        company_id=company_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        before_data=before_data,
        after_data=after_data,
    )

    db.session.add(event)
    db.session.flush()
    return event
