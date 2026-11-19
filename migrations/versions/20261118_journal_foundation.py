"""Create the foundational company-safe accounting journal.

Revision ID: p10_journal_foundation_01
Revises: p10_payroll_currency_01
"""

from alembic import context, op
import sqlalchemy as sa


revision = "p10_journal_foundation_01"
down_revision = "p10_payroll_currency_01"
branch_labels = None
depends_on = None


USER_UNIQUE_NAME = "uq_user_company_id_id"

RESERVED_INDEX_NAMES = (
    USER_UNIQUE_NAME,
    "uq_journal_company_number",
    "uq_journal_company_id_id",
    "uq_journal_company_reversal",
    "ix_journal_company_date_status",
    "ix_journal_company_period",
)


def _require_postgresql_online(bind):
    if context.is_offline_mode():
        raise RuntimeError(
            "Journal foundation migration requires an online PostgreSQL connection."
        )

    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "Journal foundation migration supports PostgreSQL only."
        )


def _preflight_user_company_unique(bind):
    """Validate the user composite key without changing the database."""

    inspector = sa.inspect(bind)

    if not inspector.has_table("user"):
        raise RuntimeError("Required table 'user' does not exist.")

    columns = {
        column["name"]
        for column in inspector.get_columns("user")
    }
    if not {"company_id", "id"}.issubset(columns):
        raise RuntimeError(
            "The user table is missing company_id or id; refusing migration."
        )

    expected = ["company_id", "id"]
    constraints = inspector.get_unique_constraints("user")

    named = [
        constraint
        for constraint in constraints
        if constraint.get("name") == USER_UNIQUE_NAME
    ]

    if len(named) > 1:
        raise RuntimeError(
            f"Multiple user constraints use the name {USER_UNIQUE_NAME}."
        )

    has_named_constraint = bool(named)

    if has_named_constraint and named[0].get("column_names") != expected:
        raise RuntimeError(
            f"{USER_UNIQUE_NAME} exists with an incompatible definition."
        )

    equivalent_constraints = [
        constraint
        for constraint in constraints
        if constraint.get("column_names") == expected
        and constraint.get("name") != USER_UNIQUE_NAME
    ]
    if equivalent_constraints:
        raise RuntimeError(
            "An equivalent user(company_id, id) unique constraint exists "
            "under another name; migration-state reconciliation is required."
        )

    for index in inspector.get_indexes("user"):
        index_name = index.get("name")
        duplicates_constraint = index.get("duplicates_constraint")

        if index_name == USER_UNIQUE_NAME:
            if (
                has_named_constraint
                and duplicates_constraint == USER_UNIQUE_NAME
                and index.get("unique")
                and index.get("column_names") == expected
            ):
                continue

            raise RuntimeError(
                f"An index already uses the reserved name {USER_UNIQUE_NAME} "
                "without matching the expected unique constraint."
            )

        if duplicates_constraint:
            continue

        if (
            index.get("unique")
            and index.get("column_names") == expected
        ):
            raise RuntimeError(
                "An equivalent user(company_id, id) unique index exists "
                "without the required named constraint; reconciliation is required."
            )

    return not has_named_constraint


def _preflight_reserved_relation_names(bind, create_user_unique):
    """Reject schema-wide relation-name collisions before any DDL."""

    statement = sa.text(
        """
        SELECT
            c.relname,
            c.relkind,
            owner_table.relname AS owner_table,
            con.conname AS constraint_name
        FROM pg_class AS c
        JOIN pg_namespace AS n
          ON n.oid = c.relnamespace
        LEFT JOIN pg_index AS idx
          ON idx.indexrelid = c.oid
        LEFT JOIN pg_class AS owner_table
          ON owner_table.oid = idx.indrelid
        LEFT JOIN pg_constraint AS con
          ON con.conindid = c.oid
         AND con.contype = 'u'
        WHERE n.nspname = current_schema()
          AND c.relname IN :names
        """
    ).bindparams(sa.bindparam("names", expanding=True))

    rows = bind.execute(
        statement,
        {"names": list(RESERVED_INDEX_NAMES)},
    ).mappings().all()

    collisions = []

    for row in rows:
        expected_existing_user_index = (
            not create_user_unique
            and row["relname"] == USER_UNIQUE_NAME
            and row["relkind"] == "i"
            and row["owner_table"] == "user"
            and row["constraint_name"] == USER_UNIQUE_NAME
        )

        if not expected_existing_user_index:
            collisions.append(
                {
                    "name": row["relname"],
                    "relation_kind": row["relkind"],
                    "owner_table": row["owner_table"],
                    "constraint": row["constraint_name"],
                }
            )

    if collisions:
        raise RuntimeError(
            "Reserved PostgreSQL relation names are already in use; "
            f"refusing migration: {collisions!r}"
        )


