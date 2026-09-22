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


# ---------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------

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
            flash("Please log in to continue.", "warning")
            return redirect(url_for("main.login"))

        return view(*args, **kwargs)

    return wrapped_view


def employer_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user = current_user()

        if not user:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("main.login"))

        if user.role not in ["employer", "admin"]:
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for("main.employee_dashboard"))

        return view(*args, **kwargs)

    return wrapped_view


@bp.app_context_processor
def inject_user():
    return {
        "current_user": current_user()
    }


# ---------------------------------------------------------
# Health check
# ---------------------------------------------------------

@bp.get("/health")
def health():
    return {
        "status": "ok",
        "service": "appex-payroll"
    }


# ---------------------------------------------------------
# Home / Dashboard
# ---------------------------------------------------------

@bp.get("/")
@login_required
def dashboard():
    user = current_user()

    if user.role == "employee":
        return redirect(url_for("main.employee_dashboard"))

    company = user.company

    employees = (
        Employee.query
        .filter_by(company_id=company.id)
        .order_by(Employee.last_name)
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


# ---------------------------------------------------------
# Registration
# ---------------------------------------------------------

@bp.route("/register", methods=["GET", "POST"])
def register():

    if current_user():
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":

        company_name = request.form.get(
            "company_name", ""
        ).strip()

        name = request.form.get(
            "name", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        confirm_password = request.form.get(
            "confirm_password", ""
        )

        if not company_name or not name or not email:
            flash("Please complete all required fields.", "danger")
            return render_template("register.html")

        if len(password) < 8:
            flash(
                "Password must be at least 8 characters.",
                "danger"
            )
            return render_template("register.html")

        if password != confirm_password:
            flash(
                "Passwords do not match.",
                "danger"
            )
            return render_template("register.html")

        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:
            flash(
                "An account with this email already exists.",
                "danger"
            )
            return render_template("register.html")

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

        return redirect(url_for("main.dashboard"))

    return render_template("register.html")


# ---------------------------------------------------------
# Login
# ---------------------------------------------------------

@bp.route("/login", methods=["GET", "POST"])
def login():

    if current_user():
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
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
            return render_template("login.html")

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

    return render_template("login.html")


# ---------------------------------------------------------
# Logout
# ---------------------------------------------------------

@bp.get("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(url_for("main.login"))


# ---------------------------------------------------------
# Employees
# ---------------------------------------------------------

@bp.get("/employees")
@employer_required
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


# ---------------------------------------------------------
# Add employee
# ---------------------------------------------------------

@bp.route("/employees/new", methods=["GET", "POST"])
@employer_required
def new_employee():

    user = current_user()
    company = user.company

    if request.method == "POST":

        employee_number = request.form.get(
            "employee_number", ""
        ).strip()

        first_name = request.form.get(
            "first_name", ""
        ).strip()

        last_name = request.form.get(
            "last_name", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        job_title = request.form.get(
            "job_title", ""
        ).strip()

        salary_text = request.form.get(
            "monthly_salary", "0"
        ).strip()

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


# ---------------------------------------------------------
# Employee invitation
# ---------------------------------------------------------

@bp.get("/employees/<int:employee_id>/invite")
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
        invitation_url=invitation_url,
        employee=employee
    )


# ---------------------------------------------------------
# Accept employee invitation
# ---------------------------------------------------------

@bp.route("/invite/<token>", methods=["GET", "POST"])
def accept_invitation(token):

    invitation = EmployeeInvitation.query.filter_by(
        token=token
    ).first()

    if not invitation or not invitation.is_valid():
        return """
        <h2>Invitation expired or invalid</h2>
        <p>Please contact your employer and request a new invitation.</p>
        """

    employee = invitation.employee

    if request.method == "POST":

        password = request.form.get(
            "password", ""
        )

        confirm_password = request.form.get(
            "confirm_password", ""
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
            name=f"{employee.first_name} {employee.last_name}",
            email=email,
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
        invitation=invitation,
        employee=employee
    )


# ---------------------------------------------------------
# Employee dashboard
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# Employee payslips
# ---------------------------------------------------------

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
        .filter_by(employee_id=employee.id)
        .order_by(Payslip.pay_date.desc())
        .all()
    )

    return render_template(
        "my_payslips.html",
        employee=employee,
        payslips=payslips
    )


# ---------------------------------------------------------
# Payroll
# ---------------------------------------------------------

@bp.get("/payroll")
@employer_required
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
        employee.monthly_salary or 0
        for employee in rows
    )

    return render_template(
        "payroll.html",
        company=company,
        employees=rows,
        total_salary=gross
    )


# ---------------------------------------------------------
# Deel integration
# ---------------------------------------------------------

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
