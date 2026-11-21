"""Create the missing company-safe accounting detail tables.

Revision ID: p11_accounting_detail_01
Revises: p11_journal_period_fk_01
"""

from alembic import context, op
import sqlalchemy as sa


revision = "p11_accounting_detail_01"
down_revision = "p11_journal_period_fk_01"
branch_labels = None
depends_on = None


USER_UNIQUE_NAME = "uq_user_company_id_id"
JOURNAL_UNIQUE_NAME = "uq_journal_company_id_id"

TABLE_NAMES = (
    "account",
    "journal_line",
    "journal_audit_event",
)

RESERVED_RELATION_NAMES = (
    "account_id_seq",
    "journal_line_id_seq",
    "journal_audit_event_id_seq",
    "account_pkey",
    "journal_line_pkey",
    "journal_audit_event_pkey",
    "uq_account_company_code",
    "uq_account_company_system_code",
    "uq_account_company_id_id",
    "fk_account_parent_same_company",
    "ck_account_valid_type",
    "ck_account_valid_normal_balance",
    "ix_account_company_type_active",
    "ix_account_parent_id",
    "fk_journal_line_same_company",
    "fk_journal_line_account_same_company",
    "uq_journal_line_number",
    "ck_journal_line_positive_number",
    "ck_journal_line_nonnegative_amounts",
    "ck_journal_line_one_positive_side",
    "ix_journal_line_company_account",
    "fk_journal_audit_entry_same_company",
    "fk_journal_audit_actor_same_company",
    "ck_journal_audit_valid_event_type",
    "ix_journal_audit_company_time",
    "ix_journal_audit_company_journal",
)


def _require_postgresql_online(bind):
    if context.is_offline_mode():
        raise RuntimeError(
            "Accounting detail migration requires an online PostgreSQL connection."
        )
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "Accounting detail migration supports PostgreSQL only."
        )


def _require_unique_constraint(inspector, table, name, columns):
    constraints = inspector.get_unique_constraints(table)
    named = [item for item in constraints if item.get("name") == name]

    if len(named) != 1 or named[0].get("column_names") != columns:
        raise RuntimeError(
            f"Required unique constraint {name} on {table}{tuple(columns)} "
            "is missing or incompatible; refusing migration."
        )

    equivalents = [
        item for item in constraints
        if item.get("column_names") == columns and item.get("name") != name
    ]
    if equivalents:
        raise RuntimeError(
            f"An equivalent unique constraint for {table}{tuple(columns)} "
            "exists under another name; migration-state reconciliation is required."
        )

    for index in inspector.get_indexes(table):
        if (
            index.get("unique")
            and index.get("column_names") == columns
            and index.get("duplicates_constraint") != name
        ):
            raise RuntimeError(
                f"An equivalent unique index for {table}{tuple(columns)} "
                "exists without the required named constraint."
            )


def _preflight(bind):
    inspector = sa.inspect(bind)

    required_tables = ("company", "user", "journal_entry", "accounting_period")
    for table in required_tables:
        if not inspector.has_table(table):
            raise RuntimeError(
                f"Required table {table!r} does not exist; refusing migration."
            )

    for table in TABLE_NAMES:
        if inspector.has_table(table):
            raise RuntimeError(
                f"Table {table!r} already exists; refusing to adopt or modify it."
            )

    _require_unique_constraint(
        inspector, "user", USER_UNIQUE_NAME, ["company_id", "id"]
    )
    _require_unique_constraint(
        inspector, "journal_entry", JOURNAL_UNIQUE_NAME, ["company_id", "id"]
    )

    journal_columns = {
        item["name"]: item for item in inspector.get_columns("journal_entry")
    }
    for name in ("company_id", "id"):
        if name not in journal_columns:
            raise RuntimeError(
                f"journal_entry is missing {name}; refusing migration."
            )
        if not isinstance(journal_columns[name]["type"], sa.Integer):
            raise RuntimeError(
                f"journal_entry.{name} must be INTEGER; refusing migration."
            )

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

    constraint_statement = sa.text(
        """
        SELECT con.conname AS relname, 'constraint' AS relkind
        FROM pg_constraint AS con
        JOIN pg_class AS t ON t.oid = con.conrelid
        JOIN pg_namespace AS n ON n.oid = t.relnamespace
        WHERE n.nspname = current_schema()
          AND con.conname IN :names
        """
    ).bindparams(sa.bindparam("names", expanding=True))

    constraint_rows = bind.execute(
        constraint_statement,
        {"names": list(RESERVED_RELATION_NAMES)},
    ).mappings().all()

    conflicts = [dict(row) for row in rows + constraint_rows]
    if conflicts:
        raise RuntimeError(
            "Accounting detail reserved PostgreSQL relation or constraint "
            "names already exist; refusing migration: "
            f"{conflicts!r}"
        )