def _create_user_company_unique():
    op.create_unique_constraint(
        USER_UNIQUE_NAME,
        "user",
        ["company_id", "id"],
    )


def _inspect_existing_journal_table(bind):
    """Verify an existing journal table, then require migration reconciliation."""

    import re

    inspector = sa.inspect(bind)

    expected_columns = {
        "id": (sa.Integer, None, False),
        "company_id": (sa.Integer, None, False),
        "journal_number": (sa.String, 40, False),
        "journal_date": (sa.Date, None, False),
        "accounting_period_id": (sa.Integer, None, True),
        "description": (sa.String, 500, False),
        "currency": (sa.String, 3, False),
        "source_type": (sa.String, 40, False),
        "source_id": (sa.Integer, None, True),
        "status": (sa.String, 20, False),
        "created_by_id": (sa.Integer, None, False),
        "posted_by_id": (sa.Integer, None, True),
        "posted_at": (sa.DateTime, None, True),
        "reversal_of_id": (sa.Integer, None, True),
        "created_at": (sa.DateTime, None, False),
    }

    column_list = inspector.get_columns("journal_entry")
    actual_column_order = [column["name"] for column in column_list]
    actual_columns = {
        column["name"]: column
        for column in column_list
    }

    if actual_column_order != list(expected_columns):
        raise RuntimeError(
            "Existing journal_entry columns are not in the expected order."
        )

    if set(actual_columns) != set(expected_columns):
        raise RuntimeError(
            "Existing journal_entry has an incompatible column set. "
            f"Missing={sorted(set(expected_columns) - set(actual_columns))}; "
            f"extra={sorted(set(actual_columns) - set(expected_columns))}."
        )

    for name, (expected_type, expected_length, expected_nullable) in (
        expected_columns.items()
    ):
        column = actual_columns[name]
        actual_type = column["type"]

        expected_visit_name = expected_type().__visit_name__
        actual_visit_name = getattr(actual_type, "__visit_name__", None)

        if actual_visit_name != expected_visit_name:
            raise RuntimeError(
                f"Existing journal_entry.{name} has incompatible type "
                f"{actual_type!r}; expected {expected_visit_name}."
            )

        if expected_type is sa.DateTime:
            expected_timezone = expected_type().timezone
            actual_timezone = getattr(actual_type, "timezone", None)

            if actual_timezone != expected_timezone:
                raise RuntimeError(
                    f"Existing journal_entry.{name} has incompatible "
                    f"timestamp timezone setting: {actual_timezone!r}; "
                    f"expected {expected_timezone!r}."
                )

        if expected_length is not None and getattr(
            actual_type, "length", None
        ) != expected_length:
            raise RuntimeError(
                f"Existing journal_entry.{name} has incompatible length."
            )

        if column["nullable"] != expected_nullable:
            raise RuntimeError(
                f"Existing journal_entry.{name} has incompatible nullability."
            )

        if column.get("default") is not None:
            raise RuntimeError(
                f"Existing journal_entry.{name} has an unexpected server default."
            )

    primary_key = inspector.get_pk_constraint("journal_entry")
    if primary_key.get("constrained_columns") != ["id"]:
        raise RuntimeError(
            "Existing journal_entry has an incompatible primary key."
        )

    expected_unique = {
        "uq_journal_company_number": ["company_id", "journal_number"],
        "uq_journal_company_id_id": ["company_id", "id"],
        "uq_journal_company_reversal": ["company_id", "reversal_of_id"],
    }
    actual_unique = {
        item.get("name"): item.get("column_names")
        for item in inspector.get_unique_constraints("journal_entry")
    }
    if actual_unique != expected_unique:
        raise RuntimeError(
            "Existing journal_entry unique constraints do not match the "
            f"required definitions. Actual={actual_unique!r}."
        )

    expected_foreign_keys = {
        (
            "fk_journal_company",
            ("company_id",),
            "company",
            ("id",),
            "RESTRICT",
        ),
        (
            "fk_journal_reversal_same_company",
            ("company_id", "reversal_of_id"),
            "journal_entry",
            ("company_id", "id"),
            "RESTRICT",
        ),
        (
            "fk_journal_creator_same_company",
            ("company_id", "created_by_id"),
            "user",
            ("company_id", "id"),
            "RESTRICT",
        ),
        (
            "fk_journal_poster_same_company",
            ("company_id", "posted_by_id"),
            "user",
            ("company_id", "id"),
            "RESTRICT",
        ),
    }

    actual_foreign_keys = set()
    for item in inspector.get_foreign_keys("journal_entry"):
        options = item.get("options") or {}
        actual_foreign_keys.add(
            (
                item.get("name"),
                tuple(item.get("constrained_columns") or ()),
                item.get("referred_table"),
                tuple(item.get("referred_columns") or ()),
                (options.get("ondelete") or "").upper(),
            )
        )

    if actual_foreign_keys != expected_foreign_keys:
        raise RuntimeError(
            "Existing journal_entry foreign keys do not match the required "
            f"same-company definitions. Actual={actual_foreign_keys!r}."
        )

    expected_checks = {
        "ck_journal_valid_status":
            "status IN ('draft', 'posted', 'reversed')",
        "ck_journal_posted_requires_period":
            "status = 'draft' OR accounting_period_id IS NOT NULL",
        "ck_journal_currency_length":
            "length(currency) = 3",
        "ck_journal_no_self_reversal":
            "reversal_of_id IS NULL OR reversal_of_id != id",
    }

    def normalize_check(expression):
        expression = expression or ""
        expression = re.sub(r"\s+", "", expression)
        expression = expression.replace('"', "").lower()
        return expression

    actual_checks = {
        item.get("name"): normalize_check(item.get("sqltext"))
        for item in inspector.get_check_constraints("journal_entry")
    }
    normalized_expected_checks = {
        name: normalize_check(expression)
        for name, expression in expected_checks.items()
    }

    if actual_checks != normalized_expected_checks:
        raise RuntimeError(
            "Existing journal_entry check constraints do not match the "
            f"required definitions. Actual={actual_checks!r}."
        )

    expected_indexes = {
        "ix_journal_company_date_status": (
            ["company_id", "journal_date", "status"],
            False,
            None,
            None,
        ),
        "ix_journal_company_period": (
            ["company_id", "accounting_period_id"],
            False,
            None,
            None,
        ),
    }

    actual_indexes = {}
    for item in inspector.get_indexes("journal_entry"):
        if item.get("duplicates_constraint"):
            continue

        name = item.get("name")
        if name:
            actual_indexes[name] = (
                item.get("column_names"),
                bool(item.get("unique")),
                item.get("expressions"),
                item.get("dialect_options", {}).get("postgresql_where"),
            )

    if actual_indexes != expected_indexes:
        raise RuntimeError(
            "Existing journal_entry indexes do not match the required "
            f"definitions. Actual={actual_indexes!r}."
        )

    raise RuntimeError(
        "Existing journal_entry passed the structural checks, but this "
        "migration will not silently adopt a pre-existing table. "
        "Stop for explicit migration-state reconciliation."
    )

