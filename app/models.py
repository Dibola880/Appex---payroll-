from datetime import datetime
from sqlalchemy import Index, text, and_
from sqlalchemy.orm import foreign, remote

from . import db


# ============================================================
# COMPANY
# ============================================================

class Company(db.Model):
    __tablename__ = "company"

    __table_args__ = (
        Index(
            "ix_company_referral_code_unique",
            "referral_code",
            unique=True,
            postgresql_where=text("referral_code IS NOT NULL"),
            sqlite_where=text("referral_code IS NOT NULL"),
        ),
    )

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(200),
        nullable=False
    )

    registration_number = db.Column(
        db.String(100)
    )

    payroll_provider = db.Column(
        db.String(100),
        default="Deel Local Payroll"
    )

    # ========================================================
    # CLIENT ACQUISITION / ONBOARDING
    # ========================================================

    contact_person = db.Column(
        db.String(200)
    )

    contact_phone = db.Column(
        db.String(50)
    )

    contact_email = db.Column(
        db.String(200)
    )

    client_status = db.Column(
        db.String(50),
        default="Trial"
    )

    subscription_plan = db.Column(
        db.String(100),
        default="Free Trial"
    )

    subscription_status = db.Column(
        db.String(50),
        default="Trial"
    )

    onboarding_completed = db.Column(
        db.Boolean,
        default=False
    )

    referral_code = db.Column(
        db.String(50),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    users = db.relationship(
        "User",
        back_populates="company",
        cascade="all, delete-orphan"
    )

    employees = db.relationship(
        "Employee",
        back_populates="company",
        cascade="all, delete-orphan"
    )

    payroll_runs = db.relationship(
        "PayrollRun",
        back_populates="company",
        cascade="all, delete-orphan"
    )

    loan_products = db.relationship(
        "LoanProduct",
        back_populates="company",
        cascade="all, delete-orphan"
    )

    sales_leads = db.relationship(
        "SalesLead",
        foreign_keys="SalesLead.converted_company_id",
        back_populates="converted_company"
    )

    referrals_made = db.relationship(
        "ClientReferral",
        foreign_keys="ClientReferral.referrer_company_id",
        back_populates="referrer_company",
        cascade="all, delete-orphan"
    )

    referrals_received = db.relationship(
        "ClientReferral",
        foreign_keys="ClientReferral.converted_company_id",
        back_populates="converted_company"
    )
    # Preserve subscription history. Company deletion is restricted
    # while subscription records still reference the company.
    subscriptions = db.relationship(
        "CompanySubscription",
        back_populates="company",
        passive_deletes="all",
    )

    subscription_invoices = db.relationship(
        "SubscriptionInvoice",
        back_populates="company",
        passive_deletes="all",
    )

    subscription_payments = db.relationship(
        "SubscriptionPayment",
        back_populates="company",
        passive_deletes="all",
    )

    integrations = db.relationship(
        "CompanyIntegration",
        back_populates="company",
        passive_deletes="all",
    )

    integration_events = db.relationship(
        "IntegrationEvent",
        back_populates="company",
        passive_deletes="all",
    )

    # Company-owned chart of accounts.
    accounts = db.relationship(
        "Account",
        back_populates="company",
        passive_deletes="all",
    )

    # Company-owned accounting financial years and periods.
    financial_years = db.relationship(
        "FinancialYear",
        back_populates="company",
        passive_deletes="all",
    )
    accounting_periods = db.relationship(
        "AccountingPeriod",
        back_populates="company",
        passive_deletes="all",
    )





# ============================================================
# ACCOUNTING: CHART OF ACCOUNTS
# ============================================================

class Account(db.Model):
    """A company-owned account in its chart of accounts."""

    __tablename__ = "account"

    __table_args__ = (
        db.UniqueConstraint(
            "company_id",
            "account_code",
            name="uq_account_company_code",
        ),
        db.UniqueConstraint(
            "company_id",
            "system_code",
            name="uq_account_company_system_code",
        ),
        db.UniqueConstraint(
            "company_id",
            "id",
            name="uq_account_company_id_id",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "parent_id"],
            ["account.company_id", "account.id"],
            ondelete="RESTRICT",
            name="fk_account_parent_same_company",
        ),
        db.CheckConstraint(
            "account_type IN ('asset', 'liability', 'equity', 'income', 'expense')",
            name="ck_account_valid_type",
        ),
        db.CheckConstraint(
            "normal_balance IN ('debit', 'credit')",
            name="ck_account_valid_normal_balance",
        ),
        db.Index(
            "ix_account_company_type_active",
            "company_id",
            "account_type",
            "is_active",
        ),
        db.Index(
            "ix_account_parent_id",
            "parent_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=False,
    )

    account_code = db.Column(db.String(32), nullable=False)
    name = db.Column(db.String(160), nullable=False)

    account_type = db.Column(db.String(20), nullable=False)
    normal_balance = db.Column(db.String(6), nullable=False)

    parent_id = db.Column(
        db.Integer,
        nullable=True,
    )

    system_code = db.Column(db.String(64), nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    allow_manual_posting = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    company = db.relationship(
        "Company",
        back_populates="accounts",
    )

    parent = db.relationship(
        "Account",
        primaryjoin=lambda: and_(
            Account.company_id == remote(Account.company_id),
            foreign(Account.parent_id) == remote(Account.id),
        ),
        remote_side=lambda: [Account.company_id, Account.id],
        foreign_keys=lambda: [Account.parent_id],
        back_populates="children",
    )

    children = db.relationship(
        "Account",
        primaryjoin=lambda: and_(
            Account.company_id == remote(Account.company_id),
            Account.id == remote(foreign(Account.parent_id)),
        ),
        foreign_keys=lambda: [Account.parent_id],
        back_populates="parent",
        passive_deletes="all",
    )


# ============================================================
# ACCOUNTING JOURNAL ENTRY
# ============================================================

class JournalEntry(db.Model):
    """Company-owned double-entry accounting journal."""

    __tablename__ = "journal_entry"

    __table_args__ = (
        db.UniqueConstraint(
            "company_id",
            "journal_number",
            name="uq_journal_company_number",
        ),
        db.UniqueConstraint(
            "company_id",
            "id",
            name="uq_journal_company_id_id",
        ),
        db.UniqueConstraint(
            "company_id",
            "reversal_of_id",
            name="uq_journal_company_reversal",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "reversal_of_id"],
            ["journal_entry.company_id", "journal_entry.id"],
            ondelete="RESTRICT",
            name="fk_journal_reversal_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "accounting_period_id"],
            ["accounting_period.company_id", "accounting_period.id"],
            ondelete="RESTRICT",
            name="fk_journal_period_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "created_by_id"],
            ["user.company_id", "user.id"],
            ondelete="RESTRICT",
            name="fk_journal_creator_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "posted_by_id"],
            ["user.company_id", "user.id"],
            ondelete="RESTRICT",
            name="fk_journal_poster_same_company",
        ),
        db.CheckConstraint(
            "status IN ('draft', 'posted', 'reversed')",
            name="ck_journal_valid_status",
        ),
        db.CheckConstraint(
            "status = 'draft' OR accounting_period_id IS NOT NULL",
            name="ck_journal_posted_requires_period",
        ),
        db.CheckConstraint(
            "length(currency) = 3",
            name="ck_journal_currency_length",
        ),
        db.CheckConstraint(
            "reversal_of_id IS NULL OR reversal_of_id != id",
            name="ck_journal_no_self_reversal",
        ),
        Index(
            "ix_journal_company_date_status",
            "company_id",
            "journal_date",
            "status",
        ),
        Index(
            "ix_journal_company_period",
            "company_id",
            "accounting_period_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=False,
    )

    journal_number = db.Column(db.String(40), nullable=False)
    journal_date = db.Column(db.Date, nullable=False)
    accounting_period_id = db.Column(db.Integer, nullable=True)
    description = db.Column(db.String(500), nullable=False)

    currency = db.Column(
        db.String(3),
        nullable=False,
        default="ZAR",
    )

    source_type = db.Column(
        db.String(40),
        nullable=False,
        default="manual",
    )

    source_id = db.Column(db.Integer, nullable=True)

    status = db.Column(
        db.String(20),
        nullable=False,
        default="draft",
    )

    created_by_id = db.Column(
        db.Integer,
        nullable=False,
    )

    posted_by_id = db.Column(
        db.Integer,
        nullable=True,
    )

    posted_at = db.Column(db.DateTime, nullable=True)

    reversal_of_id = db.Column(db.Integer, nullable=True)

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    company = db.relationship("Company")

    created_by = db.relationship(
        "User",
        primaryjoin=lambda: and_(
            JournalEntry.company_id == User.company_id,
            foreign(JournalEntry.created_by_id) == User.id,
        ),
        foreign_keys=lambda: [JournalEntry.created_by_id],
    )

    posted_by = db.relationship(
        "User",
        primaryjoin=lambda: and_(
            JournalEntry.company_id == User.company_id,
            foreign(JournalEntry.posted_by_id) == User.id,
        ),
        foreign_keys=lambda: [JournalEntry.posted_by_id],
    )

    lines = db.relationship(
        "JournalLine",
        back_populates="journal",
        foreign_keys=lambda: [
            JournalLine.company_id,
            JournalLine.journal_entry_id,
        ],
        order_by="JournalLine.line_number",
    )


# ============================================================
# ACCOUNTING JOURNAL LINES
# ============================================================

class JournalLine(db.Model):
    """One debit or credit line belonging to a journal."""

    __tablename__ = "journal_line"

    __table_args__ = (
        db.ForeignKeyConstraint(
            ["company_id", "journal_entry_id"],
            ["journal_entry.company_id", "journal_entry.id"],
            ondelete="RESTRICT",
            name="fk_journal_line_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "account_id"],
            ["account.company_id", "account.id"],
            ondelete="RESTRICT",
            name="fk_journal_line_account_same_company",
        ),
        db.UniqueConstraint(
            "company_id",
            "journal_entry_id",
            "line_number",
            name="uq_journal_line_number",
        ),
        db.CheckConstraint(
            "line_number > 0",
            name="ck_journal_line_positive_number",
        ),
        db.CheckConstraint(
            "debit >= 0 AND credit >= 0",
            name="ck_journal_line_nonnegative_amounts",
        ),
        db.CheckConstraint(
            "(debit > 0 AND credit = 0) OR "
            "(credit > 0 AND debit = 0)",
            name="ck_journal_line_one_positive_side",
        ),
        Index(
            "ix_journal_line_company_account",
            "company_id",
            "account_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(db.Integer, nullable=False)

    journal_entry_id = db.Column(
        db.Integer,
        nullable=False,
    )

    account_id = db.Column(
        db.Integer,
        nullable=False,
    )

    line_number = db.Column(
        db.Integer,
        nullable=False,
    )

    description = db.Column(db.String(300), nullable=True)

    debit = db.Column(
        db.Numeric(14, 2),
        nullable=False,
        default=0,
    )

    credit = db.Column(
        db.Numeric(14, 2),
        nullable=False,
        default=0,
    )

    journal = db.relationship(
        "JournalEntry",
        back_populates="lines",
        foreign_keys=[company_id, journal_entry_id],
    )


# ============================================================
# ACCOUNTING FINANCIAL YEAR
# ============================================================

class FinancialYear(db.Model):
    """A company-owned financial year with explicit date boundaries."""

    __tablename__ = "financial_year"

    __table_args__ = (
        db.UniqueConstraint(
            "company_id",
            "id",
            name="uq_financial_year_company_id_id",
        ),
        db.UniqueConstraint(
            "company_id",
            "name",
            name="uq_financial_year_company_name",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "closed_by_id"],
            ["user.company_id", "user.id"],
            ondelete="RESTRICT",
            name="fk_financial_year_closer_same_company",
        ),
        db.CheckConstraint(
            "start_date <= end_date",
            name="ck_financial_year_valid_dates",
        ),
        db.CheckConstraint(
            "status IN ('open', 'closed')",
            name="ck_financial_year_valid_status",
        ),
        Index(
            "ix_financial_year_company_dates",
            "company_id",
            "start_date",
            "end_date",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name = db.Column(db.String(40), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="open",
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    closed_at = db.Column(db.DateTime, nullable=True)
    closed_by_id = db.Column(db.Integer, nullable=True)

    company = db.relationship(
        "Company",
        back_populates="financial_years",
    )
    periods = db.relationship(
        "AccountingPeriod",
        back_populates="financial_year",
        primaryjoin=lambda: and_(
            FinancialYear.company_id == AccountingPeriod.company_id,
            FinancialYear.id == foreign(AccountingPeriod.financial_year_id),
        ),
        foreign_keys=lambda: [
            AccountingPeriod.company_id,
            AccountingPeriod.financial_year_id,
        ],
        order_by="AccountingPeriod.period_number",
        passive_deletes="all",
    )


# ============================================================
# ACCOUNTING PERIOD
# ============================================================

class AccountingPeriod(db.Model):
    """A company-owned posting period within one financial year."""

    __tablename__ = "accounting_period"

    __table_args__ = (
        db.UniqueConstraint(
            "company_id",
            "id",
            name="uq_accounting_period_company_id_id",
        ),
        db.UniqueConstraint(
            "company_id",
            "financial_year_id",
            "period_number",
            name="uq_accounting_period_year_number",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "financial_year_id"],
            ["financial_year.company_id", "financial_year.id"],
            ondelete="RESTRICT",
            name="fk_accounting_period_year_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "closed_by_id"],
            ["user.company_id", "user.id"],
            ondelete="RESTRICT",
            name="fk_accounting_period_closer_same_company",
        ),
        db.CheckConstraint(
            "start_date <= end_date",
            name="ck_accounting_period_valid_dates",
        ),
        db.CheckConstraint(
            "period_number > 0",
            name="ck_accounting_period_positive_number",
        ),
        db.CheckConstraint(
            "status IN ('open', 'closed')",
            name="ck_accounting_period_valid_status",
        ),
        Index(
            "ix_accounting_period_company_dates",
            "company_id",
            "start_date",
            "end_date",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=False,
    )
    financial_year_id = db.Column(db.Integer, nullable=False)
    period_number = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="open",
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    closed_at = db.Column(db.DateTime, nullable=True)
    closed_by_id = db.Column(db.Integer, nullable=True)

    company = db.relationship(
        "Company",
        back_populates="accounting_periods",
    )
    financial_year = db.relationship(
        "FinancialYear",
        back_populates="periods",
        primaryjoin=lambda: and_(
            AccountingPeriod.company_id == FinancialYear.company_id,
            foreign(AccountingPeriod.financial_year_id) == FinancialYear.id,
        ),
        foreign_keys=lambda: [
            AccountingPeriod.company_id,
            AccountingPeriod.financial_year_id,
        ],
    )


# ============================================================
# ACCOUNTING PERIOD AUDIT EVENTS
# ============================================================

class AccountingPeriodEvent(db.Model):
    """Immutable audit record for financial-year or period transitions."""

    __tablename__ = "accounting_period_event"

    __table_args__ = (
        db.ForeignKeyConstraint(
            ["company_id", "financial_year_id"],
            ["financial_year.company_id", "financial_year.id"],
            ondelete="RESTRICT",
            name="fk_accounting_event_year_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "accounting_period_id"],
            ["accounting_period.company_id", "accounting_period.id"],
            ondelete="RESTRICT",
            name="fk_accounting_event_period_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "performed_by_id"],
            ["user.company_id", "user.id"],
            ondelete="RESTRICT",
            name="fk_accounting_event_actor_same_company",
        ),
        db.CheckConstraint(
            "(financial_year_id IS NOT NULL AND accounting_period_id IS NULL) OR "
            "(financial_year_id IS NULL AND accounting_period_id IS NOT NULL)",
            name="ck_accounting_event_exactly_one_target",
        ),
        db.CheckConstraint(
            "event_type IN ('opened', 'closed', 'reopened')",
            name="ck_accounting_event_valid_type",
        ),
        Index(
            "ix_accounting_event_company_time",
            "company_id",
            "performed_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=False,
    )
    financial_year_id = db.Column(db.Integer, nullable=True)
    accounting_period_id = db.Column(db.Integer, nullable=True)
    event_type = db.Column(db.String(20), nullable=False)
    performed_by_id = db.Column(db.Integer, nullable=False)
    performed_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    reason = db.Column(db.String(500), nullable=True)


class JournalAuditEvent(db.Model):
    """Append-only audit record for company journal activity."""

    __tablename__ = "journal_audit_event"

    __table_args__ = (
        db.ForeignKeyConstraint(
            ["company_id", "journal_entry_id"],
            ["journal_entry.company_id", "journal_entry.id"],
            ondelete="RESTRICT",
            name="fk_journal_audit_entry_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "performed_by_id"],
            ["user.company_id", "user.id"],
            ondelete="RESTRICT",
            name="fk_journal_audit_actor_same_company",
        ),
        db.CheckConstraint(
            "event_type IN ('created', 'updated', 'posted', 'reversed')",
            name="ck_journal_audit_valid_event_type",
        ),
        Index(
            "ix_journal_audit_company_time",
            "company_id",
            "performed_at",
        ),
        Index(
            "ix_journal_audit_company_journal",
            "company_id",
            "journal_entry_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        nullable=False,
    )

    journal_entry_id = db.Column(
        db.Integer,
        nullable=False,
    )

    event_type = db.Column(
        db.String(20),
        nullable=False,
    )

    performed_by_id = db.Column(
        db.Integer,
        nullable=False,
    )

    performed_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    reason = db.Column(
        db.String(500),
        nullable=True,
    )

    details = db.Column(
        db.JSON,
        nullable=True,
    )


# ============================================================
# SUBSCRIPTION PLAN
# ============================================================

class SubscriptionPlan(db.Model):
    __tablename__ = "subscription_plan"

    id = db.Column(db.Integer, primary_key=True)

    code = db.Column(db.String(64), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)

    # NULL means pricing has not yet been configured.
    monthly_price = db.Column(db.Numeric(12, 2), nullable=True)
    annual_price = db.Column(db.Numeric(12, 2), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default="ZAR")
    billing_intervals = db.Column(
        db.JSON,
        nullable=False,
        default=lambda: ["monthly", "annually"],
    )

    employee_limit = db.Column(db.Integer, nullable=True)

    # Feature entitlements are introduced in Phase 7.2.
    feature_config = db.Column(db.JSON, nullable=False, default=dict)

    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    subscriptions = db.relationship(
        "CompanySubscription",
        back_populates="plan",
    )


# ============================================================
# COMPANY SUBSCRIPTION
# ============================================================

class CompanySubscription(db.Model):
    __tablename__ = "company_subscription"

    __table_args__ = (
        Index(
            "ix_company_subscription_one_current",
            "company_id",
            unique=True,
            postgresql_where=text("is_current = true"),
            sqlite_where=text("is_current = true"),
        ),
        Index(
            "ix_company_subscription_company_status",
            "company_id",
            "status",
        ),
        Index(
            "ix_company_subscription_plan_id",
            "plan_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False,
    )

    plan_id = db.Column(
        db.Integer,
        db.ForeignKey("subscription_plan.id"),
        nullable=False,
    )

    status = db.Column(db.String(50), nullable=False, default="Trial")
    billing_interval = db.Column(
        db.String(20),
        nullable=False,
        default="monthly",
    )

    # Price snapshot: later plan price changes must not rewrite history.
    currency = db.Column(db.String(3), nullable=False, default="ZAR")
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    starts_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    trial_ends_at = db.Column(db.DateTime)

    current_period_start = db.Column(db.DateTime)
    current_period_end = db.Column(db.DateTime)

    cancel_at_period_end = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
    )
    cancelled_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)

    is_current = db.Column(db.Boolean, nullable=False, default=True)

    payment_provider = db.Column(db.String(50))
    provider_customer_id = db.Column(db.String(200))
    provider_subscription_id = db.Column(db.String(200))

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    company = db.relationship(
        "Company",
        back_populates="subscriptions",
    )

    plan = db.relationship(
        "SubscriptionPlan",
        back_populates="subscriptions",
    )

    invoices = db.relationship(
        "SubscriptionInvoice",
        back_populates="subscription",
        passive_deletes="all",
    )


# ============================================================
# SUBSCRIPTION INVOICE
# ============================================================

class SubscriptionInvoice(db.Model):
    __tablename__ = "subscription_invoice"

    __table_args__ = (
        db.UniqueConstraint(
            "invoice_number",
            name="uq_subscription_invoice_number",
        ),
        db.CheckConstraint(
            "subtotal >= 0 AND tax_amount >= 0 AND total >= 0",
            name="ck_subscription_invoice_nonnegative_totals",
        ),
        db.CheckConstraint(
            "amount_paid >= 0 AND balance_due >= 0",
            name="ck_subscription_invoice_nonnegative_balance",
        ),
        db.Index(
            "ix_subscription_invoice_company_status",
            "company_id",
            "status",
        ),
        db.Index(
            "ix_subscription_invoice_subscription_id",
            "subscription_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False,
    )
    subscription_id = db.Column(
        db.Integer,
        db.ForeignKey("company_subscription.id"),
        nullable=False,
    )

    invoice_number = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="Draft")

    currency = db.Column(db.String(3), nullable=False, default="ZAR")
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    amount_paid = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    balance_due = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    issued_at = db.Column(db.DateTime)
    due_at = db.Column(db.DateTime)
    period_start = db.Column(db.DateTime)
    period_end = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    company = db.relationship(
        "Company",
        back_populates="subscription_invoices",
    )
    subscription = db.relationship(
        "CompanySubscription",
        back_populates="invoices",
    )
    items = db.relationship(
        "SubscriptionInvoiceItem",
        back_populates="invoice",
        passive_deletes="all",
    )
    payments = db.relationship(
        "SubscriptionPayment",
        back_populates="invoice",
        passive_deletes="all",
    )


# ============================================================
# SUBSCRIPTION INVOICE ITEM
# ============================================================

class SubscriptionInvoiceItem(db.Model):
    __tablename__ = "subscription_invoice_item"

    __table_args__ = (
        db.CheckConstraint(
            "quantity > 0",
            name="ck_subscription_invoice_item_positive_quantity",
        ),
        db.CheckConstraint(
            "unit_price >= 0 AND line_total >= 0",
            name="ck_subscription_invoice_item_nonnegative_amounts",
        ),
        db.Index(
            "ix_subscription_invoice_item_invoice_id",
            "invoice_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    invoice_id = db.Column(
        db.Integer,
        db.ForeignKey("subscription_invoice.id"),
        nullable=False,
    )
    plan_id = db.Column(
        db.Integer,
        db.ForeignKey("subscription_plan.id"),
        nullable=True,
    )

    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Numeric(12, 2), nullable=False, default=1)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    line_total = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    invoice = db.relationship(
        "SubscriptionInvoice",
        back_populates="items",
    )
    plan = db.relationship("SubscriptionPlan")


# ============================================================
# SUBSCRIPTION PAYMENT
# ============================================================

class SubscriptionPayment(db.Model):
    __tablename__ = "subscription_payment"

    __table_args__ = (
        db.UniqueConstraint(
            "idempotency_key",
            name="uq_subscription_payment_idempotency_key",
        ),
        db.CheckConstraint(
            "amount > 0",
            name="ck_subscription_payment_positive_amount",
        ),
        db.Index(
            "ix_subscription_payment_company_status",
            "company_id",
            "status",
        ),
        db.Index(
            "ix_subscription_payment_invoice_status",
            "invoice_id",
            "status",
        ),
        db.Index(
            "ix_subscription_payment_provider_reference",
            "payment_provider",
            "provider_payment_id",
            unique=True,
            postgresql_where=text(
                "payment_provider IS NOT NULL AND provider_payment_id IS NOT NULL"
            ),
            sqlite_where=text(
                "payment_provider IS NOT NULL AND provider_payment_id IS NOT NULL"
            ),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    invoice_id = db.Column(
        db.Integer,
        db.ForeignKey("subscription_invoice.id"),
        nullable=False,
    )
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False,
    )

    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="ZAR")
    status = db.Column(db.String(20), nullable=False, default="Pending")

    payment_provider = db.Column(db.String(50))
    provider_payment_id = db.Column(db.String(200))
    idempotency_key = db.Column(db.String(200), nullable=True)

    verified_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    invoice = db.relationship(
        "SubscriptionInvoice",
        back_populates="payments",
    )
    company = db.relationship(
        "Company",
        back_populates="subscription_payments",
    )


# ============================================================
# USER
# ============================================================

class User(db.Model):
    __tablename__ = "user"

    __table_args__ = (
        db.UniqueConstraint(
            "company_id",
            "id",
            name="uq_user_company_id_id",
        ),
    )

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    created_at = db.Column(db.DateTime, nullable=True)
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False
    )

    name = db.Column(
        db.String(200),
        nullable=False
    )

    email = db.Column(
        db.String(200),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    role = db.Column(
        db.String(50),
        default="employee",
        nullable=False
    )

    is_active = db.Column(
        db.Boolean,
        default=True
    )

    company = db.relationship(
        "Company",
        back_populates="users"
    )

    employee = db.relationship(
        "Employee",
        back_populates="user",
        uselist=False
    )


# ============================================================
# EMPLOYEE
# ============================================================

class Employee(db.Model):
    __tablename__ = "employee"

    __table_args__ = (
        Index(
            "ix_employee_user_id_unique",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
            sqlite_where=text("user_id IS NOT NULL"),
        ),
    )

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    created_at = db.Column(db.DateTime, nullable=True)
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True
    )

    employee_number = db.Column(
        db.String(100),
        nullable=False
    )

    first_name = db.Column(
        db.String(100),
        nullable=False
    )

    last_name = db.Column(
        db.String(100),
        nullable=False
    )

    date_of_birth = db.Column(
        db.Date,
        nullable=True
    )

    email = db.Column(
        db.String(200)
    )

    job_title = db.Column(
        db.String(200)
    )

    monthly_salary = db.Column(
        db.Float,
        default=0
    )

    status = db.Column(
        db.String(50),
        default="Active"
    )

    # Deel integration
    deel_employee_id = db.Column(
        db.String(200)
    )

    company = db.relationship(
        "Company",
        back_populates="employees"
    )

    user = db.relationship(
        "User",
        back_populates="employee"
    )

    invitations = db.relationship(
        "EmployeeInvitation",
        back_populates="employee",
        cascade="all, delete-orphan"
    )

    payslips = db.relationship(
        "Payslip",
        back_populates="employee",
        cascade="all, delete-orphan"
    )

    payroll_inputs = db.relationship(
        "PayrollInput",
        back_populates="employee",
        cascade="all, delete-orphan"
    )

    loan_applications = db.relationship(
        "LoanApplication",
        back_populates="employee",
        cascade="all, delete-orphan"
    )

    loan_repayments = db.relationship(
        "LoanRepayment",
        back_populates="employee",
        cascade="all, delete-orphan"
    )


# ============================================================
# EMPLOYEE INVITATION
# ============================================================

class EmployeeInvitation(db.Model):
    __tablename__ = "employee_invitation"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    created_at = db.Column(db.DateTime, nullable=True)
    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False
    )

    token = db.Column(
        db.String(255),
        unique=True,
        nullable=False
    )

    expires_at = db.Column(
        db.DateTime,
        nullable=False
    )

    used = db.Column(
        db.Boolean,
        default=False
    )

    employee = db.relationship(
        "Employee",
        back_populates="invitations"
    )

    def is_valid(self):
        return (
            not self.used
            and self.expires_at > datetime.utcnow()
        )


# ============================================================
# PAYROLL RUN
# ============================================================

class PayrollRun(db.Model):
    __tablename__ = "payroll_run"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    created_at = db.Column(db.DateTime, nullable=True)
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False
    )

    # Currency is authoritative for this payroll run.
    # Historical runs remain NULL until separately reconciled.
    currency = db.Column(
        db.String(3),
        nullable=True,
        default="ZAR",
    )

    pay_period = db.Column(
        db.String(50),
        nullable=False
    )

    pay_date = db.Column(
        db.Date
    )

    status = db.Column(
        db.String(50),
        default="Draft"
    )

    total_gross = db.Column(
        db.Float,
        default=0
    )

    total_deductions = db.Column(
        db.Float,
        default=0
    )

    total_net = db.Column(
        db.Float,
        default=0
    )

    total_employer_uif = db.Column(
        db.Float,
        default=0
    )

    total_employer_cost = db.Column(
        db.Float,
        default=0
    )

    deel_payroll_id = db.Column(
        db.String(200)
    )

    company = db.relationship(
        "Company",
        back_populates="payroll_runs"
    )

    payroll_inputs = db.relationship(
        "PayrollInput",
        back_populates="payroll_run",
        cascade="all, delete-orphan"
    )

    payslips = db.relationship(
        "Payslip",
        back_populates="payroll_run",
        cascade="all, delete-orphan"
    )

    loan_repayments = db.relationship(
        "LoanRepayment",
        back_populates="payroll_run"
    )


# ============================================================
# PAYROLL INPUT
# ============================================================

class PayrollInput(db.Model):
    __tablename__ = "payroll_input"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    payroll_run_id = db.Column(
        db.Integer,
        db.ForeignKey("payroll_run.id"),
        nullable=False,
        index=True
    )

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False,
        index=True
    )

    basic_salary = db.Column(
        db.Float,
        default=0
    )

    overtime = db.Column(
        db.Float,
        default=0
    )

    bonus = db.Column(
        db.Float,
        default=0
    )

    commission = db.Column(
        db.Float,
        default=0
    )

    other_earnings = db.Column(
        db.Float,
        default=0
    )

    other_deductions = db.Column(
        db.Float,
        default=0
    )

    # ========================================================
    # PHASE 5 LOAN DEDUCTION
    # ========================================================

    loan_repayment = db.Column(
        db.Float,
        default=0
    )

    payroll_run = db.relationship(
        "PayrollRun",
        back_populates="payroll_inputs"
    )

    employee = db.relationship(
        "Employee",
        back_populates="payroll_inputs"
    )


# ============================================================
# PAYSLIP
# ============================================================

class Payslip(db.Model):
    __tablename__ = "payslip"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    created_at = db.Column(db.DateTime, nullable=True)
    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False
    )

    payroll_run_id = db.Column(
        db.Integer,
        db.ForeignKey("payroll_run.id"),
        nullable=True
    )

    pay_period = db.Column(
        db.String(50),
        nullable=True
    )

    pay_date = db.Column(
        db.Date
    )

    basic_salary = db.Column(
        db.Float,
        default=0
    )

    overtime = db.Column(
        db.Float,
        default=0
    )

    bonus = db.Column(
        db.Float,
        default=0
    )

    commission = db.Column(
        db.Float,
        default=0
    )

    other_earnings = db.Column(
        db.Float,
        default=0
    )

    gross_pay = db.Column(
        db.Float,
        default=0
    )

    tax_deductions = db.Column(
        db.Float,
        default=0
    )

    uif = db.Column(
        db.Float,
        default=0
    )

    other_deductions = db.Column(
        db.Float,
        default=0
    )

    # ========================================================
    # PHASE 5 LOAN DEDUCTION
    # ========================================================

    loan_repayment = db.Column(
        db.Float,
        default=0
    )

    total_deductions = db.Column(
        db.Float,
        default=0
    )

    net_pay = db.Column(
        db.Float,
        default=0
    )

    employer_uif = db.Column(
        db.Float,
        default=0
    )

    employer_cost = db.Column(
        db.Float,
        default=0
    )

    deel_payslip_id = db.Column(
        db.String(200)
    )

    pdf_url = db.Column(
        db.String(500)
    )

    employee = db.relationship(
        "Employee",
        back_populates="payslips"
    )

    payroll_run = db.relationship(
        "PayrollRun",
        back_populates="payslips"
    )


# ============================================================
# LOAN PRODUCT
# ============================================================

class LoanProduct(db.Model):
    __tablename__ = "loan_product"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False,
        index=True
    )

    name = db.Column(
        db.String(150),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    minimum_amount = db.Column(
        db.Float,
        default=500,
        nullable=False
    )

    maximum_amount = db.Column(
        db.Float,
        default=3000,
        nullable=False
    )

    interest_rate = db.Column(
        db.Float,
        default=0,
        nullable=False
    )

    service_fee = db.Column(
        db.Float,
        default=0,
        nullable=False
    )

    repayment_term_months = db.Column(
        db.Integer,
        default=1,
        nullable=False
    )

    max_deduction_percent = db.Column(
        db.Float,
        default=30,
        nullable=False
    )

    minimum_employment_months = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    company = db.relationship(
        "Company",
        back_populates="loan_products"
    )

    loan_applications = db.relationship(
        "LoanApplication",
        back_populates="loan_product"
    )


# ============================================================
# LOAN APPLICATION / LOAN ACCOUNT
# ============================================================

class LoanApplication(db.Model):
    __tablename__ = "loan_application"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False,
        index=True
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("loan_product.id"),
        nullable=True,
        index=True
    )

    reference = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
        index=True
    )

    # ========================================================
    # APPLICATION AMOUNTS
    # ========================================================

    requested_amount = db.Column(
        db.Float,
        nullable=False,
        default=0
    )

    approved_amount = db.Column(
        db.Float,
        nullable=True
    )

    # ========================================================
    # LOAN INFORMATION
    # ========================================================

    loan_purpose = db.Column(
        db.String(255)
    )

    repayment_term = db.Column(
        db.String(100)
    )

    repayment_frequency = db.Column(
        db.String(50),
        default="Monthly"
    )

    monthly_income = db.Column(
        db.Float,
        default=0
    )

    monthly_expenses = db.Column(
        db.Float,
        default=0
    )

    # ========================================================
    # STATUS
    # ========================================================

    status = db.Column(
        db.String(50),
        default="Submitted",
        nullable=False,
        index=True
    )

    # Possible statuses:
    #
    # Submitted
    # Under Review
    # Approved
    # Rejected
    # Disbursed
    # Active
    # Paid
    # Cancelled
    #

    # ========================================================
    # APPROVAL INFORMATION
    # ========================================================

    reviewed_at = db.Column(
        db.DateTime,
        nullable=True
    )

    reviewed_by = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True
    )

    approval_notes = db.Column(
        db.Text,
        nullable=True
    )

    approved_at = db.Column(
        db.DateTime,
        nullable=True
    )

    # ========================================================
    # DISBURSEMENT
    # ========================================================

    disbursed_at = db.Column(
        db.DateTime,
        nullable=True
    )

    disbursement_reference = db.Column(
        db.String(100),
        nullable=True
    )

    # ========================================================
    # REPAYMENT CALCULATION
    # ========================================================

    principal_amount = db.Column(
        db.Float,
        default=0,
        nullable=True
    )

    interest_amount = db.Column(
        db.Float,
        default=0,
        nullable=True
    )

    service_fee_amount = db.Column(
        db.Float,
        default=0,
        nullable=True
    )

    total_repayable = db.Column(
        db.Float,
        nullable=True
    )

    scheduled_installment = db.Column(
        db.Float,
        default=0,
        nullable=True
    )

    # ========================================================
    # REPAYMENT TRACKING
    # ========================================================

    total_paid = db.Column(
        db.Float,
        default=0,
        nullable=True
    )

    outstanding_balance = db.Column(
        db.Float,
        default=0,
        nullable=True
    )

    number_of_payments = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    next_payment_date = db.Column(
        db.Date,
        nullable=True
    )

    last_payment_date = db.Column(
        db.Date,
        nullable=True
    )

    # ========================================================
    # TIMESTAMPS
    # ========================================================

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    employee = db.relationship(
        "Employee",
        back_populates="loan_applications"
    )

    loan_product = db.relationship(
        "LoanProduct",
        back_populates="loan_applications"
    )

    reviewer = db.relationship(
        "User",
        foreign_keys=[reviewed_by]
    )

    repayments = db.relationship(
        "LoanRepayment",
        back_populates="loan_application",
        cascade="all, delete-orphan",
        order_by="LoanRepayment.repayment_date"
    )


