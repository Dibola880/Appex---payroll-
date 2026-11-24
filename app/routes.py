import secrets
import json
import calendar
import re

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from io import BytesIO
from sqlalchemy import or_, and_, text

from flask import (
    Blueprint,
    abort,
    current_app,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
    send_file,
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash,
)
from itsdangerous import BadSignature, URLSafeTimedSerializer

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from . import db
from .accounting_setup import (
    AccountingSetupError,
    setup_company_accounting,
)
from .accounting_lifecycle_service import (
    AccountingLifecycleServiceError,
    close_accounting_period,
    reopen_accounting_period,
    close_financial_year,
    reopen_financial_year,
)
from .journal_service import (
    create_journal,
    create_reversal,
    post_journal,
    post_reversal,
    update_journal,
    journal_draft_snapshot,
    JournalServiceError,
    JournalDraftConflict,
)

from .models import (
    Account,
    JournalEntry,
    JournalLine,
    AccountingPeriod,
    FinancialYear,
    JournalAuditEvent,
    Company,
    CompanyIntegration,
    IntegrationProvider,
    PartnerServiceConsent,
    PartnerServiceConsentEvent,
    PartnerServiceRequestReview,
    PartnerServiceRequestReviewEvent,
    PlatformAuditLog,
    SubscriptionPlan,
    CompanySubscription,
    SubscriptionInvoice,
    SubscriptionPayment,
    User,
    Employee,
    EmployeeInvitation,
    PayrollRun,
    PayrollInput,
    Payslip,
    LoanApplication,
    LoanRepayment,
    SalesLead,
    ClientReferral,
)

from .platform_audit import (
    PlatformAuditError,
    record_platform_audit,
)

from .partner_consent import (
    PartnerConsentError,
    OPERATION_DATA_CATEGORIES,
    PURPOSE_BY_OPERATION,
    create_pending_partner_service_consent,
    activate_partner_service_consent,
    revoke_partner_service_consent,
    list_company_partner_service_consents,
    list_company_partner_service_consent_events,
)

from .integration_adapters.partner import (
    PARTNER_OPERATION_SCHEMAS,
    PartnerServiceRequest,
)
from .partner_payload_security import (
    PartnerPayloadEncryptionError,
    decrypt_partner_payload,
)
from .partner_services import (
    PartnerServiceRequestError,
    PartnerServiceAuditPersistenceError,
    prepare_partner_service_request,
)
from .partner_request_reviews import (
    PartnerRequestReviewError,
    submit_partner_service_request_review,
    approve_partner_service_request_review,
    reject_partner_service_request_review,
    list_company_partner_service_request_reviews,
)
from .integration_service import (
    IntegrationServiceError,
    create_company_integration,
    create_platform_integration,
    update_company_integration,
    update_platform_integration,
    get_company_integration_status,
    get_platform_integration_status,
    list_company_integrations,
    list_platform_integrations,
)

from .subscription_entitlements import (
    has_feature,
    FREE_TRIAL_DAYS,
    get_company_entitlements,
    get_current_subscription,
)
from .subscription_lifecycle import (
    request_subscription_cancellation,
    expire_due_subscriptions,
)

from .roles import (
    PLATFORM_SUPER_ADMIN,
    COMPANY_ADMIN_ROLES,
    COMPANY_OPERATIONAL_ROLES,
    EMPLOYEE,
)

from .payroll_calculator import calculate_payroll
from .payroll_accounting import create_payroll_journal


bp = Blueprint("main", __name__)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    user = User.query.get(user_id)

    if user is None or not user.is_active:
        session.clear()
        return None

    return user


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):

        if not current_user():

            flash(
                "Please log in to continue.",
                "warning"
            )

            return redirect(
                url_for("main.login")
            )

        return view(*args, **kwargs)

    return wrapped_view


def employer_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):

        user = current_user()

        if not user:

            flash(
                "Please log in to continue.",
                "warning"
            )

            return redirect(
                url_for("main.login")
            )

        if user.role not in COMPANY_OPERATIONAL_ROLES:

            flash(
                "Company operational access required.",
                "danger"
            )

            return redirect(
                url_for("main.employee_dashboard")
            )

        return view(*args, **kwargs)

    return wrapped_view


def company_admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):

        user = current_user()

        if not user:
            flash(
                "Please log in to continue.",
                "warning"
            )
            return redirect(url_for("main.login"))

        if (
            user.role not in COMPANY_ADMIN_ROLES
            or not user.company_id
            or user.company is None
        ):
            abort(403)

        return view(*args, **kwargs)

    return wrapped_view


def accounting_feature_required(view):
    """Require an active subscription that explicitly grants accounting."""
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user = current_user()
        if user is None or user.company is None:
            abort(403)
        if not has_feature(user.company, "accounting"):
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


def platform_super_admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):

        user = current_user()

        if not user:
            flash(
                "Please log in to continue.",
                "warning"
            )
            return redirect(url_for("main.login"))

        if user.role != PLATFORM_SUPER_ADMIN:
            abort(403)

        return view(*args, **kwargs)

    return wrapped_view



@bp.route("/platform/diagnostics/loan-schema", methods=["GET"])
@platform_super_admin_required
def platform_loan_schema_diagnostic():
    """Temporary, platform-admin-only, read-only PostgreSQL schema diagnostic."""

    def diagnostic_response(payload, status):
        response = jsonify(payload)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response, status

    if db.engine.dialect.name != "postgresql":
        return diagnostic_response({
            "status": "unavailable",
            "message": "This diagnostic requires PostgreSQL.",
        }, 503)

    expected_columns = {
        "loan_product": [
            "service_fee",
            "max_deduction_percent",
            "minimum_employment_months",
        ],
        "loan_application": [
            "repayment_frequency",
            "approved_at",
            "principal_amount",
            "interest_amount",
            "service_fee_amount",
            "scheduled_installment",
            "number_of_payments",
            "last_payment_date",
        ],
        "loan_repayment": [
            "balance_before",
            "balance_after",
            "payment_number",
            "source",
        ],
    }

    connection = None
    transaction = None

    try:
        connection = db.engine.connect()
        transaction = connection.begin()

        # This must be the first SQL statement in the transaction.
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")

        revision_table_present = connection.execute(
            text("SELECT to_regclass('alembic_version') IS NOT NULL")
        ).scalar_one()

        revisions = []
        if revision_table_present:
            revisions = connection.execute(
                text(
                    "SELECT version_num "
                    "FROM alembic_version "
                    "ORDER BY version_num"
                )
            ).scalars().all()

        table_names = list(expected_columns)
        column_names = sorted({
            column
            for columns in expected_columns.values()
            for column in columns
        })

        rows = connection.execute(
            text("""
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = ANY(:table_names)
                  AND column_name = ANY(:column_names)
            """),
            {
                "table_names": table_names,
                "column_names": column_names,
            },
        ).all()

        present = {}
        for table_name, column_name in rows:
            present.setdefault(table_name, set()).add(column_name)

        column_report = {}
        for table_name, columns in expected_columns.items():
            existing = present.get(table_name, set())
            column_report[table_name] = {
                "present": sorted(existing.intersection(columns)),
                "missing": sorted(set(columns) - existing),
            }

        result = {
            "status": "ok",
            "database_dialect": "postgresql",
            "alembic_version_table_present": bool(revision_table_present),
            "alembic_revisions": revisions,
            "loan_columns": column_report,
        }

        return diagnostic_response(result, 200)

    except Exception:
        current_app.logger.exception(
            "Temporary loan schema diagnostic failed."
        )
        return diagnostic_response({
            "status": "error",
            "message": "Diagnostic unavailable. Check application logs.",
        }, 503)

    finally:
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        if connection is not None:
            connection.close()


def safe_float(value, default=0.0):

    try:

        number = float(value)

        if number < 0:
            return default

        return number

    except (TypeError, ValueError):

        return default


def calculate_age_from_dob(date_of_birth):

    if not date_of_birth:
        return None

    try:

        today = datetime.utcnow().date()

        return (
            today.year
            - date_of_birth.year
            - (
                (
                    today.month,
                    today.day
                )
                <
                (
                    date_of_birth.month,
                    date_of_birth.day
                )
            )
        )

    except Exception:

        return None


# ============================================================
# CLIENT ACQUISITION HELPERS
# ============================================================

def generate_referral_code():

    """
    Generate a unique referral code for a company.
    """

    for _ in range(20):

        code = (
            "APX-"
            + secrets.token_hex(4).upper()
        )

        existing = Company.query.filter_by(
            referral_code=code
        ).first()

        if not existing:
            return code

    raise RuntimeError(
        "Unable to generate a unique referral code."
    )


def ensure_company_referral_code(company):

    """
    Make sure an existing company has a referral code.
    """

    if company and not company.referral_code:

        company.referral_code = (
            generate_referral_code()
        )

        db.session.commit()

    return company.referral_code


# ============================================================
# PHASE 5A - LOAN HELPERS
# ============================================================

def parse_repayment_term_months(repayment_term):

    text = str(
        repayment_term or ""
    ).strip().lower()

    match = re.search(
        r"(\d+)",
        text
    )

    if not match:
        return 1

    months = int(
        match.group(1)
    )

    return max(
        1,
        min(months, 60)
    )


def add_months(value, months):

    if not value:
        return None

    month_index = (
        value.month - 1
        + months
    )

    year = (
        value.year
        + month_index // 12
    )

    month = (
        month_index % 12
        + 1
    )

    day = min(
        value.day,
        calendar.monthrange(
            year,
            month
        )[1]
    )

    return value.replace(
        year=year,
        month=month,
        day=day
    )


def get_active_employee_loan(employee_id, lock_for_update=False):
    query = (
        LoanApplication.query
        .filter(
            LoanApplication.employee_id == employee_id,
            LoanApplication.status == "Disbursed",
            LoanApplication.outstanding_balance > 0
        )
        .order_by(
            LoanApplication.created_at.asc()
        )
    )

    if lock_for_update:
        query = query.with_for_update().populate_existing()

    return query.first()


def calculate_loan_installment(application):

    if not application:
        return 0.0

    total_repayable = safe_float(
        application.total_repayable
    )

    outstanding_balance = safe_float(
        application.outstanding_balance
    )

    if total_repayable <= 0:
        return 0.0

    if outstanding_balance <= 0:
        return 0.0

    months = parse_repayment_term_months(
        application.repayment_term
    )

    installment = round(
        total_repayable / months,
        2
    )

    installment = min(
        installment,
        outstanding_balance
    )

    return round(
        max(0.0, installment),
        2
    )


def get_company_loan_or_404(
    loan_id,
    user,
    lock_for_update=False
):
    query = (
        LoanApplication.query
        .join(Employee)
        .filter(
            LoanApplication.id == loan_id,
            Employee.company_id == user.company_id
        )
    )

    if lock_for_update:
        query = query.with_for_update(
            of=LoanApplication
        ).populate_existing()

    return query.first_or_404()


# ============================================================
# PHASE 5 - LOAN REPAYMENT LEDGER HELPERS
# ============================================================

def find_loan_ledger_entry(loan_application_id, employee_id, payroll_run_id):
    """Find an existing ledger row for this loan/employee/payroll run."""
    return LoanRepayment.query.filter_by(
        loan_application_id=loan_application_id,
        employee_id=employee_id,
        payroll_run_id=payroll_run_id,
    ).first()


def create_loan_repayment_ledger_entry(
    loan_application, employee, payroll_run, payslip, amount
):
    """Create one payroll repayment ledger row; never intentionally duplicate."""
    amount = round(max(0.0, safe_float(amount)), 2)
    if amount <= 0:
        return None, False

    existing = find_loan_ledger_entry(
        loan_application.id, employee.id, payroll_run.id
    )
    if existing:
        return existing, False

    outstanding = round(
        max(0.0, safe_float(loan_application.outstanding_balance)), 2
    )
    amount = round(min(amount, outstanding), 2)
    if amount <= 0:
        return None, False

    reference = (
        f"APX-LOAN-{loan_application.id}-PAY-{payroll_run.id}"
        f"-EMP-{employee.id}"
    )
    existing_reference = LoanRepayment.query.filter_by(
        reference=reference
    ).first()
    if existing_reference:
        return existing_reference, False

    last_completed_repayment = LoanRepayment.query.filter_by(
        loan_application_id=loan_application.id,
        status="Completed",
    ).order_by(LoanRepayment.payment_number.desc()).first()
    payment_number = (
        last_completed_repayment.payment_number + 1
        if last_completed_repayment
        else 1
    )

    repayment = LoanRepayment(
        loan_application_id=loan_application.id,
        employee_id=employee.id,
        payroll_run_id=payroll_run.id,
        payslip_id=payslip.id,
        amount=amount,
        balance_before=outstanding,
        balance_after=round(max(0.0, outstanding - amount), 2),
        payment_number=payment_number,
        repayment_date=payroll_run.pay_date or datetime.utcnow().date(),
        payment_method="Payroll Deduction",
        source="Payroll",
        reference=reference,
        status="Completed",
        notes="Loan repayment deducted through payroll.",
        created_at=datetime.utcnow(),
    )
    db.session.add(repayment)
    db.session.flush()
    return repayment, True


def get_employee_loan_repayment_ledger(employee_id):
    """Return an employee's ledger rows, newest first."""
    return LoanRepayment.query.filter_by(
        employee_id=employee_id
    ).order_by(LoanRepayment.id.desc()).all()


# ============================================================
# PAYROLL CALCULATION
# ============================================================

def calculate_payroll_input(payroll_input, lock_loan=False):

    employee = payroll_input.employee

    age = calculate_age_from_dob(
        employee.date_of_birth
    )

    if age is None:
        age = 30

    result = calculate_payroll(
        basic_salary=safe_float(
            payroll_input.basic_salary
        ),
        overtime=safe_float(
            payroll_input.overtime
        ),
        bonus=safe_float(
            payroll_input.bonus
        ),
        commission=safe_float(
            payroll_input.commission
        ),
        other_earnings=safe_float(
            payroll_input.other_earnings
        ),
        other_deductions=safe_float(
            payroll_input.other_deductions
        ),
        age=age,
    )

    gross_pay = safe_float(
        result.get("gross_pay", 0)
    )

    paye = safe_float(
        result.get("paye", 0)
    )

    uif = safe_float(
        result.get("uif", 0)
    )

    other_deductions = safe_float(
        result.get("other_deductions", 0)
    )

    base_total_deductions = safe_float(
        result.get(
            "total_deductions",
            paye + uif + other_deductions
        )
    )

    loan_application = None
    scheduled_loan_repayment = 0.0
    loan_repayment = 0.0
    loan_outstanding_before = 0.0

    payroll_run = payroll_input.payroll_run

    if (
        payroll_run
        and payroll_run.status == "Completed"
    ):

        loan_repayment = safe_float(
            payroll_input.loan_repayment
        )

    else:

        loan_application = get_active_employee_loan(
            employee.id,
            lock_for_update=lock_loan,
        )

        if loan_application:

            loan_outstanding_before = safe_float(
                loan_application.outstanding_balance
            )

            scheduled_loan_repayment = (
                calculate_loan_installment(
                    loan_application
                )
            )

            available_for_loan = max(
                0.0,
                gross_pay
                - base_total_deductions
            )

            loan_repayment = min(
                scheduled_loan_repayment,
                available_for_loan
            )

            loan_repayment = round(
                max(0.0, loan_repayment),
                2
            )

    total_deductions = round(
        base_total_deductions
        + loan_repayment,
        2
    )

    net_pay = round(
        max(
            0.0,
            gross_pay
            - total_deductions
        ),
        2
    )

    employer_uif = safe_float(
        result.get("employer_uif", 0)
    )

    employer_cost = round(
        gross_pay
        + employer_uif,
        2
    )

    return {
        "employee": employee,
        "payroll_input": payroll_input,
        "result": result,
        "gross_pay": gross_pay,
        "paye": paye,
        "uif": uif,
        "other_deductions": other_deductions,
        "loan_repayment": loan_repayment,
        "scheduled_loan_repayment": scheduled_loan_repayment,
        "loan_application": loan_application,
        "loan_outstanding_before": loan_outstanding_before,
        "total_deductions": total_deductions,
        "net_pay": net_pay,
        "employer_uif": employer_uif,
        "employer_cost": employer_cost,
    }


def calculate_payroll_run_totals(payroll_run, lock_loans=False):

    payroll_inputs = PayrollInput.query.filter_by(
        payroll_run_id=payroll_run.id
    ).all()

    total_gross = 0.0
    total_deductions = 0.0
    total_net = 0.0
    total_employer_uif = 0.0
    total_employer_cost = 0.0

    results = []

    for payroll_input in payroll_inputs:

        if lock_loans:
            calculated = calculate_payroll_input(
                payroll_input,
                lock_loan=True,
            )
        else:
            calculated = calculate_payroll_input(payroll_input)

        results.append(calculated)

        total_gross += calculated["gross_pay"]
        total_deductions += calculated["total_deductions"]
        total_net += calculated["net_pay"]
        total_employer_uif += calculated["employer_uif"]
        total_employer_cost += calculated["employer_cost"]

    payroll_run.total_gross = round(
        total_gross,
        2
    )

    payroll_run.total_deductions = round(
        total_deductions,
        2
    )

    payroll_run.total_net = round(
        total_net,
        2
    )

    payroll_run.total_employer_uif = round(
        total_employer_uif,
        2
    )

    payroll_run.total_employer_cost = round(
        total_employer_cost,
        2
    )

    return results


