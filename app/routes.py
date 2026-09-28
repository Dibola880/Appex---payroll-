import os
import secrets

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

        return float(value)

    except (
        TypeError,
        ValueError
    ):

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

@bp.route("/register", methods=["GET", "POST"])
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
            "Registration successful.",
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

@bp.route("/login", methods=["GET", "POST"])
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
            status="Active",
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
        expires_at=datetime.utcnow()
        + timedelta(hours=48),
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

    return invite_employee(employee_id)


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
            url_for(
                "main.dashboard"
            )
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

@bp.route("/employee/financial-services")
@login_required
def financial_services():

    user = current_user()

    if user.role != "employee":

        return redirect(
            url_for(
                "main.dashboard"
            )
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
    methods=["GET", "POST"]
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
                    "main.employee_loan_application"
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
                    "main.employee_loan_application"
                )
            )

        if requested_amount > 3000:

            flash(
                "The maximum employee loan amount is R3,000.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.employee_loan_application"
                )
            )

        if not loan_purpose:

            flash(
                "Please select the purpose of the loan.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.employee_loan_application"
                )
            )

        if not repayment_term:

            flash(
                "Please select a repayment term.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.employee_loan_application"
                )
            )

        if monthly_income <= 0:

            flash(
                "Please enter your monthly income.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.employee_loan_application"
                )
            )

        if monthly_expenses < 0:

            flash(
                "Monthly expenses cannot be negative.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.employee_loan_application"
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
                    "main.employee_loan_status"
                )
            )

        reference = (
            "APL-"
            + datetime.utcnow().strftime(
                "%Y%m%d%H%M%S"
            )
            + "-"
            + secrets.token_hex(3).upper()
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
                "main.employee_loan_status"
            )
        )

    return render_template(
        "employee_loan_application.html",
        employee=employee,
    )


# ============================================================
# EMPLOYEE LOAN STATUS
# ============================================================

@bp.route("/employee/loan-status")
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
# EMPLOYEE REPAYMENTS
# ============================================================

@bp.route("/employee/repayments")
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

    if application:

        amount_paid = safe_float(
            application.total_paid
        )

        outstanding_balance = safe_float(
            application.outstanding_balance
        )

        if (
            outstanding_balance == 0
            and application.status in [
                "Approved",
                "Disbursed",
            ]
        ):

            outstanding_balance = safe_float(
                application.total_repayable
            )

    return render_template(
        "employee_repayments.html",
        employee=employee,
        application=application,
        outstanding_balance=outstanding_balance,
        amount_paid=amount_paid,
    )


# ============================================================
# EMPLOYEE PAYSLIPS
# ============================================================

@bp.route("/employee/payslips")
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
#
# Individual employee payroll inputs.
#
# GET:
#   Displays the payroll form.
#
# POST:
#   Creates a payroll draft and saves individual PayrollInput
#   records for every active employee.
#
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

        # ----------------------------------------------------
        # VALIDATE PAY PERIOD
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # VALIDATE PAY DATE
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # VALIDATE EMPLOYEES
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # CREATE PAYROLL RUN AS DRAFT
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # CREATE INDIVIDUAL PAYROLL INPUTS
        # ----------------------------------------------------

        for employee in employees:

            prefix = (
                f"employee_{employee.id}_"
            )

            overtime = safe_float(
                request.form.get(
                    prefix + "overtime"
                )
            )

            bonus = safe_float(
                request.form.get(
                    prefix + "bonus"
                )
            )

            commission = safe_float(
                request.form.get(
                    prefix + "commission"
                )
            )

            other_earnings = safe_float(
                request.form.get(
                    prefix + "other_earnings"
                )
            )

            other_deductions = safe_float(
                request.form.get(
                    prefix + "other_deductions"
                )
            )

            # ------------------------------------------------
            # Prevent negative payroll values
            # ------------------------------------------------

            if overtime < 0:
                overtime = 0

            if bonus < 0:
                bonus = 0

            if commission < 0:
                commission = 0

            if other_earnings < 0:
                other_earnings = 0

            if other_deductions < 0:
                other_deductions = 0

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
            )

            db.session.add(payroll_input)

        db.session.commit()

        # ----------------------------------------------------
        # If employer clicked Review Payroll
        # ----------------------------------------------------

        if action == "review":

            return redirect(
                url_for(
                    "main.review_payroll",
                    payroll_id=payroll_run.id
                )
            )

        # ----------------------------------------------------
        # Otherwise keep it as Draft
        # ----------------------------------------------------

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

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

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

    if request.method == "POST":

        return payroll()

    return redirect(
        url_for(
            "main.payroll"
        )
    )


# ============================================================
# REVIEW PAYROLL
# ============================================================