# ============================================================
# LOAN REPAYMENT LEDGER
# ============================================================

class LoanRepayment(db.Model):
    __tablename__ = "loan_repayment"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # ========================================================
    # LOAN
    # ========================================================

    loan_application_id = db.Column(
        db.Integer,
        db.ForeignKey("loan_application.id"),
        nullable=False,
        index=True
    )

    # ========================================================
    # EMPLOYEE
    # ========================================================

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False,
        index=True
    )

    # ========================================================
    # PAYROLL LINK
    # ========================================================

    payroll_run_id = db.Column(
        db.Integer,
        db.ForeignKey("payroll_run.id"),
        nullable=True,
        index=True
    )

    payslip_id = db.Column(
        db.Integer,
        db.ForeignKey("payslip.id"),
        nullable=True,
        index=True
    )

    # ========================================================
    # REPAYMENT AMOUNT
    # ========================================================

    amount = db.Column(
        db.Float,
        nullable=False,
        default=0
    )

    # ========================================================
    # BALANCE TRACKING
    # ========================================================

    balance_before = db.Column(
        db.Float,
        default=0,
        nullable=True
    )

    balance_after = db.Column(
        db.Float,
        default=0,
        nullable=True
    )

    # ========================================================
    # PAYMENT SEQUENCE
    # ========================================================

    payment_number = db.Column(
        db.Integer,
        default=1,
        nullable=True
    )

    # ========================================================
    # REPAYMENT DATE
    # ========================================================

    repayment_date = db.Column(
        db.Date,
        default=lambda: datetime.utcnow().date(),
        nullable=False
    )

    # ========================================================
    # PAYMENT METHOD
    # ========================================================

    payment_method = db.Column(
        db.String(50),
        default="Payroll Deduction",
        nullable=False
    )

    # Possible methods:
    #
    # Payroll Deduction
    # Bank Transfer
    # Debit Order
    # EFT
    # Manual Payment
    # Other
    #

    # ========================================================
    # SOURCE
    # ========================================================

    source = db.Column(
        db.String(50),
        default="Payroll",
        nullable=True
    )

    # ========================================================
    # REFERENCE
    # ========================================================

    reference = db.Column(
        db.String(100),
        unique=True,
        nullable=True,
        index=True
    )

    # ========================================================
    # STATUS
    # ========================================================

    status = db.Column(
        db.String(50),
        default="Completed",
        nullable=False
    )

    # Possible statuses:
    #
    # Pending
    # Completed
    # Failed
    # Reversed
    # Cancelled
    #

    # ========================================================
    # NOTES
    # ========================================================

    notes = db.Column(
        db.Text,
        nullable=True
    )

    # ========================================================
    # TIMESTAMP
    # ========================================================

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    loan_application = db.relationship(
        "LoanApplication",
        back_populates="repayments"
    )

    employee = db.relationship(
        "Employee",
        back_populates="loan_repayments"
    )

    payroll_run = db.relationship(
        "PayrollRun",
        back_populates="loan_repayments"
    )

    payslip = db.relationship(
        "Payslip"
    )