def get_employee_payroll_value(
    employee_id,
    field_name,
    default=0.0
):

    field_name = (
        field_name or ""
    ).strip()

    individual_key = (
        f"employee_{employee_id}_{field_name}"
    )

    value = request.form.get(
        individual_key
    )

    if value not in [None, ""]:

        return safe_float(
            value,
            default
        )

    value = request.form.get(
        field_name
    )

    if value not in [None, ""]:

        return safe_float(
            value,
            default
        )

    return default


@bp.app_context_processor
def inject_user():

    return {
        "current_user": current_user()
    }


# ============================================================
# HEALTH CHECK
# ============================================================



# ============================================================
# PHASE 7.3 — SUBSCRIPTION PLAN ADMINISTRATION
# ============================================================

def _subscription_plan_form_data():
    """Validate and normalize platform-admin plan form fields."""
    code = (request.form.get("code") or "").strip().lower()
    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip() or None
    currency = (request.form.get("currency") or "ZAR").strip().upper()

    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", code):
        raise ValueError("Plan code must be 2–64 characters using lowercase letters, numbers, _ or -.")
    if not name or len(name) > 120:
        raise ValueError("Plan name is required and must be no longer than 120 characters.")
    if currency != "ZAR":
        raise ValueError("Only ZAR is enabled for the initial subscription catalogue.")

    def parse_price(field_name):
        raw = (request.form.get(field_name) or "").strip()
        if not raw:
            return None
        try:
            value = Decimal(raw)
        except (InvalidOperation, ValueError):
            raise ValueError(f"{field_name.replace('_', ' ').title()} must be a valid amount.")
        if not value.is_finite() or value < 0 or value.as_tuple().exponent < -2:
            raise ValueError(f"{field_name.replace('_', ' ').title()} must be non-negative with no more than two decimal places.")
        return value

    monthly_price = parse_price("monthly_price")
    annual_price = parse_price("annual_price")

    intervals = sorted(set(request.form.getlist("billing_intervals")))
    allowed_intervals = {"monthly", "annually"}
    if not intervals or not set(intervals).issubset(allowed_intervals):
        raise ValueError("Select at least one valid billing interval.")

    raw_limit = (request.form.get("employee_limit") or "").strip()
    if raw_limit:
        try:
            employee_limit = int(raw_limit)
        except ValueError:
            raise ValueError("Employee limit must be a whole number.")
        if employee_limit < 1:
            raise ValueError("Employee limit must be at least 1, or left blank for unlimited.")
    else:
        employee_limit = None

    raw_features = (request.form.get("feature_config") or "").strip()
    try:
        feature_config = json.loads(raw_features) if raw_features else {"features": {}}
    except json.JSONDecodeError as exc:
        raise ValueError(f"Feature configuration is not valid JSON: {exc.msg}")

    if not isinstance(feature_config, dict):
        raise ValueError("Feature configuration must be a JSON object.")
    features = feature_config.get("features")
    if not isinstance(features, dict):
        raise ValueError('Feature configuration must contain a "features" object.')
    for key, enabled in features.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(enabled, bool):
            raise ValueError("Each feature must have a non-empty name and a true/false value.")

    return {
        "code": code,
        "name": name,
        "description": description,
        "monthly_price": monthly_price,
        "annual_price": annual_price,
        "currency": currency,
        "billing_intervals": intervals,
        "employee_limit": employee_limit,
        "feature_config": feature_config,
    }


@bp.route("/platform/subscription-plans")
@platform_super_admin_required
def platform_subscription_plans():
    plans = SubscriptionPlan.query.order_by(SubscriptionPlan.name.asc()).all()
    return render_template("platform_subscription_plans.html", plans=plans)


@bp.route("/platform/subscription-plans/new", methods=["GET", "POST"])
@platform_super_admin_required
def platform_subscription_plan_new():
    if request.method == "POST":
        try:
            data = _subscription_plan_form_data()
            if SubscriptionPlan.query.filter_by(code=data["code"]).first():
                raise ValueError("A plan with that code already exists.")

            plan = SubscriptionPlan(**data, is_active=True)
            db.session.add(plan)
            db.session.commit()
            flash("Subscription plan created.", "success")
            return redirect(url_for("main.platform_subscription_plans"))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Subscription plan creation failed")
            flash("The plan could not be saved. Check the application log.", "danger")

    return render_template(
        "platform_subscription_plan_form.html",
        plan=None,
        page_title="Create subscription plan",
    )


@bp.route("/platform/subscription-plans/<int:plan_id>/edit", methods=["GET", "POST"])
@platform_super_admin_required
def platform_subscription_plan_edit(plan_id):
    plan = db.session.get(SubscriptionPlan, plan_id)
    if plan is None:
        abort(404)

    if request.method == "POST":
        try:
            data = _subscription_plan_form_data()

            duplicate = SubscriptionPlan.query.filter(
                SubscriptionPlan.code == data["code"],
                SubscriptionPlan.id != plan.id,
            ).first()
            if duplicate:
                raise ValueError("Another plan already uses that code.")

            requested_active = request.form.get("is_active") == "true"
            current_subscriptions = CompanySubscription.query.filter_by(
                plan_id=plan.id,
                is_current=True,
            ).count()

            if plan.is_active and not requested_active and current_subscriptions:
                raise ValueError(
                    "This plan has current subscriptions. It cannot be deactivated until those subscriptions have been moved or ended."
                )

            for key, value in data.items():
                setattr(plan, key, value)
            plan.is_active = requested_active

            db.session.commit()
            flash(
                "Subscription plan updated. Feature changes apply to current subscribers using this plan.",
                "success",
            )
            return redirect(url_for("main.platform_subscription_plans"))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Subscription plan update failed")
            flash("The plan could not be updated. Check the application log.", "danger")

    return render_template(
        "platform_subscription_plan_form.html",
        plan=plan,
        page_title="Edit subscription plan",
    )


# ============================================================
# ============================================================
# PHASE 9.3 — COMPANY PARTNER CONSENT MANAGEMENT
# ============================================================

@bp.route("/company/partner-consents")
@company_admin_required
def company_partner_consents():
    user = current_user()

    consents = list_company_partner_service_consents(
        db.session,
        actor=user,
    )
    consent_events = list_company_partner_service_consent_events(
        db.session,
        actor=user,
    )

    integrations = (
        CompanyIntegration.query
        .join(
            IntegrationProvider,
            IntegrationProvider.id == CompanyIntegration.provider_id,
        )
        .filter(
            IntegrationProvider.is_enabled.is_(True),
            CompanyIntegration.environment == "sandbox",
            or_(
                CompanyIntegration.ownership_scope == "platform",
                CompanyIntegration.company_id == user.company_id,
            ),
        )
        .order_by(
            IntegrationProvider.display_name.asc(),
            CompanyIntegration.id.asc(),
        )
        .all()
    )

    return render_template(
        "company_partner_consents.html",
        company=user.company,
        consents=consents,
        consent_events=consent_events,
        integrations=integrations,
        operations=(
            "payroll.compliance_summary",
            "financial_services.product_catalogue",
            "financial_services.company_offer_request",
        ),
        purpose_by_operation=PURPOSE_BY_OPERATION,
        operation_data_categories=OPERATION_DATA_CATEGORIES,
    )


@bp.route("/company/partner-consents", methods=["POST"])
@company_admin_required
def company_partner_consent_create():
    user = current_user()

    try:
        operation = request.form.get("operation", "").strip()
        if operation not in OPERATION_DATA_CATEGORIES:
            raise PartnerConsentError("Select an approved partner operation.")

        fixed_purpose = PURPOSE_BY_OPERATION.get(operation)
        purpose_code = (
            fixed_purpose
            if fixed_purpose is not None
            else request.form.get("purpose_code", "").strip()
        )

        expiry_value = request.form.get("expires_at", "").strip()
        try:
            expires_at = datetime.fromisoformat(expiry_value)
        except (TypeError, ValueError) as exc:
            raise PartnerConsentError(
                "Enter a valid consent expiry date and time in UTC."
            ) from exc

        create_pending_partner_service_consent(
            db.session,
            actor=user,
            integration_id=int(request.form.get("integration_id", "")),
            operation=operation,
            purpose_code=purpose_code,
            data_categories=sorted(OPERATION_DATA_CATEGORIES[operation]),
            expires_at=expires_at,
        )
        db.session.commit()
        flash("Pending partner consent created. Activate it separately to authorise sharing.", "success")

    except (PartnerConsentError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Partner consent creation failed")
        flash("Consent could not be created. No changes were saved.", "error")

    return redirect(url_for("main.company_partner_consents"))


@bp.route("/company/partner-consents/<int:consent_id>/activate", methods=["POST"])
@company_admin_required
def company_partner_consent_activate(consent_id):
    user = current_user()

    try:
        activate_partner_service_consent(
            db.session,
            actor=user,
            consent_id=consent_id,
        )
        db.session.commit()
        flash("Partner consent activated.", "success")

    except PartnerConsentError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Partner consent activation failed")
        flash("Consent could not be activated. No changes were saved.", "error")

    return redirect(url_for("main.company_partner_consents"))


@bp.route("/company/partner-consents/<int:consent_id>/revoke", methods=["POST"])
@company_admin_required
def company_partner_consent_revoke(consent_id):
    user = current_user()

    try:
        reason_code = request.form.get("reason_code", "").strip()
        revoke_partner_service_consent(
            db.session,
            actor=user,
            consent_id=consent_id,
            reason_code=reason_code,
        )
        db.session.commit()
        flash("Partner consent revoked. New requests covered by this consent will be blocked.", "success")

    except PartnerConsentError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Partner consent revocation failed")
        flash("Consent could not be revoked. No changes were saved.", "error")

    return redirect(url_for("main.company_partner_consents"))




# ============================================================
# PHASE 9.5 — COMPANY PARTNER REQUEST REVIEW
# ============================================================

@bp.route("/company/partner-requests", methods=["GET"])
@company_admin_required
def company_partner_requests():
    user = current_user()

    integrations = (
        CompanyIntegration.query
        .join(
            IntegrationProvider,
            CompanyIntegration.provider_id == IntegrationProvider.id,
        )
        .filter(
            IntegrationProvider.is_enabled.is_(True),
            CompanyIntegration.environment == "sandbox",
            CompanyIntegration.status == "connected",
            or_(
                CompanyIntegration.ownership_scope == "platform",
                CompanyIntegration.company_id == user.company_id,
            ),
        )
        .order_by(IntegrationProvider.display_name.asc())
        .all()
    )

    reviews = list_company_partner_service_request_reviews(
        db.session,
        actor=user,
        limit=100,
    )

    return render_template(
        "company_partner_requests.html",
        integrations=integrations,
        reviews=reviews,
        operations=tuple(PARTNER_OPERATION_SCHEMAS.keys()),
    )


@bp.route("/company/partner-requests", methods=["POST"])
@company_admin_required
def company_partner_request_submit():
    user = current_user()

    try:
        integration_id = int(request.form.get("integration_id", ""))
        operation = request.form.get("operation", "")
        request_id = request.form.get("request_id", "")
        payload_text = request.form.get("payload_json", "")

        if not isinstance(payload_text, str) or not payload_text.strip():
            raise ValueError("A JSON payload is required.")

        payload = json.loads(payload_text)
        if not isinstance(payload, dict):
            raise ValueError("The request payload must be a JSON object.")

        partner_request = PartnerServiceRequest(
            request_id=request_id,
            operation=operation,
            payload=payload,
        )

        submit_partner_service_request_review(
            db.session,
            actor=user,
            integration_id=integration_id,
            request=partner_request,
        )
        db.session.commit()
        flash(
            "Partner request submitted for independent company-admin review.",
            "success",
        )

    except (ValueError, TypeError, PartnerRequestReviewError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Partner request submission failed"
        )
        flash(
            "The partner request could not be submitted. No changes were saved.",
            "error",
        )

    return redirect(url_for("main.company_partner_requests"))


@bp.route(
    "/company/partner-requests/<int:review_id>/approve",
    methods=["POST"],
)
@company_admin_required
def company_partner_request_approve(review_id):
    user = current_user()

    try:
        review = approve_partner_service_request_review(
            db.session,
            actor=user,
            review_id=review_id,
        )
        db.session.commit()

        if review.status == "expired":
            flash("This request expired before it could be approved.", "warning")
        else:
            flash("Partner request approved. Independent approval recorded.", "success")

    except PartnerRequestReviewError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Partner request approval failed")
        flash(
            "The partner request could not be approved. No changes were saved.",
            "error",
        )

    return redirect(url_for("main.company_partner_requests"))


@bp.route(
    "/company/partner-requests/<int:review_id>/reject",
    methods=["POST"],
)
@company_admin_required
def company_partner_request_reject(review_id):
    user = current_user()

    try:
        reason_code = request.form.get("reason_code", "")
        review = reject_partner_service_request_review(
            db.session,
            actor=user,
            review_id=review_id,
            reason_code=reason_code,
        )
        db.session.commit()

        if review.status == "expired":
            flash("This request expired before it could be rejected.", "warning")
        else:
            flash("Partner request rejected.", "success")

    except PartnerRequestReviewError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Partner request rejection failed")
        flash(
            "The partner request could not be rejected. No changes were saved.",
            "error",
        )

    return redirect(url_for("main.company_partner_requests"))


@bp.route(
    "/company/partner-requests/<int:review_id>/prepare",
    methods=["POST"],
)
@company_admin_required
def company_partner_request_prepare(review_id):
    user = current_user()

    review = (
        PartnerServiceRequestReview.query
        .filter_by(id=review_id, company_id=user.company_id)
        .with_for_update()
        .first()
    )
    if review is None:
        abort(404)

    try:
        if review.status != "approved":
            raise PartnerServiceRequestError(
                "Only an approved partner request can be prepared."
            )

        # Reconstruct from the encrypted review snapshot, never browser input.
        stored_payload = decrypt_partner_payload(
            review.encrypted_payload,
            review.payload_key_version,
        )
        partner_request = PartnerServiceRequest(
            request_id=review.request_id,
            operation=review.operation,
            payload=stored_payload,
        )

        preparation = prepare_partner_service_request(
            db.session,
            company_id=user.company_id,
            integration_id=review.integration_id,
            request=partner_request,
            actor_user_id=user.id,
        )
        db.session.commit()

        if preparation.result.accepted:
            flash(
                "Partner request prepared and audited. No partner action was executed.",
                "success",
            )
        else:
            flash(
                "The adapter declined preparation. The outcome was audited.",
                "warning",
            )

    except (
        PartnerPayloadEncryptionError,
        PartnerServiceRequestError,
        PartnerServiceAuditPersistenceError,
        ValueError,
        TypeError,
    ) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Partner request preparation failed")
        flash(
            "The partner request could not be prepared. No changes were saved.",
            "error",
        )

    return redirect(url_for("main.company_partner_requests"))


# PHASE 7.3 — COMPANY SUBSCRIPTION VISIBILITY
# ============================================================

@bp.route("/company/subscription")
@company_admin_required
def company_subscription():
    user = current_user()
    history = (
        CompanySubscription.query
        .filter_by(company_id=user.company_id)
        .order_by(CompanySubscription.created_at.desc(), CompanySubscription.id.desc())
        .all()
    )
    current_subscription = next(
        (item for item in history if item.is_current),
        None,
    )
    entitlements = get_company_entitlements(user.company)

    return render_template(
        "company_subscription.html",
        company=user.company,
        current_subscription=current_subscription,
        subscription_history=history,
        entitlements=entitlements,
    )


# ============================================================
# PHASE 7.4 — SUBSCRIPTION INVOICE VISIBILITY
# ============================================================

@bp.route("/company/subscription/invoices")
@company_admin_required
def company_subscription_invoices():
    user = current_user()

    invoices = (
        SubscriptionInvoice.query
        .filter_by(company_id=user.company_id)
        .order_by(
            SubscriptionInvoice.created_at.desc(),
            SubscriptionInvoice.id.desc(),
        )
        .all()
    )

    payments = (
        SubscriptionPayment.query
        .filter_by(company_id=user.company_id)
        .order_by(
            SubscriptionPayment.created_at.desc(),
            SubscriptionPayment.id.desc(),
        )
        .all()
    )

    return render_template(
        "company_subscription_invoices.html",
        company=user.company,
        invoices=invoices,
        payments=payments,
    )


@bp.route("/platform/subscription-invoices")
@platform_super_admin_required
def platform_subscription_invoices():
    invoices = (
        SubscriptionInvoice.query
        .order_by(
            SubscriptionInvoice.created_at.desc(),
            SubscriptionInvoice.id.desc(),
        )
        .all()
    )

    payments = (
        SubscriptionPayment.query
        .order_by(
            SubscriptionPayment.created_at.desc(),
            SubscriptionPayment.id.desc(),
        )
        .all()
    )

    return render_template(
        "platform_subscription_invoices.html",
        invoices=invoices,
        payments=payments,
    )


# ============================================================
# PHASE 7.3 — SUBSCRIPTION LIFECYCLE
# ============================================================

@bp.route("/company/subscription/cancel", methods=["POST"])
@company_admin_required
def company_subscription_cancel():
    user = current_user()

    try:
        request_subscription_cancellation(user.company)
        db.session.commit()
        flash(
            "Cancellation scheduled. Your access remains available until the recorded period end.",
            "success",
        )
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Subscription cancellation failed")
        flash("The cancellation request could not be saved.", "danger")

    return redirect(url_for("main.company_subscription"))


@bp.route("/platform/subscriptions/process-expirations", methods=["POST"])
@platform_super_admin_required
def platform_process_subscription_expirations():
    try:
        expired_count = expire_due_subscriptions()
        db.session.commit()
        flash(
            f"Subscription expiry processing completed. Records expired: {expired_count}.",
            "success",
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Subscription expiry processing failed")
        flash("Subscription expiry processing failed. Check the application log.", "danger")

    return redirect(url_for("main.platform_subscription_plans"))


@bp.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "service": "appex-payroll"
    })