def upgrade():
    bind = op.get_bind()
    _require_postgresql_online(bind)

    inspector = sa.inspect(bind)

    if inspector.has_table("journal_entry"):
        _inspect_existing_journal_table(bind)

    create_user_unique = _preflight_user_company_unique(bind)
    _preflight_reserved_relation_names(bind, create_user_unique)

    if create_user_unique:
        _create_user_company_unique()

    op.create_table(
        "journal_entry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("journal_number", sa.String(length=40), nullable=False),
        sa.Column("journal_date", sa.Date(), nullable=False),
        sa.Column("accounting_period_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("posted_by_id", sa.Integer(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("reversal_of_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name="fk_journal_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "reversal_of_id"],
            ["journal_entry.company_id", "journal_entry.id"],
            name="fk_journal_reversal_same_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "created_by_id"],
            ["user.company_id", "user.id"],
            name="fk_journal_creator_same_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "posted_by_id"],
            ["user.company_id", "user.id"],
            name="fk_journal_poster_same_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "journal_number",
            name="uq_journal_company_number",
        ),
        sa.UniqueConstraint(
            "company_id",
            "id",
            name="uq_journal_company_id_id",
        ),
        sa.UniqueConstraint(
            "company_id",
            "reversal_of_id",
            name="uq_journal_company_reversal",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'posted', 'reversed')",
            name="ck_journal_valid_status",
        ),
        sa.CheckConstraint(
            "status = 'draft' OR accounting_period_id IS NOT NULL",
            name="ck_journal_posted_requires_period",
        ),
        sa.CheckConstraint(
            "length(currency) = 3",
            name="ck_journal_currency_length",
        ),
        sa.CheckConstraint(
            "reversal_of_id IS NULL OR reversal_of_id != id",
            name="ck_journal_no_self_reversal",
        ),
    )

    op.create_index(
        "ix_journal_company_date_status",
        "journal_entry",
        ["company_id", "journal_date", "status"],
        unique=False,
    )

    op.create_index(
        "ix_journal_company_period",
        "journal_entry",
        ["company_id", "accounting_period_id"],
        unique=False,
    )


def downgrade():
    raise RuntimeError(
        "Journal foundation downgrade is intentionally blocked. "
        "Review journal records and dependent revisions manually; "
        "this migration will not drop journal_entry or user constraints."
    )
