import os
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)

from werkzeug.security import generate_password_hash, check_password_hash

from . import db
from .models import (
    Company,
    User,
    Employee,
    EmployeeInvitation,
    PayrollRun,
    Payslip,
)


bp = Blueprint("main", __name__)


# =========================================================
# AUTHENTICATION HELPERS
# =========================================================

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
                "You do not have permission to access this page.",
                "danger"
            )

            return redirect(
                url_for("main.employee_dashboard")
            )

        return view(*args, **kwargs)

    return wrapped_view


# =========================================================
# GLOBAL USER CONTEXT
# =========================================================

@bp.app_context_processor
def inject_user():

    return {
        "current_user": current_user()
    }


# =========================================================
# HEALTH CHECK
# =========================================================

@bp.get("/health")
def health():

    return {
        "status": "ok",
        "service": "appex-payroll"
    }


# =========================================================
# HOME / DASHBOARD
# =========================================================

@bp.get("/")
@login_required
def dashboard():

    user = current_user()

    # Employees go to employee dashboard
    if user.role == "employee":

        return redirect(
            url_for("main.employee_dashboard")
        )

    company = user.company

    employees = (
        Employee.query
        .filter_by(
            company_id=company.id
        )
        .order_by(
            Employee.last_name
        )
        .all()
    )

    total_salary = sum(
        employee.monthly_salary or 0
        for employee in employees
        if employee.status == "Active"
    )

    return render_template(
        "dashboard.html",
        company=company,
        employees=employees,
        total_salary=total_salary
    )


# =========================================================
# REGISTRATION
# =========================================================

@bp.route("/register", methods=["GET", "POST"])
def register():

    if current_user():

        return redirect(
            url_for("main.dashboard")
        )

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

        if not company_name or not name or not email:

            flash(
                "Please complete all required fields.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        if len(password) < 8:

            flash(
                "Password must be at least 8 characters.",
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

        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:

            flash(
                "An account with this email already exists.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        company = Company(
            name=company_name,
            payroll_provider="Deel Local Payroll"
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
            is_active=True
        )

        db.session.add(user)

        db.session.commit()

        session.clear()
        session["user_id"] = user.id

        flash(
            "Your Appex Payroll account has been created.",
            "success"
        )

        return redirect(
            url_for("main.dashboard")
        )

    return render_template(
        "register.html"
    )


# =========================================================
# LOGIN
# =========================================================

@bp.route("/login", methods=["GET", "POST"])
def login():

    if current_user():

        return redirect(
            url_for("main.dashboard")
        )

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
            or not user.is_active
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

        session.clear()
        session["user_id"] = user.id

        flash(
            "Welcome back.",
            "success"
        )

        if user.role == "employee":

            return redirect(
                url_for("main.employee_dashboard")
            )

        return redirect(
            url_for("main.dashboard")
        )

    return render_template(
        "login.html"
    )


# =========================================================
# LOGOUT
# =========================================================

@bp.get("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(
        url_for("main.login")
    )


# =========================================================
# EMPLOYEES
# =========================================================

@bp.get("/employees")
@employer_required
def employees():

    user = current_user()

    company = user.company

    rows = (
        Employee.query
        .filter_by(
            company_id=company.id
        )
        .order_by(
            Employee.last_name
        )
        .all()
    )

    return render_template(
        "employees.html",
        company=company,
        employees=rows
    )


# =========================================================
# ADD EMPLOYEE
# =========================================================

@bp.route(
    "/employees/new",
    methods=["GET", "POST"]
)
@employer_required
def new_employee():

    user = current_user()

    company = user.company

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

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        job_title = request.form.get(
            "job_title",
            ""
        ).strip()

        salary_text = request.form.get(
            "monthly_salary",
            "0"
        ).strip()

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
                "employee_form.html",
                company=company
            )

        try:

            monthly_salary = float(
                salary_text or 0
            )

            if monthly_salary < 0:
                raise ValueError

        except ValueError:

            flash(
                "Please enter a valid monthly salary.",
                "danger"
            )

            return render_template(
                "employee_form.html",
                company=company
            )

        employee = Employee(
            company_id=company.id,
            employee_number=employee_number,
            first_name=first_name,
            last_name=last_name,
            email=email,
            job_title=job_title,
            monthly_salary=monthly_salary,
            status="Active"
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
        "employee_form.html",
        company=company
    )


# =========================================================
# EMPLOYEE INVITATION
# =========================================================

@bp.get(
    "/employees/<int:employee_id>/invite"
)
@employer_required
def create_invitation(employee_id):

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
        used=False
    )

    db.session.add(invitation)

    db.session.commit()

    invitation_url = url_for(
        "main.accept_invitation",
        token=token,
        _external=True
    )

    return render_template(
        "invitation_created.html",
        invitation_url=invitation_url,
        employee=employee
    )


# =========================================================
# ACCEPT EMPLOYEE INVITATION
# =========================================================