# ============================================================
# PLATFORM ADMINISTRATION HOME
# ============================================================

@bp.route("/platform")
@platform_super_admin_required
def platform_dashboard():
    """Landing page for platform-wide administration."""
    return render_template("platform_dashboard.html")


# ============================================================
# HOME / EMPLOYER DASHBOARD
# ============================================================

@bp.route("/")
@login_required
def dashboard():

    user = current_user()

    if user.role == PLATFORM_SUPER_ADMIN:
        return redirect(
            url_for("main.platform_dashboard")
        )


    if user.role == EMPLOYEE:

        return redirect(
            url_for(
                "main.employee_dashboard"
            )
        )

    if user.role not in COMPANY_OPERATIONAL_ROLES:
        abort(403)

    company = user.company

    if company:
        ensure_company_referral_code(company)

    employees = []
    payroll_runs = []

    if company:

        employees = Employee.query.filter_by(
            company_id=company.id
        ).all()

        payroll_runs = PayrollRun.query.filter_by(
            company_id=company.id
        ).order_by(
            PayrollRun.id.desc()
        ).all()

    total_employees = len(employees)

    active_employees = len([
        employee
        for employee in employees
        if employee.status == "Active"
    ])

    total_salary = sum(
        safe_float(employee.monthly_salary)
        for employee in employees
        if employee.status == "Active"
    )

    latest_payroll = (
        payroll_runs[0]
        if payroll_runs
        else None
    )

    return render_template(
        "dashboard.html",
        company=company,
        employees=employees,
        payroll_runs=payroll_runs,
        total_employees=total_employees,
        active_employees=active_employees,
        total_salary=total_salary,
        latest_payroll=latest_payroll,
    )


# ============================================================
# REGISTER
# ============================================================

@bp.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        company_name = (
            request.form.get("company_name")
            or ""
        ).strip()

        registration_number = (
            request.form.get("registration_number")
            or ""
        ).strip()

        name = (
            request.form.get("name")
            or ""
        ).strip()

        email = (
            request.form.get("email")
            or ""
        ).strip().lower()

        password = (
            request.form.get("password")
            or ""
        )

        if not company_name:

            flash(
                "Company name is required.",
                "danger"
            )

            return redirect(
                url_for("main.register")
            )

        if not name:

            flash(
                "Your name is required.",
                "danger"
            )

            return redirect(
                url_for("main.register")
            )

        if not email:

            flash(
                "Email address is required.",
                "danger"
            )

            return redirect(
                url_for("main.register")
            )

        if not password:

            flash(
                "Password is required.",
                "danger"
            )

            return redirect(
                url_for("main.register")
            )

        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:

            flash(
                "An account with this email already exists.",
                "danger"
            )

            return redirect(
                url_for("main.login")
            )

        company = Company(
            name=company_name,
            registration_number=registration_number,
            payroll_provider="Deel Local Payroll",
            contact_person=name,
            contact_email=email,
            client_status="Trial",
            subscription_plan="Free Trial",
            subscription_status="Trial",
            onboarding_completed=False,
        )

        company.referral_code = (
            generate_referral_code()
        )

        db.session.add(company)
        db.session.flush()

        # Create the initial subscription from the centrally managed
        # Free Trial plan. The migration seeds this plan.
        free_trial_plan = SubscriptionPlan.query.filter_by(
            code="free_trial",
            is_active=True,
        ).first()

        if free_trial_plan is None:
            raise RuntimeError(
                "The active Free Trial subscription plan is missing. "
                "Apply the reviewed subscription foundation migration first."
            )

        subscription_started_at = datetime.utcnow()

        db.session.add(
            CompanySubscription(
                company_id=company.id,
                plan_id=free_trial_plan.id,
                status="Trial",
                billing_interval="monthly",
                currency=free_trial_plan.currency,
                amount=free_trial_plan.monthly_price,
                starts_at=subscription_started_at,
                trial_ends_at=subscription_started_at + timedelta(days=FREE_TRIAL_DAYS),
                current_period_start=subscription_started_at,
                is_current=True,
            )
        )

        user = User(
            company_id=company.id,
            name=name,
            email=email,
            password_hash=generate_password_hash(
                password
            ),
            role="employer",
            is_active=True,
        )

        db.session.add(user)
        db.session.commit()

        session.clear()
        session["user_id"] = user.id

        flash(
            "Registration successful. Your free trial has started.",
            "success"
        )

        return redirect(
            url_for("main.dashboard")
        )

    return render_template(
        "register.html"
    )


# ============================================================
# LOGIN
# ============================================================

@bp.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = (
            request.form.get("email")
            or ""
        ).strip().lower()

        password = (
            request.form.get("password")
            or ""
        )

        user = User.query.filter_by(
            email=email
        ).first()

        if not user:

            flash(
                "Invalid email or password.",
                "danger"
            )

            return redirect(
                url_for("main.login")
            )

        if not check_password_hash(
            user.password_hash,
            password
        ):

            flash(
                "Invalid email or password.",
                "danger"
            )

            return redirect(
                url_for("main.login")
            )

        if not user.is_active:

            flash(
                "Your account is inactive.",
                "danger"
            )

            return redirect(
                url_for("main.login")
            )

        session.clear()
        session["user_id"] = user.id

        if user.role == "employee":

            return redirect(
                url_for(
                    "main.employee_dashboard"
                )
            )

        if user.role == PLATFORM_SUPER_ADMIN:
            return redirect(
                url_for("main.platform_dashboard")
            )

        return redirect(
            url_for("main.dashboard")
        )

    return render_template(
        "login.html"
    )


# ============================================================
# LOGOUT
# ============================================================

@bp.route("/logout", methods=["POST"])
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(
        url_for("main.login")
    )


# ============================================================
# EMPLOYEES
# ============================================================

@bp.route("/employees")
@employer_required
def employees():

    user = current_user()

    employees = Employee.query.filter_by(
        company_id=user.company_id
    ).order_by(
        Employee.id.desc()
    ).all()

    return render_template(
        "employees.html",
        employees=employees,
    )


# ============================================================
# ADD EMPLOYEE
# ============================================================

@bp.route(
    "/employees/new",
    methods=["GET", "POST"]
)
@employer_required
def new_employee():

    user = current_user()

    if request.method == "POST":

        employee_number = (
            request.form.get("employee_number")
            or ""
        ).strip()

        first_name = (
            request.form.get("first_name")
            or ""
        ).strip()

        last_name = (
            request.form.get("last_name")
            or ""
        ).strip()

        date_of_birth_value = (
            request.form.get("date_of_birth")
            or ""
        ).strip()

        email = (
            request.form.get("email")
            or ""
        ).strip().lower()

        job_title = (
            request.form.get("job_title")
            or ""
        ).strip()

        monthly_salary = safe_float(
            request.form.get("monthly_salary")
        )

        status = (
            request.form.get("status")
            or "Active"
        ).strip()

        if not employee_number:

            flash(
                "Employee number is required.",
                "danger"
            )

            return redirect(
                url_for("main.new_employee")
            )

        if not first_name:

            flash(
                "First name is required.",
                "danger"
            )

            return redirect(
                url_for("main.new_employee")
            )

        if not last_name:

            flash(
                "Last name is required.",
                "danger"
            )

            return redirect(
                url_for("main.new_employee")
            )

        if monthly_salary <= 0:

            flash(
                "Monthly salary must be greater than zero.",
                "danger"
            )

            return redirect(
                url_for("main.new_employee")
            )

        date_of_birth = None

        if date_of_birth_value:

            try:

                date_of_birth = datetime.strptime(
                    date_of_birth_value,
                    "%Y-%m-%d"
                ).date()

            except ValueError:

                flash(
                    "Invalid date of birth.",
                    "danger"
                )

                return redirect(
                    url_for("main.new_employee")
                )

        employee = Employee(
            company_id=user.company_id,
            employee_number=employee_number,
            first_name=first_name,
            last_name=last_name,
            date_of_birth=date_of_birth,
            email=email,
            job_title=job_title,
            monthly_salary=monthly_salary,
            status=status,
        )

        db.session.add(employee)
        db.session.commit()

        flash(
            "Employee added successfully.",
            "success"
        )

        return redirect(
            url_for("main.employees")
        )

    return render_template(
        "new_employee.html"
    )


# ============================================================
# EMPLOYEE INVITATION
# ============================================================

@bp.route(
    "/employees/<int:employee_id>/invite",
    methods=["POST"]
)
@employer_required
def invite_employee(employee_id):

    user = current_user()

    employee = Employee.query.filter_by(
        id=employee_id,
        company_id=user.company_id
    ).first_or_404()

    if employee.user_id:

        flash(
            "This employee already has an account.",
            "warning"
        )

        return redirect(
            url_for("main.employees")
        )

    token = secrets.token_urlsafe(32)

    invitation = EmployeeInvitation(
        employee_id=employee.id,
        token=token,
        expires_at=(
            datetime.utcnow()
            + timedelta(hours=48)
        ),
        used=False,
    )

    db.session.add(invitation)
    db.session.commit()

    invitation_url = url_for(
        "main.accept_invitation",
        token=token,
        _external=True
    )

    flash(
        f"Employee invitation created: {invitation_url}",
        "success"
    )

    return redirect(
        url_for("main.employees")
    )


# ============================================================
# COMPATIBILITY INVITATION ROUTE
# ============================================================

@bp.route(
    "/employees/<int:employee_id>/create-invitation",
    methods=["POST"]
)
@employer_required
def create_invitation(employee_id):

    return invite_employee(
        employee_id
    )


# ============================================================
# ACCEPT EMPLOYEE INVITATION
# ============================================================

@bp.route(
    "/invite/<token>",
    methods=["GET", "POST"]
)
def accept_invitation(token):

    invitation = EmployeeInvitation.query.filter_by(
        token=token
    ).first()

    if not invitation:
        flash("Invalid invitation.", "danger")
        return redirect(url_for("main.login"))

    if not invitation.is_valid():
        flash(
            "This invitation has expired or has already been used.",
            "danger"
        )
        return redirect(url_for("main.login"))

    employee = invitation.employee

    if not employee or employee.user_id:
        flash(
            "This invitation cannot be used. Please ask your employer for a new invitation.",
            "danger"
        )
        return redirect(url_for("main.login"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (
            request.form.get("email")
            or employee.email
            or ""
        ).strip().lower()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if not name:
            flash("Full name is required.", "danger")
            return redirect(
                url_for("main.accept_invitation", token=token)
            )

        if not email:
            flash("Email address is required.", "danger")
            return redirect(
                url_for("main.accept_invitation", token=token)
            )

        if len(email) > 200 or "@" not in email:
            flash("Please enter a valid email address.", "danger")
            return redirect(
                url_for("main.accept_invitation", token=token)
            )

        if len(password) < 8:
            flash(
                "Your password must be at least 8 characters long.",
                "danger"
            )
            return redirect(
                url_for("main.accept_invitation", token=token)
            )

        if password != confirm_password:
            flash("The passwords do not match.", "danger")
            return redirect(
                url_for("main.accept_invitation", token=token)
            )

        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            flash(
                "An account with this email already exists. Please use another email or contact your employer.",
                "danger"
            )
            return redirect(
                url_for("main.accept_invitation", token=token)
            )

        name_parts = name.split()
        first_name = name_parts[0]
        last_name = " ".join(name_parts[1:]) or first_name

        try:
            user = User(
                company_id=employee.company_id,
                name=name,
                email=email,
                password_hash=generate_password_hash(password),
                role="employee",
                is_active=True,
            )
            db.session.add(user)
            db.session.flush()

            employee.user_id = user.id
            employee.first_name = first_name
            employee.last_name = last_name
            employee.email = email
            invitation.used = True

            db.session.commit()

        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "Employee invitation account creation failed."
            )
            flash(
                "We could not create your account. Please try again or contact your employer.",
                "danger"
            )
            return redirect(
                url_for("main.accept_invitation", token=token)
            )

        session.clear()
        session["user_id"] = user.id

        flash("Employee account created successfully.", "success")
        return redirect(url_for("main.employee_dashboard"))

    return render_template(
        "accept_invitation.html",
        invitation=invitation,
        employee=employee,
    )



# ============================================================
# EMPLOYEE DASHBOARD
# ============================================================

@bp.route("/employee")
@login_required
def employee_dashboard():

    user = current_user()

    if user.role != "employee":

        return redirect(
            url_for("main.dashboard")
        )

    employee = user.employee

    if not employee:

        session.clear()

        flash(
            "No employee profile is linked to this account.",
            "danger"
        )

        return redirect(
            url_for("main.login")
        )

    return render_template(
        "employee_dashboard.html",
        employee=employee,
    )


# ============================================================
# EMPLOYEE FINANCIAL SERVICES
# ============================================================

@bp.route(
    "/employee/financial-services"
)
@login_required
def financial_services():

    user = current_user()

    if user.role != "employee":

        return redirect(
            url_for("main.dashboard")
        )

    employee = user.employee

    if not employee:

        flash(
            "No employee profile is linked to this account.",
            "danger"
        )

        return redirect(
            url_for(
                "main.employee_dashboard"
            )
        )

    application = (
        LoanApplication.query
        .filter_by(
            employee_id=employee.id
        )
        .order_by(
            LoanApplication.created_at.desc()
        )
        .first()
    )

    return render_template(
        "financial_services.html",
        employee=employee,
        application=application,
    )


# ============================================================
# EMPLOYEE LOAN APPLICATION
# ============================================================

@bp.route(
    "/employee/loan-application",
    methods=["GET", "POST"],
    endpoint="loan_application"
)
@login_required
def employee_loan_application():

    user = current_user()

    if user.role != "employee":

        return redirect(
            url_for("main.dashboard")
        )

    employee = user.employee

    if not employee:

        flash(
            "No employee profile is linked to this account.",
            "danger"
        )

        return redirect(
            url_for(
                "main.employee_dashboard"
            )
        )

    if request.method == "POST":

        consent = request.form.get(
            "application_consent"
        )

        if consent != "on":

            flash(
                "Please confirm the loan application declaration.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.loan_application"
                )
            )

        requested_amount = safe_float(
            request.form.get(
                "requested_amount"
            )
        )

        loan_purpose = (
            request.form.get(
                "loan_purpose"
            )
            or ""
        ).strip()

        repayment_term = (
            request.form.get(
                "repayment_term"
            )
            or ""
        ).strip()

        monthly_income = safe_float(
            request.form.get(
                "monthly_income"
            ),
            employee.monthly_salary or 0
        )

        monthly_expenses = safe_float(
            request.form.get(
                "monthly_expenses"
            )
        )

        if requested_amount <= 0:

            flash(
                "Please enter a valid loan amount.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.loan_application"
                )
            )

        if requested_amount > 3000:

            flash(
                "The maximum employee loan amount is R3,000.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.loan_application"
                )
            )

        if not loan_purpose:

            flash(
                "Please select the purpose of the loan.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.loan_application"
                )
            )

        if not repayment_term:

            flash(
                "Please select a repayment term.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.loan_application"
                )
            )

        if monthly_income <= 0:

            flash(
                "Please enter your monthly income.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.loan_application"
                )
            )

        if monthly_expenses < 0:

            flash(
                "Monthly expenses cannot be negative.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.loan_application"
                )
            )

        existing_application = (
            LoanApplication.query
            .filter(
                LoanApplication.employee_id == employee.id,
                LoanApplication.status.in_([
                    "Submitted",
                    "Under Review",
                    "Approved",
                    "Disbursed",
                ])
            )
            .order_by(
                LoanApplication.created_at.desc()
            )
            .first()
        )

        if existing_application:

            flash(
                "You already have an active loan application.",
                "warning"
            )

            return redirect(
                url_for(
                    "main.loan_status"
                )
            )

        reference = (
            "APL-"
            + datetime.utcnow().strftime(
                "%Y%m%d%H%M%S"
            )
            + "-"
            + secrets.token_hex(
                3
            ).upper()
        )

        application = LoanApplication(
            employee_id=employee.id,
            reference=reference,
            requested_amount=requested_amount,
            approved_amount=None,
            loan_purpose=loan_purpose,
            repayment_term=repayment_term,
            monthly_income=monthly_income,
            monthly_expenses=monthly_expenses,
            status="Submitted",
            total_repayable=None,
            total_paid=0,
            outstanding_balance=0,
        )

        db.session.add(application)
        db.session.commit()

        flash(
            "Your loan application has been submitted successfully.",
            "success"
        )

        return redirect(
            url_for(
                "main.loan_status"
            )
        )

    return render_template(
        "employee_loan_application.html",
        employee=employee,
    )


