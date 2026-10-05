import secrets
import calendar
import re

from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO

from flask import (
    Blueprint,
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

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from . import db

from .models import (
    Company,
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

from .payroll_calculator import calculate_payroll


bp = Blueprint("main", __name__)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    return User.query.get(user_id)


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

        if user.role not in ["employer", "admin"]:

            flash(
                "Employer access required.",
                "danger"
            )

            return redirect(
                url_for("main.employee_dashboard")
            )

        return view(*args, **kwargs)

    return wrapped_view


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


def get_active_employee_loan(employee_id):

    return (
        LoanApplication.query
        .filter(
            LoanApplication.employee_id == employee_id,
            LoanApplication.status == "Disbursed",
            LoanApplication.outstanding_balance > 0
        )
        .order_by(
            LoanApplication.created_at.asc()
        )
        .first()
    )


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
    user
):

    return (
        LoanApplication.query
        .join(Employee)
        .filter(
            LoanApplication.id == loan_id,
            Employee.company_id == user.company_id
        )
        .first_or_404()
    )


def _loan_repayment_columns():
    """Return the column names available on the Phase 5 ledger model."""
    return set(
        LoanRepayment.__table__.columns.keys()
    )


def find_loan_ledger_entry(
    loan_application_id,
    employee_id,
    payroll_run_id
):
    """Find an existing payroll repayment ledger entry.

    The lookup is deliberately limited to the payroll run and employee so
    the same payroll deduction cannot be posted twice to the loan ledger.
    """
    columns = _loan_repayment_columns()

    if "payroll_run_id" not in columns:
        return None

    query = LoanRepayment.query.filter(
        getattr(
            LoanRepayment,
            "payroll_run_id"
        ) == payroll_run_id
    )

    if "employee_id" in columns:
        query = query.filter(
            getattr(
                LoanRepayment,
                "employee_id"
            ) == employee_id
        )

    if "loan_application_id" in columns:
        query = query.filter(
            getattr(
                LoanRepayment,
                "loan_application_id"
            ) == loan_application_id
        )

    return query.first()


def create_loan_repayment_ledger_entry(
    loan_application,
    employee,
    payroll_run,
    payslip,
    amount
):
    """Create a Phase 5 LoanRepayment ledger entry."""

    amount = round(
        max(0.0, safe_float(amount)),
        2
    )

    if amount <= 0:
        return None

    existing = find_loan_ledger_entry(
        loan_application.id,
        employee.id,
        payroll_run.id
    )

    if existing:
        return existing

    columns = _loan_repayment_columns()
    repayment = LoanRepayment()

    pay_date = (
        payroll_run.pay_date
        or datetime.utcnow().date()
    )

    balance_before = round(
        max(
            0.0,
            safe_float(
                loan_application.outstanding_balance
            )
        ),
        2
    )

    balance_after = round(
        max(
            0.0,
            balance_before - amount
        ),
        2
    )

    previous_payments = 0

    if "loan_application_id" in columns:
        previous_payments = (
            LoanRepayment.query
            .filter(
                LoanRepayment.loan_application_id
                == loan_application.id,
                LoanRepayment.status
                == "Completed"
            )
            .count()
        )

    payment_number = previous_payments + 1

    reference = (
        "APX-LOAN-"
        + str(loan_application.id)
        + "-PAY-"
        + str(payroll_run.id)
        + "-EMP-"
        + str(employee.id)
    )

    values = {
        "loan_application_id": loan_application.id,
        "employee_id": employee.id,
        "payroll_run_id": payroll_run.id,
        "payslip_id": payslip.id,
        "amount": amount,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "payment_number": payment_number,
        "repayment_date": pay_date,
        "payment_method": "Payroll Deduction",
        "source": "Payroll",
        "reference": reference,
        "status": "Completed",
        "notes": "Loan repayment deducted through payroll.",
        "created_at": datetime.utcnow(),
    }

    for field, value in values.items():
        if field in columns:
            setattr(
                repayment,
                field,
                value
            )

    db.session.add(repayment)

    return repayment

def get_employee_loan_repayment_ledger(employee_id):
    """Return an employee's Phase 5 repayment ledger entries."""
    columns = _loan_repayment_columns()

    if "employee_id" not in columns:
        return []

    return (
        LoanRepayment.query
        .filter(
            getattr(LoanRepayment, "employee_id") == employee_id
        )
        .order_by(
            getattr(LoanRepayment, "id").desc()
        )
        .all()
    )


# ============================================================
# PAYROLL CALCULATION
# ============================================================

def calculate_payroll_input(payroll_input):

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

        loan_application = (
            get_active_employee_loan(
                employee.id
            )
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


def calculate_payroll_run_totals(payroll_run):

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

        calculated = calculate_payroll_input(
            payroll_input
        )

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

@bp.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "service": "appex-payroll"
    })


