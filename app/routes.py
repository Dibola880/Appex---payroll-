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

from werkzeug.security import generate_password_hash, check_password_hash

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from . import db

from .models import (
    Company,
    User,
    Employee,
    EmployeeInvitation,
    PayrollRun,
    Payslip,
)

from .payroll_calculator import calculate_payroll


bp = Blueprint("main", __name__)


# ============================================================
# HELPERS
# ============================================================

def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    return db.session.get(User, user_id)


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):

        user = current_user()

        if not user:
            flash(
                "Please log in first.",
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
                "Please log in first.",
                "warning"
            )

            return redirect(
                url_for("main.login")
            )

        if user.role not in ["employer", "admin"]:

            flash(
                "Employer access is required.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.employee_dashboard"
                )
            )

        return view(*args, **kwargs)

    return wrapped_view


def safe_float(value, default=0.0):
    """
    Safely convert form input to a float.

    Empty, invalid, or negative values
    become the supplied default.
    """

    try:

        if value is None or str(value).strip() == "":
            return default

        number = float(value)

        if number < 0:
            return default

        return number

    except (TypeError, ValueError):

        return default


def calculate_age_from_dob(
    date_of_birth,
    reference_date=None
):
    """
    Calculate employee age from date of birth.

    reference_date is normally the payroll
    pay date.
    """

    if not date_of_birth:
        return None

    if reference_date is None:

        reference_date = (
            datetime.utcnow().date()
        )

    age = (
        reference_date.year
        - date_of_birth.year
    )

    if (
        reference_date.month,
        reference_date.day
    ) < (
        date_of_birth.month,
        date_of_birth.day
    ):

        age -= 1

    return age


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
# EMPLOYER DASHBOARD
# ============================================================

