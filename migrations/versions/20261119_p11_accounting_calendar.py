"""Create company-scoped accounting years, periods and audit events.

Revision ID: p11_accounting_calendar_01
Revises: p10_partner_reason_100_01
"""
from alembic import context, op
import sqlalchemy as sa


revision = "p11_accounting_calendar_01"
down_revision = "p10_partner_reason_100_01"
branch_labels = None
depends_on = None


RESERVED_RELATION_NAMES = (
    "financial_year_id_seq",
    "accounting_period_id_seq",
    "accounting_period_event_id_seq",
    "financial_year_pkey",
    "accounting_period_pkey",
    "accounting_period_event_pkey",
    "uq_financial_year_company_id_id",
    "uq_financial_year_company_name",
    "ix_financial_year_company_dates",
    "uq_accounting_period_company_id_id",
    "uq_accounting_period_year_number",
    "ix_accounting_period_company_dates",
    "ix_accounting_event_company_time",
)


def _require_postgresql_online(bind):
    if context.is_offline_mode():
        raise RuntimeError(
            "Accounting calendar migration requires an online PostgreSQL connection."
        )
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "Accounting calendar migration supports PostgreSQL only."
        )


def _preflight_user_company_unique(bind):
    """Require the same-company user key established by the journal foundation."""
    inspector = sa.inspect(bind)
    if not inspector.has_table("user"):
        raise RuntimeError("Required table 'user' does not exist.")

    columns = {c["name"] for c in inspector.get_columns("user")}
    if not {"company_id", "id"}.issubset(columns):
        raise RuntimeError("user is missing company_id or id.")

    expected = ["company_id", "id"]
    constraints = inspector.get_unique_constraints("user")
    named = [
        item for item in constraints
        if item.get("name") == "uq_user_company_id_id"
    ]

    if len(named) > 1:
        raise RuntimeError("Duplicate uq_user_company_id_id constraints detected.")
    if named and named[0].get("column_names") != expected:
        raise RuntimeError("uq_user_company_id_id has an incompatible definition.")
    if not named:
        equivalents = [
            item for item in constraints
            if item.get("column_names") == expected
        ]
        if equivalents:
            raise RuntimeError(
                "An equivalent user unique constraint exists under another name; "
                "migration-state reconciliation is required."
            )
        for index in inspector.get_indexes("user"):
            if index.get("unique") and index.get("column_names") == expected:
                raise RuntimeError(
                    "An equivalent user unique index exists without the required "
                    "named constraint; reconciliation is required."
                )
        raise RuntimeError(
            "Required uq_user_company_id_id is missing; refusing calendar migration."
        )


def _preflight(bind):
    inspector = sa.inspect(bind)

    for table in ("company", "user"):
        if not inspector.has_table(table):
            raise RuntimeError(f"Required table {table!r} does not exist.")

    for table in (
        "financial_year",
        "accounting_period",
        "accounting_period_event",
    ):
        if inspector.has_table(table):
            raise RuntimeError(
                f"Table {table!r} already exists; refusing to adopt or modify it."
            )

    _preflight_user_company_unique(bind)

    statement = sa.text(
        """
        SELECT c.relname, c.relkind
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relname IN :names
        """
    ).bindparams(sa.bindparam("names", expanding=True))

    rows = bind.execute(
        statement,
        {"names": list(RESERVED_RELATION_NAMES)},
    ).mappings().all()

    if rows:
        raise RuntimeError(
            "Accounting calendar reserved relation names already exist; "
            f"refusing migration: {[dict(row) for row in rows]!r}"
        )


def upgrade():
    bind = op.get_bind()
    _require_postgresql_online(bind)
    _preflight(bind)

    op.create_table(
        "financial_year",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "closed_by_id"],
            ["user.company_id", "user.id"],
            name="fk_financial_year_closer_same_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "id",
            name="uq_financial_year_company_id_id",
        ),
        sa.UniqueConstraint(
            "company_id", "name",
            name="uq_financial_year_company_name",
        ),
        sa.CheckConstraint(
            "start_date <= end_date",
            name="ck_financial_year_valid_dates",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'closed')",
            name="ck_financial_year_valid_status",
        ),
    )
    op.create_index(
        "ix_financial_year_company_dates",
        "financial_year",
        ["company_id", "start_date", "end_date"],
        unique=False,
    )

    op.create_table(
        "accounting_period",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("financial_year_id", sa.Integer(), nullable=False),
        sa.Column("period_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "financial_year_id"],
            ["financial_year.company_id", "financial_year.id"],
            name="fk_accounting_period_year_same_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "closed_by_id"],
            ["user.company_id", "user.id"],
            name="fk_accounting_period_closer_same_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "id",
            name="uq_accounting_period_company_id_id",
        ),
        sa.UniqueConstraint(
            "company_id", "financial_year_id", "period_number",
            name="uq_accounting_period_year_number",
        ),
        sa.CheckConstraint(
            "start_date <= end_date",
            name="ck_accounting_period_valid_dates",
        ),
        sa.CheckConstraint(
            "period_number > 0",
            name="ck_accounting_period_positive_number",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'closed')",
            name="ck_accounting_period_valid_status",
        ),
    )
    op.create_index(
        "ix_accounting_period_company_dates",
        "accounting_period",
        ["company_id", "start_date", "end_date"],
        unique=False,
    )

    op.create_table(
        "accounting_period_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("financial_year_id", sa.Integer(), nullable=True),
        sa.Column("accounting_period_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("performed_by_id", sa.Integer(), nullable=False),
        sa.Column("performed_at", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "financial_year_id"],
            ["financial_year.company_id", "financial_year.id"],
            name="fk_accounting_event_year_same_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "accounting_period_id"],
            ["accounting_period.company_id", "accounting_period.id"],
            name="fk_accounting_event_period_same_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "performed_by_id"],
            ["user.company_id", "user.id"],
            name="fk_accounting_event_actor_same_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(financial_year_id IS NOT NULL AND accounting_period_id IS NULL) OR "
            "(financial_year_id IS NULL AND accounting_period_id IS NOT NULL)",
            name="ck_accounting_event_exactly_one_target",
        ),
        sa.CheckConstraint(
            "event_type IN ('opened', 'closed', 'reopened')",
            name="ck_accounting_event_valid_type",
        ),
    )
    op.create_index(
        "ix_accounting_event_company_time",
        "accounting_period_event",
        ["company_id", "performed_at"],
        unique=False,
    )


def downgrade():
    raise RuntimeError(
        "Accounting calendar downgrade is intentionally blocked. "
        "Review financial years, periods, audit events and dependent journal "
        "references manually; this migration will not drop accounting history."
    )