# ============================================================
# COMPATIBILITY ALIAS
# ============================================================

bp.add_url_rule(
    "/employee/loan-application",
    endpoint="employee_loan_application",
    view_func=employee_loan_application,
    methods=["GET", "POST"]
)


# ============================================================
# EMPLOYEE LOAN STATUS
# ============================================================

@bp.route(
    "/employee/loan-status",
    endpoint="loan_status"
)
@login_required
def employee_loan_status():

    user = current_user()

    if user.role != "employee":

        return redirect(
            url_for("main.dashboard")
        )

    employee = user.employee

    if not employee:

        flash(
            "No employee profile is linked to this account.",
            "danger"
        )

        return redirect(
            url_for(
                "main.employee_dashboard"
            )
        )

    application = (
        LoanApplication.query
        .filter_by(
            employee_id=employee.id
        )
        .order_by(
            LoanApplication.created_at.desc()
        )
        .first()
    )

    return render_template(
        "employee_loan_status.html",
        employee=employee,
        application=application,
    )


# ============================================================
# COMPATIBILITY ALIAS
# ============================================================

bp.add_url_rule(
    "/employee/loan-status",
    endpoint="employee_loan_status",
    view_func=employee_loan_status,
    methods=["GET"]
)


# ============================================================
# EMPLOYEE REPAYMENTS
# ============================================================

@bp.route(
    "/employee/repayments"
)
@login_required
def employee_repayments():

    user = current_user()

    if user.role != "employee":

        return redirect(
            url_for("main.dashboard")
        )

    employee = user.employee

    if not employee:

        flash(
            "No employee profile is linked to this account.",
            "danger"
        )

        return redirect(
            url_for(
                "main.employee_dashboard"
            )
        )

    application = (
        LoanApplication.query
        .filter_by(
            employee_id=employee.id
        )
        .order_by(
            LoanApplication.created_at.desc()
        )
        .first()
    )

    amount_paid = 0.0
    outstanding_balance = 0.0
    monthly_installment = 0.0

    if application:

        amount_paid = safe_float(
            application.total_paid
        )

        outstanding_balance = safe_float(
            application.outstanding_balance
        )

        if application.status == "Disbursed":

            monthly_installment = (
                calculate_loan_installment(
                    application
                )
            )

    return render_template(
        "employee_repayments.html",
        employee=employee,
        application=application,
        outstanding_balance=outstanding_balance,
        amount_paid=amount_paid,
        monthly_installment=monthly_installment,
        repayment_entries=get_employee_loan_repayment_ledger(employee.id),
    )


# ============================================================
# COMPATIBILITY ALIAS
# ============================================================

bp.add_url_rule(
    "/employee/repayments",
    endpoint="repayments",
    view_func=employee_repayments,
    methods=["GET"]
)


# ============================================================
# EMPLOYER LOAN MANAGEMENT
# ============================================================

@bp.route("/loans")
@employer_required
def loan_management():

    user = current_user()

    applications = (
        LoanApplication.query
        .join(Employee)
        .filter(
            Employee.company_id == user.company_id
        )
        .order_by(
            LoanApplication.created_at.desc()
        )
        .all()
    )

    return render_template(
        "loan_management.html",
        applications=applications,
    )


# ============================================================
# APPROVE LOAN
# ============================================================

@bp.route(
    "/loans/<int:loan_id>/approve",
    methods=["POST"]
)
@employer_required
def approve_loan(loan_id):

    user = current_user()

    application = get_company_loan_or_404(
        loan_id,
        user,
        lock_for_update=True
    )

    if application.status not in [
        "Submitted",
        "Under Review",
    ]:

        flash(
            "Only submitted loan applications can be approved.",
            "warning"
        )

        return redirect(
            url_for(
                "main.loan_management"
            )
        )

    approved_amount = safe_float(
        request.form.get(
            "approved_amount"
        ),
        application.requested_amount
    )

    if approved_amount <= 0:

        flash(
            "Approved amount must be greater than zero.",
            "danger"
        )

        return redirect(
            url_for(
                "main.loan_management"
            )
        )

    if approved_amount > safe_float(
        application.requested_amount
    ):

        flash(
            "Approved amount cannot exceed the requested amount.",
            "danger"
        )

        return redirect(
            url_for(
                "main.loan_management"
            )
        )

    approval_notes = (
        request.form.get(
            "approval_notes"
        )
        or ""
    ).strip()

    application.approved_amount = approved_amount
    application.total_repayable = approved_amount
    application.total_paid = 0.0
    application.outstanding_balance = approved_amount
    application.status = "Approved"
    application.reviewed_at = datetime.utcnow()
    application.reviewed_by = user.id
    application.approval_notes = approval_notes

    db.session.commit()

    flash(
        f"Loan {application.reference} approved for R {approved_amount:,.2f}.",
        "success"
    )

    return redirect(
        url_for(
            "main.loan_management"
        )
    )


# ============================================================
# REJECT LOAN
# ============================================================

@bp.route(
    "/loans/<int:loan_id>/reject",
    methods=["POST"]
)
@employer_required
def reject_loan(loan_id):

    user = current_user()

    application = get_company_loan_or_404(
        loan_id,
        user,
        lock_for_update=True
    )

    if application.status not in [
        "Submitted",
        "Under Review",
    ]:

        flash(
            "This loan application cannot be rejected at its current stage.",
            "warning"
        )

        return redirect(
            url_for(
                "main.loan_management"
            )
        )

    rejection_notes = (
        request.form.get(
            "approval_notes"
        )
        or request.form.get(
            "rejection_reason"
        )
        or ""
    ).strip()

    application.status = "Rejected"
    application.reviewed_at = datetime.utcnow()
    application.reviewed_by = user.id
    application.approval_notes = rejection_notes

    db.session.commit()

    flash(
        f"Loan {application.reference} has been rejected.",
        "success"
    )

    return redirect(
        url_for(
            "main.loan_management"
        )
    )


# ============================================================
# DISBURSE LOAN
# ============================================================

@bp.route(
    "/loans/<int:loan_id>/disburse",
    methods=["POST"]
)
@employer_required
def disburse_loan(loan_id):

    user = current_user()

    application = get_company_loan_or_404(
        loan_id,
        user,
        lock_for_update=True
    )

    if application.status != "Approved":

        flash(
            "Only approved loans can be disbursed.",
            "warning"
        )

        return redirect(
            url_for(
                "main.loan_management"
            )
        )

    approved_amount = safe_float(
        application.approved_amount
    )

    if approved_amount <= 0:

        flash(
            "The approved loan amount is invalid.",
            "danger"
        )

        return redirect(
            url_for(
                "main.loan_management"
            )
        )

    disbursement_reference = (
        request.form.get(
            "disbursement_reference"
        )
        or ""
    ).strip()

    if not disbursement_reference:

        disbursement_reference = (
            "APX-DISB-"
            + datetime.utcnow().strftime(
                "%Y%m%d%H%M%S"
            )
            + "-"
            + secrets.token_hex(
                2
            ).upper()
        )

    application.status = "Disbursed"
    application.disbursed_at = datetime.utcnow()
    application.disbursement_reference = (
        disbursement_reference
    )

    application.total_repayable = safe_float(
        application.total_repayable,
        approved_amount
    )

    application.total_paid = safe_float(
        application.total_paid
    )

    application.outstanding_balance = round(
        max(
            0.0,
            safe_float(
                application.total_repayable
            )
            - safe_float(
                application.total_paid
            )
        ),
        2
    )

    application.next_payment_date = (
        datetime.utcnow().date()
    )

    db.session.commit()

    flash(
        f"Loan {application.reference} has been disbursed.",
        "success"
    )

    return redirect(
        url_for(
            "main.loan_management"
        )
    )


# ============================================================
# EMPLOYEE PAYSLIPS
# ============================================================

@bp.route(
    "/employee/payslips"
)
@login_required
def my_payslips():

    user = current_user()

    if user.role != "employee":

        return redirect(
            url_for("main.dashboard")
        )

    employee = user.employee

    if not employee:

        flash(
            "No employee profile is linked to this account.",
            "danger"
        )

        return redirect(
            url_for(
                "main.employee_dashboard"
            )
        )

    payslips = Payslip.query.filter_by(
        employee_id=employee.id
    ).order_by(
        Payslip.id.desc()
    ).all()

    return render_template(
        "my_payslips.html",
        employee=employee,
        payslips=payslips,
    )


# ============================================================
# PAYROLL
# ============================================================

@bp.route(
    "/payroll",
    methods=["GET", "POST"]
)
@employer_required
def payroll():

    user = current_user()

    company = user.company

    employees = Employee.query.filter_by(
        company_id=company.id,
        status="Active"
    ).order_by(
        Employee.first_name.asc(),
        Employee.last_name.asc()
    ).all()

    if request.method == "POST":

        action = (
            request.form.get("action")
            or "draft"
        ).strip().lower()

        pay_period = (
            request.form.get("pay_period")
            or ""
        ).strip()

        pay_date_value = (
            request.form.get("pay_date")
            or ""
        ).strip()

        if not pay_period or len(pay_period) > 50:

            flash(
                "Pay period is required.",
                "danger"
            )

            return render_template(
                "create_payroll.html",
                employees=employees,
                company=company,
            )

        if not pay_date_value:

            flash(
                "Pay date is required.",
                "danger"
            )

            return render_template(
                "create_payroll.html",
                employees=employees,
                company=company,
            )

        try:

            pay_date = datetime.strptime(
                pay_date_value,
                "%Y-%m-%d"
            ).date()

        except ValueError:

            flash(
                "Invalid pay date.",
                "danger"
            )

            return render_template(
                "create_payroll.html",
                employees=employees,
                company=company,
            )

        if not employees:

            flash(
                "There are no active employees available for payroll.",
                "warning"
            )

            return render_template(
                "create_payroll.html",
                employees=employees,
                company=company,
            )

        existing_payroll = PayrollRun.query.filter_by(
            company_id=company.id,
            pay_period=pay_period
        ).first()

        if existing_payroll:

            flash(
                "A payroll run already exists for this pay period.",
                "warning"
            )

            return redirect(
                url_for(
                    "main.view_payroll",
                    payroll_id=existing_payroll.id
                )
            )

        payroll_run = PayrollRun(
            company_id=company.id,
            currency="ZAR",
            pay_period=pay_period,
            pay_date=pay_date,
            status="Draft",
            total_gross=0,
            total_deductions=0,
            total_net=0,
            total_employer_uif=0,
            total_employer_cost=0,
        )

        db.session.add(payroll_run)
        db.session.flush()

        for employee in employees:

            overtime = get_employee_payroll_value(
                employee.id,
                "overtime"
            )

            bonus = get_employee_payroll_value(
                employee.id,
                "bonus"
            )

            commission = get_employee_payroll_value(
                employee.id,
                "commission"
            )

            other_earnings = get_employee_payroll_value(
                employee.id,
                "other_earnings"
            )

            other_deductions = get_employee_payroll_value(
                employee.id,
                "other_deductions"
            )

            payroll_input = PayrollInput(
                payroll_run_id=payroll_run.id,
                employee_id=employee.id,
                basic_salary=safe_float(
                    employee.monthly_salary
                ),
                overtime=overtime,
                bonus=bonus,
                commission=commission,
                other_earnings=other_earnings,
                other_deductions=other_deductions,
                loan_repayment=0,
            )

            db.session.add(payroll_input)

        db.session.commit()

        calculate_payroll_run_totals(
            payroll_run
        )

        db.session.commit()

        if action == "review":

            return redirect(
                url_for(
                    "main.review_payroll",
                    payroll_id=payroll_run.id
                )
            )

        flash(
            "Payroll draft created successfully.",
            "success"
        )

        return redirect(
            url_for(
                "main.view_payroll",
                payroll_id=payroll_run.id
            )
        )

    return render_template(
        "create_payroll.html",
        employees=employees,
        company=company,
    )


# ============================================================
# COMPATIBILITY CREATE PAYROLL ROUTE
# ============================================================

@bp.route(
    "/payroll/create",
    methods=["GET", "POST"]
)
@employer_required
def create_payroll():

    return payroll()


# ============================================================
# REVIEW PAYROLL
# ============================================================

@bp.route(
    "/payroll/<int:payroll_id>/review",
    methods=["GET", "POST"]
)
@employer_required
def review_payroll(payroll_id):

    user = current_user()

    payroll_run = PayrollRun.query.filter_by(
        id=payroll_id,
        company_id=user.company_id
    ).first_or_404()

    if payroll_run.status == "Completed":

        flash(
            "This payroll has already been completed and is locked.",
            "warning"
        )

        return redirect(
            url_for(
                "main.view_payroll",
                payroll_id=payroll_run.id
            )
        )

    if payroll_run.status == "Approved":

        flash(
            "This payroll has already been approved.",
            "warning"
        )

        return redirect(
            url_for(
                "main.view_payroll",
                payroll_id=payroll_run.id
            )
        )

    payroll_inputs = PayrollInput.query.filter_by(
        payroll_run_id=payroll_run.id
    ).all()

    if not payroll_inputs:

        flash(
            "This payroll has no employee inputs.",
            "danger"
        )

        return redirect(
            url_for("main.payroll")
        )

    if request.method == "POST":

        for payroll_input in payroll_inputs:

            employee_id = payroll_input.employee_id

            payroll_input.overtime = (
                get_employee_payroll_value(
                    employee_id,
                    "overtime",
                    payroll_input.overtime
                )
            )

            payroll_input.bonus = (
                get_employee_payroll_value(
                    employee_id,
                    "bonus",
                    payroll_input.bonus
                )
            )

            payroll_input.commission = (
                get_employee_payroll_value(
                    employee_id,
                    "commission",
                    payroll_input.commission
                )
            )

            payroll_input.other_earnings = (
                get_employee_payroll_value(
                    employee_id,
                    "other_earnings",
                    payroll_input.other_earnings
                )
            )

            payroll_input.other_deductions = (
                get_employee_payroll_value(
                    employee_id,
                    "other_deductions",
                    payroll_input.other_deductions
                )
            )

        payroll_run.status = "Review"

        calculate_payroll_run_totals(
            payroll_run
        )

        db.session.commit()

        flash(
            "Payroll calculated and submitted for review.",
            "success"
        )

        return redirect(
            url_for(
                "main.view_payroll",
                payroll_id=payroll_run.id
            )
        )

    results = calculate_payroll_run_totals(
        payroll_run
    )

    return render_template(
        "review_payroll.html",
        payroll_run=payroll_run,
        results=results,
        total_gross=payroll_run.total_gross or 0,
        total_deductions=payroll_run.total_deductions or 0,
        total_net=payroll_run.total_net or 0,
        total_employer_uif=(
            payroll_run.total_employer_uif or 0
        ),
        total_employer_cost=(
            payroll_run.total_employer_cost or 0
        ),
    )


# ============================================================
# SUBMIT PAYROLL FOR REVIEW
# ============================================================

@bp.route(
    "/payroll/<int:payroll_id>/submit-review",
    methods=["POST"]
)
@employer_required
def submit_payroll_for_review(payroll_id):

    user = current_user()

    payroll_run = PayrollRun.query.filter_by(
        id=payroll_id,
        company_id=user.company_id
    ).first_or_404()

    if payroll_run.status not in [
        "Draft",
        "Review",
    ]:

        flash(
            "Only draft or review payroll can be submitted for review.",
            "warning"
        )

        return redirect(
            url_for(
                "main.view_payroll",
                payroll_id=payroll_run.id
            )
        )

    payroll_inputs = PayrollInput.query.filter_by(
        payroll_run_id=payroll_run.id
    ).all()

    if not payroll_inputs:

        flash(
            "This payroll has no employee inputs.",
            "danger"
        )

        return redirect(
            url_for(
                "main.view_payroll",
                payroll_id=payroll_run.id
            )
        )

    calculate_payroll_run_totals(
        payroll_run
    )

    payroll_run.status = "Review"

    db.session.commit()

    flash(
        "Payroll has been submitted for review.",
        "success"
    )

    return redirect(
        url_for(
            "main.view_payroll",
            payroll_id=payroll_run.id
        )
    )