# ============================================================
# SALES LEAD
# ============================================================

class SalesLead(db.Model):
    __tablename__ = "sales_lead"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    company_name = db.Column(
        db.String(200),
        nullable=False
    )

    registration_number = db.Column(
        db.String(100),
        nullable=True
    )

    contact_person = db.Column(
        db.String(200),
        nullable=False
    )

    email = db.Column(
        db.String(200),
        nullable=False
    )

    phone = db.Column(
        db.String(50),
        nullable=True
    )

    number_of_employees = db.Column(
        db.Integer,
        default=0
    )

    status = db.Column(
        db.String(50),
        default="New Lead",
        nullable=False,
        index=True
    )

    source = db.Column(
        db.String(100),
        default="Direct",
        nullable=False
    )

    notes = db.Column(
        db.Text,
        nullable=True
    )

    assigned_to = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True
    )

    converted_company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    assigned_user = db.relationship(
        "User",
        foreign_keys=[assigned_to]
    )

    converted_company = db.relationship(
        "Company",
        foreign_keys=[converted_company_id],
        back_populates="sales_leads"
    )


# ============================================================
# CLIENT REFERRAL
# ============================================================

class ClientReferral(db.Model):
    __tablename__ = "client_referral"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    referrer_company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False,
        index=True
    )

    referred_company_name = db.Column(
        db.String(200),
        nullable=False
    )

    referred_contact_person = db.Column(
        db.String(200),
        nullable=False
    )

    referred_email = db.Column(
        db.String(200),
        nullable=False
    )

    referred_phone = db.Column(
        db.String(50),
        nullable=True
    )

    status = db.Column(
        db.String(50),
        default="Submitted",
        nullable=False,
        index=True
    )

    converted_company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    referrer_company = db.relationship(
        "Company",
        foreign_keys=[referrer_company_id],
        back_populates="referrals_made"
    )

    converted_company = db.relationship(
        "Company",
        foreign_keys=[converted_company_id],
        back_populates="referrals_received"
    )


