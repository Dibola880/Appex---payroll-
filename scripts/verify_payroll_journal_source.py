"""
Read-only verification for the payroll journal source uniqueness migration.

Usage:
    DATABASE_URL='...' python scripts/verify_payroll_journal_source.py

This script does not modify database objects or data.
"""

import os
import re
import sys

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("FAIL: psycopg is not installed.")
    sys.exit(2)


INDEX_NAME = "uq_journal_payroll_source"

REQUIRED_COLUMNS = {
    "journal_entry": {
        "id", "company_id", "source_type", "source_id"
    },
    "payroll_run": {
        "id", "company_id"
    },
}

CAST_PATTERN = re.compile(
    r"::\s*(?:character varying(?:\s*\(\s*\d+\s*\))?|"
    r"varchar(?:\s*\(\s*\d+\s*\))?|text)(?=\s|$)",
    flags=re.IGNORECASE,
)
NORMALIZE_PATTERN = re.compile(r'[\s()"]+')


def normalize_predicate(predicate):
    predicate = predicate or ""
    predicate = CAST_PATTERN.sub("", predicate)
    return NORMALIZE_PATTERN.sub("", predicate).lower()


def print_samples(title, rows):
    if not rows:
        return
    print(f"\n{title} (up to 10 examples):")
    for row in rows:
        print("  " + ", ".join(f"{key}={value!r}" for key, value in row.items()))