# ============================================================
# APPROVE PAYROLL
# ============================================================

@bp.route(
    "/payroll/<int:payroll_id>/approve",
    methods=["POST"]
)
@employer_required
def approve_payroll(payroll_id):

    user = current_user()

    payroll_run = PayrollRun.query.filter_by(
        id=payroll_id,
        company_id=user.company_id
    ).first_or_404()

    if payroll_run.status != "Review":

        flash(
            "Only payroll in Review status can be approved.",
            "warning"
        )

        return redirect(
            url_for(
                "main.view_payroll",
                payroll_id=payroll_run.id
            )
        )

    payroll_inputs = PayrollInput.query.filter_by(
        payroll_run_id=payroll_run.id
    ).all()

    if not payroll_inputs:

        flash(
            "This payroll has no employee inputs.",
            "danger"
        )

        return redirect(
            url_for(
                "main.view_payroll",
                payroll_id=payroll_run.id
            )
        )

    calculate_payroll_run_totals(
        payroll_run
    )

    payroll_run.status = "Approved"

    db.session.commit()

    flash(
        "Payroll approved successfully.",
        "success"
    )

    return redirect(
        url_for(
            "main.view_payroll",
            payroll_id=payroll_run.id
        )
    )


# ============================================================
# COMPLETE PAYROLL
# ============================================================

@bp.route(
    "/payroll/<int:payroll_id>/complete",
    methods=["POST"]
)
@employer_required
def complete_payroll(payroll_id):
    user = current_user()

    payroll_run = (
        PayrollRun.query
        .filter_by(
            id=payroll_id,
            company_id=user.company_id,
        )
        .with_for_update()
        .populate_existing()
        .first_or_404()
    )

    if payroll_run.status == "Completed":
        flash("This payroll has already been completed.", "warning")
        return redirect(
            url_for("main.view_payroll", payroll_id=payroll_run.id)
        )

    if payroll_run.status != "Approved":
        flash("Only approved payroll can be completed.", "warning")
        return redirect(
            url_for("main.view_payroll", payroll_id=payroll_run.id)
        )

    payroll_inputs = PayrollInput.query.filter_by(
        payroll_run_id=payroll_run.id
    ).all()

    if not payroll_inputs:
        flash("This payroll has no employee inputs.", "danger")
        return redirect(
            url_for("main.view_payroll", payroll_id=payroll_run.id)
        )

    # Prevent duplicate payslips by rejecting duplicate employee inputs.
    employee_ids = [
        payroll_input.employee_id
        for payroll_input in payroll_inputs
    ]

    if len(employee_ids) != len(set(employee_ids)):
        flash(
            "This payroll contains duplicate inputs for one or more "
            "employees. No changes were made. Review and remove the "
            "duplicate inputs before completing payroll.",
            "danger",
        )
        return redirect(
            url_for("main.view_payroll", payroll_id=payroll_run.id)
        )

    # Reject payroll inputs for employees outside this company.
    employees_by_id = {
        employee.id: employee
        for employee in Employee.query.filter(
            Employee.id.in_(employee_ids)
        ).all()
    }

    if any(
        employee_id not in employees_by_id
        or employees_by_id[employee_id].company_id != payroll_run.company_id
        for employee_id in employee_ids
    ):
        flash(
            "This payroll contains an employee who does not belong to "
            "this company. No changes were made.",
            "danger",
        )
        return redirect(
            url_for("main.view_payroll", payroll_id=payroll_run.id)
        )

    try:
        # Preserve existing payslips because ledger rows may reference them.
        if Payslip.query.filter_by(
            payroll_run_id=payroll_run.id
        ).count():
            flash(
                "This payroll already has payslips. No changes were made. "
                "Review the existing records before retrying.",
                "warning",
            )
            return redirect(
                url_for("main.view_payroll", payroll_id=payroll_run.id)
            )

        company = Company.query.filter_by(
            id=payroll_run.company_id
        ).first()

        if company is None:
            raise ValueError("Payroll company could not be found.")

        accounting_enabled = has_feature(company, "accounting")

        if accounting_enabled:
            if payroll_run.pay_date is None:
                raise ValueError(
                    "Set the payroll pay date before completing "
                    "accounting-enabled payroll."
                )

            currency = payroll_run.currency
            if (
                not isinstance(currency, str)
                or len(currency.strip()) != 3
                or not currency.strip().isascii()
                or not currency.strip().isalpha()
            ):
                raise ValueError(
                    "Set a valid three-letter payroll currency "
                    "before completing accounting-enabled payroll."
                )

        results = calculate_payroll_run_totals(
            payroll_run,
            lock_loans=True,
        )

        if accounting_enabled and any(
            item.get("loan_application") is not None
            and item["loan_application"].status == "Disbursed"
            and round(
                min(
                    round(
                        max(0.0, safe_float(item.get("loan_repayment", 0))),
                        2,
                    ),
                    max(
                        0.0,
                        safe_float(
                            item["loan_application"].outstanding_balance
                        ),
                    ),
                ),
                2,
            ) > 0
            for item in results
        ):
            raise ValueError(
                "Accounting-enabled payroll cannot include loan "
                "repayments until loan disbursement accounting "
                "is implemented."
            )

        for calculated in results:
            employee = calculated["employee"]
            payroll_input = calculated["payroll_input"]
            result = calculated["result"]
            loan_application = calculated.get("loan_application")

            loan_repayment = round(
                max(0.0, safe_float(calculated.get("loan_repayment", 0))),
                2,
            )

            if loan_application and loan_application.status == "Disbursed":
                loan_repayment = round(
                    min(
                        loan_repayment,
                        max(0.0, safe_float(loan_application.outstanding_balance)),
                    ),
                    2,
                )
            else:
                loan_application = None
                loan_repayment = 0.0

            payroll_input.loan_repayment = loan_repayment

            payslip = Payslip(
                employee_id=employee.id,
                payroll_run_id=payroll_run.id,
                pay_period=payroll_run.pay_period,
                pay_date=payroll_run.pay_date,
                basic_salary=safe_float(
                    result.get("basic_salary", payroll_input.basic_salary)
                ),
                overtime=safe_float(result.get("overtime", payroll_input.overtime)),
                bonus=safe_float(result.get("bonus", payroll_input.bonus)),
                commission=safe_float(
                    result.get("commission", payroll_input.commission)
                ),
                other_earnings=safe_float(
                    result.get("other_earnings", payroll_input.other_earnings)
                ),
                gross_pay=calculated["gross_pay"],
                tax_deductions=calculated["paye"],
                uif=calculated["uif"],
                other_deductions=calculated["other_deductions"],
                loan_repayment=loan_repayment,
                total_deductions=calculated["total_deductions"],
                net_pay=calculated["net_pay"],
                employer_uif=calculated["employer_uif"],
                employer_cost=calculated["employer_cost"],
            )
            db.session.add(payslip)
            db.session.flush()

            if loan_application and loan_repayment > 0:
                ledger_entry, ledger_created = create_loan_repayment_ledger_entry(
                    loan_application=loan_application,
                    employee=employee,
                    payroll_run=payroll_run,
                    payslip=payslip,
                    amount=loan_repayment,
                )

                # If an entry already exists, roll back this whole attempt.
                if not ledger_created:
                    raise ValueError(
                        "A repayment ledger entry already exists for this payroll."
                    )

                recorded_amount = round(
                    min(
                        loan_repayment,
                        max(0.0, safe_float(loan_application.outstanding_balance)),
                    ),
                    2,
                )
                total_repayable = max(
                    0.0, safe_float(loan_application.total_repayable)
                )
                new_total_paid = round(
                    min(
                        total_repayable,
                        max(0.0, safe_float(loan_application.total_paid))
                        + recorded_amount,
                    ),
                    2,
                )
                new_outstanding = round(
                    max(0.0, total_repayable - new_total_paid), 2
                )

                loan_application.total_paid = new_total_paid
                loan_application.outstanding_balance = new_outstanding

                if new_outstanding <= 0.01:
                    loan_application.total_paid = total_repayable
                    loan_application.outstanding_balance = 0.0
                    loan_application.status = "Repaid"
                    loan_application.next_payment_date = None
                else:
                    loan_application.status = "Disbursed"
                    loan_application.next_payment_date = add_months(
                        payroll_run.pay_date or datetime.utcnow().date(), 1
                    )

        if accounting_enabled:
            create_payroll_journal(
                payroll_run=payroll_run,
                actor_id=user.id,
            )

        payroll_run.status = "Completed"
        db.session.commit()

    except Exception:
        db.session.rollback()
        flash(
            "Payroll completion failed. This attempt was rolled back. "
            "Review the payroll and ledger records before retrying.",
            "danger",
        )
        return redirect(
            url_for("main.view_payroll", payroll_id=payroll_run.id)
        )

    flash(
        "Payroll completed successfully. Loan repayments have been recorded.",
        "success",
    )
    return redirect(
        url_for("main.view_payroll", payroll_id=payroll_run.id)
    )


# ============================================================
# PAYROLL HISTORY
# ============================================================

@bp.route(
    "/payroll/history"
)
@employer_required
def payroll_history():

    user = current_user()

    payroll_runs = PayrollRun.query.filter_by(
        company_id=user.company_id
    ).order_by(
        PayrollRun.id.desc()
    ).all()

    return render_template(
        "payroll_history.html",
        payroll_runs=payroll_runs,
    )


# ============================================================
# VIEW PAYROLL RUN
# ============================================================

@bp.route(
    "/payroll/<int:payroll_id>",
    endpoint="view_payroll"
)
@employer_required
def view_payroll(payroll_id):

    user = current_user()

    payroll_run = PayrollRun.query.filter_by(
        id=payroll_id,
        company_id=user.company_id
    ).first_or_404()

    payslips = Payslip.query.filter_by(
        payroll_run_id=payroll_run.id
    ).all()

    payroll_inputs = PayrollInput.query.filter_by(
        payroll_run_id=payroll_run.id
    ).all()

    results = []

    for payroll_input in payroll_inputs:

        results.append(
            calculate_payroll_input(
                payroll_input
            )
        )

    return render_template(
        "payroll_run.html",
        payroll_run=payroll_run,
        payslips=payslips,
        payroll_inputs=payroll_inputs,
        results=results,
    )


# ============================================================
# VIEW PAYSLIP
# ============================================================

@bp.route(
    "/payroll/payslip/<int:payslip_id>"
)
@login_required
def view_payslip(payslip_id):

    user = current_user()

    payslip = Payslip.query.get_or_404(
        payslip_id
    )

    employee = payslip.employee

    if not employee:

        flash(
            "Employee record not found.",
            "danger"
        )

        if user.role == "employee":

            return redirect(
                url_for(
                    "main.employee_dashboard"
                )
            )

        return redirect(
            url_for(
                "main.dashboard"
            )
        )

    if user.role == "employee":

        if employee.user_id != user.id:

            flash(
                "You are not authorised to view this payslip.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.employee_dashboard"
                )
            )

    else:

        if employee.company_id != user.company_id:

            flash(
                "You are not authorised to view this payslip.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.dashboard"
                )
            )

    company = Company.query.get(
        employee.company_id
    )

    return render_template(
        "payslip.html",
        payslip=payslip,
        employee=employee,
        company=company,
    )


# ============================================================
# DOWNLOAD PAYSLIP PDF
# ============================================================

@bp.route(
    "/payroll/payslip/<int:payslip_id>/pdf"
)
@login_required
def download_payslip_pdf(payslip_id):

    user = current_user()

    payslip = Payslip.query.get_or_404(
        payslip_id
    )

    employee = payslip.employee

    if not employee:

        flash(
            "Employee record not found.",
            "danger"
        )

        return redirect(
            url_for("main.dashboard")
        )

    if user.role == "employee":

        if employee.user_id != user.id:

            flash(
                "You are not authorised to download this payslip.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.employee_dashboard"
                )
            )

    else:

        if employee.company_id != user.company_id:

            flash(
                "You are not authorised to download this payslip.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.dashboard"
                )
            )

    buffer = BytesIO()

    pdf = canvas.Canvas(
        buffer,
        pagesize=A4
    )

    width, height = A4

    y = height - 50

    pdf.setFont(
        "Helvetica-Bold",
        18
    )

    pdf.drawString(
        50,
        y,
        "Appex Payroll Payslip"
    )

    y -= 40

    pdf.setFont(
        "Helvetica",
        11
    )

    pdf.drawString(
        50,
        y,
        "Employee:"
    )

    pdf.drawString(
        150,
        y,
        f"{employee.first_name} {employee.last_name}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        "Employee Number:"
    )

    pdf.drawString(
        150,
        y,
        str(
            employee.employee_number
            or "-"
        )
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        "Pay Period:"
    )

    pdf.drawString(
        150,
        y,
        str(
            payslip.pay_period
            or "-"
        )
    )

    y -= 40

    pdf.setFont(
        "Helvetica-Bold",
        12
    )

    pdf.drawString(
        50,
        y,
        "Earnings"
    )

    y -= 25

    pdf.setFont(
        "Helvetica",
        11
    )

    pdf.drawString(
        50,
        y,
        "Basic Salary:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.basic_salary):,.2f}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        "Overtime:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.overtime):,.2f}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        "Bonus:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.bonus):,.2f}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        "Commission:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.commission):,.2f}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        "Other Earnings:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.other_earnings):,.2f}"
    )

    y -= 30

    pdf.setFont(
        "Helvetica-Bold",
        12
    )

    pdf.drawString(
        50,
        y,
        "Gross Pay:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.gross_pay):,.2f}"
    )

    y -= 40

    pdf.drawString(
        50,
        y,
        "Deductions"
    )

    y -= 25

    pdf.setFont(
        "Helvetica",
        11
    )

    pdf.drawString(
        50,
        y,
        "PAYE / Tax:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.tax_deductions):,.2f}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        "Employee UIF:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.uif):,.2f}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        "Loan Repayment:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.loan_repayment):,.2f}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        "Other Deductions:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.other_deductions):,.2f}"
    )

    y -= 30

    pdf.setFont(
        "Helvetica-Bold",
        12
    )

    pdf.drawString(
        50,
        y,
        "Total Deductions:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.total_deductions):,.2f}"
    )

    y -= 35

    pdf.setFont(
        "Helvetica-Bold",
        14
    )

    pdf.drawString(
        50,
        y,
        "NET PAY:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.net_pay):,.2f}"
    )

    y -= 35

    pdf.setFont(
        "Helvetica",
        10
    )

    pdf.drawString(
        50,
        y,
        "Employer UIF:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.employer_uif):,.2f}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        "Employer Cost:"
    )

    pdf.drawRightString(
        500,
        y,
        f"R {safe_float(payslip.employer_cost):,.2f}"
    )

    y -= 40

    pdf.setFont(
        "Helvetica",
        9
    )

    pdf.drawString(
        50,
        y,
        "Generated by Appex Payroll"
    )

    pdf.save()

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=(
            f"payslip-{employee.employee_number or employee.id}.pdf"
        ),
        mimetype="application/pdf",
    )


# ============================================================
# DEEL LOCAL PAYROLL INTEGRATION
# ============================================================

@bp.route("/integration")
@employer_required
def integration():

    user = current_user()
    company = user.company

    if company is None:
        abort(403)

    integrations = list_company_integrations(company.id)
    providers = (
        IntegrationProvider.query
        .filter_by(is_enabled=True)
        .order_by(IntegrationProvider.display_name.asc())
        .all()
    )

    return render_template(
        "integration.html",
        company=company,
        integrations=integrations,
        providers=providers,
    )


# ============================================================
# PAYROLL CALCULATOR TEST
# ============================================================

@bp.route(
    "/payroll-calculator-test",
    methods=["GET", "POST"]
)
@login_required
def payroll_calculator_test():

    result = None

    if request.method == "POST":

        salary = safe_float(
            request.form.get("salary")
        )

        try:

            result = calculate_payroll(
                salary
            )

        except TypeError:

            result = {
                "basic_salary": salary,
                "gross_pay": salary,
                "tax_deductions": 0,
                "paye": 0,
                "uif": 0,
                "other_deductions": 0,
                "total_deductions": 0,
                "net_pay": salary,
                "employer_uif": 0,
                "employer_cost": salary,
            }

    return render_template(
        "payroll_calculator_test.html",
        result=result,
    )


# ============================================================
# CLIENT ACQUISITION
# ============================================================

@bp.route("/leads")
@employer_required
def leads():

    user = current_user()

    # Sales leads are assigned to the user who created/owns them.
    leads = (
        SalesLead.query
        .filter(
            SalesLead.assigned_to == user.id
        )
        .order_by(
            SalesLead.created_at.desc()
        )
        .all()
    )

    total_leads = len(leads)

    new_leads = len([
        lead for lead in leads
        if lead.status == "New Lead"
    ])

    contacted_leads = len([
        lead for lead in leads
        if lead.status == "Contacted"
    ])

    demo_leads = len([
        lead for lead in leads
        if lead.status == "Demo"
    ])

    trial_leads = len([
        lead for lead in leads
        if lead.status == "Trial"
    ])

    converted_leads = len([
        lead for lead in leads
        if lead.status == "Converted"
    ])

    return render_template(
        "leads.html",
        leads=leads,
        total_leads=total_leads,
        new_leads=new_leads,
        contacted_leads=contacted_leads,
        demo_leads=demo_leads,
        trial_leads=trial_leads,
        converted_leads=converted_leads,
    )


