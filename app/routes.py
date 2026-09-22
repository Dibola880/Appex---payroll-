from flask import Blueprint, render_template, request, redirect, url_for, flash
from . import db
from .models import Company, Employee

bp = Blueprint("main", __name__)


@bp.get("/health")
def health():
    return {
        "status": "ok",
        "service": "appex-payroll"
    }


@bp.get("/")
def dashboard():
    company = Company.query.first()

    employees = (
        Employee.query
        .filter_by(company_id=company.id)
        .all()
        if company else []
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


@bp.get("/employees")
def employees():
    company = Company.query.first()

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


@bp.route("/employees/new", methods=["GET", "POST"])
def new_employee():
    company = Company.query.first()

    if request.method == "POST":
        employee = Employee(
            company_id=company.id,
            employee_number=request.form["employee_number"].strip(),
            first_name=request.form["first_name"].strip(),
            last_name=request.form["last_name"].strip(),
            email=request.form.get("email", "").strip(),
            job_title=request.form.get("job_title", "").strip(),
            monthly_salary=float(
                request.form.get("monthly_salary") or 0
            ),
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


@bp.get("/payroll")
def payroll():
    company = Company.query.first()

    rows = (
        Employee.query
        .filter_by(
            company_id=company.id,
            status="Active"
        )
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


@bp.get("/integration")
def integration():
    import os

    configured = all(
        os.getenv(k)
        for k in [
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