# ============================================================
# HOME / EMPLOYER DASHBOARD
# ============================================================

@bp.route("/")
@login_required
def dashboard():

    user = current_user()

    if user.role == "employee":

        return redirect(
            url_for(
                "main.employee_dashboard"
            )
        )

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

        return redirect(
            url_for("main.dashboard")
        )

    return render_template(
        "login.html"
    )


# ============================================================
# LOGOUT
# ============================================================

@bp.route("/logout")
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
    methods=["GET", "POST"]
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
    methods=["GET", "POST"]
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

        flash(
            "Invalid invitation.",
            "danger"
        )

        return redirect(
            url_for("main.login")
        )

    if not invitation.is_valid():

        flash(
            "This invitation has expired or has already been used.",
            "danger"
        )

        return redirect(
            url_for("main.login")
        )

    employee = invitation.employee

    if request.method == "POST":

        name = (
            request.form.get("name")
            or ""
        ).strip()

        email = (
            request.form.get("email")
            or employee.email
            or ""
        ).strip().lower()

        password = (
            request.form.get("password")
            or ""
        )

        if not name:

            flash(
                "Name is required.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.accept_invitation",
                    token=token
                )
            )

        if not email:

            flash(
                "Email is required.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.accept_invitation",
                    token=token
                )
            )

        if not password:

            flash(
                "Password is required.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.accept_invitation",
                    token=token
                )
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

        user = User(
            company_id=employee.company_id,
            name=name,
            email=email,
            password_hash=generate_password_hash(
                password
            ),
            role="employee",
            is_active=True,
        )

        db.session.add(user)
        db.session.flush()

        employee.user_id = user.id

        if not employee.email:
            employee.email = email

        invitation.used = True

        db.session.commit()

        session.clear()
        session["user_id"] = user.id

        flash(
            "Employee account created successfully.",
            "success"
        )

        return redirect(
            url_for(
                "main.employee_dashboard"
            )
        )

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

        flash(
            "No employee profile is linked to this account.",
            "danger"
        )

        return redirect(
            url_for("main.logout")
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

    repayments = get_employee_loan_repayment_ledger(
        employee.id
    )

    return render_template(
        "employee_repayments.html",
        employee=employee,
        application=application,
        repayments=repayments,
        outstanding_balance=outstanding_balance,
        amount_paid=amount_paid,
        monthly_installment=monthly_installment,
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
        user
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
        user
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
        user
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

        if not pay_period:

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

    payroll_run = PayrollRun.query.filter_by(
        id=payroll_id,
        company_id=user.company_id
    ).first_or_404()

    # --------------------------------------------------------
    # Payroll must be approved before completion.
    # Completed payroll is permanently locked.
    # --------------------------------------------------------
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

    if payroll_run.status != "Approved":

        flash(
            "Only approved payroll can be completed.",
            "warning"
        )

        return redirect(
            url_for(
                "main.view_payroll",
                payroll_id=payroll_run.id
            )
        )

    # --------------------------------------------------------
    # Payroll inputs
    # --------------------------------------------------------
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

    # --------------------------------------------------------
    # Calculate final payroll totals
    # --------------------------------------------------------
    results = calculate_payroll_run_totals(
        payroll_run
    )

    # --------------------------------------------------------
    # Remove any previously generated payslips for this run.
    # The payroll itself is still Approved at this point.
    # --------------------------------------------------------
    Payslip.query.filter_by(
        payroll_run_id=payroll_run.id
    ).delete(
        synchronize_session=False
    )

    # --------------------------------------------------------
    # Create final payslips and process loan deductions.
    # --------------------------------------------------------
    for calculated in results:

        employee = calculated["employee"]

        payroll_input = calculated["payroll_input"]

        result = calculated["result"]

        loan_application = calculated.get(
            "loan_application"
        )

        loan_repayment = round(
            max(
                0.0,
                safe_float(
                    calculated.get(
                        "loan_repayment",
                        0
                    )
                )
            ),
            2
        )

        payroll_input.loan_repayment = (
            loan_repayment
        )

        payslip = Payslip(
            employee_id=employee.id,
            payroll_run_id=payroll_run.id,
            pay_period=payroll_run.pay_period,
            pay_date=payroll_run.pay_date,

            basic_salary=safe_float(
                result.get(
                    "basic_salary",
                    payroll_input.basic_salary
                )
            ),

            overtime=safe_float(
                result.get(
                    "overtime",
                    payroll_input.overtime
                )
            ),

            bonus=safe_float(
                result.get(
                    "bonus",
                    payroll_input.bonus
                )
            ),

            commission=safe_float(
                result.get(
                    "commission",
                    payroll_input.commission
                )
            ),

            other_earnings=safe_float(
                result.get(
                    "other_earnings",
                    payroll_input.other_earnings
                )
            ),

            gross_pay=calculated["gross_pay"],

            tax_deductions=calculated["paye"],

            uif=calculated["uif"],

            other_deductions=calculated[
                "other_deductions"
            ],

            loan_repayment=loan_repayment,

            total_deductions=calculated[
                "total_deductions"
            ],

            net_pay=calculated["net_pay"],

            employer_uif=calculated[
                "employer_uif"
            ],

            employer_cost=calculated[
                "employer_cost"
            ],
        )

        db.session.add(payslip)

        # Payslip ID is required by the Phase 5 ledger.
        db.session.flush()

        # ----------------------------------------------------
        # Phase 5 loan repayment ledger
        # ----------------------------------------------------
        if (
            loan_application
            and loan_repayment > 0
            and loan_application.status == "Disbursed"
        ):

            create_loan_repayment_ledger_entry(
                loan_application=loan_application,
                employee=employee,
                payroll_run=payroll_run,
                payslip=payslip,
                amount=loan_repayment,
            )

            # ------------------------------------------------
            # Update loan totals
            # ------------------------------------------------
            current_total_paid = safe_float(
                loan_application.total_paid
            )

            total_repayable = safe_float(
                loan_application.total_repayable
            )

            new_total_paid = round(
                current_total_paid
                + loan_repayment,
                2
            )

            new_outstanding = round(
                max(
                    0.0,
                    total_repayable
                    - new_total_paid
                ),
                2
            )

            loan_application.total_paid = (
                new_total_paid
            )

            loan_application.outstanding_balance = (
                new_outstanding
            )

            # ------------------------------------------------
            # Fully repaid loan
            # ------------------------------------------------
            if new_outstanding <= 0.01:

                loan_application.total_paid = (
                    total_repayable
                )

                loan_application.outstanding_balance = 0.0

                loan_application.status = "Repaid"

                loan_application.next_payment_date = None

            # ------------------------------------------------
            # Loan still active
            # ------------------------------------------------
            else:

                loan_application.status = "Disbursed"

                loan_application.next_payment_date = (
                    add_months(
                        payroll_run.pay_date
                        or datetime.utcnow().date(),
                        1
                    )
                )

    # --------------------------------------------------------
    # Payroll is now permanently completed.
    # --------------------------------------------------------
    payroll_run.status = "Completed"

    db.session.commit()

    flash(
        "Payroll completed successfully. Loan repayments have been recorded.",
        "success"
    )

    return redirect(
        url_for(
            "main.view_payroll",
            payroll_id=payroll_run.id
        )
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

    return render_template(
        "integration.html",
        company=company,
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