# ============================================================
# NEW SALES LEAD
# ============================================================

@bp.route(
    "/leads/new",
    methods=["GET", "POST"]
)
@employer_required
def new_lead():

    user = current_user()

    if request.method == "POST":

        company_name = (
            request.form.get("company_name")
            or ""
        ).strip()

        registration_number = (
            request.form.get("registration_number")
            or ""
        ).strip()

        contact_person = (
            request.form.get("contact_person")
            or ""
        ).strip()

        email = (
            request.form.get("email")
            or ""
        ).strip().lower()

        phone = (
            request.form.get("phone")
            or ""
        ).strip()

        number_of_employees = request.form.get(
            "number_of_employees"
        )

        source = (
            request.form.get("source")
            or "Direct"
        ).strip()

        notes = (
            request.form.get("notes")
            or ""
        ).strip()

        try:

            number_of_employees = int(
                number_of_employees or 0
            )

        except ValueError:

            number_of_employees = 0

        if number_of_employees < 0:
            number_of_employees = 0

        if not company_name:

            flash(
                "Company name is required.",
                "danger"
            )

            return redirect(
                url_for("main.new_lead")
            )

        if not contact_person:

            flash(
                "Contact person is required.",
                "danger"
            )

            return redirect(
                url_for("main.new_lead")
            )

        if not email:

            flash(
                "Email address is required.",
                "danger"
            )

            return redirect(
                url_for("main.new_lead")
            )

        lead = SalesLead(
            company_name=company_name,
            registration_number=registration_number,
            contact_person=contact_person,
            email=email,
            phone=phone,
            number_of_employees=number_of_employees,
            status="New Lead",
            source=source,
            notes=notes,
            assigned_to=user.id,
        )

        db.session.add(lead)
        db.session.commit()

        flash(
            "New client lead added successfully.",
            "success"
        )

        return redirect(
            url_for("main.leads")
        )

    return render_template(
        "new_lead.html"
    )


# ============================================================
# UPDATE LEAD STATUS
# ============================================================

@bp.route(
    "/leads/<int:lead_id>/status",
    methods=["POST"]
)
@employer_required
def update_lead_status(lead_id):

    user = current_user()

    lead = SalesLead.query.filter_by(
        id=lead_id,
        assigned_to=user.id
    ).first_or_404()

    status = (
        request.form.get("status")
        or ""
    ).strip()

    allowed_statuses = [
        "New Lead",
        "Contacted",
        "Demo",
        "Trial",
        "Registered",
        "Active Client",
        "Converted",
        "Lost",
    ]

    if status not in allowed_statuses:

        flash(
            "Invalid lead status.",
            "danger"
        )

        return redirect(
            url_for("main.leads")
        )

    lead.status = status

    db.session.commit()

    flash(
        f"Lead status updated to {status}.",
        "success"
    )

    return redirect(
        url_for("main.leads")
    )


# ============================================================
# CLIENT REFERRALS
# ============================================================

@bp.route("/referrals")
@employer_required
def referrals():

    user = current_user()

    company = user.company

    ensure_company_referral_code(company)

    referrals = (
        ClientReferral.query
        .filter_by(
            referrer_company_id=company.id
        )
        .order_by(
            ClientReferral.created_at.desc()
        )
        .all()
    )

    return render_template(
        "referrals.html",
        company=company,
        referrals=referrals,
    )


# ============================================================
# NEW REFERRAL
# ============================================================

@bp.route(
    "/referrals/new",
    methods=["GET", "POST"]
)
@employer_required
def new_referral():

    user = current_user()

    company = user.company

    ensure_company_referral_code(company)

    if request.method == "POST":

        referred_company_name = (
            request.form.get(
                "referred_company_name"
            )
            or ""
        ).strip()

        referred_contact_person = (
            request.form.get(
                "referred_contact_person"
            )
            or ""
        ).strip()

        referred_email = (
            request.form.get(
                "referred_email"
            )
            or ""
        ).strip().lower()

        referred_phone = (
            request.form.get(
                "referred_phone"
            )
            or ""
        ).strip()

        if not referred_company_name:

            flash(
                "Referred company name is required.",
                "danger"
            )

            return redirect(
                url_for("main.new_referral")
            )

        if not referred_contact_person:

            flash(
                "Contact person is required.",
                "danger"
            )

            return redirect(
                url_for("main.new_referral")
            )

        if not referred_email:

            flash(
                "Email address is required.",
                "danger"
            )

            return redirect(
                url_for("main.new_referral")
            )

        referral = ClientReferral(
            referrer_company_id=company.id,
            referred_company_name=referred_company_name,
            referred_contact_person=referred_contact_person,
            referred_email=referred_email,
            referred_phone=referred_phone,
            status="Submitted",
        )

        db.session.add(referral)
        db.session.commit()

        flash(
            "Client referral submitted successfully.",
            "success"
        )

        return redirect(
            url_for("main.referrals")
        )

    return render_template(
        "new_referral.html",
        company=company,
    )


# ============================================================
# CLIENT ONBOARDING
# ============================================================

@bp.route(
    "/client-onboarding",
    methods=["GET", "POST"]
)
@employer_required
def client_onboarding():

    user = current_user()

    company = user.company

    if request.method == "POST":

        company.name = (
            request.form.get("company_name")
            or company.name
        ).strip()

        company.registration_number = (
            request.form.get(
                "registration_number"
            )
            or company.registration_number
            or ""
        ).strip()

        company.contact_person = (
            request.form.get(
                "contact_person"
            )
            or company.contact_person
            or ""
        ).strip()

        company.contact_phone = (
            request.form.get(
                "contact_phone"
            )
            or company.contact_phone
            or ""
        ).strip()

        company.contact_email = (
            request.form.get(
                "contact_email"
            )
            or company.contact_email
            or ""
        ).strip().lower()

        company.onboarding_completed = True

        if company.client_status in [
            None,
            "",
            "Prospect",
        ]:

            company.client_status = "Trial"

        if not company.subscription_status:

            company.subscription_status = "Trial"

        if not company.subscription_plan:

            company.subscription_plan = "Free Trial"

        ensure_company_referral_code(company)

        db.session.commit()

        flash(
            "Company onboarding has been completed.",
            "success"
        )

        return redirect(
            url_for("main.dashboard")
        )

    ensure_company_referral_code(company)

    return render_template(
        "client_onboarding.html",
        company=company,
    )


# ============================================================
# CLIENT ACQUISITION DASHBOARD
# ============================================================

@bp.route(
    "/client-acquisition"
)
@employer_required
def client_acquisition():

    user = current_user()

    company = user.company

    ensure_company_referral_code(company)

    leads = (
        SalesLead.query
        .filter(
            SalesLead.assigned_to == user.id
        )
        .order_by(
            SalesLead.created_at.desc()
        )
        .all()
    )

    referrals = (
        ClientReferral.query
        .filter_by(
            referrer_company_id=company.id
        )
        .order_by(
            ClientReferral.created_at.desc()
        )
        .all()
    )

    lead_counts = {
        "New Lead": 0,
        "Contacted": 0,
        "Demo": 0,
        "Trial": 0,
        "Registered": 0,
        "Active Client": 0,
        "Converted": 0,
        "Lost": 0,
    }

    for lead in leads:

        if lead.status in lead_counts:

            lead_counts[
                lead.status
            ] += 1

    return render_template(
        "client_acquisition.html",
        company=company,
        leads=leads,
        referrals=referrals,
        lead_counts=lead_counts,
    )

# PHASE 7.5 PLATFORM COMPANY DIRECTORY
# Read-only platform administration views.

@bp.route("/platform/companies")
@platform_super_admin_required
def platform_companies():
    search_term = request.args.get("q", "").strip()
    query = Company.query

    if search_term:
        escaped = (
            search_term
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        query = query.filter(
            or_(
                Company.name.ilike(pattern, escape="\\"),
                Company.registration_number.ilike(pattern, escape="\\"),
                Company.contact_email.ilike(pattern, escape="\\"),
                Company.referral_code.ilike(pattern, escape="\\"),
            )
        )

    companies = (
        query
        .order_by(Company.name.asc(), Company.id.asc())
        .limit(100)
        .all()
    )

    return render_template(
        "platform_companies.html",
        companies=companies,
        search_term=search_term,
        result_limit=100,
    )


@bp.route("/platform/companies/<int:company_id>")
@platform_super_admin_required
def platform_company_detail(company_id):
    company = Company.query.get_or_404(company_id)

    administrator_roles = ("company_admin", "employer", "admin")
    administrators = (
        User.query
        .filter(
            User.company_id == company.id,
            User.role.in_(administrator_roles),
        )
        .order_by(User.name.asc(), User.id.asc())
        .all()
    )

    employee_count = Employee.query.filter_by(
        company_id=company.id
    ).count()

    active_employee_count = Employee.query.filter_by(
        company_id=company.id,
        status="Active",
    ).count()

    payroll_run_count = PayrollRun.query.filter_by(
        company_id=company.id
    ).count()

    invoice_count = SubscriptionInvoice.query.filter_by(
        company_id=company.id
    ).count()

    subscriptions = (
        CompanySubscription.query
        .filter_by(company_id=company.id)
        .order_by(
            CompanySubscription.created_at.desc(),
            CompanySubscription.id.desc(),
        )
        .all()
    )

    return render_template(
        "platform_company_detail.html",
        company=company,
        administrators=administrators,
        employee_count=employee_count,
        active_employee_count=active_employee_count,
        payroll_run_count=payroll_run_count,
        invoice_count=invoice_count,
        subscriptions=subscriptions,
    )


# ============================================================
# PHASE 7.5 — AUDITED PLATFORM COMPANY CONTROLS
# ============================================================

@bp.route(
    "/platform/companies/<int:company_id>/administrators/<int:admin_user_id>/status",
    methods=["POST"],
)
@platform_super_admin_required
def platform_company_update_administrator_status(
    company_id,
    admin_user_id,
):
    # Lock the company first so concurrent administrator changes
    # for this company are serialized on databases supporting row locks.
    company = (
        Company.query
        .filter_by(id=company_id)
        .with_for_update()
        .first_or_404()
    )

    administrator_roles = ("company_admin", "employer", "admin")

    # Only company administrator accounts are addressable here.
    # Employee and platform-super-admin accounts resolve to 404.
    administrator = (
        User.query
        .filter(
            User.id == admin_user_id,
            User.company_id == company.id,
            User.role.in_(administrator_roles),
        )
        .with_for_update()
        .first_or_404()
    )

    requested_status = request.form.get("account_status", "").strip()
    reason = request.form.get("reason", "")

    if requested_status not in {"active", "inactive"}:
        flash("Choose a valid administrator account status.", "warning")
        return redirect(
            url_for("main.platform_company_detail", company_id=company.id)
        )

    target_active = requested_status == "active"
    previous_active = bool(administrator.is_active)

    if previous_active == target_active:
        flash("The administrator already has that account status.", "info")
        return redirect(
            url_for("main.platform_company_detail", company_id=company.id)
        )

    # Never allow this control to remove the company's last active
    # administrator. Count all three supported administrator roles.
    if previous_active and not target_active:
        other_active_administrators = (
            User.query
            .filter(
                User.company_id == company.id,
                User.role.in_(administrator_roles),
                User.is_active.is_(True),
                User.id != administrator.id,
            )
            .count()
        )

        if other_active_administrators == 0:
            flash(
                "This account is the company's last active administrator. "
                "Activate another administrator before deactivating it.",
                "warning",
            )
            return redirect(
                url_for("main.platform_company_detail", company_id=company.id)
            )

    try:
        administrator.is_active = target_active

        record_platform_audit(
            actor=current_user(),
            action=(
                "company_admin.account_activated"
                if target_active
                else "company_admin.account_deactivated"
            ),
            target_type="company_admin_user",
            target_id=administrator.id,
            company_id=company.id,
            reason=reason,
            before_data={
                "is_active": previous_active,
                "role": administrator.role,
            },
            after_data={
                "is_active": target_active,
                "role": administrator.role,
            },
        )

        # Account change and audit event commit together.
        db.session.commit()

        display_status = "activated" if target_active else "deactivated"
        flash(
            f"Company administrator account {display_status}.",
            "success",
        )

    except PlatformAuditError as exc:
        db.session.rollback()
        flash(str(exc), "warning")

    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Platform company administrator status update failed"
        )
        flash(
            "The administrator account could not be updated. "
            "No change was saved.",
            "danger",
        )

    return redirect(
        url_for("main.platform_company_detail", company_id=company.id)
    )



@bp.route(
    "/platform/companies/<int:company_id>/status",
    methods=["POST"],
)
@platform_super_admin_required
def platform_company_update_status(company_id):
    target_status = request.form.get("client_status", "").strip()
    reason = request.form.get("reason", "")

    if target_status not in {"Active", "Suspended"}:
        flash("Choose a valid company operational status.", "warning")
        return redirect(
            url_for("main.platform_company_detail", company_id=company_id)
        )

    company = (
        Company.query
        .filter_by(id=company_id)
        .with_for_update()
        .first_or_404()
    )

    try:
        previous_status = company.client_status

        if previous_status == target_status:
            flash("The company already has that operational status.", "info")
            return redirect(
                url_for("main.platform_company_detail", company_id=company_id)
            )

        company.client_status = target_status

        record_platform_audit(
            actor=current_user(),
            action="company.status_changed",
            target_type="company",
            target_id=company.id,
            company_id=company.id,
            reason=reason,
            before_data={"client_status": previous_status},
            after_data={"client_status": target_status},
        )

        db.session.commit()
        flash(
            f"Company operational status changed to {target_status}.",
            "success",
        )

    except PlatformAuditError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Platform company status update failed"
        )
        flash(
            "The company status could not be updated. No change was saved.",
            "danger",
        )

    return redirect(
        url_for("main.platform_company_detail", company_id=company_id)
    )


@bp.route(
    "/platform/companies/<int:company_id>/onboarding",
    methods=["POST"],
)
@platform_super_admin_required
def platform_company_update_onboarding(company_id):
    target_value = request.form.get("onboarding_status", "").strip()
    reason = request.form.get("reason", "")

    if target_value not in {"complete", "incomplete"}:
        flash("Choose a valid onboarding status.", "warning")
        return redirect(
            url_for("main.platform_company_detail", company_id=company_id)
        )

    target_completed = target_value == "complete"

    company = (
        Company.query
        .filter_by(id=company_id)
        .with_for_update()
        .first_or_404()
    )

    try:
        previous_completed = bool(company.onboarding_completed)

        if previous_completed == target_completed:
            flash("The company already has that onboarding status.", "info")
            return redirect(
                url_for("main.platform_company_detail", company_id=company_id)
            )

        company.onboarding_completed = target_completed

        record_platform_audit(
            actor=current_user(),
            action="company.onboarding_changed",
            target_type="company",
            target_id=company.id,
            company_id=company.id,
            reason=reason,
            before_data={
                "onboarding_completed": previous_completed,
            },
            after_data={
                "onboarding_completed": target_completed,
            },
        )

        db.session.commit()
        display_status = "Complete" if target_completed else "Incomplete"
        flash(
            f"Company onboarding status changed to {display_status}.",
            "success",
        )

    except PlatformAuditError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Platform company onboarding update failed"
        )
        flash(
            "The onboarding status could not be updated. No change was saved.",
            "danger",
        )

    return redirect(
        url_for("main.platform_company_detail", company_id=company_id)
    )


# ============================================================
# PHASE 7.5 — READ-ONLY PLATFORM AUDIT LOG VIEWER
# ============================================================

@bp.route("/platform/audit-logs", methods=["GET"])
@platform_super_admin_required
def platform_audit_logs():
    page = request.args.get("page", 1, type=int)
    company_id = request.args.get("company_id", type=int)
    action = request.args.get("action", "").strip()

    if page is None or page < 1:
        page = 1

    if len(action) > 100:
        action = action[:100]

    query = PlatformAuditLog.query

    if company_id and company_id > 0:
        query = query.filter(
            PlatformAuditLog.company_id == company_id
        )
    else:
        company_id = None

    if action:
        query = query.filter(
            PlatformAuditLog.action == action
        )

    pagination = (
        query
        .order_by(
            PlatformAuditLog.created_at.desc(),
            PlatformAuditLog.id.desc(),
        )
        .paginate(
            page=page,
            per_page=50,
            error_out=False,
        )
    )

    companies = Company.query.order_by(Company.name.asc()).all()

    actions = [
        row[0]
        for row in (
            db.session.query(PlatformAuditLog.action)
            .distinct()
            .order_by(PlatformAuditLog.action.asc())
            .all()
        )
    ]

    return render_template(
        "platform_audit_logs.html",
        pagination=pagination,
        audit_events=pagination.items,
        companies=companies,
        actions=actions,
        selected_company_id=company_id,
        selected_action=action,
    )


