"""Isolated tests for the journal foundation migration verifier.

These tests mock SQLAlchemy inspection. They do not connect to a database.
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
    / "20261118_journal_foundation.py"
)

spec = importlib.util.spec_from_file_location(
    "journal_foundation_migration_under_test",
    MIGRATION_PATH,
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class FakeInspector:
    def __init__(self, *, columns=None):
        self.columns = columns or self.valid_columns()

    @staticmethod
    def valid_columns():
        definitions = [
            ("id", sa.Integer(), False),
            ("company_id", sa.Integer(), False),
            ("journal_number", sa.String(40), False),
            ("journal_date", sa.Date(), False),
            ("accounting_period_id", sa.Integer(), True),
            ("description", sa.String(500), False),
            ("currency", sa.String(3), False),
            ("source_type", sa.String(40), False),
            ("source_id", sa.Integer(), True),
            ("status", sa.String(20), False),
            ("created_by_id", sa.Integer(), False),
            ("posted_by_id", sa.Integer(), True),
            ("posted_at", sa.DateTime(), True),
            ("reversal_of_id", sa.Integer(), True),
            ("created_at", sa.DateTime(), False),
        ]

        return [
            {"name": name, "type": column_type, "nullable": nullable, "default": None}
            for name, column_type, nullable in definitions
        ]

    def get_columns(self, table):
        return self.columns

    def get_pk_constraint(self, table):
        return {"constrained_columns": ["id"]}

    def get_unique_constraints(self, table):
        return [
            {
                "name": "uq_journal_company_number",
                "column_names": ["company_id", "journal_number"],
            },
            {
                "name": "uq_journal_company_id_id",
                "column_names": ["company_id", "id"],
            },
            {
                "name": "uq_journal_company_reversal",
                "column_names": ["company_id", "reversal_of_id"],
            },
        ]

    def get_foreign_keys(self, table):
        return [
            {
                "name": "fk_journal_company",
                "constrained_columns": ["company_id"],
                "referred_table": "company",
                "referred_columns": ["id"],
                "options": {"ondelete": "RESTRICT"},
            },
            {
                "name": "fk_journal_reversal_same_company",
                "constrained_columns": ["company_id", "reversal_of_id"],
                "referred_table": "journal_entry",
                "referred_columns": ["company_id", "id"],
                "options": {"ondelete": "RESTRICT"},
            },
            {
                "name": "fk_journal_creator_same_company",
                "constrained_columns": ["company_id", "created_by_id"],
                "referred_table": "user",
                "referred_columns": ["company_id", "id"],
                "options": {"ondelete": "RESTRICT"},
            },
            {
                "name": "fk_journal_poster_same_company",
                "constrained_columns": ["company_id", "posted_by_id"],
                "referred_table": "user",
                "referred_columns": ["company_id", "id"],
                "options": {"ondelete": "RESTRICT"},
            },
        ]

    def get_check_constraints(self, table):
        return [
            {
                "name": "ck_journal_valid_status",
                "sqltext": "status IN ('draft', 'posted', 'reversed')",
            },
            {
                "name": "ck_journal_posted_requires_period",
                "sqltext": "status = 'draft' OR accounting_period_id IS NOT NULL",
            },
            {
                "name": "ck_journal_currency_length",
                "sqltext": "length(currency) = 3",
            },
            {
                "name": "ck_journal_no_self_reversal",
                "sqltext": "reversal_of_id IS NULL OR reversal_of_id != id",
            },
        ]

    def get_indexes(self, table):
        return [
            {
                "name": "ix_journal_company_date_status",
                "column_names": ["company_id", "journal_date", "status"],
                "unique": False,
                "expressions": None,
                "dialect_options": {},
            },
            {
                "name": "ix_journal_company_period",
                "column_names": ["company_id", "accounting_period_id"],
                "unique": False,
                "expressions": None,
                "dialect_options": {},
            },
        ]


class JournalFoundationMigrationTests(unittest.TestCase):
    def inspect_with(self, inspector):
        with patch.object(
            migration.sa,
            "inspect",
            return_value=inspector,
        ):
            migration._inspect_existing_journal_table(object())

    def test_rejects_big_integer_where_integer_is_expected(self):
        inspector = FakeInspector()
        inspector.columns[0]["type"] = sa.BigInteger()

        with self.assertRaisesRegex(RuntimeError, "incompatible type"):
            self.inspect_with(inspector)

    def test_rejects_timezone_aware_timestamp(self):
        inspector = FakeInspector()

        for column in inspector.columns:
            if column["name"] == "posted_at":
                column["type"] = sa.DateTime(timezone=True)
                break

        with self.assertRaisesRegex(RuntimeError, "timezone setting"):
            self.inspect_with(inspector)

    def test_matching_existing_table_is_not_silently_adopted(self):
        inspector = FakeInspector()

        with self.assertRaisesRegex(
            RuntimeError,
            "will not silently adopt a pre-existing table",
        ):
            self.inspect_with(inspector)

    def test_downgrade_remains_blocked(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "downgrade is intentionally blocked",
        ):
            migration.downgrade()

    def test_rejects_small_integer_where_integer_is_expected(self):
        inspector = FakeInspector()
        inspector.columns[0]["type"] = sa.SmallInteger()

        with self.assertRaisesRegex(RuntimeError, "incompatible type"):
            self.inspect_with(inspector)

    def test_fresh_table_path_creates_journal_and_indexes(self):
        inspector = FakeInspector()
        inspector.has_table = lambda table: False

        bind = type(
            "FakeBind",
            (),
            {"dialect": type("Dialect", (), {"name": "postgresql"})()},
        )()

        created_tables = []
        created_indexes = []

        with (
            patch.object(migration.context, "is_offline_mode", return_value=False),
            patch.object(migration.op, "get_bind", return_value=bind),
            patch.object(migration.sa, "inspect", return_value=inspector),
            patch.object(
                migration,
                "_preflight_user_company_unique",
                return_value=False,
            ),
            patch.object(migration, "_preflight_reserved_relation_names"),
            patch.object(
                migration.op,
                "create_table",
                side_effect=lambda *args, **kwargs: created_tables.append(args[0]),
            ),
            patch.object(
                migration.op,
                "create_index",
                side_effect=lambda *args, **kwargs: created_indexes.append(args[0]),
            ),
        ):
            migration.upgrade()

        self.assertEqual(created_tables, ["journal_entry"])
        self.assertEqual(
            created_indexes,
            [
                "ix_journal_company_date_status",
                "ix_journal_company_period",
            ],
        )



    def test_rejects_offline_migration(self):
        bind = type(
            "FakeBind",
            (),
            {"dialect": type("Dialect", (), {"name": "postgresql"})()},
        )()

        with patch.object(migration.context, "is_offline_mode", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "online PostgreSQL"):
                migration._require_postgresql_online(bind)

    def test_rejects_non_postgresql_database(self):
        bind = type(
            "FakeBind",
            (),
            {"dialect": type("Dialect", (), {"name": "sqlite"})()},
        )()

        with patch.object(migration.context, "is_offline_mode", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "PostgreSQL only"):
                migration._require_postgresql_online(bind)

    def test_user_preflight_rejects_missing_user_table(self):
        class Inspector:
            def has_table(self, table):
                return False

        with patch.object(migration.sa, "inspect", return_value=Inspector()):
            with self.assertRaisesRegex(RuntimeError, "user.*does not exist"):
                migration._preflight_user_company_unique(object())

    def test_user_preflight_rejects_missing_required_column(self):
        class Inspector:
            def has_table(self, table):
                return True

            def get_columns(self, table):
                return [{"name": "id"}]

        with patch.object(migration.sa, "inspect", return_value=Inspector()):
            with self.assertRaisesRegex(RuntimeError, "missing company_id or id"):
                migration._preflight_user_company_unique(object())

    def test_user_preflight_rejects_incompatible_named_constraint(self):
        class Inspector:
            def has_table(self, table):
                return True

            def get_columns(self, table):
                return [{"name": "company_id"}, {"name": "id"}]

            def get_unique_constraints(self, table):
                return [{
                    "name": migration.USER_UNIQUE_NAME,
                    "column_names": ["id", "company_id"],
                }]

            def get_indexes(self, table):
                return []

        with patch.object(migration.sa, "inspect", return_value=Inspector()):
            with self.assertRaisesRegex(RuntimeError, "incompatible definition"):
                migration._preflight_user_company_unique(object())

    def test_user_preflight_rejects_equivalent_constraint_under_another_name(self):
        class Inspector:
            def has_table(self, table):
                return True

            def get_columns(self, table):
                return [{"name": "company_id"}, {"name": "id"}]

            def get_unique_constraints(self, table):
                return [{
                    "name": "uq_user_other_name",
                    "column_names": ["company_id", "id"],
                }]

            def get_indexes(self, table):
                return []

        with patch.object(migration.sa, "inspect", return_value=Inspector()):
            with self.assertRaisesRegex(RuntimeError, "under another name"):
                migration._preflight_user_company_unique(object())

    def test_user_preflight_rejects_equivalent_unique_index(self):
        class Inspector:
            def has_table(self, table):
                return True

            def get_columns(self, table):
                return [{"name": "company_id"}, {"name": "id"}]

            def get_unique_constraints(self, table):
                return []

            def get_indexes(self, table):
                return [{
                    "name": "ix_user_company_id",
                    "unique": True,
                    "column_names": ["company_id", "id"],
                    "duplicates_constraint": None,
                }]

        with patch.object(migration.sa, "inspect", return_value=Inspector()):
            with self.assertRaisesRegex(RuntimeError, "unique index exists"):
                migration._preflight_user_company_unique(object())

    def test_reserved_relation_preflight_rejects_collision(self):
        class Result:
            def mappings(self):
                return self

            def all(self):
                return [{
                    "relname": "ix_journal_company_period",
                    "relkind": "i",
                    "owner_table": "another_table",
                    "constraint_name": None,
                }]

        class Bind:
            def execute(self, statement, parameters):
                return Result()

        with self.assertRaisesRegex(RuntimeError, "relation names are already in use"):
            migration._preflight_reserved_relation_names(Bind(), False)

    def test_fresh_table_path_stops_when_user_preflight_fails(self):
        inspector = FakeInspector()
        inspector.has_table = lambda table: False

        bind = type(
            "FakeBind",
            (),
            {"dialect": type("Dialect", (), {"name": "postgresql"})()},
        )()

        with (
            patch.object(migration.context, "is_offline_mode", return_value=False),
            patch.object(migration.op, "get_bind", return_value=bind),
            patch.object(migration.sa, "inspect", return_value=inspector),
            patch.object(
                migration,
                "_preflight_user_company_unique",
                side_effect=RuntimeError("user preflight blocked"),
            ),
            patch.object(migration.op, "create_table") as create_table,
        ):
            with self.assertRaisesRegex(RuntimeError, "user preflight blocked"):
                migration.upgrade()

        create_table.assert_not_called()

    def test_existing_journal_rejects_wrong_column_nullability(self):
        inspector = FakeInspector()
        inspector.columns[1]["nullable"] = True

        with self.assertRaisesRegex(RuntimeError, "incompatible nullability"):
            self.inspect_with(inspector)

    def test_existing_journal_rejects_unexpected_server_default(self):
        inspector = FakeInspector()
        inspector.columns[0]["default"] = "1"

        with self.assertRaisesRegex(RuntimeError, "unexpected server default"):
            self.inspect_with(inspector)

    def test_existing_journal_rejects_missing_same_company_foreign_key(self):
        inspector = FakeInspector()
        inspector.get_foreign_keys = lambda table: []

        with self.assertRaisesRegex(RuntimeError, "same-company definitions"):
            self.inspect_with(inspector)

    def test_existing_journal_rejects_incorrect_check_constraint(self):
        inspector = FakeInspector()
        inspector.get_check_constraints = lambda table: []

        with self.assertRaisesRegex(RuntimeError, "check constraints"):
            self.inspect_with(inspector)

    def test_existing_journal_rejects_missing_index(self):
        inspector = FakeInspector()
        inspector.get_indexes = lambda table: []

        with self.assertRaisesRegex(RuntimeError, "indexes do not match"):
            self.inspect_with(inspector)


if __name__ == "__main__":
    unittest.main(verbosity=2)