# ============================================================
# PLATFORM AUDIT LOG
# Append-only record of platform administrative activity.
# ============================================================

class PlatformAuditLog(db.Model):
    __tablename__ = "platform_audit_log"

    __table_args__ = (
        Index(
            "ix_platform_audit_company_created",
            "company_id",
            "created_at",
        ),
        Index(
            "ix_platform_audit_actor_created",
            "actor_user_id",
            "created_at",
        ),
        Index(
            "ix_platform_audit_action_created",
            "action",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    actor_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Snapshot retained even if the actor's account later changes.
    actor_role = db.Column(
        db.String(50),
        nullable=False,
    )

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="SET NULL"),
        nullable=True,
    )

    action = db.Column(
        db.String(100),
        nullable=False,
    )

    target_type = db.Column(
        db.String(80),
        nullable=True,
    )

    # String supports IDs from different target record types.
    target_id = db.Column(
        db.String(128),
        nullable=True,
    )

    reason = db.Column(
        db.Text,
        nullable=True,
    )

    # Sanitised snapshots only; never store credentials or payroll data.
    before_data = db.Column(
        db.JSON,
        nullable=True,
    )

    after_data = db.Column(
        db.JSON,
        nullable=True,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )


# ============================================================
# INTEGRATION PROVIDER CATALOGUE
# Platform-managed list of supported external providers.
# ============================================================

