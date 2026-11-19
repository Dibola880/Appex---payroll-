"""Enforce same-company journal accounting-period references.

Revision ID: p11_journal_period_fk_01
Revises: p11_accounting_calendar_01
"""
from alembic import context, op
import sqlalchemy as sa


revision = "p11_journal_period_fk_01"
down_revision = "p11_accounting_calendar_01"
branch_labels = None
depends_on = None

FOREIGN_KEY_NAME = "fk_journal_period_same_company"


def _require_postgresql_online(bind):
    if context.is_offline_mode():
        raise RuntimeError(
            "Journal-period FK migration requires an online PostgreSQL connection."
        )
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "Journal-period FK migration supports PostgreSQL only."
        )


def _preflight(bind):
    inspector = sa.inspect(bind)

    for table in ("journal_entry", "accounting_period"):
        if not inspector.has_table(table):
            raise RuntimeError(
                f"Required table {table!r} does not exist; refusing migration."
            )

    journal_columns = {
        column["name"]: column
        for column in inspector.get_columns("journal_entry")
    }
    period_columns = {
        column["name"]: column
        for column in inspector.get_columns("accounting_period")
    }

    for name in ("company_id", "accounting_period_id"):
        if name not in journal_columns:
            raise RuntimeError(
                f"journal_entry is missing {name}; refusing migration."
            )
    for name in ("company_id", "id"):
        if name not in period_columns:
            raise RuntimeError(
                f"accounting_period is missing {name}; refusing migration."
            )

    expected_columns = (
        (journal_columns, "company_id", False, "journal_entry"),
        (journal_columns, "accounting_period_id", True, "journal_entry"),
        (period_columns, "company_id", False, "accounting_period"),
        (period_columns, "id", False, "accounting_period"),
    )
    for columns, name, nullable, table in expected_columns:
        column = columns[name]
        if not isinstance(column["type"], sa.Integer):
            raise RuntimeError(
                f"{table}.{name} must be an INTEGER column; refusing migration."
            )
        if column["nullable"] is not nullable:
            expected = "nullable" if nullable else "NOT NULL"
            raise RuntimeError(
                f"{table}.{name} must be {expected}; refusing migration."
            )

    period_unique = [
        item for item in inspector.get_unique_constraints("accounting_period")
        if item.get("column_names") == ["company_id", "id"]
    ]
    if len(period_unique) != 1:
        raise RuntimeError(
            "accounting_period lacks exactly one unique (company_id, id) "
            "constraint required by the composite foreign key."
        )

    foreign_keys = inspector.get_foreign_keys("journal_entry")
    exact = [
        item for item in foreign_keys
        if item.get("name") == FOREIGN_KEY_NAME
    ]
    if exact:
        raise RuntimeError(
            f"{FOREIGN_KEY_NAME} already exists; migration-state reconciliation "
            "is required rather than silent adoption."
        )

    equivalent = [
        item for item in foreign_keys
        if item.get("constrained_columns") == ["company_id", "accounting_period_id"]
        and item.get("referred_table") == "accounting_period"
        and item.get("referred_columns") == ["company_id", "id"]
    ]
    if equivalent:
        raise RuntimeError(
            "An equivalent journal-period foreign key already exists under "
            "another name; migration-state reconciliation is required."
        )

    orphan_count = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM journal_entry AS j
            LEFT JOIN accounting_period AS p
              ON p.company_id = j.company_id
             AND p.id = j.accounting_period_id
            WHERE j.accounting_period_id IS NOT NULL
              AND p.id IS NULL
            """
        )
    ).scalar_one()

    if orphan_count:
        raise RuntimeError(
            f"Found {orphan_count} journal row(s) with missing or cross-company "
            "accounting-period references. No rows were changed. Resolve through "
            "a separately reviewed data-reconciliation process."
        )


def upgrade():
    bind = op.get_bind()
    _require_postgresql_online(bind)
    _preflight(bind)

    op.create_foreign_key(
        FOREIGN_KEY_NAME,
        "journal_entry",
        "accounting_period",
        ["company_id", "accounting_period_id"],
        ["company_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade():
    raise RuntimeError(
        "Journal-period FK downgrade is intentionally blocked. "
        "Removing this same-company integrity safeguard requires a separate "
        "manual review and approval."
    )