# ============================================================
# PLATFORM INTEGRATIONS OVERVIEW
# Read-only provider catalogue and platform connection status.
# ============================================================

@bp.route("/platform/integrations")
@platform_super_admin_required
def platform_integrations():
    providers = (
        IntegrationProvider.query
        .order_by(
            IntegrationProvider.category.asc(),
            IntegrationProvider.display_name.asc(),
        )
        .all()
    )

    integrations = list_platform_integrations()

    return render_template(
        "platform_integrations.html",
        providers=providers,
        integrations=integrations,
    )


@bp.route("/platform/integrations/providers", methods=["POST"])
@platform_super_admin_required
def platform_provider_create():
    code = request.form.get("code", "").strip().lower()
    display_name = request.form.get("display_name", "").strip()
    category = request.form.get("category", "").strip().lower()
    description = request.form.get("description", "").strip()
    capabilities_text = request.form.get("capabilities", "")
    reason = request.form.get("reason", "").strip()

    import re

    if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,79}", code):
        flash("Provider code must be 2–80 valid characters.", "error")
        return redirect(url_for("main.platform_integrations"))

    if not display_name or len(display_name) > 160:
        flash("Provider name is required and must not exceed 160 characters.", "error")
        return redirect(url_for("main.platform_integrations"))

    if not category or len(category) > 40:
        flash("A valid provider category is required.", "error")
        return redirect(url_for("main.platform_integrations"))

    if len(description) > 2000 or not reason or len(reason) > 2000:
        flash("Description or audit reason is invalid.", "error")
        return redirect(url_for("main.platform_integrations"))

    capabilities = [
        item.strip()
        for item in capabilities_text.split(",")
        if item.strip()
    ]

    if len(capabilities) > 30 or any(len(item) > 80 for item in capabilities):
        flash("Provider capabilities are invalid.", "error")
        return redirect(url_for("main.platform_integrations"))

    if IntegrationProvider.query.filter_by(code=code).first():
        flash("A provider with that code already exists.", "error")
        return redirect(url_for("main.platform_integrations"))

    try:
        provider = IntegrationProvider(
            code=code,
            display_name=display_name,
            category=category,
            description=description or None,
            capabilities=capabilities,
            is_enabled=False,
        )
        db.session.add(provider)
        db.session.flush()

        record_platform_audit(
            actor=current_user(),
            action="integration_provider.created",
            target_type="integration_provider",
            target_id=provider.id,
            reason=reason,
            after_data={
                "code": provider.code,
                "display_name": provider.display_name,
                "category": provider.category,
                "capabilities": provider.capabilities,
                "is_enabled": False,
            },
        )

        db.session.commit()
        flash("Provider registered in the disabled state.", "success")

    except PlatformAuditError as exc:
        db.session.rollback()
        flash(f"Provider registration was rolled back: {exc}", "error")
    except Exception:
        db.session.rollback()
        flash("Provider registration failed. No changes were saved.", "error")

    return redirect(url_for("main.platform_integrations"))


@bp.route("/platform/integrations/providers/<int:provider_id>/status", methods=["POST"])
@platform_super_admin_required
def platform_provider_status(provider_id):
    provider = db.session.get(IntegrationProvider, provider_id)

    if provider is None:
        abort(404)

    requested_status = request.form.get("enabled", "")
    reason = request.form.get("reason", "").strip()

    if requested_status not in {"true", "false"}:
        flash("Invalid provider status.", "error")
        return redirect(url_for("main.platform_integrations"))

    if not reason or len(reason) > 2000:
        flash("A valid audit reason is required.", "error")
        return redirect(url_for("main.platform_integrations"))

    target_enabled = requested_status == "true"
    previous_enabled = bool(provider.is_enabled)

    if previous_enabled == target_enabled:
        flash("The provider already has that availability status.", "info")
        return redirect(url_for("main.platform_integrations"))

    try:
        provider.is_enabled = target_enabled

        record_platform_audit(
            actor=current_user(),
            action=(
                "integration_provider.enabled"
                if target_enabled
                else "integration_provider.disabled"
            ),
            target_type="integration_provider",
            target_id=provider.id,
            reason=reason,
            before_data={"is_enabled": previous_enabled},
            after_data={"is_enabled": target_enabled},
        )

        db.session.commit()
        flash(
            "Provider availability updated. Existing connections were preserved.",
            "success",
        )

    except PlatformAuditError as exc:
        db.session.rollback()
        flash(f"Provider status change was rolled back: {exc}", "error")
    except Exception:
        db.session.rollback()
        flash("Provider status change failed. No changes were saved.", "error")

    return redirect(url_for("main.platform_integrations"))


# ============================================================
# PHASE 8.1 — COMPANY AND PLATFORM CONNECTION MANAGEMENT
# No live provider calls are performed by these routes.
# ============================================================

def _integration_json_object(field_name, blank_value=None):
    raw = request.form.get(field_name, "").strip()
    if not raw:
        return blank_value

    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name.replace('_', ' ').capitalize()} must be valid JSON.")

    if not isinstance(value, dict):
        raise ValueError(f"{field_name.replace('_', ' ').capitalize()} must be a JSON object.")

    return value


def _integration_audit_snapshot(snapshot):
    """Build an audit-safe connection snapshot without credential material."""
    return {
        "provider_code": snapshot.get("provider_code"),
        "ownership_scope": snapshot.get("ownership_scope"),
        "environment": snapshot.get("environment"),
        "status": snapshot.get("status"),
        "has_credentials": bool(snapshot.get("has_credentials")),
    }


