"""Regression tests for the company-admin partner preparation route."""

import os
import re
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

TEMP_DIR = tempfile.TemporaryDirectory(prefix="appex_partner_route_")
DB_PATH = str(Path(TEMP_DIR.name) / "partner_route_tests.sqlite")

from cryptography.fernet import Fernet

TEST_KEY = Fernet.generate_key().decode("ascii")

os.environ["APP_ENV"] = "development"
os.environ["SECRET_KEY"] = "partner-route-test-secret"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["PARTNER_PAYLOAD_ENCRYPTION_KEYS"] = (
    '{"route-test-v1":"' + TEST_KEY + '"}'
)
os.environ["PARTNER_PAYLOAD_ENCRYPTION_ACTIVE_KEY_VERSION"] = "route-test-v1"

from app import create_app, db
from app.models import (
    Company,
    User,
    IntegrationProvider,
    CompanyIntegration,
    PartnerServiceRequestReview,
    PartnerServiceRequestReviewEvent,
)
from app.partner_consent import (
    create_pending_partner_service_consent,
    activate_partner_service_consent,
)
from app.partner_request_reviews import (
    submit_partner_service_request_review,
    approve_partner_service_request_review,
)
from app.partner_services import prepare_partner_service_request as real_prepare
from app.integration_adapters.partner import (
    PartnerServiceAdapter,
    PartnerServiceRequest,
    PartnerServicePreparationResult,
)
from app.integration_adapters.partner_registry import (
    PartnerServiceAdapterRegistry,
)
import importlib

route_module = importlib.import_module("app.routes")

results = []


def record(name, passed, detail=""):
    results.append((name, bool(passed)))
    suffix = f" — {detail}" if detail else ""
    print(f"{'PASS' if passed else 'FAIL'}: {name}{suffix}")


