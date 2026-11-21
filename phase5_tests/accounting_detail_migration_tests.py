"""Isolated safety tests for the Phase 11 accounting detail migration.

These tests mock Alembic operations and PostgreSQL inspection.
They do not create or connect to any database.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa


sys.dont_write_bytecode = True

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20261121_p11_accounting_detail_tables.py"
)

spec = importlib.util.spec_from_file_location(
    "accounting_detail_migration_under_test",
    MIGRATION_PATH,
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class FakeMappings:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def mappings(self):
        return FakeMappings(self.rows)


class FakeBind:
    def __init__(self, dialect_name="postgresql", conflict_on_call=None):
        self.dialect = type("Dialect", (), {"name": dialect_name})()
        self.calls = 0
        self.conflict_on_call = conflict_on_call

    def execute(self, statement, parameters=None):
        self.calls += 1
        if self.calls == self.conflict_on_call:
            return FakeResult([{"relname": "unexpected_conflict", "relkind": "constraint"}])
        return FakeResult()


class FakeInspector:
    def __init__(
        self,
        *,
        existing_tables=None,
        missing_tables=None,
        missing_unique=None,
        reserved_conflict=False,
    ):
        self.existing_tables = set(existing_tables or [])
        self.missing_tables = set(missing_tables or [])
        self.missing_unique = set(missing_unique or [])
        self.reserved_conflict = reserved_conflict

    def has_table(self, table):
        if table in self.missing_tables:
            return False
        return table in self.existing_tables or table in {
            "company",
            "user",
            "journal_entry",
            "accounting_period",
        }

    def get_unique_constraints(self, table):
        expected = {
            ("user", migration.USER_UNIQUE_NAME): ["company_id", "id"],
            ("journal_entry", migration.JOURNAL_UNIQUE_NAME): ["company_id", "id"],
        }
        result = []
        for (target_table, name), columns in expected.items():
            if target_table == table and name not in self.missing_unique:
                result.append({"name": name, "column_names": columns})
        return result

    def get_indexes(self, table):
        return []

    def get_columns(self, table):
        return [
            {"name": "id", "type": sa.Integer()},
            {"name": "company_id", "type": sa.Integer()},
        ]


class AccountingDetailMigrationTests(unittest.TestCase):
    def run_upgrade(self, inspector=None, bind=None):
        inspector = inspector or FakeInspector()
        bind = bind or FakeBind()
        created_tables = []
        created_indexes = []

        with (
            patch.object(migration.context, "is_offline_mode", return_value=False),
            patch.object(migration.op, "get_bind", return_value=bind),
            patch.object(migration.sa, "inspect", return_value=inspector),
            patch.object(
                migration.op,
                "create_table",
                side_effect=lambda *args, **kwargs: created_tables.append((args, kwargs)),
            ),
            patch.object(
                migration.op,
                "create_index",
                side_effect=lambda *args, **kwargs: created_indexes.append((args, kwargs)),
            ),
        ):
            migration.upgrade()

        return created_tables, created_indexes, bind

    def test_revision_metadata(self):
        self.assertEqual(migration.revision, "p11_accounting_detail_01")
        self.assertEqual(migration.down_revision, "p11_journal_period_fk_01")

    def test_upgrade_creates_three_tables_in_dependency_order(self):
        tables, indexes, bind = self.run_upgrade()

        self.assertEqual(
            [args[0] for args, _ in tables],
            ["account", "journal_line", "journal_audit_event"],
        )
        self.assertEqual(len(indexes), 5)
        self.assertEqual(bind.calls, 2)

    def test_account_constraints_and_indexes(self):
        tables, indexes, _ = self.run_upgrade()
        args, _ = tables[0]
        constraints = [item for item in args[1:] if isinstance(
            item,
            (
                sa.PrimaryKeyConstraint,
                sa.ForeignKeyConstraint,
                sa.UniqueConstraint,
                sa.CheckConstraint,
            ),
        )]
        names = {item.name for item in constraints}

        self.assertTrue({
            "fk_account_parent_same_company",
            "uq_account_company_code",
            "uq_account_company_system_code",
            "uq_account_company_id_id",
            "ck_account_valid_type",
            "ck_account_valid_normal_balance",
        }.issubset(names))
        self.assertEqual(indexes[0][0][0], "ix_account_company_type_active")
        self.assertEqual(indexes[1][0][0], "ix_account_parent_id")

    def test_journal_line_has_tenant_safe_foreign_keys_and_checks(self):
        tables, _, _ = self.run_upgrade()
        args, _ = tables[1]
        constraints = [item for item in args[1:] if isinstance(
            item,
            (
                sa.PrimaryKeyConstraint,
                sa.ForeignKeyConstraint,
                sa.UniqueConstraint,
                sa.CheckConstraint,
            ),
        )]
        names = {item.name for item in constraints}

        self.assertTrue({
            "fk_journal_line_same_company",
            "fk_journal_line_account_same_company",
            "uq_journal_line_number",
            "ck_journal_line_positive_number",
            "ck_journal_line_nonnegative_amounts",
            "ck_journal_line_one_positive_side",
        }.issubset(names))

        foreign_keys = [
            item for item in constraints
            if isinstance(item, sa.ForeignKeyConstraint)
        ]
        self.assertEqual(len(foreign_keys), 2)
        for foreign_key in foreign_keys:
            self.assertEqual(foreign_key.ondelete, "RESTRICT")
            self.assertEqual(
                list(foreign_key.column_keys)[0],
                "company_id",
            )

    def test_audit_event_has_tenant_safe_foreign_keys_and_event_check(self):
        tables, indexes, _ = self.run_upgrade()
        args, _ = tables[2]
        constraints = [item for item in args[1:] if isinstance(
            item,
            (
                sa.PrimaryKeyConstraint,
                sa.ForeignKeyConstraint,
                sa.UniqueConstraint,
                sa.CheckConstraint,
            ),
        )]
        names = {item.name for item in constraints}

        self.assertTrue({
            "fk_journal_audit_entry_same_company",
            "fk_journal_audit_actor_same_company",
            "ck_journal_audit_valid_event_type",
        }.issubset(names))
        self.assertEqual(indexes[3][0][0], "ix_journal_audit_company_time")
        self.assertEqual(indexes[4][0][0], "ix_journal_audit_company_journal")

    def test_offline_mode_is_rejected_before_inspection(self):
        bind = FakeBind()
        with (
            patch.object(migration.context, "is_offline_mode", return_value=True),
            patch.object(migration.op, "get_bind", return_value=bind),
            patch.object(migration.sa, "inspect") as inspect,
        ):
            with self.assertRaisesRegex(RuntimeError, "online PostgreSQL"):
                migration.upgrade()
        inspect.assert_not_called()
        self.assertEqual(bind.calls, 0)

    def test_non_postgresql_dialect_is_rejected(self):
        bind = FakeBind(dialect_name="sqlite")
        with (
            patch.object(migration.context, "is_offline_mode", return_value=False),
            patch.object(migration.op, "get_bind", return_value=bind),
            patch.object(migration.sa, "inspect") as inspect,
        ):
            with self.assertRaisesRegex(RuntimeError, "PostgreSQL only"):
                migration.upgrade()
        inspect.assert_not_called()

    def test_missing_prerequisite_is_rejected_before_ddl(self):
        inspector = FakeInspector(missing_tables={"accounting_period"})
        bind = FakeBind()
        with (
            patch.object(migration.context, "is_offline_mode", return_value=False),
            patch.object(migration.op, "get_bind", return_value=bind),
            patch.object(migration.sa, "inspect", return_value=inspector),
            patch.object(migration.op, "create_table") as create_table,
        ):
            with self.assertRaisesRegex(RuntimeError, "accounting_period"):
                migration.upgrade()
        create_table.assert_not_called()

    def test_existing_target_table_is_rejected_before_ddl(self):
        inspector = FakeInspector(existing_tables={"account"})
        bind = FakeBind()
        with (
            patch.object(migration.context, "is_offline_mode", return_value=False),
            patch.object(migration.op, "get_bind", return_value=bind),
            patch.object(migration.sa, "inspect", return_value=inspector),
            patch.object(migration.op, "create_table") as create_table,
        ):
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                migration.upgrade()
        create_table.assert_not_called()

    def test_missing_required_composite_unique_is_rejected(self):
        inspector = FakeInspector(
            missing_unique={migration.USER_UNIQUE_NAME}
        )
        bind = FakeBind()
        with (
            patch.object(migration.context, "is_offline_mode", return_value=False),
            patch.object(migration.op, "get_bind", return_value=bind),
            patch.object(migration.sa, "inspect", return_value=inspector),
            patch.object(migration.op, "create_table") as create_table,
        ):
            with self.assertRaisesRegex(RuntimeError, "uq_user_company_id_id"):
                migration.upgrade()
        create_table.assert_not_called()

    def test_reserved_constraint_collision_is_rejected_before_ddl(self):
        inspector = FakeInspector()
        bind = FakeBind(conflict_on_call=2)
        with (
            patch.object(migration.context, "is_offline_mode", return_value=False),
            patch.object(migration.op, "get_bind", return_value=bind),
            patch.object(migration.sa, "inspect", return_value=inspector),
            patch.object(migration.op, "create_table") as create_table,
        ):
            with self.assertRaisesRegex(RuntimeError, "constraint names"):
                migration.upgrade()
        create_table.assert_not_called()

    def test_downgrade_is_blocked(self):
        with self.assertRaisesRegex(RuntimeError, "intentionally blocked"):
            migration.downgrade()


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        AccountingDetailMigrationTests
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