@bp.route("/integration/connections", methods=["POST"])
@employer_required
def company_integration_create():
    user = current_user()
    company = user.company

    if company is None:
        abort(403)

    try:
        configuration = _integration_json_object(
            "configuration",
            blank_value={},
        )
        credentials = _integration_json_object(
            "credentials",
            blank_value=None,
        )

        create_company_integration(
            company_id=company.id,
            provider_code=request.form.get("provider_code", "").strip(),
            environment=request.form.get("environment", "sandbox").strip(),
            configuration=configuration,
            credentials=credentials,
        )
        db.session.commit()
        flash("Company integration connection created.", "success")

    except (IntegrationServiceError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        flash("Connection creation failed. No changes were saved.", "error")

    return redirect(url_for("main.integration"))


@bp.route("/integration/connections/<int:integration_id>", methods=["POST"])
@employer_required
def company_integration_update(integration_id):
    user = current_user()
    company = user.company

    if company is None:
        abort(403)

    try:
        configuration = _integration_json_object(
            "configuration",
            blank_value=None,
        )
        credentials = _integration_json_object(
            "credentials",
            blank_value=None,
        )

        if configuration is None and credentials is None:
            raise ValueError("Enter configuration or new credentials to update.")

        update_company_integration(
            company_id=company.id,
            integration_id=integration_id,
            configuration=configuration,
            credentials=credentials,
        )
        db.session.commit()
        flash("Company integration connection updated.", "success")

    except (IntegrationServiceError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        flash("Connection update failed. No changes were saved.", "error")

    return redirect(url_for("main.integration"))


@bp.route("/platform/integrations/connections", methods=["POST"])
@platform_super_admin_required
def platform_integration_create():
    reason = request.form.get("reason", "").strip()

    if not reason or len(reason) > 2000:
        flash("A valid audit reason is required.", "error")
        return redirect(url_for("main.platform_integrations"))

    try:
        configuration = _integration_json_object(
            "configuration",
            blank_value={},
        )
        credentials = _integration_json_object(
            "credentials",
            blank_value=None,
        )

        connection = create_platform_integration(
            provider_code=request.form.get("provider_code", "").strip(),
            environment=request.form.get("environment", "sandbox").strip(),
            configuration=configuration,
            credentials=credentials,
        )

        snapshot = get_platform_integration_status(connection.id)

        record_platform_audit(
            actor=current_user(),
            action="integration_connection.created",
            target_type="integration_connection",
            target_id=connection.id,
            reason=reason,
            after_data=_integration_audit_snapshot(snapshot),
        )

        db.session.commit()
        flash("Platform-owned connection created.", "success")

    except (IntegrationServiceError, ValueError, PlatformAuditError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        flash("Platform connection creation failed. No changes were saved.", "error")

    return redirect(url_for("main.platform_integrations"))


@bp.route(
    "/platform/integrations/connections/<int:integration_id>",
    methods=["POST"],
)
@platform_super_admin_required
def platform_integration_update(integration_id):
    reason = request.form.get("reason", "").strip()

    if not reason or len(reason) > 2000:
        flash("A valid audit reason is required.", "error")
        return redirect(url_for("main.platform_integrations"))

    try:
        configuration = _integration_json_object(
            "configuration",
            blank_value=None,
        )
        credentials = _integration_json_object(
            "credentials",
            blank_value=None,
        )

        if configuration is None and credentials is None:
            raise ValueError("Enter configuration or new credentials to update.")

        before = get_platform_integration_status(integration_id)

        update_platform_integration(
            integration_id=integration_id,
            configuration=configuration,
            credentials=credentials,
        )

        after = get_platform_integration_status(integration_id)

        record_platform_audit(
            actor=current_user(),
            action="integration_connection.updated",
            target_type="integration_connection",
            target_id=integration_id,
            reason=reason,
            before_data=_integration_audit_snapshot(before),
            after_data=_integration_audit_snapshot(after),
        )

        db.session.commit()
        flash("Platform-owned connection updated.", "success")

    except (IntegrationServiceError, ValueError, PlatformAuditError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        flash("Platform connection update failed. No changes were saved.", "error")

    return redirect(url_for("main.platform_integrations"))


# ============================================================
# COMPANY ACCOUNTING — INITIAL SETUP
# ============================================================

@bp.route("/accounting/setup", methods=["GET", "POST"])
@company_admin_required
@accounting_feature_required
def accounting_setup():
    user = current_user()
    form_values = {
        "financial_year_name": request.form.get("financial_year_name", ""),
        "start_date": request.form.get("start_date", ""),
        "end_date": request.form.get("end_date", ""),
    }

    if request.method == "POST":
        try:
            start_date = date.fromisoformat(form_values["start_date"].strip())
            end_date = date.fromisoformat(form_values["end_date"].strip())
        except ValueError:
            flash("Enter valid financial-year start and end dates.", "error")
            return render_template(
                "accounting_setup.html",
                form_values=form_values,
            )

        try:
            result = setup_company_accounting(
                company_id=user.company_id,
                actor_id=user.id,
                financial_year_name=form_values["financial_year_name"],
                start_date=start_date,
                end_date=end_date,
            )
        except (AccountingSetupError, ValueError) as exc:
            flash(str(exc), "error")
            return render_template(
                "accounting_setup.html",
                form_values=form_values,
            )
        except Exception:
            current_app.logger.exception(
                "Company accounting setup failed."
            )
            flash(
                "Accounting setup failed. No changes were saved. "
                "Please contact support if the problem continues.",
                "error",
            )
            return render_template(
                "accounting_setup.html",
                form_values=form_values,
            )

        if result["already_configured"]:
            flash(
                "Accounting setup is already complete. "
                "No duplicate financial year was created.",
                "info",
            )
        else:
            flash(
                "Company accounting setup completed successfully.",
                "success",
            )

        return redirect(url_for("main.accounting_setup"))

    return render_template(
        "accounting_setup.html",
        form_values=form_values,
    )


# ============================================================
# COMPANY ACCOUNTING — FINANCIAL YEAR AND PERIOD CALENDAR
# ============================================================

def _perform_accounting_lifecycle_action(operation, record_id, success_message):
    user = current_user()
    reason = request.form.get("reason", "")

    try:
        operation(
            user.company_id,
            record_id,
            user.id,
            reason,
        )
        flash(success_message, "success")
    except (AccountingLifecycleServiceError, ValueError) as exc:
        flash(str(exc), "error")
    except Exception:
        current_app.logger.exception(
            "Company accounting lifecycle action failed."
        )
        flash(
            "The accounting lifecycle action failed. "
            "No changes were saved. Please try again or contact support.",
            "error",
        )

    return redirect(url_for("main.accounting_calendar"))


@bp.route("/accounting/calendar", methods=["GET"])
@company_admin_required
@accounting_feature_required
def accounting_calendar():
    user = current_user()

    financial_years = (
        FinancialYear.query
        .filter_by(company_id=user.company_id)
        .order_by(
            FinancialYear.start_date.desc(),
            FinancialYear.id.desc(),
        )
        .all()
    )

    return render_template(
        "accounting_calendar.html",
        financial_years=financial_years,
    )


@bp.route("/accounting/periods/<int:period_id>/close", methods=["POST"])
@company_admin_required
@accounting_feature_required
def accounting_period_close(period_id):
    return _perform_accounting_lifecycle_action(
        close_accounting_period,
        period_id,
        "Accounting period closed successfully.",
    )


@bp.route("/accounting/periods/<int:period_id>/reopen", methods=["POST"])
@company_admin_required
@accounting_feature_required
def accounting_period_reopen(period_id):
    return _perform_accounting_lifecycle_action(
        reopen_accounting_period,
        period_id,
        "Accounting period reopened successfully.",
    )


@bp.route(
    "/accounting/financial-years/<int:financial_year_id>/close",
    methods=["POST"],
)
@company_admin_required
@accounting_feature_required
def accounting_financial_year_close(financial_year_id):
    return _perform_accounting_lifecycle_action(
        close_financial_year,
        financial_year_id,
        "Financial year closed successfully.",
    )


@bp.route(
    "/accounting/financial-years/<int:financial_year_id>/reopen",
    methods=["POST"],
)
@company_admin_required
@accounting_feature_required
def accounting_financial_year_reopen(financial_year_id):
    return _perform_accounting_lifecycle_action(
        reopen_financial_year,
        financial_year_id,
        "Financial year reopened successfully. Its periods remain closed.",
    )


# ============================================================
# COMPANY ACCOUNTING — READ-ONLY JOURNAL REGISTER
# ============================================================


@bp.route("/accounting/journals/new", methods=["GET", "POST"])
@company_admin_required
@accounting_feature_required
def journal_create():
    user = current_user()
    company_id = user.company_id

    child_account_ids = (
        db.session.query(Account.parent_id)
        .filter(
            Account.company_id == company_id,
            Account.parent_id.isnot(None),
        )
    )

    accounts = (
        Account.query.filter(
            Account.company_id == company_id,
            Account.is_active.is_(True),
            Account.allow_manual_posting.is_(True),
            ~Account.id.in_(child_account_ids),
        )
        .order_by(Account.account_code.asc(), Account.id.asc())
        .all()
    )

    periods = (
        db.session.query(AccountingPeriod, FinancialYear)
        .join(
            FinancialYear,
            and_(
                FinancialYear.id == AccountingPeriod.financial_year_id,
                FinancialYear.company_id == AccountingPeriod.company_id,
            ),
        )
        .filter(
            AccountingPeriod.company_id == company_id,
            AccountingPeriod.status == "open",
            FinancialYear.status == "open",
        )
        .order_by(
            FinancialYear.start_date.asc(),
            AccountingPeriod.period_number.asc(),
        )
        .all()
    )

    if request.method == "GET":
        return render_template(
            "journal_form.html",
            journal=None,
            form_lines=[],
            accounts=accounts,
            periods=periods,
        )

    try:
        journal_number = (
            request.form.get("journal_number") or ""
        ).strip()
        journal_date_text = (
            request.form.get("journal_date") or ""
        ).strip()
        description = request.form.get("description") or ""
        currency = request.form.get("currency") or "ZAR"
        period_text = (
            request.form.get("accounting_period_id") or ""
        ).strip()

        if not journal_number:
            raise ValueError("Journal number is required.")

        if not period_text.isdigit():
            raise ValueError("Select an accounting period.")

        try:
            journal_date = datetime.strptime(
                journal_date_text,
                "%Y-%m-%d",
            ).date()
        except ValueError as exc:
            raise ValueError("Enter a valid journal date.") from exc

        selected_period_id = int(period_text)

        account_values = request.form.getlist("account_id")
        debit_values = request.form.getlist("debit")
        credit_values = request.form.getlist("credit")
        descriptions = request.form.getlist("line_description")

        row_count = max(
            len(account_values),
            len(debit_values),
            len(credit_values),
            len(descriptions),
        )

        lines = []

        for index in range(row_count):
            account_text = (
                account_values[index]
                if index < len(account_values) else ""
            )
            debit_text = (
                debit_values[index]
                if index < len(debit_values) else ""
            )
            credit_text = (
                credit_values[index]
                if index < len(credit_values) else ""
            )
            line_description = (
                descriptions[index]
                if index < len(descriptions) else ""
            )

            values = (
                account_text,
                debit_text,
                credit_text,
                line_description,
            )

            if not any(value.strip() for value in values):
                continue

            if not account_text.isdigit():
                raise ValueError(
                    f"Select an account for line {index + 1}."
                )

            lines.append({
                "line_number": len(lines) + 1,
                "account_id": int(account_text),
                "debit": debit_text.strip() or "0",
                "credit": credit_text.strip() or "0",
                "description": line_description.strip() or None,
            })

        journal = create_journal(
            company_id=company_id,
            actor_id=user.id,
            journal_number=journal_number,
            journal_date=journal_date,
            description=description,
            currency=currency,
            lines=lines,
            source_type="manual",
            source_id=None,
            accounting_period_id=selected_period_id,
        )

        db.session.commit()

        flash(
            "Manual journal draft created successfully.",
            "success",
        )

        return redirect(
            url_for(
                "main.journal_detail",
                journal_id=journal.id,
            )
        )

    except (JournalServiceError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc), "error")

    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Manual journal draft creation failed."
        )
        flash(
            "The journal draft could not be saved. "
            "No changes were committed.",
            "error",
        )

    return redirect(url_for("main.journal_create"))


@bp.route(
    "/accounting/journals/<int:journal_id>/edit",
    methods=["GET", "POST"],
)
@company_admin_required
@accounting_feature_required
def journal_edit(journal_id):
    user = current_user()
    company_id = user.company_id

    journal = JournalEntry.query.filter_by(
        id=journal_id,
        company_id=company_id,
    ).first()

    if journal is None:
        abort(404)

    if (
        journal.status != "draft"
        or journal.reversal_of_id is not None
        or journal.source_type == "reversal"
    ):
        abort(404)

    child_account_ids = (
        db.session.query(Account.parent_id)
        .filter(
            Account.company_id == company_id,
            Account.parent_id.isnot(None),
        )
    )

    accounts = (
        Account.query.filter(
            Account.company_id == company_id,
            Account.is_active.is_(True),
            Account.allow_manual_posting.is_(True),
            ~Account.id.in_(child_account_ids),
        )
        .order_by(Account.account_code.asc(), Account.id.asc())
        .all()
    )

    periods = (
        db.session.query(AccountingPeriod, FinancialYear)
        .join(
            FinancialYear,
            and_(
                FinancialYear.id == AccountingPeriod.financial_year_id,
                FinancialYear.company_id == AccountingPeriod.company_id,
            ),
        )
        .filter(
            AccountingPeriod.company_id == company_id,
            AccountingPeriod.status == "open",
            FinancialYear.status == "open",
        )
        .order_by(
            FinancialYear.start_date.asc(),
            AccountingPeriod.period_number.asc(),
        )
        .all()
    )

    form_lines = (
        JournalLine.query.filter_by(
            company_id=company_id,
            journal_entry_id=journal.id,
        )
        .order_by(JournalLine.line_number.asc())
        .all()
    )

    serializer = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt="appex-journal-draft-edit-v1",
    )

    if request.method == "GET":
        snapshot_token = serializer.dumps(
            journal_draft_snapshot(journal)
        )
        return render_template(
            "journal_form.html",
            journal=journal,
            form_lines=form_lines,
            accounts=accounts,
            periods=periods,
            snapshot_token=snapshot_token,
            form_values={},
        )

    submitted_form_values = {
        "journal_number": request.form.get("journal_number", ""),
        "journal_date": request.form.get("journal_date", ""),
        "accounting_period_id": request.form.get("accounting_period_id", ""),
        "description": request.form.get("description", ""),
        "currency": request.form.get("currency", "ZAR"),
        "reason": request.form.get("reason", ""),
    }

    submitted_accounts = request.form.getlist("account_id")
    submitted_debits = request.form.getlist("debit")
    submitted_credits = request.form.getlist("credit")
    submitted_descriptions = request.form.getlist("line_description")

    submitted_form_lines = []
    submitted_row_count = max(
        len(submitted_accounts),
        len(submitted_debits),
        len(submitted_credits),
        len(submitted_descriptions),
    )
    for index in range(submitted_row_count):
        submitted_form_lines.append({
            "account_id": (
                submitted_accounts[index]
                if index < len(submitted_accounts) else ""
            ),
            "debit": (
                submitted_debits[index]
                if index < len(submitted_debits) else ""
            ),
            "credit": (
                submitted_credits[index]
                if index < len(submitted_credits) else ""
            ),
            "description": (
                submitted_descriptions[index]
                if index < len(submitted_descriptions) else ""
            ),
        })

    try:
        expected_snapshot = serializer.loads(
            request.form.get("snapshot_token", ""),
            max_age=3600,
        )
    except BadSignature:
        flash(
            "This edit form has expired or is invalid. "
            "Reload the current journal draft.",
            "error",
        )
        return redirect(
            url_for("main.journal_edit", journal_id=journal_id)
        )

    try:
        journal_number = (
            request.form.get("journal_number") or ""
        ).strip()
        journal_date_text = (
            request.form.get("journal_date") or ""
        ).strip()
        description = request.form.get("description") or ""
        currency = request.form.get("currency") or "ZAR"
        period_text = (
            request.form.get("accounting_period_id") or ""
        ).strip()

        if not journal_number:
            raise ValueError("Journal number is required.")
        if not period_text.isdigit():
            raise ValueError("Select an accounting period.")

        try:
            edited_date = datetime.strptime(
                journal_date_text, "%Y-%m-%d"
            ).date()
        except ValueError as exc:
            raise ValueError("Enter a valid journal date.") from exc

        selected_period_id = int(period_text)
        account_values = request.form.getlist("account_id")
        debit_values = request.form.getlist("debit")
        credit_values = request.form.getlist("credit")
        descriptions = request.form.getlist("line_description")

        row_count = max(
            len(account_values),
            len(debit_values),
            len(credit_values),
            len(descriptions),
        )

        lines = []
        for index in range(row_count):
            account_text = (
                account_values[index] if index < len(account_values) else ""
            )
            debit_text = (
                debit_values[index] if index < len(debit_values) else ""
            )
            credit_text = (
                credit_values[index] if index < len(credit_values) else ""
            )
            line_description = (
                descriptions[index] if index < len(descriptions) else ""
            )

            values = (
                account_text,
                debit_text,
                credit_text,
                line_description,
            )
            if not any(value.strip() for value in values):
                continue
            if not account_text.isdigit():
                raise ValueError(
                    f"Select an account for line {index + 1}."
                )

            lines.append({
                "line_number": len(lines) + 1,
                "account_id": int(account_text),
                "debit": debit_text.strip() or "0",
                "credit": credit_text.strip() or "0",
                "description": line_description.strip() or None,
            })

        updated = update_journal(
            company_id=company_id,
            journal_id=journal.id,
            actor_id=user.id,
            journal_number=journal_number,
            journal_date=edited_date,
            description=description,
            currency=currency,
            lines=lines,
            accounting_period_id=selected_period_id,
            reason=(request.form.get("reason") or "").strip() or None,
            expected_snapshot=expected_snapshot,
        )

        db.session.commit()
        flash("Manual journal draft updated successfully.", "success")
        return redirect(
            url_for("main.journal_detail", journal_id=updated.id)
        )

    except JournalDraftConflict as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(
            url_for("main.journal_edit", journal_id=journal_id)
        )
    except (JournalServiceError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return render_template(
            "journal_form.html",
            journal=journal,
            form_lines=submitted_form_lines,
            accounts=accounts,
            periods=periods,
            form_values=submitted_form_values,
            snapshot_token=request.form.get("snapshot_token", ""),
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Manual journal draft update failed."
        )
        flash(
            "The journal draft could not be updated. "
            "No changes were committed.",
            "error",
        )
        return render_template(
            "journal_form.html",
            journal=journal,
            form_lines=submitted_form_lines,
            accounts=accounts,
            periods=periods,
            form_values=submitted_form_values,
            snapshot_token=request.form.get("snapshot_token", ""),
        )
@bp.route("/accounting/journals", methods=["GET"])
@company_admin_required
@accounting_feature_required
def journal_list():
    user = current_user()
    company_id = user.company_id

    rows = (
        db.session.query(JournalEntry, AccountingPeriod, FinancialYear)
        .outerjoin(
            AccountingPeriod,
            and_(
                AccountingPeriod.id == JournalEntry.accounting_period_id,
                AccountingPeriod.company_id == JournalEntry.company_id,
            ),
        )
        .outerjoin(
            FinancialYear,
            and_(
                FinancialYear.id == AccountingPeriod.financial_year_id,
                FinancialYear.company_id == JournalEntry.company_id,
            ),
        )
        .filter(JournalEntry.company_id == company_id)
        .order_by(
            JournalEntry.journal_date.desc(),
            JournalEntry.id.desc(),
        )
        .all()
    )

    return render_template("journals.html", rows=rows)


@bp.route(
    "/accounting/journals/<int:journal_id>/reverse",
    methods=["GET", "POST"],
)
@company_admin_required
@accounting_feature_required
def journal_reverse_create(journal_id):
    user = current_user()
    company_id = user.company_id

    original = JournalEntry.query.filter_by(
        id=journal_id,
        company_id=company_id,
    ).first()

    if original is None:
        abort(404)

    if (
        original.status != "posted"
        or original.reversal_of_id is not None
        or original.source_type == "reversal"
    ):
        abort(404)

    existing = JournalEntry.query.filter_by(
        company_id=company_id,
        reversal_of_id=original.id,
    ).first()
    if existing is not None:
        flash("This journal already has a reversal.", "error")
        return redirect(
            url_for("main.journal_detail", journal_id=original.id)
        )

    if request.method == "GET":
        return render_template(
            "reversal_form.html",
            original=original,
            form_values={},
        )

    reversal_number = (
        request.form.get("reversal_journal_number") or ""
    ).strip()
    reversal_date_text = (
        request.form.get("reversal_date") or ""
    ).strip()
    reason = (request.form.get("reason") or "").strip()
    description = (
        request.form.get("description") or ""
    ).strip() or None

    form_values = {
        "reversal_journal_number": reversal_number,
        "reversal_date": reversal_date_text,
        "reason": reason,
        "description": description or "",
    }

    def render_form_again():
        fresh_original = JournalEntry.query.filter_by(
            id=journal_id,
            company_id=company_id,
        ).first()
        if fresh_original is None:
            abort(404)
        return render_template(
            "reversal_form.html",
            original=fresh_original,
            form_values=form_values,
        )

    try:
        if not reversal_number:
            raise ValueError("Reversal journal number is required.")
        if len(reversal_number) > 40:
            raise ValueError("Reversal journal number cannot exceed 40 characters.")
        if not reason:
            raise ValueError("A reversal reason is required.")
        if len(reason) > 500:
            raise ValueError("Reversal reason cannot exceed 500 characters.")
        if description is not None and len(description) > 500:
            raise ValueError("Reversal description cannot exceed 500 characters.")

        try:
            reversal_date = datetime.strptime(
                reversal_date_text,
                "%Y-%m-%d",
            ).date()
        except ValueError as exc:
            raise ValueError("Enter a valid reversal date.") from exc

        reversal = create_reversal(
            company_id=company_id,
            original_journal_id=original.id,
            actor_id=user.id,
            reversal_journal_number=reversal_number,
            reversal_date=reversal_date,
            reason=reason,
            description=description,
        )
        db.session.commit()
        flash("Reversal draft created successfully.", "success")
        return redirect(
            url_for("main.journal_detail", journal_id=reversal.id)
        )

    except (JournalServiceError, ValueError) as exc:
        db.session.rollback()
        existing = JournalEntry.query.filter_by(
            company_id=company_id,
            reversal_of_id=journal_id,
        ).first()
        if existing is not None:
            flash(
                "A reversal already exists for this journal. "
                "The existing reversal is available from the journal details.",
                "error",
            )
            return redirect(
                url_for("main.journal_detail", journal_id=journal_id)
            )
        flash(str(exc), "error")
        return render_form_again()

    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Manual journal reversal creation failed."
        )
        existing = JournalEntry.query.filter_by(
            company_id=company_id,
            reversal_of_id=journal_id,
        ).first()
        if existing is not None:
            flash(
                "A reversal already exists for this journal. "
                "The existing reversal is available from the journal details.",
                "error",
            )
            return redirect(
                url_for("main.journal_detail", journal_id=journal_id)
            )
        flash(
            "The reversal draft could not be created. "
            "No changes were committed.",
            "error",
        )
        return render_form_again()

@bp.route(
    "/accounting/journals/<int:original_journal_id>/"
    "reversals/<int:reversal_journal_id>/post",
    methods=["POST"],
)
@company_admin_required
@accounting_feature_required
def journal_reverse_post(original_journal_id, reversal_journal_id):
    user = current_user()
    company_id = user.company_id

    original = JournalEntry.query.filter_by(
        id=original_journal_id,
        company_id=company_id,
    ).first()

    reversal = JournalEntry.query.filter_by(
        id=reversal_journal_id,
        company_id=company_id,
    ).first()

    if original is None or reversal is None:
        abort(404)

    if (
        reversal.reversal_of_id != original.id
        or reversal.source_type != "reversal"
        or reversal.source_id != original.id
        or reversal.status != "draft"
    ):
        abort(404)

    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("A reason is required to post the reversal.", "error")
        return redirect(
            url_for("main.journal_detail", journal_id=reversal.id)
        )
    if len(reason) > 500:
        flash("Reversal posting reason cannot exceed 500 characters.", "error")
        return redirect(
            url_for("main.journal_detail", journal_id=reversal.id)
        )

    try:
        post_reversal(
            company_id=company_id,
            original_journal_id=original.id,
            reversal_journal_id=reversal.id,
            actor_id=user.id,
            reason=reason,
        )
        db.session.commit()
        flash("Journal reversal posted successfully.", "success")
    except (JournalServiceError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Manual journal reversal posting failed."
        )
        flash(
            "The reversal could not be posted. "
            "No changes were committed.",
            "error",
        )

    return redirect(
        url_for("main.journal_detail", journal_id=reversal.id)
    )


@bp.route(
    "/accounting/journals/<int:journal_id>/post",
    methods=["POST"],
)
@company_admin_required
@accounting_feature_required
def journal_post(journal_id):
    user = current_user()
    company_id = user.company_id

    journal = JournalEntry.query.filter_by(
        id=journal_id,
        company_id=company_id,
    ).first()

    if journal is None:
        abort(404)

    if (
        journal.status != "draft"
        or journal.reversal_of_id is not None
        or journal.source_type == "reversal"
    ):
        abort(404)

    try:
        post_journal(
            company_id=company_id,
            journal_id=journal.id,
            actor_id=user.id,
        )
        db.session.commit()
        flash("Journal posted successfully.", "success")
    except (JournalServiceError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Manual journal posting failed.")
        flash(
            "The journal could not be posted. No changes were committed.",
            "error",
        )

    return redirect(
        url_for("main.journal_detail", journal_id=journal.id)
    )


@bp.route("/accounting/journals/<int:journal_id>", methods=["GET"])
@company_admin_required
@accounting_feature_required
def journal_detail(journal_id):
    user = current_user()
    company_id = user.company_id

    journal = JournalEntry.query.filter_by(
        id=journal_id,
        company_id=company_id,
    ).first()

    if journal is None:
        abort(404)

    line_rows = (
        db.session.query(JournalLine, Account)
        .join(
            Account,
            and_(
                Account.id == JournalLine.account_id,
                Account.company_id == JournalLine.company_id,
            ),
        )
        .filter(
            JournalLine.company_id == company_id,
            JournalLine.journal_entry_id == journal.id,
        )
        .order_by(JournalLine.line_number.asc())
        .all()
    )

    period_row = (
        db.session.query(AccountingPeriod, FinancialYear)
        .outerjoin(
            FinancialYear,
            and_(
                FinancialYear.id == AccountingPeriod.financial_year_id,
                FinancialYear.company_id == AccountingPeriod.company_id,
            ),
        )
        .filter(
            AccountingPeriod.company_id == company_id,
            AccountingPeriod.id == journal.accounting_period_id,
        )
        .first()
        if journal.accounting_period_id is not None
        else None
    )

    audit_rows = (
        db.session.query(JournalAuditEvent, User)
        .join(
            User,
            and_(
                User.id == JournalAuditEvent.performed_by_id,
                User.company_id == JournalAuditEvent.company_id,
            ),
        )
        .filter(
            JournalAuditEvent.company_id == company_id,
            JournalAuditEvent.journal_entry_id == journal.id,
        )
        .order_by(
            JournalAuditEvent.performed_at.asc(),
            JournalAuditEvent.id.asc(),
        )
        .all()
    )

    original_journal = (
        JournalEntry.query.filter_by(
            id=journal.reversal_of_id,
            company_id=company_id,
        ).first()
        if journal.reversal_of_id is not None
        else None
    )

    reversal_journal = (
        JournalEntry.query.filter_by(
            company_id=company_id,
            reversal_of_id=journal.id,
        ).first()
        if journal.reversal_of_id is None
        else None
    )

    return render_template(
        "journal_detail.html",
        journal=journal,
        line_rows=line_rows,
        period_row=period_row,
        audit_rows=audit_rows,
        original_journal=original_journal,
        reversal_journal=reversal_journal,
    )