class IntegrationProvider(db.Model):
    __tablename__ = "integration_provider"

    __table_args__ = (
        Index(
            "ix_integration_provider_category_enabled",
            "category",
            "is_enabled",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), nullable=False, unique=True)
    display_name = db.Column(db.String(160), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    description = db.Column(db.Text)
    capabilities = db.Column(db.JSON, nullable=False, default=list)
    is_enabled = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    connections = db.relationship(
        "CompanyIntegration",
        back_populates="provider",
        passive_deletes="all",
    )


# ============================================================
# COMPANY / PLATFORM PROVIDER CONNECTION
# Platform-owned connections have a NULL company_id.
# Company-owned connections must have a company_id.
# Credentials are stored only as authenticated ciphertext.
# ============================================================

class CompanyIntegration(db.Model):
    __tablename__ = "company_integration"

    __table_args__ = (
        db.CheckConstraint(
            "ownership_scope IN ('platform', 'company')",
            name="ck_company_integration_ownership_scope",
        ),
        db.CheckConstraint(
            "(ownership_scope = 'platform' AND company_id IS NULL) OR "
            "(ownership_scope = 'company' AND company_id IS NOT NULL)",
            name="ck_company_integration_scope_company",
        ),
        db.CheckConstraint(
            "environment IN ('sandbox', 'production')",
            name="ck_company_integration_environment",
        ),
        db.CheckConstraint(
            "status IN ('not_connected', 'pending', 'connected', 'error', 'disabled')",
            name="ck_company_integration_status",
        ),
        Index(
            "ix_company_integration_company_status",
            "company_id",
            "status",
        ),
        Index(
            "ix_company_integration_provider_status",
            "provider_id",
            "status",
        ),
        Index(
            "uq_company_integration_company_provider_env",
            "company_id",
            "provider_id",
            "environment",
            unique=True,
            postgresql_where=text("company_id IS NOT NULL"),
            sqlite_where=text("company_id IS NOT NULL"),
        ),
        Index(
            "uq_company_integration_platform_provider_env",
            "provider_id",
            "environment",
            unique=True,
            postgresql_where=text("company_id IS NULL"),
            sqlite_where=text("company_id IS NULL"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=True,
    )
    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("integration_provider.id", ondelete="RESTRICT"),
        nullable=False,
    )

    ownership_scope = db.Column(
        db.String(20),
        nullable=False,
    )
    environment = db.Column(
        db.String(20),
        nullable=False,
        default="sandbox",
    )
    status = db.Column(
        db.String(30),
        nullable=False,
        default="not_connected",
    )

    # Non-secret provider settings only. Never put credentials here.
    configuration = db.Column(
        db.JSON,
        nullable=False,
        default=dict,
    )

    credentials_encrypted = db.Column(db.Text)
    credential_key_version = db.Column(db.String(40))

    last_connected_at = db.Column(db.DateTime)
    last_error_at = db.Column(db.DateTime)
    last_error_code = db.Column(db.String(100))

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    company = db.relationship(
        "Company",
        back_populates="integrations",
    )
    provider = db.relationship(
        "IntegrationProvider",
        back_populates="connections",
    )
    events = db.relationship(
        "IntegrationEvent",
        back_populates="integration",
        passive_deletes="all",
    )


# ============================================================
# INTEGRATION EVENT REGISTER
# Stores event metadata and hashes, not raw sensitive payloads.
# ============================================================

class IntegrationEvent(db.Model):
    __tablename__ = "integration_event"

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('received', 'verified', 'processing', 'processed', 'failed', 'ignored', 'dead_letter')",
            name="ck_integration_event_status",
        ),
        Index(
            "ix_integration_event_company_received",
            "company_id",
            "received_at",
        ),
        Index(
            "ix_integration_event_status_received",
            "status",
            "received_at",
        ),
        Index(
            "ix_integration_event_status_lease",
            "status",
            "processing_lease_expires_at",
        ),
        Index(
            "ix_integration_event_status_retry",
            "status",
            "next_attempt_at",
            "received_at",
        ),
        db.CheckConstraint(
            "processing_attempts >= 0",
            name="ck_integration_event_processing_attempts",
        ),


        Index(
            "uq_integration_event_connection_external",
            "integration_id",
            "external_event_id",
            unique=True,
            postgresql_where=text("external_event_id IS NOT NULL"),
            sqlite_where=text("external_event_id IS NOT NULL"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("integration_provider.id", ondelete="RESTRICT"),
        nullable=False,
    )
    integration_id = db.Column(
        db.Integer,
        db.ForeignKey("company_integration.id", ondelete="RESTRICT"),
        nullable=False,
    )
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="SET NULL"),
        nullable=True,
    )

    external_event_id = db.Column(db.String(200))
    event_type = db.Column(db.String(120), nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="received",
    )

    payload_hash = db.Column(db.String(64))
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    error_code = db.Column(db.String(100))

    received_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    provider_timestamp = db.Column(db.DateTime)
    verified_at = db.Column(db.DateTime)
    processed_at = db.Column(db.DateTime)
    processing_token = db.Column(db.String(64))
    processing_started_at = db.Column(db.DateTime)
    processing_lease_expires_at = db.Column(db.DateTime)
    processing_attempts = db.Column(
        db.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    next_attempt_at = db.Column(db.DateTime)


    company = db.relationship(
        "Company",
        back_populates="integration_events",
    )
    provider = db.relationship("IntegrationProvider")
    integration = db.relationship(
        "CompanyIntegration",
        back_populates="events",
    )


# ============================================================
# PAYMENT RECONCILIATION HISTORY
# Stores safe reconciliation outcomes, not raw provider payloads.
# ============================================================

class PaymentReconciliation(db.Model):
    __tablename__ = "payment_reconciliation"

    __table_args__ = (
        db.CheckConstraint(
            "outcome IN ('reconciled', 'unmatched', 'mismatch', 'duplicate', 'exception')",
            name="ck_payment_reconciliation_outcome",
        ),
        db.CheckConstraint(
            "amount IS NULL OR amount > 0",
            name="ck_payment_reconciliation_positive_amount",
        ),
        db.UniqueConstraint(
            "event_id",
            name="uq_payment_reconciliation_event",
        ),
        Index(
            "ix_payment_reconciliation_company_attempted",
            "company_id",
            "attempted_at",
        ),
        Index(
            "ix_payment_reconciliation_provider_reference",
            "provider_id",
            "provider_payment_id",
        ),
        Index(
            "uq_payment_reconciliation_success_payment",
            "payment_id",
            unique=True,
            postgresql_where=text(
                "outcome = 'reconciled' AND payment_id IS NOT NULL"
            ),
            sqlite_where=text(
                "outcome = 'reconciled' AND payment_id IS NOT NULL"
            ),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    event_id = db.Column(
        db.Integer,
        db.ForeignKey("integration_event.id", ondelete="RESTRICT"),
        nullable=False,
    )
    integration_id = db.Column(
        db.Integer,
        db.ForeignKey("company_integration.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("integration_provider.id", ondelete="RESTRICT"),
        nullable=False,
    )
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=True,
    )
    invoice_id = db.Column(
        db.Integer,
        db.ForeignKey("subscription_invoice.id", ondelete="RESTRICT"),
        nullable=True,
    )
    payment_id = db.Column(
        db.Integer,
        db.ForeignKey("subscription_payment.id", ondelete="RESTRICT"),
        nullable=True,
    )

    provider_payment_id = db.Column(
        db.String(200),
        nullable=False,
    )
    amount = db.Column(db.Numeric(12, 2))
    currency = db.Column(db.String(3))

    outcome = db.Column(
        db.String(20),
        nullable=False,
    )
    reason_code = db.Column(db.String(100))

    attempted_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    reconciled_at = db.Column(db.DateTime)


# ============================================================
# PAYROLL DISBURSEMENT BATCH
# Prepared payroll payout instructions; no money movement.
# ============================================================

class PayrollDisbursementBatch(db.Model):
    __tablename__ = "payroll_disbursement_batch"

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('prepared', 'cancelled')",
            name="ck_payroll_disbursement_batch_status",
        ),
        db.CheckConstraint(
            "total_amount > 0",
            name="ck_payroll_disbursement_batch_positive_total",
        ),
        db.CheckConstraint(
            "instruction_count > 0",
            name="ck_payroll_disbursement_batch_positive_count",
        ),
        db.UniqueConstraint(
            "payroll_run_id",
            name="uq_payroll_disbursement_batch_payroll_run",
        ),
        Index(
            "ix_payroll_disbursement_batch_company_status",
            "company_id",
            "status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=False,
    )

    payroll_run_id = db.Column(
        db.Integer,
        db.ForeignKey("payroll_run.id", ondelete="RESTRICT"),
        nullable=False,
    )

    integration_id = db.Column(
        db.Integer,
        db.ForeignKey("company_integration.id", ondelete="RESTRICT"),
        nullable=True,
    )

    currency = db.Column(db.String(3), nullable=False)

    total_amount = db.Column(
        db.Numeric(14, 2),
        nullable=False,
    )

    instruction_count = db.Column(
        db.Integer,
        nullable=False,
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="prepared",
        server_default="prepared",
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=db.func.now(),
    )

    cancelled_at = db.Column(db.DateTime)


# ============================================================
# PAYROLL DISBURSEMENT INSTRUCTION
# Contains no employee bank-account details.
# ============================================================

class PayrollDisbursementInstruction(db.Model):
    __tablename__ = "payroll_disbursement_instruction"

    __table_args__ = (
        db.CheckConstraint(
            "amount > 0",
            name="ck_payroll_disbursement_instruction_positive_amount",
        ),
        db.UniqueConstraint(
            "payslip_id",
            name="uq_payroll_disbursement_instruction_payslip",
        ),
        Index(
            "ix_payroll_disbursement_instruction_batch",
            "batch_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    batch_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "payroll_disbursement_batch.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    payslip_id = db.Column(
        db.Integer,
        db.ForeignKey("payslip.id", ondelete="RESTRICT"),
        nullable=False,
    )

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id", ondelete="RESTRICT"),
        nullable=False,
    )

    amount = db.Column(
        db.Numeric(14, 2),
        nullable=False,
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=db.func.now(),
    )


# ============================================================
# PARTNER SERVICE AUDIT HISTORY
# Safe, persistent record of approved partner-service activity.
# Submitted payloads and credentials are never stored.
# ============================================================

class PartnerServiceAuditLog(db.Model):
    __tablename__ = "partner_service_audit_log"

    __table_args__ = (
        db.CheckConstraint(
            "outcome IN ('prepared', 'rejected')",
            name="ck_partner_service_audit_outcome",
        ),
        db.CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_partner_service_audit_payload_hash_length",
        ),
        db.UniqueConstraint(
            "integration_id",
            "request_id",
            name="uq_partner_service_audit_integration_request",
        ),
        Index(
            "ix_partner_service_audit_company_created",
            "company_id",
            "created_at",
        ),
        Index(
            "ix_partner_service_audit_provider_operation_created",
            "provider_id",
            "operation",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=False,
    )

    integration_id = db.Column(
        db.Integer,
        db.ForeignKey("company_integration.id", ondelete="RESTRICT"),
        nullable=False,
    )

    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("integration_provider.id", ondelete="RESTRICT"),
        nullable=False,
    )

    request_id = db.Column(db.String(120), nullable=False)
    provider_code = db.Column(db.String(80), nullable=False)
    operation = db.Column(db.String(100), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)

    outcome = db.Column(db.String(20), nullable=False)
    error_code = db.Column(db.String(100))
    partner_reference = db.Column(db.String(120))

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=db.func.now(),
    )

# ============================================================
# PARTNER SERVICE CONSENT
# Company-specific, purpose-limited authorisation for sharing.
# Consent records are retained as governance history.
# ============================================================
class PartnerServiceConsent(db.Model):
    __tablename__ = "partner_service_consent"

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'active', 'revoked', 'expired')",
            name="ck_partner_service_consent_status",
        ),
        db.CheckConstraint(
            "consent_version >= 1",
            name="ck_partner_service_consent_version",
        ),
        Index(
            "ix_partner_consent_scope_status_expiry",
            "company_id",
            "integration_id",
            "operation",
            "status",
            "expires_at",
        ),
        Index(
            "ix_partner_consent_provider_created",
            "provider_id",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=False,
    )
    integration_id = db.Column(
        db.Integer,
        db.ForeignKey("company_integration.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("integration_provider.id", ondelete="RESTRICT"),
        nullable=False,
    )

    provider_code = db.Column(db.String(80), nullable=False)
    operation = db.Column(db.String(100), nullable=False)
    purpose_code = db.Column(db.String(80), nullable=False)
    data_categories = db.Column(
        db.JSON,
        nullable=False,
        default=list,
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending",
    )
    consent_version = db.Column(
        db.Integer,
        nullable=False,
        default=1,
    )

    granted_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    activated_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime, nullable=False)

    revoked_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="RESTRICT"),
    )
    revoked_at = db.Column(db.DateTime)
    revocation_reason_code = db.Column(db.String(80))

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=db.func.now(),
    )



