"""Enforce one accounting journal per payroll run.

Revision ID: p10_payroll_journal_source_01
Revises: p10_journal_foundation_01
"""
from alembic import context, op
import sqlalchemy as sa

revision = "p10_payroll_journal_source_01"
down_revision = "p10_journal_foundation_01"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_journal_payroll_source"


def _require_postgresql_online(bind):
    if context.is_offline_mode():
        raise RuntimeError(
            "This migration requires an online PostgreSQL connection "
            "because its preflight checks must execute before index creation."
        )
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "Payroll journal source uniqueness migration requires PostgreSQL."
        )


def _require_schema(bind):
    required = {
        "journal_entry": {"id", "company_id", "source_type", "source_id"},
        "payroll_run": {"id", "company_id"},
    }

    for table_name, required_columns in required.items():
        rows = bind.execute(
            sa.text(
                "SELECT column_name "
                "FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = :table_name"
            ),
            {"table_name": table_name},
        ).scalars().all()

        missing = required_columns - set(rows)
        if missing:
            raise RuntimeError(
                f"Cannot create {INDEX_NAME}: {table_name} is missing "
                f"required columns: {', '.join(sorted(missing))}."
            )


def _assert_clean_payroll_sources(bind):
    noncanonical = bind.execute(
        sa.text(
            "SELECT id, company_id, source_id, source_type "
            "FROM journal_entry "
            "WHERE lower(btrim(source_type)) = 'payroll' "
            "AND source_type <> 'payroll' "
            "ORDER BY id LIMIT 10"
        )
    ).mappings().all()

    if noncanonical:
        raise RuntimeError(
            "Cannot create payroll journal uniqueness index: noncanonical "
            "payroll source_type values exist (case/whitespace variants). "
            f"Example rows: {[dict(row) for row in noncanonical]}"
        )

    duplicates = bind.execute(
        sa.text(
            "SELECT company_id, source_id, COUNT(*) AS journal_count "
            "FROM journal_entry "
            "WHERE source_type = 'payroll' AND source_id IS NOT NULL "
            "GROUP BY company_id, source_id "
            "HAVING COUNT(*) > 1 "
            "ORDER BY company_id, source_id LIMIT 10"
        )
    ).mappings().all()

    if duplicates:
        raise RuntimeError(
            "Cannot create payroll journal uniqueness index: duplicate "
            "payroll source references exist. Reconcile them without deleting "
            f"financial history before retrying. Examples: {[dict(row) for row in duplicates]}"
        )

    orphans = bind.execute(
        sa.text(
            "SELECT je.id, je.company_id, je.source_id "
            "FROM journal_entry AS je "
            "LEFT JOIN payroll_run AS pr "
            "ON pr.id = je.source_id AND pr.company_id = je.company_id "
            "WHERE je.source_type = 'payroll' "
            "AND je.source_id IS NOT NULL "
            "AND pr.id IS NULL "
            "ORDER BY je.id LIMIT 10"
        )
    ).mappings().all()

    if orphans:
        raise RuntimeError(
            "Cannot create payroll journal uniqueness index: orphaned or "
            "cross-company payroll source references exist. Reconcile them "
            f"before retrying. Examples: {[dict(row) for row in orphans]}"
        )


def _assert_index_name_available(bind):
    import re

    existing = bind.execute(
        sa.text(
            """
            SELECT
                index_relation.relname AS indexname,
                index_data.indisunique AS is_unique,
                index_data.indisvalid AS is_valid,
                index_data.indisready AS is_ready,
                index_data.indnkeyatts AS key_column_count,
                index_data.indnatts AS total_column_count,
                index_data.indexprs IS NOT NULL AS has_expressions,
                ARRAY(
                    SELECT attribute.attname
                    FROM unnest(index_data.indkey)
                         WITH ORDINALITY AS key_column(attnum, ordinal)
                    LEFT JOIN pg_attribute AS attribute
                      ON attribute.attrelid = index_data.indrelid
                     AND attribute.attnum = key_column.attnum
                    WHERE key_column.ordinal <= index_data.indnkeyatts
                    ORDER BY key_column.ordinal
                ) AS key_columns,
                pg_get_expr(
                    index_data.indpred,
                    index_data.indrelid
                ) AS predicate
            FROM pg_index AS index_data
            JOIN pg_class AS index_relation
              ON index_relation.oid = index_data.indexrelid
            JOIN pg_class AS table_relation
              ON table_relation.oid = index_data.indrelid
            JOIN pg_namespace AS table_namespace
              ON table_namespace.oid = table_relation.relnamespace
            WHERE table_namespace.nspname = current_schema()
              AND table_relation.relname = 'journal_entry'
            ORDER BY index_relation.relname
            """
        )
    ).mappings().all()

    for row in existing:
        if row["indexname"] == INDEX_NAME:
            raise RuntimeError(
                f"Cannot create {INDEX_NAME}: an index with that name "
                "already exists. Inspect its definition and reconcile "
                f"migration state. Existing metadata: {dict(row)}"
            )

        predicate = row["predicate"] or ""
        predicate = re.sub(
            r"::\s*(?:character varying(?:\s*\(\s*\d+\s*\))?|varchar(?:\s*\(\s*\d+\s*\))?|text)(?=\s|$)",
            "",
            predicate,
            flags=re.IGNORECASE,
        )
        normalized_predicate = re.sub(
            r'[\s()"]+',
            "",
            predicate,
        ).lower()

        equivalent_definition = (
            row["is_unique"]
            and row["key_column_count"] == 2
            and row["total_column_count"] == 2
            and not row["has_expressions"]
            and list(row["key_columns"]) == ["company_id", "source_id"]
            and normalized_predicate
                == "source_type='payroll'andsource_idisnotnull"
        )

        if equivalent_definition:
            raise RuntimeError(
                "An equivalent payroll-source unique index already exists "
                f"under the name {row['indexname']}. "
                f"Valid: {row['is_valid']}; ready: {row['is_ready']}. "
                "Inspect it and reconcile migration state before proceeding."
            )

def upgrade():
    bind = op.get_bind()
    _require_postgresql_online(bind)
    _require_schema(bind)
    _assert_clean_payroll_sources(bind)
    _assert_index_name_available(bind)

    op.create_index(
        INDEX_NAME,
        "journal_entry",
        ["company_id", "source_id"],
        unique=True,
        postgresql_where=sa.text(
            "source_type = 'payroll' AND source_id IS NOT NULL"
        ),
    )


def downgrade():
    bind = op.get_bind()
    _require_postgresql_online(bind)
    op.drop_index(INDEX_NAME, table_name="journal_entry")