class RouteTestAdapter(PartnerServiceAdapter):
    seen_payloads = []

    @property
    def supported_operations(self):
        return frozenset({"financial_services.product_catalogue"})

    def prepare_request(self, *, context, request, configuration):
        self.seen_payloads.append(dict(request.payload))
        return PartnerServicePreparationResult(
            accepted=True,
            partner_reference="route-test-reference",
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
            raise RuntimeError("Refusing to run: unexpected test database.")

        print(f"Disposable database verified: {actual_db}")
        db.create_all()

        now = datetime(2026, 11, 18, 12, 0, 0)

        company_a = Company(name="Preparation Route Company A")
        company_b = Company(name="Preparation Route Company B")
        db.session.add_all([company_a, company_b])
        db.session.flush()

        admin_a = User(
            company_id=company_a.id,
            name="Company A Administrator",
            email="route-admin-a@example.test",
            password_hash="test-password-hash",
            role="company_admin",
            is_active=True,
        )
        requester_a = User(
            company_id=company_a.id,
            name="Company A Requester",
            email="route-requester-a@example.test",
            password_hash="test-password-hash",
            role="company_admin",
            is_active=True,
        )
        admin_b = User(
            company_id=company_b.id,
            name="Company B Administrator",
            email="route-admin-b@example.test",
            password_hash="test-password-hash",
            role="company_admin",
            is_active=True,
        )
        db.session.add_all([admin_a, requester_a, admin_b])
        db.session.flush()

        operation = "financial_services.product_catalogue"
        provider = IntegrationProvider(
            code="route.test.partner",
            display_name="Route Test Partner",
            category="financial_services",
            description="Test-only provider",
            capabilities=[operation],
            is_enabled=True,
        )
        db.session.add(provider)
        db.session.flush()

        integration = CompanyIntegration(
            company_id=company_a.id,
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
            actor=requester_a,
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
            actor=requester_a,
            consent_id=consent.id,
            now=now,
        )
        db.session.commit()

        integration_id = integration.id
        requester_a_id = requester_a.id
        admin_a_id = admin_a.id

        def make_review(request_id, *, approved=True, payload=None):
            request = PartnerServiceRequest(
                request_id=request_id,
                operation=operation,
                payload={"product_category": "business_financing"}
                if payload is None else payload,
            )
            review = submit_partner_service_request_review(
                db.session,
                actor=db.session.get(User, requester_a_id),
                integration_id=integration_id,
                request=request,
                now=now,
            )
            db.session.flush()

            if approved:
                approve_partner_service_request_review(
                    db.session,
                    actor=db.session.get(User, admin_a_id),
                    review_id=review.id,
                    now=now,
                )

            db.session.commit()
            return review.id

        approved_id = make_review("route-approved")
        pending_id = make_review("route-pending", approved=False)
        default_registry_id = make_review("route-default-registry")

        approved_snapshot_hash = db.session.get(
            PartnerServiceRequestReview, approved_id
        ).payload_hash

        admin_a_id = admin_a.id
        admin_b_id = admin_b.id

    client = app.test_client()

    def login(user_id):
        with client.session_transaction() as session:
            session.clear()
            session["user_id"] = user_id

    # TEST 1: Successful preparation through the real service, with a
    # deterministic adapter injected only for this test.
    registry = PartnerServiceAdapterRegistry()
    adapter = RouteTestAdapter()
    registry.register("route.test.partner", adapter)

    def prepare_with_test_registry(*args, **kwargs):
        kwargs["registry"] = registry
        return real_prepare(*args, **kwargs)

    login(admin_a_id)
    with patch.object(
        route_module,
        "prepare_partner_service_request",
        side_effect=prepare_with_test_registry,
    ):
        response = client.post(
            f"/company/partner-requests/{approved_id}/prepare",
            data={
                "payload": '{"source":"browser-tampering"}',
                "integration_id": "999999",
                "operation": "browser.operation",
                "request_id": "browser-request",
            },
            follow_redirects=False,
        )

    record(
        "Approved review preparation redirects successfully",
        response.status_code == 302,
        f"HTTP {response.status_code}",
    )

    with app.app_context():
        review = db.session.get(PartnerServiceRequestReview, approved_id)
        event = PartnerServiceRequestReviewEvent.query.filter_by(
            review_id=approved_id,
            event_type="prepared",
        ).one_or_none()

        record(
            "Approved review transitions to prepared",
            review is not None and review.status == "prepared",
        )
        record(
            "Preparation event records authenticated administrator",
            event is not None and event.actor_user_id == admin_a_id,
        )
        record(
            "Browser payload does not replace encrypted snapshot",
            adapter.seen_payloads == [{"product_category": "business_financing"}],
        )
        record(
            "Review snapshot hash remains unchanged",
            review is not None and review.payload_hash == approved_snapshot_hash,
        )

    # TEST 2: Another company's administrator cannot access the review.
    login(admin_b_id)
    response = client.post(
        f"/company/partner-requests/{default_registry_id}/prepare",
        follow_redirects=False,
    )
    record(
        "Foreign-company review is hidden with 404",
        response.status_code == 404,
        f"HTTP {response.status_code}",
    )

    # TEST 3: A pending review cannot be prepared.
    login(admin_a_id)
    response = client.post(
        f"/company/partner-requests/{pending_id}/prepare",
        follow_redirects=False,
    )
    with app.app_context():
        pending = db.session.get(PartnerServiceRequestReview, pending_id)
        pending_events = PartnerServiceRequestReviewEvent.query.filter_by(
            review_id=pending_id,
            event_type="prepared",
        ).count()

        record(
            "Pending review remains pending",
            pending is not None and pending.status == "pending",
        )
        record(
            "Pending review receives no prepared event",
            pending_events == 0,
        )

    # TEST 4: The actual production default registry is empty. The route
    # must fail closed and leave the approved review unchanged.
    login(admin_a_id)
    response = client.post(
        f"/company/partner-requests/{default_registry_id}/prepare",
        follow_redirects=False,
    )

    with app.app_context():
        default_review = db.session.get(
            PartnerServiceRequestReview, default_registry_id
        )
        default_events = PartnerServiceRequestReviewEvent.query.filter_by(
            review_id=default_registry_id,
            event_type="prepared",
        ).count()

        record(
            "Default empty registry fails closed",
            response.status_code == 302
            and default_review is not None
            and default_review.status == "approved",
            f"HTTP {response.status_code}",
        )
        record(
            "Failed default-registry attempt creates no prepared event",
            default_events == 0,
        )

        from app.models import PartnerServiceAuditLog
        default_audits = PartnerServiceAuditLog.query.filter_by(
            integration_id=default_review.integration_id,
            request_id="route-default-registry",
        ).count()

        record(
            "Unavailable default adapter creates no audit record",
            default_audits == 0,
        )

    # TEST 5: CSRF protection rejects a POST without a token.
    with app.app_context():
        csrf_missing_id = make_review("route-csrf-missing")

    app.config["WTF_CSRF_ENABLED"] = True
    login(admin_a_id)

    response = client.post(
        f"/company/partner-requests/{csrf_missing_id}/prepare",
        follow_redirects=False,
    )

    with app.app_context():
        csrf_missing_review = db.session.get(
            PartnerServiceRequestReview, csrf_missing_id
        )
        csrf_missing_events = PartnerServiceRequestReviewEvent.query.filter_by(
            review_id=csrf_missing_id,
            event_type="prepared",
        ).count()

        record(
            "Missing CSRF token is rejected with HTTP 400",
            response.status_code == 400,
            f"HTTP {response.status_code}",
        )
        record(
            "CSRF rejection leaves review approved",
            csrf_missing_review is not None
            and csrf_missing_review.status == "approved",
        )
        record(
            "CSRF rejection creates no prepared event",
            csrf_missing_events == 0,
        )

    # TEST 6: A valid token permits the preparation route.
    with app.app_context():
        csrf_valid_id = make_review("route-csrf-valid")

    login(admin_a_id)
    page = client.get("/company/partner-requests")
    token_match = re.search(
        rb'name="csrf_token"\s+value="([^"]+)"',
        page.data,
    )

    record(
        "Partner requests page provides a CSRF token",
        page.status_code == 200 and token_match is not None,
        f"GET HTTP {page.status_code}",
    )

    if token_match is not None:
        csrf_token = token_match.group(1).decode("utf-8")

        with patch.object(
            route_module,
            "prepare_partner_service_request",
            side_effect=prepare_with_test_registry,
        ):
            response = client.post(
                f"/company/partner-requests/{csrf_valid_id}/prepare",
                data={"csrf_token": csrf_token},
                follow_redirects=False,
            )

        with app.app_context():
            csrf_valid_review = db.session.get(
                PartnerServiceRequestReview, csrf_valid_id
            )
            csrf_valid_event = PartnerServiceRequestReviewEvent.query.filter_by(
                review_id=csrf_valid_id,
                event_type="prepared",
            ).one_or_none()

            record(
                "Valid CSRF token permits preparation",
                response.status_code == 302
                and csrf_valid_review is not None
                and csrf_valid_review.status == "prepared",
                f"HTTP {response.status_code}",
            )
            record(
                "Valid-CSRF preparation records administrator",
                csrf_valid_event is not None
                and csrf_valid_event.actor_user_id == admin_a_id,
            )
    else:
        record("Valid CSRF token permits preparation", False, "Token unavailable")
        record("Valid-CSRF preparation records administrator", False)

    # TEST 7: A database commit failure rolls back all preparation writes.
    with app.app_context():
        commit_failure_id = make_review("route-commit-failure")
        session_class = type(db.session())

    login(admin_a_id)

    # Reuse a freshly rendered token for this POST.
    page = client.get("/company/partner-requests")
    token_match = re.search(
        rb'name="csrf_token"\s+value="([^"]+)"',
        page.data,
    )

    record(
        "Rollback test obtains a valid CSRF token",
        page.status_code == 200 and token_match is not None,
    )

    if token_match is not None:
        csrf_token = token_match.group(1).decode("utf-8")

        with patch.object(
            session_class,
            "commit",
            side_effect=RuntimeError("simulated database commit failure"),
        ) as commit_mock:
            with patch.object(
                route_module,
                "prepare_partner_service_request",
                side_effect=prepare_with_test_registry,
            ):
                response = client.post(
                    f"/company/partner-requests/{commit_failure_id}/prepare",
                    data={"csrf_token": csrf_token},
                    follow_redirects=False,
                )

        record(
            "Simulated database commit failure was reached",
            commit_mock.call_count == 1,
            f"commit calls: {commit_mock.call_count}",
        )
        record(
            "Commit failure returns safely through route",
            response.status_code == 302,
            f"HTTP {response.status_code}",
        )

        # Query after the request has ended, using a fresh app context.
        with app.app_context():
            from app.models import PartnerServiceAuditLog

            failed_review = db.session.get(
                PartnerServiceRequestReview, commit_failure_id
            )

            prepared_events = PartnerServiceRequestReviewEvent.query.filter_by(
                review_id=commit_failure_id,
                event_type="prepared",
            ).count()

            audit_count = PartnerServiceAuditLog.query.filter_by(
                integration_id=failed_review.integration_id,
                request_id="route-commit-failure",
            ).count() if failed_review is not None else -1

            record(
                "Commit failure rolls review back to approved",
                failed_review is not None
                and failed_review.status == "approved",
            )
            record(
                "Commit failure leaves no prepared event",
                prepared_events == 0,
            )
            record(
                "Commit failure leaves no audit record",
                audit_count == 0,
            )
    else:
        record("Simulated database commit failure was reached", False)
        record("Commit failure returns safely through route", False)
        record("Commit failure rolls review back to approved", False)
        record("Commit failure leaves no prepared event", False)
        record("Commit failure leaves no audit record", False)

    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed

    print("\n===== PARTNER PREPARATION ROUTE TEST SUMMARY =====")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    finally:
        TEMP_DIR.cleanup()