def upgrade():
    bind = op.get_bind()
    _require_postgresql_online(bind)
    _preflight(bind)

    op.create_table(
        "account",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("account_code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("account_type", sa.String(length=20), nullable=False),
        sa.Column("normal_balance", sa.String(length=6), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("system_code", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("allow_manual_posting", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "parent_id"],
            ["account.company_id", "account.id"],
            name="fk_account_parent_same_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "account_code", name="uq_account_company_code"
        ),
        sa.UniqueConstraint(
            "company_id", "system_code", name="uq_account_company_system_code"
        ),
        sa.UniqueConstraint(
            "company_id", "id", name="uq_account_company_id_id"
        ),
        sa.CheckConstraint(
            "account_type IN ('asset', 'liability', 'equity', 'income', 'expense')",
            name="ck_account_valid_type",
        ),
        sa.CheckConstraint(
            "normal_balance IN ('debit', 'credit')",
            name="ck_account_valid_normal_balance",
        ),
    )
    op.create_index(
        "ix_account_company_type_active",
        "account",
        ["company_id", "account_type", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_account_parent_id",
        "account",
        ["parent_id"],
        unique=False,
    )

    op.create_table(
        "journal_line",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column(
            "debit", sa.Numeric(precision=14, scale=2), nullable=False
        ),
        sa.Column(
            "credit", sa.Numeric(precision=14, scale=2), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "journal_entry_id"],
            ["journal_entry.company_id", "journal_entry.id"],
            name="fk_journal_line_same_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "account_id"],
            ["account.company_id", "account.id"],
            name="fk_journal_line_account_same_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "journal_entry_id",
            "line_number",
            name="uq_journal_line_number",
        ),
        sa.CheckConstraint(
            "line_number > 0",
            name="ck_journal_line_positive_number",
        ),
        sa.CheckConstraint(
            "debit >= 0 AND credit >= 0",
            name="ck_journal_line_nonnegative_amounts",
        ),
        sa.CheckConstraint(
            "(debit > 0 AND credit = 0) OR "
            "(credit > 0 AND debit = 0)",
            name="ck_journal_line_one_positive_side",
        ),
    )
    op.create_index(
        "ix_journal_line_company_account",
        "journal_line",
        ["company_id", "account_id"],
        unique=False,
    )

    op.create_table(
        "journal_audit_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("performed_by_id", sa.Integer(), nullable=False),
        sa.Column("performed_at", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id", "journal_entry_id"],
            ["journal_entry.company_id", "journal_entry.id"],
            name="fk_journal_audit_entry_same_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "performed_by_id"],
            ["user.company_id", "user.id"],
            name="fk_journal_audit_actor_same_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "event_type IN ('created', 'updated', 'posted', 'reversed')",
            name="ck_journal_audit_valid_event_type",
        ),
    )
    op.create_index(
        "ix_journal_audit_company_time",
        "journal_audit_event",
        ["company_id", "performed_at"],
        unique=False,
    )
    op.create_index(
        "ix_journal_audit_company_journal",
        "journal_audit_event",
        ["company_id", "journal_entry_id"],
        unique=False,
    )


def downgrade():
    raise RuntimeError(
        "Accounting detail migration downgrade is intentionally blocked. "
        "Removing accounting accounts, journal lines, or audit events requires "
        "a separate manual review and approval."
    )