@bp.route("/")
@login_required
def dashboard():

    user = current_user()

    # --------------------------------------------------------
    # Redirect employees to employee dashboard
    # --------------------------------------------------------

    if user.role == "employee":

        return redirect(
            url_for(
                "main.employee_dashboard"
            )
        )

    company = user.company

    # --------------------------------------------------------
    # EMPLOYEES
    # --------------------------------------------------------

    employees = (
        Employee.query
        .filter_by(
            company_id=company.id
        )
        .order_by(
            Employee.last_name.asc()
        )
        .all()
    )

    active_employees = [
        employee
        for employee in employees
        if employee.status == "Active"
    ]

    total_employees = len(
        employees
    )

    active_employee_count = len(
        active_employees
    )

    # --------------------------------------------------------
    # MONTHLY SALARY BILL
    # --------------------------------------------------------

    total_salary = sum(
        employee.monthly_salary or 0
        for employee in active_employees
    )

    # --------------------------------------------------------
    # PAYROLL HISTORY
    # --------------------------------------------------------

    payroll_runs = (
        PayrollRun.query
        .filter_by(
            company_id=company.id
        )
        .order_by(
            PayrollRun.pay_date.desc()
        )
        .all()
    )

    total_payroll_runs = len(
        payroll_runs
    )

    # --------------------------------------------------------
    # TOTAL PAYROLL VALUES
    # --------------------------------------------------------

    total_gross_payroll = sum(
        payroll.total_gross or 0
        for payroll in payroll_runs
    )

    total_deductions = sum(
        payroll.total_deductions or 0
        for payroll in payroll_runs
    )

    total_net_payroll = sum(
        payroll.total_net or 0
        for payroll in payroll_runs
    )

    total_employer_uif = sum(
        payroll.total_employer_uif or 0
        for payroll in payroll_runs
    )

    total_employer_cost = sum(
        payroll.total_employer_cost or 0
        for payroll in payroll_runs
    )

    # --------------------------------------------------------
    # LATEST PAYROLL
    # --------------------------------------------------------

    latest_payroll = (
        payroll_runs[0]
        if payroll_runs
        else None
    )

    # --------------------------------------------------------
    # RECENT PAYROLL RUNS
    # --------------------------------------------------------

    recent_payroll_runs = payroll_runs[:5]

    # --------------------------------------------------------
    # RENDER DASHBOARD
    # --------------------------------------------------------

    return render_template(
        "dashboard.html",

        company=company,

        employees=employees,

        total_salary=total_salary,

        total_employees=total_employees,

        active_employee_count=active_employee_count,

        total_payroll_runs=total_payroll_runs,

        total_gross_payroll=total_gross_payroll,

        total_deductions=total_deductions,

        total_net_payroll=total_net_payroll,

        total_employer_uif=total_employer_uif,

        total_employer_cost=total_employer_cost,

        latest_payroll=latest_payroll,

        recent_payroll_runs=recent_payroll_runs,
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

        company_name = request.form.get(
            "company_name",
            ""
        ).strip()

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if (
            not company_name
            or not name
            or not email
            or not password
        ):

            flash(
                "Please complete all required fields.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        if len(password) < 8:

            flash(
                "Password must contain at least 8 characters.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:

            flash(
                "An account with that email already exists.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        company = Company(
            name=company_name,
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
            "Company account created successfully.",
            "success"
        )

        return redirect(
            url_for(
                "main.dashboard"
            )
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

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        user = User.query.filter_by(
            email=email
        ).first()

        if (
            not user
            or not check_password_hash(
                user.password_hash,
                password
            )
        ):

            flash(
                "Invalid email or password.",
                "danger"
            )

            return render_template(
                "login.html"
            )

        if not user.is_active:

            flash(
                "This account is inactive.",
                "danger"
            )

            return render_template(
                "login.html"
            )

        session.clear()

        session["user_id"] = user.id

        flash(
            "Login successful.",
            "success"
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

    employees = (
        Employee.query
        .filter_by(
            company_id=user.company_id
        )
        .order_by(
            Employee.last_name.asc()
        )
        .all()
    )

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

        employee_number = request.form.get(
            "employee_number",
            ""
        ).strip()

        first_name = request.form.get(
            "first_name",
            ""
        ).strip()

        last_name = request.form.get(
            "last_name",
            ""
        ).strip()

        date_of_birth = request.form.get(
            "date_of_birth",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        job_title = request.form.get(
            "job_title",
            ""
        ).strip()

        monthly_salary = safe_float(
            request.form.get(
                "monthly_salary"
            )
        )

        if (
            not employee_number
            or not first_name
            or not last_name
        ):

            flash(
                "Employee number, first name and last name are required.",
                "danger"
            )

            return render_template(
                "employee_form.html"
            )

        # ----------------------------------------------------
        # DATE OF BIRTH
        # ----------------------------------------------------

        parsed_date_of_birth = None

        if date_of_birth:

            try:

                parsed_date_of_birth = (
                    datetime.strptime(
                        date_of_birth,
                        "%Y-%m-%d"
                    ).date()
                )

            except ValueError:

                flash(
                    "Please enter a valid date of birth.",
                    "danger"
                )

                return render_template(
                    "employee_form.html"
                )

            if (
                parsed_date_of_birth
                > datetime.utcnow().date()
            ):

                flash(
                    "Date of birth cannot be in the future.",
                    "danger"
                )

                return render_template(
                    "employee_form.html"
                )

        # ----------------------------------------------------
        # CREATE EMPLOYEE
        # ----------------------------------------------------

        employee = Employee(
            company_id=user.company_id,
            employee_number=employee_number,
            first_name=first_name,
            last_name=last_name,
            date_of_birth=parsed_date_of_birth,
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
            url_for(
                "main.employees"
            )
        )

    return render_template(
        "employee_form.html"
    )


# ============================================================
# EMPLOYEE INVITATION
# ============================================================

@bp.route(
    "/employees/<int:employee_id>/invite"
)
@employer_required
def create_invitation(employee_id):

    user = current_user()

    employee = Employee.query.filter_by(
        id=employee_id,
        company_id=user.company_id,
    ).first_or_404()

    if employee.user_id:

        flash(
            "This employee already has an account.",
            "warning"
        )

        return redirect(
            url_for(
                "main.employees"
            )
        )

    token = secrets.token_urlsafe(
        32
    )

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
        _external=True,
    )

    return render_template(
        "invitation_created.html",
        invitation_url=invitation_url,
        employee=employee,
    )


# ============================================================
# ACCEPT EMPLOYEE INVITATION
# ============================================================

@bp.route(
    "/invite/<token>",
    methods=["GET", "POST"]
)
def accept_invitation(token):

    invitation = (
        EmployeeInvitation.query
        .filter_by(
            token=token
        )
        .first_or_404()
    )

    if not invitation.is_valid():

        flash(
            "This invitation is expired or has already been used.",
            "danger"
        )

        return redirect(
            url_for(
                "main.login"
            )
        )

    employee = invitation.employee

    if request.method == "POST":

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if len(password) < 8:

            flash(
                "Password must contain at least 8 characters.",
                "danger"
            )

            return render_template(
                "accept_invitation.html",
                invitation=invitation,
                employee=employee,
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "danger"
            )

            return render_template(
                "accept_invitation.html",
                invitation=invitation,
                employee=employee,
            )

        if not employee.email:

            flash(
                "This employee does not have an email address.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.login"
                )
            )

        existing_user = User.query.filter_by(
            email=employee.email.lower()
        ).first()

        if existing_user:

            flash(
                "An account already exists for this email.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.login"
                )
            )

        new_user = User(
            company_id=employee.company_id,
            name=(
                f"{employee.first_name} "
                f"{employee.last_name}"
            ),
            email=employee.email.lower(),
            password_hash=generate_password_hash(
                password
            ),
            role="employee",
            is_active=True,
        )

        db.session.add(new_user)

        db.session.flush()

        employee.user_id = new_user.id

        invitation.used = True

        db.session.commit()

        session.clear()

        session["user_id"] = new_user.id

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
            url_for(
                "main.logout"
            )
        )

    return render_template(
        "employee_dashboard.html",
        employee=employee,
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

    payslips = (
        Payslip.query
        .filter_by(
            employee_id=employee.id
        )
        .order_by(
            Payslip.pay_date.desc()
        )
        .all()
    )

    return render_template(
        "my_payslips.html",
        employee=employee,
        payslips=payslips,
    )


# ============================================================
# PAYROLL DASHBOARD
# ============================================================

@bp.route("/payroll")
@employer_required
def payroll():

    user = current_user()

    employees = (
        Employee.query
        .filter_by(
            company_id=user.company_id,
            status="Active",
        )
        .order_by(
            Employee.last_name.asc()
        )
        .all()
    )

    total_salary = sum(
        employee.monthly_salary or 0
        for employee in employees
    )

    return render_template(
        "payroll.html",
        employees=employees,
        total_salary=total_salary,
    )


# ============================================================
# CREATE PAYROLL
# ============================================================

@bp.route(
    "/payroll/create",
    methods=["POST"]
)
@employer_required
def create_payroll():

    user = current_user()

    pay_period = request.form.get(
        "pay_period",
        ""
    ).strip()

    pay_date_string = request.form.get(
        "pay_date",
        ""
    ).strip()

    if (
        not pay_period
        or not pay_date_string
    ):

        flash(
            "Payroll period and pay date are required.",
            "danger"
        )

        return redirect(
            url_for(
                "main.payroll"
            )
        )

    # --------------------------------------------------------
    # PAY DATE
    # --------------------------------------------------------

    try:

        pay_date = datetime.strptime(
            pay_date_string,
            "%Y-%m-%d"
        ).date()

    except ValueError:

        flash(
            "Invalid pay date.",
            "danger"
        )

        return redirect(
            url_for(
                "main.payroll"
            )
        )

    # --------------------------------------------------------
    # ACTIVE EMPLOYEES
    # --------------------------------------------------------

    employees = (
        Employee.query
        .filter_by(
            company_id=user.company_id,
            status="Active",
        )
        .order_by(
            Employee.last_name.asc()
        )
        .all()
    )

    if not employees:

        flash(
            "There are no active employees to process.",
            "warning"
        )

        return redirect(
            url_for(
                "main.payroll"
            )
        )

    # --------------------------------------------------------
    # PREVENT DUPLICATE PAYROLL
    # --------------------------------------------------------

    existing_payroll = (
        PayrollRun.query
        .filter_by(
            company_id=user.company_id,
            pay_period=pay_period,
        )
        .first()
    )

    if existing_payroll:

        flash(
            f"Payroll for {pay_period} already exists.",
            "warning"
        )

        return redirect(
            url_for(
                "main.view_payroll",
                payroll_id=existing_payroll.id,
            )
        )

    # --------------------------------------------------------
    # CREATE PAYROLL RUN
    # --------------------------------------------------------

    payroll_run = PayrollRun(
        company_id=user.company_id,
        pay_period=pay_period,
        pay_date=pay_date,
        status="Processing",
        total_gross=0,
        total_deductions=0,
        total_net=0,
        total_employer_uif=0,
        total_employer_cost=0,
    )

    db.session.add(
        payroll_run
    )

    db.session.flush()

    # --------------------------------------------------------
    # TOTALS
    # --------------------------------------------------------

    total_gross = 0.0

    total_deductions = 0.0

    total_net = 0.0

    total_employer_uif = 0.0

    total_employer_cost = 0.0

    # ========================================================
    # PROCESS EACH EMPLOYEE
    # ========================================================

    for employee in employees:

        # ----------------------------------------------------
        # BASIC SALARY
        # ----------------------------------------------------

        basic_salary = safe_float(
            employee.monthly_salary
        )

        # ----------------------------------------------------
        # EARNINGS
        # ----------------------------------------------------

        overtime = safe_float(
            request.form.get(
                f"overtime_{employee.id}"
            )
        )

        bonus = safe_float(
            request.form.get(
                f"bonus_{employee.id}"
            )
        )

        commission = safe_float(
            request.form.get(
                f"commission_{employee.id}"
            )
        )

        other_earnings = safe_float(
            request.form.get(
                f"other_earnings_{employee.id}"
            )
        )

        # ----------------------------------------------------
        # DEDUCTIONS
        # ----------------------------------------------------

        other_deductions = safe_float(
            request.form.get(
                f"other_deductions_{employee.id}"
            )
        )

        # ----------------------------------------------------
        # AGE
        # ----------------------------------------------------

        age = calculate_age_from_dob(
            employee.date_of_birth,
            pay_date
        )

        # Temporary fallback for employees
        # who do not yet have a date of birth.

        if age is None:

            age = 30

        # ----------------------------------------------------
        # VALIDATE AGE
        # ----------------------------------------------------

        if age < 0 or age > 120:

            flash(
                f"Invalid Date of Birth for "
                f"{employee.first_name} "
                f"{employee.last_name}.",
                "danger"
            )

            db.session.rollback()

            return redirect(
                url_for(
                    "main.payroll"
                )
            )

        # ====================================================
        # CALCULATE PAYROLL
        # ====================================================

        calculation = calculate_payroll(

            basic_salary=basic_salary,

            overtime=overtime,

            bonus=bonus,

            commission=commission,

            other_earnings=other_earnings,

            other_deductions=other_deductions,

            age=age,
        )

        # ----------------------------------------------------
        # EMPLOYEE VALUES
        # ----------------------------------------------------

        gross_pay = float(
            calculation["gross_pay"]
        )

        tax_deductions = float(
            calculation["paye"]
        )

        uif = float(
            calculation["uif"]
        )

        total_employee_deductions = float(
            calculation["total_deductions"]
        )

        net_pay = float(
            calculation["net_pay"]
        )

        # ----------------------------------------------------
        # EMPLOYER UIF
        # ----------------------------------------------------

        employer_uif = float(
            calculation.get(
                "employer_uif",
                0
            )
        )

        # ----------------------------------------------------
        # EMPLOYER COST
        # ----------------------------------------------------

        employer_cost = (
            gross_pay
            + employer_uif
        )

        # ====================================================
        # CREATE PAYSLIP
        # ====================================================

        payslip = Payslip(

            employee_id=employee.id,

            payroll_run_id=payroll_run.id,

            pay_period=pay_period,

            pay_date=pay_date,

            basic_salary=basic_salary,

            overtime=overtime,

            bonus=bonus,

            commission=commission,

            other_earnings=other_earnings,

            gross_pay=gross_pay,

            tax_deductions=tax_deductions,

            uif=uif,

            other_deductions=other_deductions,

            total_deductions=(
                total_employee_deductions
            ),

            net_pay=net_pay,

            employer_uif=employer_uif,

            employer_cost=employer_cost,
        )

        db.session.add(
            payslip
        )

        # ----------------------------------------------------
        # UPDATE TOTALS
        # ----------------------------------------------------

        total_gross += gross_pay

        total_deductions += (
            total_employee_deductions
        )

        total_net += net_pay

        total_employer_uif += (
            employer_uif
        )

        total_employer_cost += (
            employer_cost
        )

    # ========================================================
    # SAVE PAYROLL TOTALS
    # ========================================================

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

    payroll_run.status = "Completed"

    db.session.commit()

    flash(
        f"Payroll for {pay_period} processed successfully.",
        "success"
    )

    return redirect(
        url_for(
            "main.view_payroll",
            payroll_id=payroll_run.id,
        )
    )


# ============================================================
# PAYROLL HISTORY
# ============================================================

@bp.route("/payroll/history")
@employer_required
def payroll_history():

    user = current_user()

    payroll_runs = (
        PayrollRun.query
        .filter_by(
            company_id=user.company_id
        )
        .order_by(
            PayrollRun.pay_date.desc()
        )
        .all()
    )

    return render_template(
        "payroll_history.html",
        payroll_runs=payroll_runs,
    )


# ============================================================
# VIEW PAYROLL RUN
# ============================================================

@bp.route(
    "/payroll/<int:payroll_id>"
)
@employer_required
def view_payroll(payroll_id):

    user = current_user()

    payroll_run = (
        PayrollRun.query
        .filter_by(
            id=payroll_id,
            company_id=user.company_id,
        )
        .first_or_404()
    )

    payslips = (
        Payslip.query
        .join(Employee)
        .filter(
            Payslip.payroll_run_id
            == payroll_run.id,

            Employee.company_id
            == user.company_id,
        )
        .order_by(
            Employee.last_name.asc()
        )
        .all()
    )

    return render_template(
        "payroll_run.html",
        payroll_run=payroll_run,
        payslips=payslips,
    )


# ============================================================
# VIEW INDIVIDUAL PAYSLIP
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
            "Employee record could not be found.",
            "danger"
        )

        return redirect(
            url_for(
                "main.dashboard"
            )
        )

    # --------------------------------------------------------
    # EMPLOYER / ADMIN
    # --------------------------------------------------------

    if user.role in [
        "employer",
        "admin"
    ]:

        if (
            employee.company_id
            != user.company_id
        ):

            flash(
                "You do not have permission to view this payslip.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.dashboard"
                )
            )

    # --------------------------------------------------------
    # EMPLOYEE
    # --------------------------------------------------------

    elif user.role == "employee":

        if employee.user_id != user.id:

            flash(
                "You do not have permission to view this payslip.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.employee_dashboard"
                )
            )

    else:

        flash(
            "You do not have permission to view this payslip.",
            "danger"
        )

        return redirect(
            url_for(
                "main.login"
            )
        )

    return render_template(
        "payslip.html",
        payslip=payslip,
        employee=employee,
        company=employee.company,
    )


