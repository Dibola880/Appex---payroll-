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
    flash,
    session,
    send_file,
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash,
)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import (
    getSampleStyleSheet,
    ParagraphStyle,
)
from reportlab.lib.enums import (
    TA_CENTER,
    TA_RIGHT,
)
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

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

    employee = (
        Employee.query
        .filter_by(
            id=employee_id,
            company_id=user.company_id
        )
        .first_or_404()
    )

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

    invitation = (
        EmployeeInvitation.query
        .filter_by(
            token=token
        )
        .first()
    )

    if (
        not invitation
        or not invitation.is_valid()
    ):

        return """
        <h2>Invitation expired or invalid</h2>
        <p>
            Please contact your employer
            and request a new invitation.
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

    employee = (
        Employee.query
        .filter_by(
            user_id=user.id,
            company_id=user.company_id
        )
        .first()
    )

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
# EMPLOYEE PAYSLIPS
# =========================================================

@bp.get("/my-payslips")
@login_required
def my_payslips():

    user = current_user()

    if user.role != "employee":

        return redirect(
            url_for("main.dashboard")
        )

    employee = (
        Employee.query
        .filter_by(
            user_id=user.id,
            company_id=user.company_id
        )
        .first()
    )

    if not employee:

        flash(
            "Employee profile not found.",
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

    existing_run = (
        PayrollRun.query
        .filter_by(
            company_id=company.id,
            pay_period=pay_period
        )
        .first()
    )

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
        # CURRENT PHASE 3 CALCULATION
        # -------------------------------------------------

        other_earnings = 0.0

        tax_deductions = 0.0

        other_deductions = 0.0

        gross_pay = (
            basic_salary
            + other_earnings
        )

        total_employee_deductions = (
            tax_deductions
            + other_deductions
        )

        net_pay = (
            gross_pay
            - total_employee_deductions
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
                total_employee_deductions
            ),

            net_pay=net_pay
        )

        db.session.add(payslip)

        total_gross += gross_pay

        total_deductions += (
            total_employee_deductions
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

    payroll_run = (
        PayrollRun.query
        .filter_by(
            id=payroll_id,
            company_id=user.company_id
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
#
# Works for BOTH employer and employee.
# =========================================================

@bp.get(
    "/payroll/payslip/<int:payslip_id>"
)
@login_required
def view_payslip(payslip_id):

    user = current_user()

    payslip = (
        Payslip.query
        .join(Employee)
        .filter(
            Payslip.id == payslip_id
        )
        .first_or_404()
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
                    "main.my_payslips"
                )
            )

        return redirect(
            url_for("main.payroll")
        )

    # -----------------------------------------------------
    # EMPLOYER / ADMIN ACCESS
    # -----------------------------------------------------

    if user.role in ["employer", "admin"]:

        if employee.company_id != user.company_id:

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

        if employee.user_id != user.id:

            flash(
                "You do not have permission to view this payslip.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.my_payslips"
                )
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

    return render_template(
        "payslip.html",
        payslip=payslip
    )


# =========================================================
# DOWNLOAD PAYSLIP AS PDF
#
# Works for BOTH employer and employee.
# =========================================================

@bp.get(
    "/payroll/payslip/<int:payslip_id>/pdf"
)
@login_required
def download_payslip_pdf(payslip_id):

    user = current_user()

    payslip = (
        Payslip.query
        .join(Employee)
        .filter(
            Payslip.id == payslip_id
        )
        .first_or_404()
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
                    "main.my_payslips"
                )
            )

        return redirect(
            url_for("main.payroll")
        )

    # -----------------------------------------------------
    # EMPLOYER / ADMIN ACCESS
    # -----------------------------------------------------

    if user.role in ["employer", "admin"]:

        if employee.company_id != user.company_id:

            flash(
                "You do not have permission to download this payslip.",
                "danger"
            )

            return redirect(
                url_for("main.payroll")
            )

    # -----------------------------------------------------
    # EMPLOYEE ACCESS
    # -----------------------------------------------------

    elif user.role == "employee":

        if employee.user_id != user.id:

            flash(
                "You do not have permission to download this payslip.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.my_payslips"
                )
            )

    # -----------------------------------------------------
    # UNKNOWN ROLE
    # -----------------------------------------------------

    else:

        flash(
            "You do not have permission to download this payslip.",
            "danger"
        )

        return redirect(
            url_for("main.dashboard")
        )

    # =====================================================
    # COMPANY / EMPLOYEE INFORMATION
    # =====================================================

    company = employee.company

    company_name = (
        company.name
        if company
        else "Appex Payroll"
    )

    employee_name = (
        f"{employee.first_name} "
        f"{employee.last_name}"
    )

    employee_number = (
        employee.employee_number
        or "-"
    )

    job_title = (
        employee.job_title
        or "-"
    )

    payroll_provider = (
        company.payroll_provider
        if company
        else "Appex Payroll"
    )

    # =====================================================
    # CREATE PDF
    # =====================================================

    pdf_buffer = BytesIO()

    document = SimpleDocTemplate(
        pdf_buffer,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "PayslipTitle",
        parent=styles["Title"],
        fontSize=24,
        leading=28,
        alignment=TA_CENTER,
        spaceAfter=8,
    )

    subtitle_style = ParagraphStyle(
        "PayslipSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.grey,
    )

    section_style = ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading2"],
        fontSize=13,
        leading=16,
        spaceBefore=15,
        spaceAfter=8,
    )

    normal_style = ParagraphStyle(
        "NormalPayslip",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
    )

    right_style = ParagraphStyle(
        "RightPayslip",
        parent=normal_style,
        alignment=TA_RIGHT,
    )

    story = []

    # =====================================================
    # HEADER
    # =====================================================

    story.append(
        Paragraph(
            "APPEX",
            title_style
        )
    )

    story.append(
        Paragraph(
            "PAYROLL",
            subtitle_style
        )
    )

    story.append(
        Paragraph(
            "Employee Payroll Services",
            subtitle_style
        )
    )

    story.append(
        Spacer(1, 15)
    )

    story.append(
        Paragraph(
            "PAYSLIP",
            section_style
        )
    )

    # =====================================================
    # PAY PERIOD / PAY DATE
    # =====================================================

    period_data = [
        [
            Paragraph(
                "<b>Pay Period</b>",
                normal_style
            ),

            Paragraph(
                str(
                    payslip.pay_period
                    or "-"
                ),
                normal_style
            ),

            Paragraph(
                "<b>Pay Date</b>",
                normal_style
            ),

            Paragraph(
                str(
                    payslip.pay_date
                    or "-"
                ),
                normal_style
            ),
        ]
    ]

    period_table = Table(
        period_data,
        colWidths=[
            80,
            150,
            70,
            150
        ]
    )

    period_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, -1),
                colors.whitesmoke
            ),

            (
                "BOX",
                (0, 0),
                (-1, -1),
                0.5,
                colors.lightgrey
            ),

            (
                "INNERGRID",
                (0, 0),
                (-1, -1),
                0.25,
                colors.lightgrey
            ),

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE"
            ),

            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                8
            ),
        ])
    )

    story.append(
        period_table
    )

    story.append(
        Spacer(1, 15)
    )

    # =====================================================
    # EMPLOYER / EMPLOYEE INFORMATION
    # =====================================================

    story.append(
        Paragraph(
            "Employer & Employee Information",
            section_style
        )
    )

    info_data = [

        [
            Paragraph(
                "<b>Employer</b>",
                normal_style
            ),

            Paragraph(
                company_name,
                normal_style
            ),
        ],

        [
            Paragraph(
                "<b>Payroll Provider</b>",
                normal_style
            ),

            Paragraph(
                payroll_provider
                or "-",
                normal_style
            ),
        ],

        [
            Paragraph(
                "<b>Employee</b>",
                normal_style
            ),

            Paragraph(
                employee_name,
                normal_style
            ),
        ],

        [
            Paragraph(
                "<b>Employee Number</b>",
                normal_style
            ),

            Paragraph(
                str(employee_number),
                normal_style
            ),
        ],

        [
            Paragraph(
                "<b>Job Title</b>",
                normal_style
            ),

            Paragraph(
                job_title,
                normal_style
            ),
        ],
    ]

    info_table = Table(
        info_data,
        colWidths=[
            140,
            310
        ]
    )

    info_table.setStyle(
        TableStyle([
            (
                "BOX",
                (0, 0),
                (-1, -1),
                0.5,
                colors.lightgrey
            ),

            (
                "INNERGRID",
                (0, 0),
                (-1, -1),
                0.25,
                colors.lightgrey
            ),

            (
                "BACKGROUND",
                (0, 0),
                (0, -1),
                colors.whitesmoke
            ),

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            ),

            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                7
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                7
            ),
        ])
    )

    story.append(
        info_table
    )

    # =====================================================
    # EARNINGS
    # =====================================================

    story.append(
        Paragraph(
            "Earnings",
            section_style
        )
    )

    earnings_data = [

        [
            Paragraph(
                "<b>Description</b>",
                normal_style
            ),

            Paragraph(
                "<b>Amount</b>",
                right_style
            ),
        ],

        [
            Paragraph(
                "Basic Salary",
                normal_style
            ),

            Paragraph(
                f"R {float(payslip.basic_salary or 0):,.2f}",
                right_style
            ),
        ],

        [
            Paragraph(
                "Other Earnings",
                normal_style
            ),

            Paragraph(
                f"R {float(payslip.other_earnings or 0):,.2f}",
                right_style
            ),
        ],

        [
            Paragraph(
                "<b>Gross Pay</b>",
                normal_style
            ),

            Paragraph(
                f"<b>R {float(payslip.gross_pay or 0):,.2f}</b>",
                right_style
            ),
        ],
    ]

    earnings_table = Table(
        earnings_data,
        colWidths=[
            310,
            140
        ]
    )

    earnings_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.whitesmoke
            ),

            (
                "LINEBELOW",
                (0, -1),
                (-1, -1),
                1,
                colors.black
            ),

            (
                "LINEBELOW",
                (0, 0),
                (-1, 0),
                0.5,
                colors.grey
            ),

            (
                "ALIGN",
                (1, 0),
                (1, -1),
                "RIGHT"
            ),

            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                8
            ),
        ])
    )

    story.append(
        earnings_table
    )

    # =====================================================
    # DEDUCTIONS
    # =====================================================

    story.append(
        Paragraph(
            "Deductions",
            section_style
        )
    )

    deductions_data = [

        [
            Paragraph(
                "<b>Description</b>",
                normal_style
            ),

            Paragraph(
                "<b>Amount</b>",
                right_style
            ),
        ],

        [
            Paragraph(
                "Tax / PAYE",
                normal_style
            ),

            Paragraph(
                f"R {float(payslip.tax_deductions or 0):,.2f}",
                right_style
            ),
        ],

        [
            Paragraph(
                "Other Deductions",
                normal_style
            ),

            Paragraph(
                f"R {float(payslip.other_deductions or 0):,.2f}",
                right_style
            ),
        ],

        [
            Paragraph(
                "<b>Total Deductions</b>",
                normal_style
            ),

            Paragraph(
                f"<b>R {float(payslip.total_deductions or 0):,.2f}</b>",
                right_style
            ),
        ],
    ]

    deductions_table = Table(
        deductions_data,
        colWidths=[
            310,
            140
        ]
    )

    deductions_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.whitesmoke
            ),

            (
                "LINEBELOW",
                (0, -1),
                (-1, -1),
                1,
                colors.black
            ),

            (
                "LINEBELOW",
                (0, 0),
                (-1, 0),
                0.5,
                colors.grey
            ),

            (
                "ALIGN",
                (1, 0),
                (1, -1),
                "RIGHT"
            ),

            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                8
            ),
        ])
    )

    story.append(
        deductions_table
    )

    # =====================================================
    # NET PAY
    # =====================================================

    story.append(
        Spacer(1, 20)
    )

    net_pay = float(
        payslip.net_pay or 0
    )

    net_data = [

        [
            Paragraph(
                "<b>NET PAY</b>",
                normal_style
            ),

            Paragraph(
                f"<b>R {net_pay:,.2f}</b>",
                right_style
            ),
        ]
    ]

    net_table = Table(
        net_data,
        colWidths=[
            310,
            140
        ]
    )

    net_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, -1),
                colors.whitesmoke
            ),

            (
                "BOX",
                (0, 0),
                (-1, -1),
                1,
                colors.black
            ),

            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                12
            ),

            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                12
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                12
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                12
            ),
        ])
    )

    story.append(
        net_table
    )

    story.append(
        Spacer(1, 25)
    )

    story.append(
        Paragraph(
            "This payslip was generated electronically by Appex Payroll.",
            subtitle_style
        )
    )

    # =====================================================
    # BUILD PDF
    # =====================================================

    document.build(
        story
    )

    pdf_buffer.seek(0)

    # =====================================================
    # SAFE FILE NAME
    # =====================================================

    safe_employee_name = (
        employee_name
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    safe_period = (
        str(
            payslip.pay_period
            or "Payroll"
        )
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    filename = (
        f"Appex_Payslip_"
        f"{safe_employee_name}_"
        f"{safe_period}.pdf"
    )

    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
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