class PartnerServiceConsentEvent(db.Model):
    """Append-only history of company partner-consent lifecycle changes."""

    __tablename__ = "partner_service_consent_event"

    __table_args__ = (
        db.CheckConstraint(
            "event_type IN ('created', 'activated', 'revoked', 'expired')",
            name="ck_partner_consent_event_type",
        ),
        db.CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('pending', 'active', 'revoked', 'expired')",
            name="ck_partner_consent_event_from_status",
        ),
        db.CheckConstraint(
            "to_status IN ('pending', 'active', 'revoked', 'expired')",
            name="ck_partner_consent_event_to_status",
        ),
        Index(
            "ix_partner_consent_event_company_created",
            "company_id",
            "created_at",
        ),
        Index(
            "ix_partner_consent_event_consent_created",
            "consent_id",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    consent_id = db.Column(
        db.Integer,
        db.ForeignKey("partner_service_consent.id", ondelete="RESTRICT"),
        nullable=False,
    )
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=False,
    )
    integration_id = db.Column(
        db.Integer,
        db.ForeignKey("company_integration.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("integration_provider.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )

    event_type = db.Column(db.String(20), nullable=False)
    from_status = db.Column(db.String(20))
    to_status = db.Column(db.String(20), nullable=False)
    reason_code = db.Column(db.String(80))

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=db.func.now(),
    )