# ============================================================
# PAYSLIP PDF
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
            "Employee record could not be found.",
            "danger"
        )

        return redirect(
            url_for(
                "main.dashboard"
            )
        )

    # --------------------------------------------------------
    # AUTHORIZATION
    # --------------------------------------------------------

    if user.role in [
        "employer",
        "admin"
    ]:

        if (
            employee.company_id
            != user.company_id
        ):

            flash(
                "You do not have permission to download this payslip.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.dashboard"
                )
            )

    elif user.role == "employee":

        if employee.user_id != user.id:

            flash(
                "You do not have permission to download this payslip.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.employee_dashboard"
                )
            )

    else:

        flash(
            "You do not have permission to download this payslip.",
            "danger"
        )

        return redirect(
            url_for(
                "main.login"
            )
        )

    # ========================================================
    # CREATE PDF
    # ========================================================

    buffer = BytesIO()

    pdf = canvas.Canvas(
        buffer,
        pagesize=A4,
    )

    width, height = A4

    y = height - 50

    # ========================================================
    # HEADER
    # ========================================================

    pdf.setFont(
        "Helvetica-Bold",
        18
    )

    pdf.drawString(
        50,
        y,
        "APPEX PAYROLL"
    )

    y -= 25

    pdf.setFont(
        "Helvetica",
        10
    )

    pdf.drawString(
        50,
        y,
        str(employee.company.name)
    )

    y -= 20

    pdf.line(
        50,
        y,
        width - 50,
        y
    )

    y -= 30

    pdf.setFont(
        "Helvetica-Bold",
        15
    )

    pdf.drawString(
        50,
        y,
        "EMPLOYEE PAYSLIP"
    )

    y -= 30

    # ========================================================
    # EMPLOYEE INFORMATION
    # ========================================================

    pdf.setFont(
        "Helvetica-Bold",
        10
    )

    pdf.drawString(
        50,
        y,
        "Employee:"
    )

    pdf.setFont(
        "Helvetica",
        10
    )

    pdf.drawString(
        120,
        y,
        f"{employee.first_name} "
        f"{employee.last_name}"
    )

    y -= 18

    pdf.setFont(
        "Helvetica-Bold",
        10
    )

    pdf.drawString(
        50,
        y,
        "Employee No:"
    )

    pdf.setFont(
        "Helvetica",
        10
    )

    pdf.drawString(
        120,
        y,
        str(employee.employee_number)
    )

    y -= 18

    pdf.setFont(
        "Helvetica-Bold",
        10
    )

    pdf.drawString(
        50,
        y,
        "Pay Period:"
    )

    pdf.setFont(
        "Helvetica",
        10
    )

    pdf.drawString(
        120,
        y,
        str(payslip.pay_period)
    )

    y -= 18

    pdf.setFont(
        "Helvetica-Bold",
        10
    )

    pdf.drawString(
        50,
        y,
        "Pay Date:"
    )

    pdf.setFont(
        "Helvetica",
        10
    )

    pdf.drawString(
        120,
        y,
        str(payslip.pay_date)
    )

    y -= 35

    # ========================================================
    # EARNINGS
    # ========================================================

    pdf.setFont(
        "Helvetica-Bold",
        12
    )

    pdf.drawString(
        50,
        y,
        "Earnings"
    )

    y -= 22

    pdf.setFont(
        "Helvetica-Bold",
        10
    )

    pdf.drawString(
        60,
        y,
        "Description"
    )

    pdf.drawRightString(
        width - 60,
        y,
        "Amount"
    )

    y -= 18

    pdf.setFont(
        "Helvetica",
        10
    )

    earnings = [

        (
            "Basic Salary",
            payslip.basic_salary
        ),

        (
            "Overtime",
            payslip.overtime
        ),

        (
            "Bonus",
            payslip.bonus
        ),

        (
            "Commission",
            payslip.commission
        ),

        (
            "Other Earnings",
            payslip.other_earnings
        ),

    ]

    for description, amount in earnings:

        pdf.drawString(
            60,
            y,
            description
        )

        pdf.drawRightString(
            width - 60,
            y,
            f"R {amount or 0:.2f}"
        )

        y -= 17

    pdf.line(
        50,
        y + 5,
        width - 50,
        y + 5
    )

    pdf.setFont(
        "Helvetica-Bold",
        10
    )

    pdf.drawString(
        60,
        y - 10,
        "Gross Pay"
    )

    pdf.drawRightString(
        width - 60,
        y - 10,
        f"R {payslip.gross_pay or 0:.2f}"
    )

    y -= 40

    # ========================================================
    # DEDUCTIONS
    # ========================================================

    pdf.setFont(
        "Helvetica-Bold",
        12
    )

    pdf.drawString(
        50,
        y,
        "Deductions"
    )

    y -= 22

    pdf.setFont(
        "Helvetica-Bold",
        10
    )

    pdf.drawString(
        60,
        y,
        "Description"
    )

    pdf.drawRightString(
        width - 60,
        y,
        "Amount"
    )

    y -= 18

    pdf.setFont(
        "Helvetica",
        10
    )

    deductions = [

        (
            "PAYE",
            payslip.tax_deductions
        ),

        (
            "UIF",
            payslip.uif
        ),

        (
            "Other Deductions",
            payslip.other_deductions
        ),

    ]

    for description, amount in deductions:

        pdf.drawString(
            60,
            y,
            description
        )

        pdf.drawRightString(
            width - 60,
            y,
            f"R {amount or 0:.2f}"
        )

        y -= 17

    pdf.line(
        50,
        y + 5,
        width - 50,
        y + 5
    )

    pdf.setFont(
        "Helvetica-Bold",
        10
    )

    pdf.drawString(
        60,
        y - 10,
        "Total Deductions"
    )

    pdf.drawRightString(
        width - 60,
        y - 10,
        f"R {payslip.total_deductions or 0:.2f}"
    )

    y -= 45

    # ========================================================
    # NET PAY
    # ========================================================

    pdf.setFont(
        "Helvetica-Bold",
        14
    )

    pdf.drawString(
        50,
        y,
        "NET PAY"
    )

    pdf.drawRightString(
        width - 60,
        y,
        f"R {payslip.net_pay or 0:.2f}"
    )

    y -= 35

    # ========================================================
    # EMPLOYER CONTRIBUTIONS
    # ========================================================

    pdf.setFont(
        "Helvetica-Bold",
        11
    )

    pdf.drawString(
        50,
        y,
        "Employer Contributions"
    )

    y -= 20

    pdf.setFont(
        "Helvetica",
        10
    )

    pdf.drawString(
        60,
        y,
        "Employer UIF"
    )

    pdf.drawRightString(
        width - 60,
        y,
        f"R {payslip.employer_uif or 0:.2f}"
    )

    y -= 18

    pdf.drawString(
        60,
        y,
        "Total Employer Cost"
    )

    pdf.drawRightString(
        width - 60,
        y,
        f"R {payslip.employer_cost or 0:.2f}"
    )

    y -= 35

    # ========================================================
    # FOOTER
    # ========================================================

    pdf.setFont(
        "Helvetica",
        9
    )

    pdf.drawString(
        50,
        y,
        "Generated by Appex Payroll."
    )

    y -= 15

    pdf.drawString(
        50,
        y,
        "PAYE and UIF values are calculated by "
        "the Appex payroll calculator."
    )

    pdf.save()

    buffer.seek(0)

    filename = (
        f"payslip_"
        f"{employee.employee_number}_"
        f"{payslip.pay_period.replace(' ', '_')}.pdf"
    )

    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