def main():
    conninfo = os.environ.get("DATABASE_URL")
    if not conninfo:
        print("STOP: DATABASE_URL is not configured.")
        print("No database connection was attempted.")
        return 2

    # Accept Render's legacy postgres:// URL scheme without displaying it.
    if conninfo.startswith("postgres://"):
        conninfo = "postgresql://" + conninfo[len("postgres://"):]

    if conninfo.startswith("postgresql+psycopg://"):
        conninfo = "postgresql://" + conninfo[len("postgresql+psycopg://"):]

    connection = None
    failures = []
    warnings = []

    try:
        connection = psycopg.connect(
            conninfo,
            connect_timeout=10,
            row_factory=dict_row,
            autocommit=True,
        )

        # This must be the first SQL command in the transaction.
        connection.execute("BEGIN TRANSACTION READ ONLY")
        connection.execute("SET LOCAL statement_timeout = '30s'")

        identity = connection.execute(
            """
            SELECT current_database() AS database_name,
                   current_schema() AS schema_name,
                   current_setting('server_version') AS server_version
            """
        ).fetchone()

        print("===== READ-ONLY DATABASE VERIFICATION =====")
        print(f"Database: {identity['database_name']}")
        print(f"Schema: {identity['schema_name']}")
        print(f"PostgreSQL: {identity['server_version']}")
        print("Transaction mode: READ ONLY")

        if identity["schema_name"] is None:
            failures.append("No active current_schema() was resolved.")

        # 1. Required columns and their actual PostgreSQL types.
        print("\n===== REQUIRED COLUMNS =====")
        column_rows = connection.execute(
            """
            SELECT table_name, column_name, data_type, udt_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name IN ('journal_entry', 'payroll_run')
            ORDER BY table_name, ordinal_position
            """
        ).fetchall()

        found = {}
        for row in column_rows:
            found.setdefault(row["table_name"], set()).add(row["column_name"])
            print(
                f"{row['table_name']}.{row['column_name']}: "
                f"{row['data_type']} ({row['udt_name']}), "
                f"nullable={row['is_nullable']}"
            )

        for table_name, required in REQUIRED_COLUMNS.items():
            missing = required - found.get(table_name, set())
            if missing:
                failures.append(
                    f"{table_name} is missing columns: {sorted(missing)}"
                )

        if not failures:
            print("PASS: all required columns exist.")

        # 2. Noncanonical payroll source_type values.
        print("\n===== NONCANONICAL PAYROLL SOURCE VALUES =====")
        noncanonical_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM journal_entry
            WHERE lower(btrim(source_type)) = 'payroll'
              AND source_type <> 'payroll'
            """
        ).fetchone()["count"]

        noncanonical_samples = connection.execute(
            """
            SELECT id, company_id, source_id, source_type
            FROM journal_entry
            WHERE lower(btrim(source_type)) = 'payroll'
              AND source_type <> 'payroll'
            ORDER BY id
            LIMIT 10
            """
        ).fetchall()

        print(f"Count: {noncanonical_count}")
        print_samples("Examples", noncanonical_samples)
        if noncanonical_count:
            failures.append(
                f"{noncanonical_count} noncanonical payroll source_type rows."
            )

        # 3. Duplicate payroll source references.
        print("\n===== DUPLICATE PAYROLL SOURCE REFERENCES =====")
        duplicate_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM (
                SELECT company_id, source_id
                FROM journal_entry
                WHERE source_type = 'payroll'
                  AND source_id IS NOT NULL
                GROUP BY company_id, source_id
                HAVING COUNT(*) > 1
            ) AS duplicates
            """
        ).fetchone()["count"]

        duplicate_samples = connection.execute(
            """
            SELECT company_id, source_id, COUNT(*) AS journal_count
            FROM journal_entry
            WHERE source_type = 'payroll'
              AND source_id IS NOT NULL
            GROUP BY company_id, source_id
            HAVING COUNT(*) > 1
            ORDER BY company_id, source_id
            LIMIT 10
            """
        ).fetchall()

        print(f"Duplicate groups: {duplicate_count}")
        print_samples("Examples", duplicate_samples)
        if duplicate_count:
            failures.append(
                f"{duplicate_count} duplicate payroll source groups."
            )

        # 4. Orphaned and cross-company payroll references.
        print("\n===== ORPHANED / CROSS-COMPANY REFERENCES =====")
        orphan_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM journal_entry AS je
            LEFT JOIN payroll_run AS pr
              ON pr.id = je.source_id
             AND pr.company_id = je.company_id
            WHERE je.source_type = 'payroll'
              AND je.source_id IS NOT NULL
              AND pr.id IS NULL
            """
        ).fetchone()["count"]

        orphan_samples = connection.execute(
            """
            SELECT je.id, je.company_id, je.source_id
            FROM journal_entry AS je
            LEFT JOIN payroll_run AS pr
              ON pr.id = je.source_id
             AND pr.company_id = je.company_id
            WHERE je.source_type = 'payroll'
              AND je.source_id IS NOT NULL
              AND pr.id IS NULL
            ORDER BY je.id
            LIMIT 10
            """
        ).fetchall()

        print(f"Count: {orphan_count}")
        print_samples("Examples", orphan_samples)
        if orphan_count:
            failures.append(
                f"{orphan_count} orphaned or cross-company payroll references."
            )

        # 5. Execute the exact PostgreSQL catalog query used by the migration.
        print("\n===== POSTGRESQL INDEX CATALOG QUERY =====")
        indexes = connection.execute(
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
        ).fetchall()

        print(f"Catalog query executed successfully. Indexes found: {len(indexes)}")

        for row in indexes:
            print(
                f"  {row['indexname']}: unique={row['is_unique']}, "
                f"valid={row['is_valid']}, ready={row['is_ready']}, "
                f"keys={row['key_columns']}, predicate={row['predicate']!r}"
            )

            if row["indexname"] == INDEX_NAME:
                failures.append(
                    f"Index name {INDEX_NAME} already exists; inspect migration state."
                )
                continue

            equivalent = (
                row["is_unique"]
                and row["key_column_count"] == 2
                and row["total_column_count"] == 2
                and not row["has_expressions"]
                and list(row["key_columns"]) == ["company_id", "source_id"]
                and normalize_predicate(row["predicate"])
                    == "source_type='payroll'andsource_idisnotnull"
            )

            if equivalent:
                failures.append(
                    f"Equivalent payroll-source index already exists as "
                    f"{row['indexname']} (valid={row['is_valid']}, "
                    f"ready={row['is_ready']})."
                )

        # Read-only transaction is explicitly rolled back below.
        print("\n===== RESULT =====")
        if failures:
            print("FAIL: migration preflight is not clean.")
            for item in failures:
                print(f" - {item}")
        else:
            print("PASS: no migration preflight conflicts were detected.")

        if warnings:
            for item in warnings:
                print(f"WARNING: {item}")

        print("No database changes were made.")
        return 1 if failures else 0

    except Exception as exc:
        print("\nFAIL: read-only verification could not complete.")
        # Do not print connection strings or exception text that might
        # contain connection details.
        print(f"Error type: {type(exc).__name__}")
        print("No migration or schema changes were attempted.")
        return 2

    finally:
        if connection is not None:
            try:
                connection.rollback()
            finally:
                connection.close()


if __name__ == "__main__":
    sys.exit(main())
