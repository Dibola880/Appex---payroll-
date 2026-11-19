"""Regression tests for partner adapter preparation review outcomes."""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

TEMP_DIR = tempfile.TemporaryDirectory(prefix="appex_partner_review_")
DB_PATH = str(Path(TEMP_DIR.name) / "partner_review_tests.sqlite")

from cryptography.fernet import Fernet

TEST_PARTNER_PAYLOAD_KEY = Fernet.generate_key().decode("ascii")

os.environ["APP_ENV"] = "development"
os.environ["SECRET_KEY"] = "partner-review-test-secret"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["PARTNER_PAYLOAD_ENCRYPTION_KEYS"] = (
    '{"test-v1":"' + TEST_PARTNER_PAYLOAD_KEY + '"}'
)
os.environ["PARTNER_PAYLOAD_ENCRYPTION_ACTIVE_KEY_VERSION"] = "test-v1"

from app import create_app, db
from app.models import (
    Company,
    User,
    IntegrationProvider,
    CompanyIntegration,
    PartnerServiceConsent,
    PartnerServiceAuditLog,
    PartnerServiceRequestReview,
    PartnerServiceRequestReviewEvent,
)
from app.partner_consent import (
    create_pending_partner_service_consent,
    activate_partner_service_consent,
)
from app.partner_request_reviews import (
    PartnerRequestReviewError,
    submit_partner_service_request_review,
    approve_partner_service_request_review,
    reject_partner_service_request_review,
    require_approved_partner_service_request_review,
    _set_terminal_timestamps,
    mark_partner_service_request_review_preparation_rejected,
)
from app.partner_services import (
    PartnerServiceRequestError,
    prepare_partner_service_request,
)
from app.integration_adapters.partner import (
    PartnerServiceAdapter,
    PartnerServiceRequest,
    PartnerServicePreparationResult,
)
from app.integration_adapters.partner_registry import (
    PartnerServiceAdapterRegistry,
)

results = []


def record(name, passed, detail=""):
    results.append((name, passed))
    status = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"{status}: {name}{suffix}")


class DeterministicTestAdapter(PartnerServiceAdapter):
    seen_payloads = []

    @property
    def supported_operations(self):
        return frozenset({"financial_services.product_catalogue"})

    def prepare_request(self, *, context, request, configuration):
        self.seen_payloads.append(dict(request.payload))
        if request.request_id == "request-refused":
            return PartnerServicePreparationResult(
                accepted=False,
                error_code="partner_unavailable",
            )

        if request.request_id == "request-refused-long":
            return PartnerServicePreparationResult(
                accepted=False,
                error_code="x" + ("a" * 99),
            )

        return PartnerServicePreparationResult(
            accepted=True,
            partner_reference="test-partner-reference",
        )