@bp.route(
    "/invite/<token>",
    methods=["GET", "POST"]
)
def accept_invitation(token):

    invitation = EmployeeInvitation.query.filter_by(
        token=token
    ).first()

    if (
        not invitation
        or not invitation.is_valid()
    ):

        return """
        <h2>Invitation expired or invalid</h2>
        <p>
            Please contact your employer and
            request a new invitation.
        </p>
        """

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
                "Password must be at least 8 characters.",
                "danger"
            )

            return render_template(
                "accept_invitation.html",
                invitation=invitation,
                employee=employee
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "danger"
            )

            return render_template(
                "accept_invitation.html",
                invitation=invitation,
                employee=employee
            )

        email = (
            employee.email.strip().lower()
            if employee.email
            else None
        )

        if not email:

            flash(
                "This employee does not have an email address.",
                "danger"
            )

            return render_template(
                "accept_invitation.html",
                invitation=invitation,
                employee=employee
            )

        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:

            flash(
                "An account already exists with this email address.",
                "danger"
            )

            return redirect(
                url_for("main.login")
            )

        user = User(
            company_id=employee.company_id,
            name=(
                f"{employee.first_name} "
                f"{employee.last_name}"
            ),
            email=email,
            password_hash=generate_password_hash(
                password
            ),
            role="employee",
            is_active=True
        )

        db.session.add(user)

        db.session.flush()

        employee.user_id = user.id

        invitation.used = True

        db.session.commit()

        session.clear()
        session["user_id"] = user.id

        flash(
            "Your employee account has been created.",
            "success"
        )

        return redirect(
            url_for("main.employee_dashboard")
        )

    return render_template(
        "accept_invitation.html",
        invitation=invitation,
        employee=employee
    )


# =========================================================
# EMPLOYEE DASHBOARD
# =========================================================

@bp.get("/employee")
@login_required
def employee_dashboard():

    user = current_user()

    if user.role != "employee":

        return redirect(
            url_for("main.dashboard")
        )

    employee = Employee.query.filter_by(
        user_id=user.id,
        company_id=user.company_id
    ).first()

    if not employee:

        flash(
            "Your employee profile has not been linked yet.",
            "warning"
        )

        return redirect(
            url_for("main.logout")
        )

    return render_template(
        "employee_dashboard.html",
        employee=employee
    )


# =========================================================
# EMPLOYEE MY PAYSLIPS
# =========================================================

@bp.get("/my-payslips")
@login_required
def my_payslips():

    user = current_user()

    if user.role != "employee":

        return redirect(
            url_for("main.dashboard")
        )

    employee = Employee.query.filter_by(
        user_id=user.id,
        company_id=user.company_id
    ).first()

    if not employee:

        flash(
            "Employee profile not found.",
            "danger"
        )

        return redirect(
            url_for("main.employee_dashboard")
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
        payslips=payslips
    )


# =========================================================
# PAYROLL DASHBOARD
# =========================================================

@bp.get("/payroll")
@employer_required
def payroll():

    user = current_user()

    company = user.company

    employees = (
        Employee.query
        .filter_by(
            company_id=company.id,
            status="Active"
        )
        .order_by(
            Employee.last_name
        )
        .all()
    )

    total_basic_salary = sum(
        employee.monthly_salary or 0
        for employee in employees
    )

    return render_template(
        "payroll.html",
        company=company,
        employees=employees,
        total_salary=total_basic_salary
    )


# =========================================================
# CREATE PAYROLL RUN
# =========================================================