# ============================================================
# DEEL INTEGRATION
# ============================================================

@bp.route("/integration")
@employer_required
def integration():

    configured = all([
        os.getenv("DEEL_AUTH_URL"),
        os.getenv("DEEL_API_URL"),
        os.getenv("DEEL_CLIENT_ID"),
        os.getenv("DEEL_CLIENT_SECRET"),
    ])

    return render_template(
        "integration.html",

        configured=configured,

        deel_auth_url=os.getenv(
            "DEEL_AUTH_URL"
        ),

        deel_api_url=os.getenv(
            "DEEL_API_URL"
        ),

        deel_client_id=os.getenv(
            "DEEL_CLIENT_ID"
        ),
    )


# ============================================================
# PAYROLL CALCULATOR TEST
# ============================================================

@bp.route(
    "/payroll-calculator-test"
)
@login_required
def payroll_calculator_test():

    result = calculate_payroll(

        basic_salary=15000,

        overtime=1000,

        bonus=500,

        commission=750,

        other_earnings=250,

        other_deductions=300,

        age=30,
    )

    return jsonify({

        "tax_year": str(
            result["tax_year"]
        ),

        "basic_salary": str(
            result["basic_salary"]
        ),

        "overtime": str(
            result["overtime"]
        ),

        "bonus": str(
            result["bonus"]
        ),

        "commission": str(
            result["commission"]
        ),

        "other_earnings": str(
            result["other_earnings"]
        ),

        "gross_pay": str(
            result["gross_pay"]
        ),

        "paye": str(
            result["paye"]
        ),

        "uif": str(
            result["uif"]
        ),

        "other_deductions": str(
            result["other_deductions"]
        ),

        "total_deductions": str(
            result["total_deductions"]
        ),

        "net_pay": str(
            result["net_pay"]
        ),

        "employer_uif": str(
            result["employer_uif"]
        ),

    })