# ============================================================
# PHASE 9.5 — PARTNER SERVICE REQUEST REVIEW
# Independent company-admin approval before preparation.
# Payloads are stored only as encrypted snapshots; credentials are never stored.
# ============================================================

class PartnerServiceRequestReview(db.Model):
    __tablename__ = "partner_service_request_review"

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'prepared', 'preparation_rejected')",
            name="ck_partner_request_review_status",
        ),
        db.CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_partner_request_review_hash_length",
        ),
        db.CheckConstraint(
            "(encrypted_payload IS NULL AND payload_key_version IS NULL) OR "
            "(encrypted_payload IS NOT NULL AND payload_key_version IS NOT NULL)",
            name="ck_partner_review_snapshot_key_pair",
        ),
        db.CheckConstraint(
            "payload_snapshot_erased_at IS NULL OR "
            "(encrypted_payload IS NULL AND payload_key_version IS NULL)",
            name="ck_partner_review_erased_snapshot_empty",
        ),
        db.CheckConstraint(
            "(terminal_at IS NULL AND payload_retention_until IS NULL) OR "
            "(terminal_at IS NOT NULL AND payload_retention_until IS NOT NULL)",
            name="ck_partner_review_terminal_retention_pair",
        ),
        db.CheckConstraint(
            "reviewed_by_user_id IS NULL OR "
            "reviewed_by_user_id != requested_by_user_id",
            name="ck_partner_request_review_independent_reviewer",
        ),
        db.UniqueConstraint(
            "integration_id",
            "request_id",
            name="uq_partner_request_review_integration_request",
        ),
        Index(
            "ix_partner_request_review_company_status",
            "company_id",
            "status",
            "submitted_at",
        ),
        Index(
            "ix_partner_request_review_integration_status",
            "integration_id",
            "status",
            "expires_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=False,
    )
    integration_id = db.Column(
        db.Integer,
        db.ForeignKey("company_integration.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("integration_provider.id", ondelete="RESTRICT"),
        nullable=False,
    )

    request_id = db.Column(db.String(120), nullable=False)
    provider_code = db.Column(db.String(80), nullable=False)
    operation = db.Column(db.String(100), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    encrypted_payload = db.Column(db.Text, nullable=True)
    payload_key_version = db.Column(db.String(40), nullable=True)

    status = db.Column(db.String(20), nullable=False, default="pending")

    requested_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reviewed_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )

    submitted_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=db.func.now(),
    )
    reviewed_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime, nullable=False)
    prepared_at = db.Column(db.DateTime)
    terminal_at = db.Column(db.DateTime)
    payload_retention_until = db.Column(db.DateTime)
    payload_snapshot_erased_at = db.Column(db.DateTime)

    rejection_reason_code = db.Column(db.String(80))


