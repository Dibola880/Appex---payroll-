from datetime import datetime, timedelta
from functools import wraps
import os
import secrets

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)

from werkzeug.security import generate_password_hash, check_password_hash

from . import db
from .models import (
    Company,
    User,
    Employee,
    EmployeeInvitation,
    PayrollRun,
    Payslip
)


bp = Blueprint("main", __name__)


# =========================================================
# AUTHENTICATION HELPERS
# =========================================================

def current_user():
    """Return the currently logged-in user."""
    user_id = session.get("user_id")

    if not user_id:
        return None

    return db.session.get(User, user_id)


def login_required(view):
    """Require a logged-in user."""

    @wraps(view)
    def wrapped_view(*args, **kwargs):

        user = current_user()

        if not user or not user.is_active:
            session.clear()

            flash(
                "Please log in to continue.",
                "warning"
            )

            return redirect(
                url_for("main.login")
            )

        return view(*args, **kwargs)

    return wrapped_view


def role_required(*roles):
    """Require the logged-in user to have one of the specified roles."""

    def decorator(view):

        @wraps(view)
        def wrapped_view(*args, **kwargs):

            user = current_user()

            if not user or not user.is_active:
                session.clear()

                flash(
                    "Please log in to continue.",
                    "warning"
                )

                return redirect(
                    url_for("main.login")
                )

            if user.role not in roles:

                flash(
                    "You do not have permission to access this page.",
                    "danger"
                )

                if user.role == "employee":
                    return redirect(
                        url_for("main.employee_dashboard")
                    )

                return redirect(
                    url_for("main.dashboard")
                )

            return view(*args, **kwargs)

        return wrapped_view

    return decorator


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
def index():

    user = current_user()

    if not user:
        return redirect(
            url_for("main.login")
        )

    if user.role == "employee":
        return redirect(
            url_for("main.employee_dashboard")
        )

    return redirect(
        url_for("main.dashboard")
    )


@bp.get("/dashboard")
@role_required("employer", "admin")
def dashboard():

    user = current_user()
    company = user.company

    employees = (
        Employee.query
        .filter_by(company_id=company.id)
        .order_by(Employee.last_name)
        .all()
    )

    total_salary = sum(
        e.monthly_salary or 0
        for e in employees
        if e.status == "Active"
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
            url_for("main.index")
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
                "Password must contain at least 8 characters.",
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
                "An account with that email already exists.",
                "danger"
            )

            return redirect(
                url_for("main.login")
            )

        company = Company(
            name=company_name
        )

        db.session.add(company)
        db.session.flush()

        user = User(
            company_id=company.id,
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
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
            url_for("main.index")
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

        if not user or not check_password_hash(
            user.password_hash,
            password
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
                "Your account is inactive.",
                "danger"
            )

            return render_template(
                "login.html"
            )

        session.clear()
        session["user_id"] = user.id

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
@role_required("employer", "admin")
def employees():

    user = current_user()
    company = user.company

    rows = (
        Employee.query
        .filter_by(company_id=company.id)
        .order_by(Employee.last_name)
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

@bp.route("/employees/new", methods=["GET", "POST"])
@role_required("employer", "admin")
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
        )

        if not employee_number or not first_name or not last_name:

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

        except ValueError:

            flash(
                "Please enter a valid monthly salary.",
                "danger"
            )

            return render_template(
                "employee_form.html",
                company=company
            )

        if monthly_salary < 0:

            flash(
                "Monthly salary cannot be negative.",
                "danger"
            )

            return render_template(
                "employee_form.html",
                company=company
            )

        existing_employee = Employee.query.filter_by(
            company_id=company.id,
            employee_number=employee_number
        ).first()

        if existing_employee:

            flash(
                "That employee number already exists.",
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
# CREATE EMPLOYEE INVITATION
# =========================================================

@bp.get("/employees/<int:employee_id>/invite")
@role_required("employer", "admin")
def create_invitation(employee_id):

    user = current_user()

    employee = Employee.query.filter_by(
        id=employee_id,
        company_id=user.company_id
    ).first_or_404()

    if not employee.email:

        flash(
            "This employee does not have an email address.",
            "danger"
        )

        return redirect(
            url_for("main.employees")
        )

    token = secrets.token_urlsafe(48)

    invitation = EmployeeInvitation(
        employee_id=employee.id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=48),
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
        company=user.company,
        employee=employee,
        invitation_url=invitation_url
    )


# =========================================================
# ACCEPT EMPLOYEE INVITATION
# =========================================================

@bp.route("/invite/<token>", methods=["GET", "POST"])
def accept_invitation(token):

    invitation = EmployeeInvitation.query.filter_by(
        token=token
    ).first()

    if not invitation:

        flash(
            "This invitation is invalid.",
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
                employee=employee,
                invitation=invitation
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "danger"
            )

            return render_template(
                "accept_invitation.html",
                employee=employee,
                invitation=invitation
            )

        if not employee.email:

            flash(
                "The employee does not have an email address.",
                "danger"
            )

            return redirect(
                url_for("main.login")
            )

        existing_user = User.query.filter_by(
            email=employee.email.lower()
        ).first()

        if existing_user:

            employee.user_id = existing_user.id
            invitation.used = True

            db.session.commit()

            flash(
                "An account already exists for this employee.",
                "info"
            )

            return redirect(
                url_for("main.login")
            )

        user = User(
            company_id=employee.company_id,
            name=f"{employee.first_name} {employee.last_name}",
            email=employee.email.lower(),
            password_hash=generate_password_hash(password),
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
        employee=employee,
        invitation=invitation
    )


# =========================================================
# EMPLOYEE DASHBOARD
# =========================================================

@bp.get("/employee/dashboard")
@role_required("employee")
def employee_dashboard():

    user = current_user()

    employee = user.employee

    if not employee:

        flash(
            "Your employee profile could not be found.",
            "danger"
        )

        return redirect(
            url_for("main.logout")
        )

    return render_template(
        "employee_dashboard.html",
        employee=employee
    )


# =========================================================
# EMPLOYEE PAYSLIPS
# =========================================================

@bp.get("/employee/payslips")
@role_required("employee")
def my_payslips():

    user = current_user()

    employee = user.employee

    if not employee:

        flash(
            "Your employee profile could not be found.",
            "danger"
        )

        return redirect(
            url_for("main.logout")
        )

    payslips = (
        Payslip.query
        .filter_by(employee_id=employee.id)
        .order_by(Payslip.pay_date.desc())
        .all()
    )

    return render_template(
        "my_payslips.html",
        employee=employee,
        payslips=payslips
    )


# =========================================================
# PAYROLL
# =========================================================

@bp.get("/payroll")
@role_required("employer", "admin")
def payroll():

    user = current_user()
    company = user.company

    rows = (
        Employee.query
        .filter_by(
            company_id=company.id,
            status="Active"
        )
        .order_by(Employee.last_name)
        .all()
    )

    gross = sum(
        e.monthly_salary or 0
        for e in rows
    )

    return render_template(
        "payroll.html",
        company=company,
        employees=rows,
        total_salary=gross
    )


# =========================================================
# DEEL INTEGRATION
# =========================================================

@bp.get("/integration")
@role_required("employer", "admin")
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
        company=current_user().company,
        configured=configured
        )