def main():
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    with app.app_context():
        if db.engine.dialect.name != "sqlite":
            raise RuntimeError("Refusing to run: test database is not SQLite.")

        actual_db = str(Path(db.engine.url.database).resolve())
        expected_db = str(Path(DB_PATH).resolve())

        if actual_db != expected_db:
            raise RuntimeError(
                "Refusing to run: database URL does not match disposable test DB."
            )

        print(f"Disposable database verified: {actual_db}")
        db.create_all()

        now = datetime(2026, 11, 18, 12, 0, 0)

        company = Company(name="Partner Review Test Company")
        db.session.add(company)
        db.session.flush()

        requester = User(
            company_id=company.id,
            name="Review Requester",
            email="partner-requester@example.test",
            password_hash="test-password-hash",
            role="company_admin",
            is_active=True,
        )
        reviewer = User(
            company_id=company.id,
            name="Independent Reviewer",
            email="partner-reviewer@example.test",
            password_hash="test-password-hash",
            role="company_admin",
            is_active=True,
        )
        db.session.add_all([requester, reviewer])
        db.session.flush()

        operation = "financial_services.product_catalogue"
        provider = IntegrationProvider(
            code="test.partner",
            display_name="Test Partner",
            category="financial_services",
            description="Deterministic test provider",
            capabilities=[operation],
            is_enabled=True,
        )
        db.session.add(provider)
        db.session.flush()

        integration = CompanyIntegration(
            company_id=company.id,
            provider_id=provider.id,
            ownership_scope="company",
            environment="sandbox",
            status="connected",
            configuration={},
        )
        db.session.add(integration)
        db.session.flush()

        consent = create_pending_partner_service_consent(
            db.session,
            actor=requester,
            integration_id=integration.id,
            operation=operation,
            purpose_code="product_discovery",
            data_categories=[],
            expires_at=now + timedelta(days=30),
            now=now,
        )
        db.session.flush()

        activate_partner_service_consent(
            db.session,
            actor=requester,
            consent_id=consent.id,
            now=now,
        )
        db.session.commit()

        registry = PartnerServiceAdapterRegistry()
        registry.register("test.partner", DeterministicTestAdapter())

        def prepare_review(request_id, *, prepare=True, payload=None):
            request = PartnerServiceRequest(
                request_id=request_id,
                operation=operation,
                payload={} if payload is None else payload,
            )

            review = submit_partner_service_request_review(
                db.session,
                actor=requester,
                integration_id=integration.id,
                request=request,
                now=now,
            )
            db.session.flush()

            approve_partner_service_request_review(
                db.session,
                actor=reviewer,
                review_id=review.id,
                now=now,
            )
            record(
                f"{request_id}: approved review has no terminal timestamps",
                review.status == "approved"
                and review.terminal_at is None
                and review.payload_retention_until is None,
            )
            db.session.commit()

            if not prepare:
                return review.id, request, None

            result = prepare_partner_service_request(
                db.session,
                company_id=company.id,
                integration_id=integration.id,
                request=request,
                registry=registry,
                now=now,
            )
            db.session.flush()

            return review.id, request, result

        # --------------------------------------------------
        # ACCEPTED PREPARATION
        # --------------------------------------------------
        accepted_review_id, accepted_request, accepted_result = prepare_review(
            "request-accepted"
        )

        accepted_review = db.session.get(
            PartnerServiceRequestReview, accepted_review_id
        )
        accepted_audit = db.session.query(PartnerServiceAuditLog).filter_by(
            integration_id=integration.id,
            request_id="request-accepted",
        ).one()
        accepted_event = db.session.query(
            PartnerServiceRequestReviewEvent
        ).filter_by(
            review_id=accepted_review_id,
            event_type="prepared",
        ).one()

        record(
            "Accepted adapter result is successful",
            accepted_result.result.accepted is True,
        )
        record(
            "Accepted review becomes prepared",
            accepted_review.status == "prepared",
        )
        record(
            "Accepted review has prepared_at",
            accepted_review.prepared_at is not None,
        )
        expected_retention = now.replace(year=now.year + 7)
        record(
            "Prepared review records terminal and seven-year retention timestamps",
            accepted_review.terminal_at == now
            and accepted_review.payload_retention_until == expected_retention,
        )
        record(
            "Accepted review has no human rejection reason",
            accepted_review.rejection_reason_code is None,
        )
        record(
            "Accepted audit outcome is prepared",
            accepted_audit.outcome == "prepared"
            and accepted_audit.error_code is None,
        )
        record(
            "Accepted event records approved-to-prepared",
            accepted_event.from_status == "approved"
            and accepted_event.to_status == "prepared",
        )

        db.session.commit()

        # --------------------------------------------------
        # REFUSED PREPARATION
        # --------------------------------------------------
        refused_review_id, refused_request, refused_result = prepare_review(
            "request-refused"
        )

        refused_review = db.session.get(
            PartnerServiceRequestReview, refused_review_id
        )
        refused_audit = db.session.query(PartnerServiceAuditLog).filter_by(
            integration_id=integration.id,
            request_id="request-refused",
        ).one()
        refused_event = db.session.query(
            PartnerServiceRequestReviewEvent
        ).filter_by(
            review_id=refused_review_id,
            event_type="preparation_rejected",
        ).one()

        record(
            "Refused adapter result is rejected",
            refused_result.result.accepted is False,
        )
        record(
            "Refused review enters preparation_rejected",
            refused_review.status == "preparation_rejected",
        )
        record(
            "Refused review has no prepared_at",
            refused_review.prepared_at is None,
        )
        record(
            "Preparation-rejected review records terminal and retention timestamps",
            refused_review.terminal_at == now
            and refused_review.payload_retention_until == expected_retention,
        )
        record(
            "Refused review has no human rejection reason",
            refused_review.rejection_reason_code is None,
        )
        record(
            "Refused audit outcome and error code are preserved",
            refused_audit.outcome == "rejected"
            and refused_audit.error_code == "partner_unavailable",
        )
        record(
            "Refused event records approved-to-preparation_rejected",
            refused_event.from_status == "approved"
            and refused_event.to_status == "preparation_rejected"
            and refused_event.reason_code == "partner_unavailable",
        )

        # Verify the full adapter error-code contract at its 100-character limit.
        long_review_id, _, long_result = prepare_review(
            "request-refused-long"
        )
        long_audit = db.session.query(PartnerServiceAuditLog).filter_by(
            integration_id=integration.id,
            request_id="request-refused-long",
        ).one()
        long_event = db.session.query(
            PartnerServiceRequestReviewEvent
        ).filter_by(
            review_id=long_review_id,
            event_type="preparation_rejected",
        ).one()
        expected_long_code = "x" + ("a" * 99)

        record(
            "100-character adapter error code persists in audit and review event",
            long_result.result.accepted is False
            and len(expected_long_code) == 100
            and long_audit.error_code == expected_long_code
            and long_event.reason_code == expected_long_code,
        )

        prepared_events_for_refused = db.session.query(
            PartnerServiceRequestReviewEvent
        ).filter_by(
            review_id=refused_review_id,
            event_type="prepared",
        ).count()

        record(
            "Refused review has no prepared event",
            prepared_events_for_refused == 0,
        )

        # --------------------------------------------------
        # TERMINAL TIMESTAMP COVERAGE
        # --------------------------------------------------
        rejected_request = PartnerServiceRequest(
            request_id="request-human-rejected",
            operation=operation,
            payload={},
        )
        rejected_review = submit_partner_service_request_review(
            db.session,
            actor=requester,
            integration_id=integration.id,
            request=rejected_request,
            now=now,
        )
        db.session.flush()
        record(
            "Pending review has no terminal timestamps",
            rejected_review.terminal_at is None
            and rejected_review.payload_retention_until is None,
        )
        reject_partner_service_request_review(
            db.session,
            actor=reviewer,
            review_id=rejected_review.id,
            reason_code="outside_company_policy",
            now=now,
        )
        record(
            "Human-rejected review records terminal and retention timestamps",
            rejected_review.status == "rejected"
            and rejected_review.terminal_at == now
            and rejected_review.payload_retention_until == expected_retention,
        )

        expired_request = PartnerServiceRequest(
            request_id="request-expired",
            operation=operation,
            payload={},
        )
        expired_review = submit_partner_service_request_review(
            db.session,
            actor=requester,
            integration_id=integration.id,
            request=expired_request,
            now=now,
        )
        db.session.flush()
        expiry_time = now + timedelta(hours=25)
        approve_partner_service_request_review(
            db.session,
            actor=reviewer,
            review_id=expired_review.id,
            now=expiry_time,
        )
        expected_expiry_retention = expiry_time.replace(
            year=expiry_time.year + 7
        )
        record(
            "Expired review records expiry time and seven-year retention deadline",
            expired_review.status == "expired"
            and expired_review.terminal_at == expiry_time
            and expired_review.payload_retention_until
            == expected_expiry_retention,
        )

        leap_day_review = SimpleNamespace(
            terminal_at=None,
            payload_retention_until=None,
        )
        leap_day = datetime(2024, 2, 29, 10, 30, 0)
        _set_terminal_timestamps(leap_day_review, leap_day)
        record(
            "Leap-day retention deadline maps to 28 February",
            leap_day_review.terminal_at == leap_day
            and leap_day_review.payload_retention_until
            == datetime(2031, 2, 28, 10, 30, 0),
        )

        try:
            _set_terminal_timestamps(leap_day_review, leap_day)
            duplicate_timestamp_blocked = False
        except PartnerRequestReviewError:
            duplicate_timestamp_blocked = True
        record(
            "Existing terminal timestamps cannot be overwritten",
            duplicate_timestamp_blocked,
        )

        inconsistent_review = SimpleNamespace(
            terminal_at=now,
            payload_retention_until=None,
        )
        try:
            _set_terminal_timestamps(inconsistent_review, now)
            inconsistent_pair_blocked = False
        except PartnerRequestReviewError:
            inconsistent_pair_blocked = True
        record(
            "Inconsistent terminal timestamp pair fails closed",
            inconsistent_pair_blocked,
        )

        db.session.commit()

        # --------------------------------------------------
        # APPROVED SNAPSHOT AUTHORITY AND FAIL-CLOSED TESTS
        # --------------------------------------------------

        authority_id, original_request, _ = prepare_review(
            "request-snapshot-authority",
            prepare=False,
            payload={},
        )
        altered_caller_request = PartnerServiceRequest(
            request_id=original_request.request_id,
            operation=operation,
            payload={"currency": "ZAR"},
        )

        adapter_calls_before = len(DeterministicTestAdapter.seen_payloads)
        authority_result = prepare_partner_service_request(
            db.session,
            company_id=company.id,
            integration_id=integration.id,
            request=altered_caller_request,
            registry=registry,
            now=now,
        )
        authority_review = db.session.get(
            PartnerServiceRequestReview, authority_id
        )
        authority_audit = db.session.query(PartnerServiceAuditLog).filter_by(
            integration_id=integration.id,
            request_id="request-snapshot-authority",
        ).one()

        record(
            "Caller payload cannot replace approved snapshot",
            authority_result.result.accepted is True
            and DeterministicTestAdapter.seen_payloads[-1] == {},
        )
        record(
            "Snapshot authority test invokes adapter exactly once",
            len(DeterministicTestAdapter.seen_payloads)
            == adapter_calls_before + 1,
        )
        record(
            "Audit hash remains the approved snapshot hash",
            authority_audit.payload_hash == authority_review.payload_hash,
        )
        db.session.commit()

        def assert_snapshot_failure(request_id, mutation, label):
            review_id, request, _ = prepare_review(
                request_id,
                prepare=False,
            )
            review_row = db.session.get(
                PartnerServiceRequestReview, review_id
            )
            mutation(review_row)
            db.session.commit()

            calls_before = len(DeterministicTestAdapter.seen_payloads)
            rejected = False
            try:
                prepare_partner_service_request(
                    db.session,
                    company_id=company.id,
                    integration_id=integration.id,
                    request=request,
                    registry=registry,
                    now=now,
                )
            except PartnerServiceRequestError:
                rejected = True
            finally:
                db.session.rollback()

            record(
                label,
                rejected
                and len(DeterministicTestAdapter.seen_payloads) == calls_before,
            )

        def remove_snapshot(row):
            row.encrypted_payload = None
            row.payload_key_version = None

        def erase_snapshot(row):
            row.encrypted_payload = None
            row.payload_key_version = None
            row.payload_snapshot_erased_at = now

        def tamper_snapshot(row):
            token = row.encrypted_payload
            row.encrypted_payload = token[:-1] + (
                "A" if token[-1] != "A" else "B"
            )

        def alter_snapshot_hash(row):
            row.payload_hash = "0" * 64

        def remove_historical_key(row):
            row.payload_key_version = "missing-historical-key"

        def corrupt_hash_format(row):
            row.payload_hash = "g" * 64

        assert_snapshot_failure(
            "request-snapshot-missing",
            remove_snapshot,
            "Missing snapshot fails before adapter invocation",
        )
        assert_snapshot_failure(
            "request-snapshot-erased",
            erase_snapshot,
            "Erased snapshot fails before adapter invocation",
        )
        assert_snapshot_failure(
            "request-snapshot-tampered",
            tamper_snapshot,
            "Tampered ciphertext fails before adapter invocation",
        )
        assert_snapshot_failure(
            "request-snapshot-hash-mismatch",
            alter_snapshot_hash,
            "Changed snapshot hash fails before adapter invocation",
        )
        assert_snapshot_failure(
            "request-snapshot-key-missing",
            remove_historical_key,
            "Unavailable historical key fails before adapter invocation",
        )
        assert_snapshot_failure(
            "request-snapshot-hash-malformed",
            corrupt_hash_format,
            "Malformed stored hash fails before adapter invocation",
        )

        # --------------------------------------------------
        # TERMINAL STATE PROTECTION
        # --------------------------------------------------
        context = refused_result.audit_record
        # Rebuild the context from the known integration scope.
        from app.integration_adapters.partner import PartnerServiceContext

        partner_context = PartnerServiceContext(
            company_id=company.id,
            integration_id=integration.id,
            provider_code=provider.code,
            environment=integration.environment,
            ownership_scope=integration.ownership_scope,
            integration_company_id=integration.company_id,
        )

        try:
            require_approved_partner_service_request_review(
                db.session,
                context=partner_context,
                request=refused_request,
                provider_id=provider.id,
                now=now,
            )
            reusable = True
        except PartnerRequestReviewError:
            reusable = False

        record(
            "Preparation-rejected review cannot be reused",
            reusable is False,
        )

        try:
            mark_partner_service_request_review_preparation_rejected(
                db.session,
                review=refused_review,
                reason_code="partner_unavailable",
                now=now,
            )
            repeated_transition_blocked = False
        except PartnerRequestReviewError:
            repeated_transition_blocked = True

        record(
            "Preparation rejection transition cannot be repeated",
            repeated_transition_blocked,
        )

        try:
            approve_partner_service_request_review(
                db.session,
                actor=reviewer,
                review_id=refused_review_id,
                now=now,
            )
            reapproval_blocked = False
        except PartnerRequestReviewError:
            reapproval_blocked = True

        record(
            "Preparation-rejected review cannot be re-approved",
            reapproval_blocked,
        )

        db.session.rollback()

    failures = [name for name, passed in results if not passed]

    print("\n===== PARTNER REVIEW TEST SUMMARY =====")
    print(f"Passed: {len(results) - len(failures)}")
    print(f"Failed: {len(failures)}")

    if failures:
        for failure in failures:
            print(f"FAILED CHECK: {failure}")
        return 1

    print("ALL PARTNER REVIEW REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as exc:
        print(f"TEST SCRIPT ERROR: {type(exc).__name__}: {exc}")
        raise
    finally:
        TEMP_DIR.cleanup()

    sys.exit(exit_code)