class PartnerServiceRequestReviewEvent(db.Model):
    __tablename__ = "partner_service_request_review_event"

    __table_args__ = (
        db.CheckConstraint(
            "event_type IN ('submitted', 'approved', 'rejected', 'expired', 'prepared', 'preparation_rejected')",
            name="ck_partner_request_review_event_type",
        ),
        db.CheckConstraint(
            "to_status IN ('pending', 'approved', 'rejected', 'expired', 'prepared', 'preparation_rejected')",
            name="ck_partner_request_review_event_to_status",
        ),
        db.CheckConstraint(
            "from_status IS NULL OR "
            "from_status IN ('pending', 'approved', 'rejected', 'expired', 'prepared', 'preparation_rejected')",
            name="ck_partner_request_review_event_from_status",
        ),
        Index(
            "ix_partner_request_review_event_company_created",
            "company_id",
            "created_at",
        ),
        Index(
            "ix_partner_request_review_event_review_created",
            "review_id",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    review_id = db.Column(
        db.Integer,
        db.ForeignKey("partner_service_request_review.id", ondelete="RESTRICT"),
        nullable=False,
    )
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=False,
    )
    integration_id = db.Column(
        db.Integer,
        db.ForeignKey("company_integration.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("integration_provider.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )

    event_type = db.Column(db.String(20), nullable=False)
    from_status = db.Column(db.String(20))
    to_status = db.Column(db.String(20), nullable=False)
    reason_code = db.Column(db.String(100))

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=db.func.now(),
    )