@bp.route(
    "/payroll/create",
    methods=["POST"]
)
@employer_required
def create_payroll():

    user = current_user()

    company = user.company

    pay_period = request.form.get(
        "pay_period",
        ""
    ).strip()

    pay_date_text = request.form.get(
        "pay_date",
        ""
    ).strip()

    if not pay_period:

        flash(
            "Please enter a payroll period.",
            "danger"
        )

        return redirect(
            url_for("main.payroll")
        )

    if not pay_date_text:

        flash(
            "Please enter a pay date.",
            "danger"
        )

        return redirect(
            url_for("main.payroll")
        )

    try:

        pay_date = datetime.strptime(
            pay_date_text,
            "%Y-%m-%d"
        ).date()

    except ValueError:

        flash(
            "Please enter a valid pay date.",
            "danger"
        )

        return redirect(
            url_for("main.payroll")
        )

    employees = (
        Employee.query
        .filter_by(
            company_id=company.id,
            status="Active"
        )
        .all()
    )

    if not employees:

        flash(
            "There are no active employees to process.",
            "warning"
        )

        return redirect(
            url_for("main.payroll")
        )

    # Prevent duplicate payroll runs
    existing_run = PayrollRun.query.filter_by(
        company_id=company.id,
        pay_period=pay_period
    ).first()

    if existing_run:

        flash(
            "A payroll run already exists for this pay period.",
            "warning"
        )

        return redirect(
            url_for("main.payroll")
        )

    payroll_run = PayrollRun(
        company_id=company.id,
        pay_period=pay_period,
        pay_date=pay_date,
        status="Processing",
        total_gross=0,
        total_deductions=0,
        total_net=0
    )

    db.session.add(payroll_run)

    db.session.flush()

    total_gross = 0
    total_deductions = 0
    total_net = 0

    for employee in employees:

        basic_salary = float(
            employee.monthly_salary or 0
        )

        # -------------------------------------------------
        # Phase 3 basic payroll calculation
        # -------------------------------------------------

        other_earnings = 0.0

        # PAYE/UIF calculations will be added
        # in the statutory payroll phase.
        tax_deductions = 0.0

        other_deductions = 0.0

        gross_pay = (
            basic_salary
            + other_earnings
        )

        employee_total_deductions = (
            tax_deductions
            + other_deductions
        )

        net_pay = (
            gross_pay
            - employee_total_deductions
        )

        payslip = Payslip(

            employee_id=employee.id,

            payroll_run_id=payroll_run.id,

            pay_period=pay_period,

            pay_date=pay_date,

            basic_salary=basic_salary,

            other_earnings=other_earnings,

            gross_pay=gross_pay,

            tax_deductions=tax_deductions,

            other_deductions=other_deductions,

            total_deductions=(
                employee_total_deductions
            ),

            net_pay=net_pay
        )

        db.session.add(payslip)

        total_gross += gross_pay

        total_deductions += (
            employee_total_deductions
        )

        total_net += net_pay

    payroll_run.total_gross = total_gross

    payroll_run.total_deductions = (
        total_deductions
    )

    payroll_run.total_net = total_net

    payroll_run.status = "Completed"

    db.session.commit()

    flash(
        f"Payroll processed successfully for {pay_period}.",
        "success"
    )

    return redirect(
        url_for(
            "main.payroll_history"
        )
    )


# =========================================================
# PAYROLL HISTORY
# =========================================================

@bp.get("/payroll/history")
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
        payroll_runs=payroll_runs
    )


# =========================================================
# VIEW PAYROLL RUN
# =========================================================

@bp.get(
    "/payroll/<int:payroll_id>"
)
@employer_required
def view_payroll(payroll_id):

    user = current_user()

    payroll_run = PayrollRun.query.filter_by(
        id=payroll_id,
        company_id=user.company_id
    ).first_or_404()

    payslips = (
        Payslip.query
        .join(Employee)
        .filter(
            Payslip.payroll_run_id
            == payroll_run.id,

            Employee.company_id
            == user.company_id
        )
        .order_by(
            Employee.last_name
        )
        .all()
    )

    return render_template(
        "payroll_run.html",
        payroll_run=payroll_run,
        payslips=payslips
    )


# =========================================================
# VIEW INDIVIDUAL PAYSLIP
# =========================================================
#
# IMPORTANT:
# This route uses @login_required instead of
# @employer_required so BOTH employers and employees
# can view payslips.
#
# Employers can view their company's payslips.
# Employees can ONLY view their own payslips.
# =========================================================

@bp.get(
    "/payroll/payslip/<int:payslip_id>"
)
@login_required
def view_payslip(payslip_id):

    user = current_user()

    payslip = Payslip.query.get_or_404(
        payslip_id
    )

    # -----------------------------------------------------
    # EMPLOYER / ADMIN ACCESS
    # -----------------------------------------------------

    if user.role in ["employer", "admin"]:

        if (
            not payslip.employee
            or payslip.employee.company_id
            != user.company_id
        ):

            flash(
                "You do not have permission to view this payslip.",
                "danger"
            )

            return redirect(
                url_for("main.payroll")
            )

    # -----------------------------------------------------
    # EMPLOYEE ACCESS
    # -----------------------------------------------------

    elif user.role == "employee":

        if not payslip.employee:

            flash(
                "Employee record not found.",
                "danger"
            )

            return redirect(
                url_for("main.employee_dashboard")
            )

        if (
            payslip.employee.user_id
            != user.id
        ):

            flash(
                "You do not have permission to view this payslip.",
                "danger"
            )

            return redirect(
                url_for("main.my_payslips")
            )

    # -----------------------------------------------------
    # UNKNOWN ROLE
    # -----------------------------------------------------

    else:

        flash(
            "You do not have permission to view this payslip.",
            "danger"
        )

        return redirect(
            url_for("main.dashboard")
        )

    # -----------------------------------------------------
    # DISPLAY PAYSLIP
    # -----------------------------------------------------

    return render_template(
        "payslip.html",
        payslip=payslip
    )


# =========================================================
# DEEL INTEGRATION
# =========================================================

@bp.get("/integration")
@employer_required
def integration():

    configured = all(
        os.getenv(key)
        for key in [
            "DEEL_AUTH_URL",
            "DEEL_API_URL",
            "DEEL_CLIENT_ID",
            "DEEL_CLIENT_SECRET"
        ]
    )

    return render_template(
        "integration.html",
        configured=configured
    )