@bp.route(
    "/payroll/<int:payroll_id>/review"
)
@employer_required
def review_payroll(payroll_id):

    user = current_user()

    payroll_run = PayrollRun.query.filter_by(
        id=payroll_id,
        company_id=user.company_id
    ).first_or_404()

    # --------------------------------------------------------
    # Completed payroll is locked
    # --------------------------------------------------------

    if payroll_run.status == "Completed":

        flash(
            "This payroll has already been completed.",
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

    results = []

    total_gross = 0.0
    total_deductions = 0.0
    total_net = 0.0
    total_employer_uif = 0.0
    total_employer_cost = 0.0

    # --------------------------------------------------------
    # Calculate each employee
    # --------------------------------------------------------

    for payroll_input in payroll_inputs:

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
            result.get(
                "gross_pay",
                0
            )
        )

        paye = safe_float(
            result.get(
                "paye",
                0
            )
        )

        uif = safe_float(
            result.get(
                "uif",
                0
            )
        )

        other_deductions = safe_float(
            result.get(
                "other_deductions",
                0
            )
        )

        total_employee_deductions = safe_float(
            result.get(
                "total_deductions",
                paye
                + uif
                + other_deductions
            )
        )

        net_pay = safe_float(
            result.get(
                "net_pay",
                0
            )
        )

        employer_uif = safe_float(
            result.get(
                "employer_uif",
                0
            )
        )

        employer_cost = (
            gross_pay
            + employer_uif
        )

        results.append({
            "employee": employee,
            "payroll_input": payroll_input,
            "result": result,
            "gross_pay": gross_pay,
            "paye": paye,
            "uif": uif,
            "other_deductions": other_deductions,
            "total_deductions": total_employee_deductions,
            "net_pay": net_pay,
            "employer_uif": employer_uif,
            "employer_cost": employer_cost,
        })

        total_gross += gross_pay

        total_deductions += (
            total_employee_deductions
        )

        total_net += net_pay

        total_employer_uif += employer_uif

        total_employer_cost += employer_cost

    return render_template(
        "review_payroll.html",
        payroll_run=payroll_run,
        results=results,
        total_gross=total_gross,
        total_deductions=total_deductions,
        total_net=total_net,
        total_employer_uif=total_employer_uif,
        total_employer_cost=total_employer_cost,
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

    if payroll_run.status != "Draft":

        flash(
            "Only draft payroll can be submitted for review.",
            "warning"
        )

        return redirect(
            url_for(
                "main.review_payroll",
                payroll_id=payroll_run.id
            )
        )

    payroll_run.status = "Under Review"

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

    if payroll_run.status != "Under Review":

        flash(
            "Only payroll under review can be approved.",
            "warning"
        )

        return redirect(
            url_for(
                "main.view_payroll",
                payroll_id=payroll_run.id
            )
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
    # Remove existing payslips for this payroll run
    # --------------------------------------------------------

    Payslip.query.filter_by(
        payroll_run_id=payroll_run.id
    ).delete(
        synchronize_session=False
    )

    total_gross = 0.0
    total_deductions = 0.0
    total_net = 0.0
    total_employer_uif = 0.0
    total_employer_cost = 0.0

    # --------------------------------------------------------
    # Generate final payslips
    # --------------------------------------------------------

    for payroll_input in payroll_inputs:

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

        basic_salary = safe_float(
            result.get(
                "basic_salary",
                payroll_input.basic_salary
            )
        )

        overtime = safe_float(
            result.get(
                "overtime",
                payroll_input.overtime
            )
        )

        bonus = safe_float(
            result.get(
                "bonus",
                payroll_input.bonus
            )
        )

        commission = safe_float(
            result.get(
                "commission",
                payroll_input.commission
            )
        )

        other_earnings = safe_float(
            result.get(
                "other_earnings",
                payroll_input.other_earnings
            )
        )

        gross_pay = safe_float(
            result.get(
                "gross_pay",
                0
            )
        )

        paye = safe_float(
            result.get(
                "paye",
                0
            )
        )

        uif = safe_float(
            result.get(
                "uif",
                0
            )
        )

        other_deductions = safe_float(
            result.get(
                "other_deductions",
                0
            )
        )

        total_employee_deductions = safe_float(
            result.get(
                "total_deductions",
                paye
                + uif
                + other_deductions
            )
        )

        net_pay = safe_float(
            result.get(
                "net_pay",
                0
            )
        )

        employer_uif = safe_float(
            result.get(
                "employer_uif",
                0
            )
        )

        employer_cost = (
            gross_pay
            + employer_uif
        )

        payslip = Payslip(
            employee_id=employee.id,
            payroll_run_id=payroll_run.id,
            pay_period=payroll_run.pay_period,
            pay_date=payroll_run.pay_date,
            basic_salary=basic_salary,
            overtime=overtime,
            bonus=bonus,
            commission=commission,
            other_earnings=other_earnings,
            gross_pay=gross_pay,
            tax_deductions=paye,
            uif=uif,
            other_deductions=other_deductions,
            total_deductions=total_employee_deductions,
            net_pay=net_pay,
            employer_uif=employer_uif,
            employer_cost=employer_cost,
        )

        db.session.add(payslip)

        total_gross += gross_pay

        total_deductions += (
            total_employee_deductions
        )

        total_net += net_pay

        total_employer_uif += employer_uif

        total_employer_cost += employer_cost

    # --------------------------------------------------------
    # Save payroll totals
    # --------------------------------------------------------

    payroll_run.total_gross = total_gross

    payroll_run.total_deductions = (
        total_deductions
    )

    payroll_run.total_net = total_net

    payroll_run.total_employer_uif = (
        total_employer_uif
    )

    payroll_run.total_employer_cost = (
        total_employer_cost
    )

    payroll_run.status = "Completed"

    db.session.commit()

    flash(
        "Payroll completed successfully and payslips generated.",
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

@bp.route("/payroll/history")
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

    return render_template(
        "payroll_run.html",
        payroll_run=payroll_run,
        payslips=payslips,
        payroll_inputs=payroll_inputs,
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

    # --------------------------------------------------------
    # Employee security
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Employer security
    # --------------------------------------------------------

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
            url_for(
                "main.dashboard"
            )
        )

    # --------------------------------------------------------
    # Employee security
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Employer security
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Create PDF
    # --------------------------------------------------------

    buffer = BytesIO()

    pdf = canvas.Canvas(
        buffer,
        pagesize=A4
    )

    width, height = A4

    y = height - 50

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # EMPLOYEE DETAILS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # EARNINGS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # DEDUCTIONS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # NET PAY
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # EMPLOYER COST
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # FOOTER
    # --------------------------------------------------------

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
            request.form.get(
                "salary"
            )
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
